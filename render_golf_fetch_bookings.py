#!/usr/bin/env python3
"""
Helper script: logs in, scrapes current bookings, prints JSON to stdout.
Called by golf_server.py as a subprocess.
"""

import ssl, os, sys, json, certifi, re
from datetime import datetime

def fix_ssl():
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

fix_ssl()

import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
import time as _t

LOGIN_URL         = "https://www.rosevillegolf.com.au/web/pages/login"
MY_BOOKINGS_URL   = "https://www.rosevillegolf.com.au/group/pages/my-bookings"
USERNAME          = "4291"
PASSWORD          = "NewcastleTaree1!"
USERNAME_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_login"
PASSWORD_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_password"

def main():
    chromedriver_autoinstaller.install()
    options = Options()
    options.add_argument("--window-size=1400,900")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-setuid-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)

    driver = webdriver.Chrome(options=options)
    wait = WebDriverWait(driver, 10)

    try:
        # Login
        driver.get(LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, USERNAME_FIELD_ID)))
        driver.find_element(By.ID, USERNAME_FIELD_ID).send_keys(USERNAME)
        driver.find_element(By.ID, PASSWORD_FIELD_ID).send_keys(PASSWORD)
        driver.find_element(By.ID, PASSWORD_FIELD_ID).submit()
        wait.until(EC.url_changes(LOGIN_URL))

        # Try my-bookings page
        driver.get(MY_BOOKINGS_URL)
        _t.sleep(3)

        bookings = []

        # Try to find booking rows - miclub uses various structures
        # Look for table rows or booking cards
        page_source = driver.page_source

        # Try common selectors
        rows = driver.find_elements(By.CSS_SELECTOR,
            "tr.booking-row, div.booking-item, div.my-booking, "
            "table.bookingList tr, .bookingDetails, "
            "[class*='booking'] tr, [class*='mybooking']"
        )

        if not rows:
            # Try React-rendered content
            for _ in range(10):
                rows = driver.find_elements(By.CSS_SELECTOR,
                    "tr.booking-row, div.booking-item, div.my-booking, "
                    "table.bookingList tr, .bookingDetails"
                )
                if rows:
                    break
                _t.sleep(0.5)

        # Scrape all text lines and group into booking objects
        body_text = driver.find_element(By.TAG_NAME, 'body').text
        lines = [l.strip() for l in body_text.splitlines() if l.strip()]

        # Page format: time, then "Weekday DD Month", then comp name
        # e.g. "8:17am", "Saturday 07 March", "Saturday Competitions - ..."
        time_pat = re.compile(r'^\d{1,2}:\d{2}(am|pm)$', re.I)
        date_pat = re.compile(r'^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday)\s+\d{1,2}\s+\w+', re.I)

        i = 0
        while i < len(lines):
            line = lines[i]
            if time_pat.match(line):
                entry = {'time': line, 'date': '', 'name': ''}
                if i+1 < len(lines) and date_pat.match(lines[i+1]):
                    entry['date'] = lines[i+1]
                    i += 1
                if i+1 < len(lines) and len(lines[i+1]) > 5 and not time_pat.match(lines[i+1]):
                    entry['name'] = lines[i+1]
                    i += 1
                bookings.append(entry)
            i += 1

        # Also grab page title for debugging
        # Dump raw body text for debugging
        body_text_debug = driver.find_element(By.TAG_NAME, 'body').text
        print(f"RAW_BODY:{body_text_debug[:3000]}")
        print(f"Page title: {driver.title}")
        print(f"URL: {driver.current_url}")
        print(f"Found {len(rows)} rows, {len(bookings)} bookings")
        print(f"BOOKINGS_JSON:" + json.dumps(bookings[:20]))

    finally:
        driver.quit()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"BOOKINGS_ERROR:{e}", file=sys.stdout)
        traceback.print_exc(file=sys.stderr)
