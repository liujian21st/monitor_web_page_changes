import smtplib
import ssl
import time
import os
import platform
import imagehash
import base64
import datetime
from email import encoders
from email.mime.base import MIMEBase
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from selenium import webdriver
from PIL import Image
from io import BytesIO
from random import randint
from multiprocessing.pool import ThreadPool as Pool

HASH_SIZE = 128             # Size of the perceptual hash
MAX_HASH_DIFFERENCE = 65536 # Maximum possible distance between hashes

# Use this class to handle actual sending of e-mail
# I'll just e-mail myself 
# New accounts need to enable: https://myaccount.google.com/lesssecureapps?pli=1
class Email_Client:

    def __init__(self, sender_email, password):

        self.sender_email = sender_email
        self.password = password

        self.port = 465
        self.smtp_server = "smtp.gmail.com"
        
    def send_email(self, receiver_email, message):

        context = ssl.create_default_context()

        with smtplib.SMTP_SSL(self.smtp_server, self.port, context=context) as server:
            server.login(self.sender_email, self.password)
            server.sendmail(self.sender_email, receiver_email, message)

# Set up selenium and use this class to handle screenshots and related browser operations
class Chrome_Driver:

    def __init__(self, executable_path, data_dir=None):

        self.options = webdriver.ChromeOptions()
        self.options.add_argument("--ignore-certificate-errors")
        self.options.add_argument("--test-type")
        self.options.add_argument("--headless")
        self.driver = webdriver.Chrome(options=self.options, executable_path=executable_path)
    
    # Open page, scroll or zoom, then couple seconds for page load
    def open_page(self, url, scroll_percent = 0):
        if scroll_percent != 0:
            denominator = (100 / scroll_percent)
            self.driver.get(url)
            #self.driver.execute_script("document.body.style.zoom='80%'") # May be useful later
            self.driver.execute_script(f"window.scrollTo(0, document.body.scrollHeight / {denominator});")
        else:
            self.driver.get(url)
        
        time.sleep(2)

    # When we're done, just close driver
    def close(self):

        self.driver.close()

    # Use selenium to screenshot page and open it with pillow 
    def screenshot_page(self):

        page_screenshot = self.driver.get_screenshot_as_png()
        page_screenshot = Image.open(BytesIO(page_screenshot))
        
        return page_screenshot

    # Display a screenshot of page locally for testing purposes
    def display_screenshot(self, page_screenshot):

        page_screenshot.show()

# We'll use this class for doing actual monitoring of URL in question
# It'll use e-mail client class above to alert user to changes
class Change_Monitor:

    def __init__(self, Chrome_Driver, Email_Client):

        self.driver = Chrome_Driver
        self.client = Email_Client

    # Get perceptual hash of screenshot so we can compare hashes
    # Avoids the need to write custom DOM scraper for every new page we monitor 
    def calculate_hash(self, page_screenshot):

        return imagehash.phash(page_screenshot, hash_size=HASH_SIZE)

    # Calculate perceptual hash difference between old and new page screenshot
    def get_hash_difference_percent(self, old_screenshot, new_screenshot):
        
        old_hash = self.calculate_hash(old_screenshot)
        new_hash  = self.calculate_hash(new_screenshot)
        difference = old_hash - new_hash
        percent_difference = ( difference / MAX_HASH_DIFFERENCE ) * 100
        
        return percent_difference

    def prepare_message(self, message, old_screenshot, new_screenshot, url):

        # Compose actual message
        message_body = f"Change alert for {url}"
        message["Subject"] = "Change alert!"
        message["From"]    = self.client.sender_email
        message["To"]      = self.client.sender_email

        # Add body to email
        message.attach(MIMEText(message_body, "plain"))

        # Attach old and new page screenshot to e-mail so user can visually inspect change
        message = self.attach_screenshot(message, new_screenshot, "new_screenshot.png")
        message = self.attach_screenshot(message, old_screenshot, "old_screenshot.png")

        return message.as_string()

    # When we finally detect a change, intiate e-mail alert
    def send_change_alert(self, url, old_screenshot, new_screenshot):
        
        message = self.prepare_message(MIMEMultipart(), old_screenshot, new_screenshot, url)
        self.client.send_email(self.client.sender_email, message)

    # Convoluted method of preparing out file as attachment.. fix dis
    def attach_screenshot(self, message, file, filename):
        
        stream = BytesIO()                                  # Create an in-memory binary stream
        file.save(stream, "PNG")                            # Save screenshot to stream
        stream.seek(0)                                      # Set stream offset
        screenshot = stream.read()                          # Read stream into memory
        part = MIMEBase("application", "octet-stream")      
        part.set_payload(screenshot)

        # Encode file in ASCII characters to send by email    
        encoders.encode_base64(part)

        # Add header as key/value pair to attachment part
        part.add_header(
            "Content-Disposition",
            f"attachment; filename={filename}",
        )

        message.attach(part)

        return message

    # Use this to continually monitor a given URL for visual changes
    # Takes a URL, an interval for checking page, and a scroll value for how far 
    # down we'd like to screenshot
    def check_page_for_changes(self, args):
        url, check_interval, scroll_percent = args[0], args[1], args[2]
        old_screenshot = None
        new_screenshot = None

        while True:

            self.driver.open_page(url, scroll_percent)

            if old_screenshot == None:
                old_screenshot = self.driver.screenshot_page()
            else:
                new_screenshot = self.driver.screenshot_page()
                percent_different = self.get_hash_difference_percent(old_screenshot, new_screenshot)

                current_time = datetime.datetime.now()
                current_time = current_time.strftime("%I:%M:%S %p")

                if percent_different > 1:
                    self.send_change_alert(url, old_screenshot, new_screenshot)
                    print(f"\nChange detected at {current_time}!\n")
                    print("The screenshots are different by: ", percent_different)
                else:
                    print(f"No change detected at {current_time}.")

                old_screenshot = new_screenshot
            
            # Not sure if necessary, but randomize our check interval so we don't look too suspicious
            minimum_sleep = int(check_interval * 0.7)
            time.sleep(randint(minimum_sleep, check_interval))

    # Use this to send a test e-mail alert
    def simulate_change(self, url, dummy_url, driver, monitor):

        driver.open_page(url, 6)
        old_screenshot = driver.screenshot_page()
        driver.open_page(dummy_url, 6)
        new_screenshot = driver.screenshot_page()
        monitor.send_change_alert(url, old_screenshot, new_screenshot)

def get_dependency_name():
    
    if (platform.system() == "Windows"):
        name = "chromedriver_windows.exe"
    elif (platform.system() == 'Linux'):
        name = "chromedriver_linux"
    else:
        name = "chromedriver_mac"
    return name

def get_credentials():

    try:
        # Try to open a credentials text file right outside of the root directory
        # Generally not a good idea to have plaintext passwords sitting around but 
        # I'm using a dummy account so shouldn't be a big deal for now
        # text file contains a single line formatted as: e-mail,password
        # Note-to-self: look up best practices for this type of thing
        credentials = open("../credentials.txt", "r").read().split(",")
        return credentials[0], credentials[1]
    except:
        return "some_email@domain.com", "some_password"

def main():

    email, password = get_credentials()

    urls_to_monitor = [("https://www.google.com", 120, 0)]
    
    dummy_url = "https://www.reddit.com/" # Optional: Only needed for simulate_change function
    
    directory_this_script = os.path.dirname(os.path.realpath(__file__)) # Get location of where this file is located
    chrome_driver_name = get_dependency_name()
    chrome_driver_location = os.path.join(directory_this_script, "bin", chrome_driver_name) # Assume chromedriver is in same directory
    
    pool = Pool(len(urls_to_monitor))

    for url in urls_to_monitor:
        driver = Chrome_Driver(chrome_driver_location)
        email_client = Email_Client(email, password)
        monitor = Change_Monitor(driver, email_client)
        pool.apply_async(monitor.check_page_for_changes, (url,))

    pool.close()
    pool.join()
    
if __name__ == '__main__':
    main()

