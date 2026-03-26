#!/usr/bin/env python3
"""
Helper script: logs in, scrapes upcoming rounds, prints JSON to stdout.
Called by golf_server.py as a subprocess.
"""

import ssl, os, sys, json, certifi
from datetime import datetime

def fix_ssl():
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

fix_ssl()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

LOGIN_URL         = "https://www.rosevillegolf.com.au/web/pages/login"
BOOK_A_ROUND      = "https://www.rosevillegolf.com.au/group/pages/book-a-round"
USERNAME          = os.environ.get("CLUB_USERNAME", "4291")
PASSWORD          = os.environ.get("CLUB_PASSWORD", "")
USERNAME_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_login"
PASSWORD_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_password"

EXCLUDE_KEYWORDS = ["ladies", "women's only", "bridge", "9 hole ladies", "women", "womens", "woman"]
INCLUDE_KEYWORDS = [
    "men's comp", "mens comp", "saturday competition", "stableford", "stroke",
    "medley", "championship", "trophy", "2bbb", "4bbb", "ambrose", "pennant",
    "social", "twilight", "friday", "wednesday", "thursday", "tuesday", "monday"
]

def should_include(title):
    t = title.lower()
    for ex in EXCLUDE_KEYWORDS:
        if ex in t:
            return False
    for inc in INCLUDE_KEYWORDS:
        if inc in t:
            return True
    return False

def parse_event_date(day_name, day_date):
    year = datetime.now().year
    try:
        dt = datetime.strptime(f"{day_name} {day_date} {year}", "%a %d %b %Y")
        if dt < datetime.now().replace(hour=0, minute=0, second=0):
            dt = datetime.strptime(f"{day_name} {day_date} {year + 1}", "%a %d %b %Y")
        return dt
    except Exception:
        return None

def main():
    options = Options()
    options.add_argument("--window-size=1400,900")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
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
        username_field = wait.until(EC.element_to_be_clickable((By.ID, USERNAME_FIELD_ID)))
        username_field.send_keys(USERNAME)
        password_field = wait.until(EC.element_to_be_clickable((By.ID, PASSWORD_FIELD_ID)))
        password_field.send_keys(PASSWORD)
        password_field.submit()
        wait.until(EC.url_changes(LOGIN_URL))

        # Navigate directly to the booking page
        BOOK_A_ROUND = "https://www.rosevillegolf.com.au/group/pages/book-a-round"
        print(f"Navigating to booking page...", file=sys.stderr)
        driver.get(BOOK_A_ROUND)

        # Wait for React to render the event list
        import time as _t
        import re as _re_url
        for _ in range(60):
            # If the page redirected to miclub with booking_resource_id, strip it
            # so we see ALL events (not filtered to one resource)
            cur = driver.current_url
            if 'booking_resource_id' in cur:
                clean_url = _re_url.sub(r'[&?]booking_resource_id=[^&]*', '', cur)
                # Fix any resulting &&, ?&, &? or leading & after the path
                clean_url = _re_url.sub(r'\?&+', '?', clean_url)   # ?& or ?&& → ?
                clean_url = _re_url.sub(r'&&+', '&', clean_url)    # && → &
                clean_url = _re_url.sub(r'\.xhtml&', '.xhtml?', clean_url)  # xhtml& → xhtml?
                clean_url = clean_url.rstrip('?&')
                print(f"Stripping booking_resource_id, navigating to: {clean_url}", file=sys.stderr)
                driver.get(clean_url)
                _t.sleep(1)
                break
            spans = driver.find_elements(By.CSS_SELECTOR,
                "span.eventStatusOpen, span.eventStatusClosed, span.eventStatusLocked")
            if spans:
                break
            _t.sleep(0.3)

        # Now wait up to 18s for events to appear
        for _ in range(60):
            spans = driver.find_elements(By.CSS_SELECTOR,
                "span.eventStatusOpen, span.eventStatusClosed, span.eventStatusLocked")
            if spans:
                break
            _t.sleep(0.3)
        else:
            print(f"EVENTS_ERROR:Timed out waiting for events to load")
            return

        print(f"Booking page URL: {driver.current_url}", file=sys.stderr)

        all_spans = driver.find_elements(
            By.CSS_SELECTOR,
            "span.eventStatusOpen, span.eventStatusClosed, span.eventStatusLocked"
        )

        events = []
        seen = set()
        last_event_date = None  # carry forward date for ALL rows including VIEW ONLY

        for span in all_spans:
            status = span.text.strip()

            # Always update last_event_date regardless of status
            # so VIEW ONLY rows still advance the date for subsequent rows
            try:
                container  = span.find_element(By.XPATH, "ancestor::div[contains(@class,'left-content-container')]")
                date_span  = container.find_element(By.CSS_SELECTOR, "span.dateColumnClass")
                date_spans = date_span.find_elements(By.TAG_NAME, "span")
                if date_spans:
                    day_name = date_spans[0].text.strip()
                    day_date = date_spans[1].text.strip()
                    parsed   = parse_event_date(day_name, day_date)
                    if parsed and parsed.date() >= datetime.now().date():
                        last_event_date = parsed
            except Exception:
                pass

            if status not in ('OPEN', 'LOCKED'):
                continue

            event_date = last_event_date

            if event_date is None or event_date.date() < datetime.now().date():
                continue

            try:
                full_div  = span.find_element(By.XPATH, "ancestor::div[contains(@class,'full')]")
                title_el  = full_div.find_element(By.CSS_SELECTOR, "span.event-title")
                title     = title_el.text.strip()
            except Exception as _te:
                title = ''

            if not title or not should_include(title):
                continue

            # Extract booking_event_id from the span's ancestor anchor
            event_id = ''
            try:
                link = span.find_element(By.XPATH, "ancestor::a")
                href = link.get_attribute('href') or ''
                import re as _re
                m = _re.search(r'booking_event_id=(\d+)', href)
                if m:
                    event_id = m.group(1)
            except Exception:
                try:
                    # Try sibling/nearby anchor
                    link = span.find_element(By.XPATH, "ancestor::div[contains(@class,'eventStatusClass')]//a")
                    href = link.get_attribute('href') or ''
                    import re as _re2
                    m = _re2.search(r'booking_event_id=(\d+)', href)
                    if m:
                        event_id = m.group(1)
                except Exception:
                    pass

            key = f"{title}_{event_date.date()}"
            if key in seen:
                continue
            seen.add(key)

            events.append({
                'title':    title,
                'date':     event_date.strftime('%A %d %B %Y'),
                'date_iso': event_date.strftime('%Y-%m-%d'),
                'status':   status,
                'event_id': event_id,
                'label':    f"{title} — {event_date.strftime('%a %d %b')}",
            })

        events.sort(key=lambda e: e['date_iso'])

        # If server only wants events after a certain date (cache edge check), filter here
        fetch_from = os.environ.get('FETCH_FROM_DATE', '').strip()
        if fetch_from:
            events = [e for e in events if e['date_iso'] > fetch_from]

        # Print JSON to stdout — server reads this
        print("EVENTS_JSON:" + json.dumps(events[:40]))

    finally:
        driver.quit()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"EVENTS_ERROR:{e}", file=sys.stderr)
        sys.exit(1)
