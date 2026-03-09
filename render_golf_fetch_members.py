#!/usr/bin/env python3
"""
Helper script: logs in, scrapes member directory, prints JSON to stdout.
Uses identical login flow to roseville_golf_booking.py.
"""

import ssl, sys, json, certifi, time

def fix_ssl():
    ssl._create_default_https_context = lambda: ssl.create_default_context(cafile=certifi.where())

fix_ssl()

import chromedriver_autoinstaller
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options

LOGIN_URL         = "https://www.rosevillegolf.com.au/web/pages/login"
MEMBER_DIR_URL    = "https://www.rosevillegolf.com.au/group/pages/member-directory1"
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
    options.set_capability("unhandledPromptBehavior", "ignore")

    driver = webdriver.Chrome(options=options)
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source":
        "window.alert=function(m){}; window.confirm=function(m){return true;};"
    })
    wait = WebDriverWait(driver, 15)

    try:
        # Login
        print("Logging in...", file=sys.stderr)
        driver.get(LOGIN_URL)
        wait.until(EC.presence_of_element_located((By.ID, USERNAME_FIELD_ID)))
        driver.find_element(By.ID, USERNAME_FIELD_ID).send_keys(USERNAME)
        driver.find_element(By.ID, PASSWORD_FIELD_ID).send_keys(PASSWORD)
        driver.find_element(By.ID, PASSWORD_FIELD_ID).submit()
        wait.until(EC.url_changes(LOGIN_URL))
        print(f"Logged in — now at: {driver.current_url}", file=sys.stderr)

        # Navigate to member directory
        driver.get(MEMBER_DIR_URL)
        time.sleep(2)
        print(f"Page: {driver.current_url} — {driver.title}", file=sys.stderr)

        # Print HTML sample to help debug DOM structure
        html = driver.execute_script("return document.body ? document.body.innerHTML.substring(0, 4000) : 'NO BODY';")
        print(f"--- HTML SAMPLE ---\n{html}\n--- END SAMPLE ---", file=sys.stderr)

        # Poll for members
        members = []
        for attempt in range(40):
            result = driver.execute_script("""
                var out = {source: 'none', members: []};

                // Table rows
                var rows = document.querySelectorAll('table tbody tr');
                if (rows.length > 3) {
                    rows.forEach(function(tr) {
                        var tds = tr.querySelectorAll('td');
                        if (tds.length > 0) {
                            var t = tds[0].textContent.trim();
                            if (t.length > 2 && t.length < 60) out.members.push(t);
                        }
                    });
                    if (out.members.length > 3) { out.source = 'table'; return out; }
                    out.members = [];
                }

                // Class patterns
                var els = document.querySelectorAll('[class*="member"],[class*="Member"],[class*="directory"],[class*="person"],[class*="contact"]');
                els.forEach(function(el) {
                    if (el.children.length < 4) {
                        var t = el.textContent.trim();
                        if (t.length > 3 && t.length < 60 && t.split(' ').length >= 2) out.members.push(t);
                    }
                });
                if (out.members.length > 3) { out.source = 'member-class'; return out; }
                out.members = [];

                // List items
                document.querySelectorAll('ul li, ol li').forEach(function(li) {
                    var t = li.textContent.trim();
                    if (t.length > 3 && t.length < 60 && t.split(' ').length >= 2) out.members.push(t);
                });
                if (out.members.length > 5) { out.source = 'list'; return out; }

                return {source: 'none', members: []};
            """)

            source = result.get('source', 'none')
            found  = result.get('members', [])
            print(f"Attempt {attempt+1}: source={source}, count={len(found)}", file=sys.stderr)

            if source != 'none' and len(found) > 5:
                members = found
                break
            time.sleep(0.5)

        # Deduplicate and clean
        seen, clean = set(), []
        for m in members:
            m = ' '.join(m.split())
            if m and m not in seen and 2 < len(m) < 60:
                seen.add(m)
                clean.append(m)
        clean.sort()

        print(f"MEMBERS_JSON:{json.dumps(clean)}")
        print(f"Total: {len(clean)}", file=sys.stderr)

    finally:
        driver.quit()

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        import traceback
        traceback.print_exc(file=sys.stderr)
        print(f"MEMBERS_ERROR:{e}")
        sys.exit(1)
