#!/usr/bin/env python3
"""
Helper script: logs in, scrapes ALL members from member directory (all letters, all pages),
prints JSON to stdout.  Called by golf_server.py as a subprocess.

The member directory uses server-side pagination (PrimeFaces DataGrid).
Each letter tab shows up to 20 members per page.  We click A–Z and paginate
through every page using the ui-paginator-next button.
"""

import ssl, os, sys, json, certifi, time as _t

def fix_ssl():
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

fix_ssl()

import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import (
    TimeoutException, StaleElementReferenceException, NoSuchElementException
)

LOGIN_URL      = "https://www.rosevillegolf.com.au/web/pages/login"
MEMBERS_URL    = "https://www.rosevillegolf.com.au/group/pages/member-directory1"
USERNAME       = os.environ.get("CLUB_USERNAME", "4291")
PASSWORD       = os.environ.get("CLUB_PASSWORD", "NewcastleTaree1!")
USERNAME_FIELD = "_com_liferay_login_web_portlet_LoginPortlet_login"
PASSWORD_FIELD = "_com_liferay_login_web_portlet_LoginPortlet_password"


def get_driver():
    chromedriver_autoinstaller.install()
    opts = Options()
    opts.add_argument("--window-size=1400,900")
    opts.add_argument("--headless=new")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-blink-features=AutomationControlled")
    opts.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                      "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    opts.add_experimental_option("excludeSwitches", ["enable-automation"])
    opts.add_experimental_option("useAutomationExtension", False)
    return webdriver.Chrome(options=opts)


def login(driver, wait):
    driver.get(LOGIN_URL)
    wait.until(EC.presence_of_element_located((By.ID, USERNAME_FIELD)))
    driver.find_element(By.ID, USERNAME_FIELD).send_keys(USERNAME)
    driver.find_element(By.ID, PASSWORD_FIELD).send_keys(PASSWORD)
    driver.find_element(By.ID, PASSWORD_FIELD).submit()
    wait.until(EC.url_changes(LOGIN_URL))


def get_names_on_page(driver):
    """Collect all span.roster-member-name texts on the current page."""
    spans = driver.find_elements(By.CSS_SELECTOR, "span.roster-member-name")
    return [s.text.strip() for s in spans if s.text.strip()]


def wait_for_roster_update(driver, wait, old_names):
    """Wait until roster content changes (AJAX reload after paginator click)."""
    for _ in range(40):  # up to 4 seconds
        _t.sleep(0.1)
        try:
            new_names = get_names_on_page(driver)
            if new_names and new_names != old_names:
                return new_names
        except StaleElementReferenceException:
            pass
    return get_names_on_page(driver)


def paginate_all(driver, wait):
    """
    Paginate through ALL pages for the currently active letter tab.
    Returns a list of member name strings.
    """
    all_names = []

    while True:
        names = get_names_on_page(driver)
        for n in names:
            if n and n not in all_names:
                all_names.append(n)

        # Find next-page button
        try:
            next_btn = driver.find_element(By.CSS_SELECTOR, "a.ui-paginator-next")
        except NoSuchElementException:
            break  # No paginator = single page

        btn_classes = next_btn.get_attribute("class") or ""
        if "ui-state-disabled" in btn_classes:
            break  # Last page

        old_names = names[:]
        try:
            driver.execute_script("arguments[0].click();", next_btn)
        except Exception:
            break

        new_names = wait_for_roster_update(driver, wait, old_names)
        if not new_names or new_names == old_names:
            break

    return all_names


def click_letter(driver, wait, letter):
    """Click the letter tab and wait for roster to load."""
    try:
        # Try both class formats seen in PrimeFaces roster components
        candidates = driver.find_elements(
            By.CSS_SELECTOR, "a.roster-search-alphabet"
        )
        target = None
        for btn in candidates:
            txt = btn.text.strip().upper()
            cls = btn.get_attribute("class") or ""
            if txt == letter.upper():
                target = btn
                break
            if letter.upper() in cls.split():
                target = btn
                break
        if target is None:
            return False

        old_names = get_names_on_page(driver)
        driver.execute_script("arguments[0].click();", target)
        _t.sleep(0.8)
        new_names = wait_for_roster_update(driver, wait, old_names)
        return bool(new_names)
    except Exception:
        return False


def main():
    driver = get_driver()
    wait = WebDriverWait(driver, 15)

    try:
        login(driver, wait)

        driver.get(MEMBERS_URL)
        _t.sleep(2)

        try:
            wait.until(EC.presence_of_element_located(
                (By.CSS_SELECTOR, "a.roster-search-alphabet, span.roster-member-name")
            ))
        except TimeoutException:
            print("MEMBERS_ERROR: Could not load member directory page", flush=True)
            sys.exit(1)

        all_members = []
        seen = set()

        letter_buttons = driver.find_elements(
            By.CSS_SELECTOR, "a.roster-search-alphabet"
        )

        if letter_buttons:
            # Build list of letters from button text or class
            available_letters = []
            for btn in letter_buttons:
                txt = btn.text.strip().upper()
                if len(txt) == 1 and txt.isalpha():
                    available_letters.append(txt)
                else:
                    for ch in (btn.get_attribute("class") or "").split():
                        if len(ch) == 1 and ch.isalpha():
                            available_letters.append(ch.upper())
                            break

            # Deduplicate
            seen_letters, letters_to_scrape = set(), []
            for l in available_letters:
                if l not in seen_letters:
                    seen_letters.add(l)
                    letters_to_scrape.append(l)

            print(f"[MEMBERS] Found {len(letters_to_scrape)} letter tabs", flush=True)

            for letter in letters_to_scrape:
                print(f"[MEMBERS] Scraping letter {letter}…", flush=True)
                if not click_letter(driver, wait, letter):
                    print(f"[MEMBERS]   Could not click {letter}, skipping", flush=True)
                    continue

                names = paginate_all(driver, wait)
                added = 0
                for name in names:
                    if name and name not in seen:
                        seen.add(name)
                        all_members.append({"name": name})
                        added += 1
                print(f"[MEMBERS]   {letter}: {added} members", flush=True)

        else:
            # No letter buttons — scrape visible + paginate
            print("[MEMBERS] No letter buttons found, scraping all visible", flush=True)
            names = paginate_all(driver, wait)
            for name in names:
                if name and name not in seen:
                    seen.add(name)
                    all_members.append({"name": name})

        print(f"[MEMBERS] Total: {len(all_members)} members", flush=True)
        print("MEMBERS_JSON:" + json.dumps(all_members), flush=True)

    finally:
        driver.quit()


if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        print(f"MEMBERS_ERROR:{e}", flush=True)
        traceback.print_exc(file=sys.stderr)
