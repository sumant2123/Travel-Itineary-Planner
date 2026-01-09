from selenium import webdriver
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from webdriver_manager.chrome import ChromeDriverManager
import time
import pyautogui
import base64
from PIL import Image
import io
import anthropic
import os
from dotenv import load_dotenv
import logging
import sys
from datetime import datetime
import httpx
from tenacity import retry, stop_after_attempt, wait_exponential

# Create logs directory if it doesn't exist
if not os.path.exists('logs'):
    os.makedirs('logs')

# Create screenshots directory if it doesn't exist
if not os.path.exists('screenshots'):
    os.makedirs('screenshots')

# Generate timestamp for log file
timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
log_file = f"logs/expedia_bot_{timestamp}.log"

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler(log_file),
        logging.StreamHandler(sys.stdout)
    ]
)
logger = logging.getLogger(__name__)

# Log the start of the session
logger.info(f"Starting new session. Log file: {log_file}")

# Load environment variables from .env file
load_dotenv()
logger.info("Environment variables loaded")

def setup_driver():
    logger.info("Setting up Chrome driver")
    try:
        # Set up Chrome options
        chrome_options = Options()
        chrome_options.add_argument("--start-maximized")
        
        # Set up the Chrome driver
        service = Service(ChromeDriverManager().install())
        driver = webdriver.Chrome(service=service, options=chrome_options)
        logger.info("Chrome driver setup successful")
        return driver
    except Exception as e:
        logger.error(f"Failed to setup Chrome driver: {str(e)}")
        raise

def take_screenshot(driver):
    logger.debug("Taking screenshot")
    try:
        # Take screenshot using Selenium
        screenshot = driver.get_screenshot_as_png()
        logger.debug(f"Screenshot taken, size: {len(screenshot)} bytes")
        
        # Convert to PIL Image
        image = Image.open(io.BytesIO(screenshot))
        logger.debug(f"Image converted to PIL format, size: {image.size}")
        
        # Save screenshot locally for debugging
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        local_path = f"screenshots/screenshot_{timestamp}.png"
        image.save(local_path)
        logger.info(f"Screenshot saved locally at: {local_path}")
        
        # Convert to base64
        buffered = io.BytesIO()
        image.save(buffered, format="PNG")
        base64_image = base64.b64encode(buffered.getvalue()).decode()
        logger.debug(f"Image converted to base64, length: {len(base64_image)}")
        
        return base64_image
    except Exception as e:
        logger.error(f"Failed to take screenshot: {str(e)}")
        raise

@retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, min=4, max=10))
def get_claude_guidance(image_base64):
    logger.info("Getting guidance from Claude")
    try:
        # Get API key from environment variable
        api_key = os.getenv('ANTHROPIC_API_KEY')
        if not api_key:
            logger.error("ANTHROPIC_API_KEY not found in environment variables")
            raise ValueError("ANTHROPIC_API_KEY not found in environment variables")
        
        logger.debug("Initializing Anthropic client")
        client = anthropic.Anthropic(
            api_key=api_key,
            timeout=60.0  # Increased timeout to 60 seconds
        )
        
        logger.debug("Sending request to Claude")
        try:
            message = client.messages.create(
                model="claude-3-opus-20240229",
                max_tokens=1000,
                messages=[{
                    "role": "user",
                    "content": [
                        {
                            "type": "text",
                            "text": """I'm trying to navigate Expedia.com to find the best rated hotel in Seattle for April 17th to April 20.
                            Step by Step example is:
                            Step1: click on stays,
                            Step2: close any pop ups on the screen. 
                            Step3: Type in Seattle. Step4: Enter the dates
                            Step4: Click on search
                            Step5: Optionally sign in as Sumant
                            Please analyze this screenshot and tell me what element I should click next. Return the response in this format: 'CLICK: [xpath or css selector]' or 'TYPE: [text to type]' or 'WAIT: [seconds]' or 'DONE' if we've reached the hotel page.
                            """
                        },
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/png",
                                "data": image_base64
                            }
                        }
                    ]
                }]
            )
            
            guidance = message.content[0].text
            logger.info(f"Received guidance from Claude: {guidance}")
            return guidance
        except httpx.TimeoutException as e:
            logger.error(f"Request to Claude timed out after 60 seconds: {str(e)}")
            raise
        except httpx.RequestError as e:
            logger.error(f"Network error while requesting Claude: {str(e)}")
            raise
        except Exception as e:
            logger.error(f"Unexpected error while requesting Claude: {str(e)}")
            raise
            
    except Exception as e:
        logger.error(f"Failed to get Claude guidance: {str(e)}")
        raise

def find_best_seattle_hotel():
    logger.info("Starting hotel search process")
    driver = None
    try:
        driver = setup_driver()
        
        # Navigate to Expedia
        logger.info("Navigating to Expedia.com")
        driver.get("https://www.expedia.com")
        
        # Wait for page to load
        logger.info("Waiting for page to load")
        time.sleep(5)
        
        while True:
            logger.debug("Starting new iteration of navigation loop")
            try:
                # Take screenshot and get Claude's guidance
                screenshot = take_screenshot(driver)
                guidance = get_claude_guidance(screenshot)
                
                if guidance.startswith('CLICK:'):
                    # Extract the selector from the guidance
                    selector = guidance.replace('CLICK:', '').strip()
                    logger.info(f"Attempting to click element with selector: {selector}")
                    try:
                        # Try to find and click the element
                        element = WebDriverWait(driver, 10).until(
                            EC.element_to_be_clickable((By.XPATH if '//' in selector else By.CSS_SELECTOR, selector))
                        )
                        element.click()
                        logger.info("Successfully clicked element")
                    except Exception as e:
                        logger.error(f"Failed to click element: {str(e)}")
                
                elif guidance.startswith('TYPE:'):
                    # Extract the text to type
                    text = guidance.replace('TYPE:', '').strip()
                    logger.info(f"Attempting to type text: {text}")
                    try:
                        # Find the active element and type
                        active_element = driver.switch_to.active_element
                        active_element.send_keys(text)
                        logger.info("Successfully typed text")
                    except Exception as e:
                        logger.error(f"Failed to type text: {str(e)}")
                
                elif guidance.startswith('WAIT:'):
                    # Extract the number of seconds to wait
                    seconds = float(guidance.replace('WAIT:', '').strip())
                    logger.info(f"Waiting for {seconds} seconds")
                    time.sleep(seconds)
                
                elif guidance == 'DONE':
                    logger.info("Reached the hotel page successfully!")
                    break
                
            except Exception as e:
                logger.error(f"Error in navigation loop: {str(e)}")
                time.sleep(5)  # Wait before retrying
                continue
            
            # Small delay between actions
            time.sleep(1)
        
    except Exception as e:
        logger.error(f"An error occurred in main process: {str(e)}")
        raise
    finally:
        if driver:
            logger.info("Closing browser")
            driver.quit()

if __name__ == "__main__":
    try:
        logger.info("Starting Expedia hotel search bot")
        find_best_seattle_hotel()
        logger.info("Bot execution completed successfully")
    except Exception as e:
        logger.error(f"Bot execution failed: {str(e)}")
        sys.exit(1)
