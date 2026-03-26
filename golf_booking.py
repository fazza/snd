#!/usr/bin/env python3
"""
Roseville Golf Club - Full booking bot.
Logs in, navigates via Book A Round, finds next Wednesday,
books earliest tee time with 4 available spots.
"""

import ssl
import os
import subprocess
import sys
import certifi
from datetime import datetime, timedelta
from collections import defaultdict
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def fix_ssl():
    cert_cmd = os.path.join(os.path.dirname(sys.executable), "Install Certificates.command")
    if os.path.exists(cert_cmd):
        print("🔧 Running Python SSL certificate installer...")
        subprocess.run(["bash", cert_cmd], check=False)
    else:
        print("🔧 Patching SSL to use certifi certificates...")
        ssl._create_default_https_context = lambda: ssl.create_default_context(
            cafile=certifi.where()
        )
    print("✅ SSL configured.")

fix_ssl()

from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
# ── Config ──────────────────────────────────────────────
LOGIN_URL      = "https://www.rosevillegolf.com.au/web/pages/login"
BOOK_A_ROUND   = "https://www.rosevillegolf.com.au/group/pages/book-a-round"
USERNAME       = os.environ.get("CLUB_USERNAME", "4291")
PASSWORD       = os.environ.get("CLUB_PASSWORD", "")
USERNAME_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_login"
PASSWORD_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_password"
# Email config
EMAIL_SENDER    = "rwfarrelly@gmail.com"
EMAIL_PASSWORD  = "pzyj vffy ykjb afhl"
EMAIL_RECIPIENT = "rwfarrelly@gmail.com"
# ────────────────────────────────────────────────────────

def parse_event_date(date_span):
    try:
        spans = date_span.find_elements(By.TAG_NAME, "span")
        day_name = spans[0].text.strip()
        day_date = spans[1].text.strip()
        year = datetime.now().year
        combined = f"{day_name} {day_date} {year}"
        dt = datetime.strptime(combined, "%a %d %b %Y")
        if dt < datetime.now().replace(hour=0, minute=0, second=0):
            dt = datetime.strptime(f"{day_name} {day_date} {year + 1}", "%a %d %b %Y")
        return dt
    except Exception as e:
        print(f"   ⚠️  Could not parse date: {e}")
        return None

def parse_tee_time(time_str):
    try:
        return datetime.strptime(time_str.strip().lower(), "%I:%M %p")
    except Exception:
        try:
            return datetime.strptime(time_str.strip().lower(), "%I:%M%p")
        except Exception:
            return None


def send_email(tee_time_str, event_date, success=True, players=None):
    msg = MIMEMultipart()
    msg["From"]    = EMAIL_SENDER
    msg["To"]      = EMAIL_RECIPIENT

    if success:
        msg["Subject"] = f"⛳ Tee Time Booked: {tee_time_str} on {event_date}"
        body = (
            f"Your tee time has been successfully booked!\n\n"
            f"Date  : {event_date}\n"
            f"Time  : {tee_time_str}\n"
            f"Group : {chr(10).join(players) if players else 'Unknown'}\n\n"
            f"See you on the course! 🏌️"
        )
    else:
        msg["Subject"] = f"❌ Tee Time Booking FAILED for {event_date}"
        body = (
            f"The booking bot was unable to complete your tee time booking.\n\n"
            f"Please log in manually at:\n"
            f"https://www.rosevillegolf.com.au/group/pages/book-a-round\n\n"
            f"Error details: {tee_time_str}"
        )

    msg.attach(MIMEText(body, "plain"))

    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as server:
            server.starttls()
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
        print(f"   📧 Email sent to {EMAIL_RECIPIENT}")
    except Exception as e:
        print(f"   ⚠️  Failed to send email: {e}")

def main():
    options = Options()
    options.add_argument("--window-size=1400,900")
    options.add_argument("--headless=new")
    options.add_argument("--disable-gpu")
    options.add_argument("--no-sandbox")
    options.add_argument("--disable-dev-shm-usage")
    options.add_argument("--no-zygote")
    options.add_argument("--disable-setuid-sandbox")
    chrome_bin = os.environ.get('CHROME_BIN')
    if chrome_bin:
        options.binary_location = chrome_bin
    options.add_argument("--disable-blink-features=AutomationControlled")
    options.add_argument("--user-agent=Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36")
    options.add_experimental_option("excludeSwitches", ["enable-automation"])
    options.add_experimental_option("useAutomationExtension", False)
    # Auto-dismiss ALL native alerts/confirms at ChromeDriver level — prevents segfaults
    options.set_capability("unhandledPromptBehavior", "ignore")


    print("Launching browser...")
    driver = webdriver.Chrome(options=options)
    # Inject alert/confirm overrides via CDP so they run BEFORE any page JS
    # This prevents segfaults from alerts that fire during page load
    driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": """
        window._suppressedAlerts = [];
        window.alert = function(msg) { window._suppressedAlerts.push({type:'alert', msg:String(msg)}); };
        window.confirm = function(msg) {
            var isLocked = msg && msg.toLowerCase().indexOf('lock') >= 0;
            window._suppressedAlerts.push({type:'confirm', msg:String(msg), cancelled:isLocked});
            return !isLocked;
        };
    """})
    wait = WebDriverWait(driver, 8)

    try:
        # ── Step 1: Log in ───────────────────────────────────
        print(f"\nLogging in...")
        driver.get(LOGIN_URL)
        username_field = wait.until(EC.element_to_be_clickable((By.ID, USERNAME_FIELD_ID)))
        username_field.clear()
        username_field.send_keys(USERNAME)
        password_field = wait.until(EC.element_to_be_clickable((By.ID, PASSWORD_FIELD_ID)))
        password_field.clear()
        password_field.send_keys(PASSWORD)
        password_field.submit()
        wait.until(EC.url_changes(LOGIN_URL))
        print(f"✅ Login successful!")

        # ── Step 2: Navigate to Book A Round ──────────────────
        import time as _nav_time
        import re as _re_nav
        print(f"\nNavigating to Book A Round page...")
        driver.get(BOOK_A_ROUND)

        # The page may redirect to miclub with a booking_resource_id that filters
        # to a specific resource.  Strip it so we see all events.
        for _ in range(30):
            cur = driver.current_url
            if 'booking_resource_id' in cur:
                clean_url = _re_nav.sub(r'[&?]booking_resource_id=[^&]*', '', cur)
                clean_url = _re_nav.sub(r'\?&+', '?', clean_url)
                clean_url = _re_nav.sub(r'&&+', '&', clean_url)
                clean_url = _re_nav.sub(r'\.xhtml&', '.xhtml?', clean_url)
                clean_url = clean_url.rstrip('?&')
                print(f"   Stripping booking_resource_id → {clean_url}")
                driver.get(clean_url)
                _nav_time.sleep(1)
                break
            if driver.find_elements(By.CSS_SELECTOR,
                    "span.eventStatusOpen, span.eventStatusLocked, span.eventStatusClosed"):
                break
            _nav_time.sleep(0.3)

        wait.until(EC.presence_of_element_located((
            By.CSS_SELECTOR, "span.eventStatusOpen, span.eventStatusLocked, span.eventStatusClosed"
        )))
        print(f"✅ Booking page loaded!")
        print(f"   URL: {driver.current_url}")

        # ── Step 3: Navigate directly to selected event ─────
        import os as _os_step3
        selected_title    = _os_step3.environ.get("SELECTED_EVENT_TITLE", "").strip()
        selected_date_iso = _os_step3.environ.get("SELECTED_EVENT_DATE_ISO", "").strip()
        selected_status   = _os_step3.environ.get("SELECTED_EVENT_STATUS", "OPEN").strip()
        selected_event_id = _os_step3.environ.get("SELECTED_EVENT_ID", "").strip()

        if not selected_title or not selected_date_iso:
            print("\n❌ No event selected — please select a round from the GUI.")
            return

        target_date  = datetime.strptime(selected_date_iso, "%Y-%m-%d")
        target_title = selected_title
        print(f"\n   GUI-selected event: '{target_title}' on {target_date.strftime('%A %d %B %Y')}")
        print(f"   Event ID: {selected_event_id or '(none)'}, Status: {selected_status}")

        import time as _poll_time

        if selected_status == "LOCKED":
            # ── Polling mode: reload every 2s until event opens ──
            POLL_TIMEOUT = 600
            poll_start   = _poll_time.time()
            print(f"\n⏳ Polling for event to open (every 2s, up to 10 min)...")
            while _poll_time.time() - poll_start < POLL_TIMEOUT:
                try:
                    if selected_event_id:
                        event_url = f"https://roseville.miclub.com.au/members/bookings/open/event.msp?booking_event_id={selected_event_id}"
                        driver.get(event_url)
                    else:
                        driver.get(BOOK_A_ROUND)
                    _poll_time.sleep(2)
                    if driver.find_elements(By.CSS_SELECTOR, "div.row-heading-inner"):
                        print(f"\n🚀 OPEN at {datetime.now().strftime('%H:%M:%S')}!")
                        break
                    elapsed = int(_poll_time.time() - poll_start)
                    print(f"   {datetime.now().strftime('%H:%M:%S')} — still locked ({elapsed}s), retrying...")
                    _poll_time.sleep(1)
                except Exception as e:
                    print(f"   ⚠️  Poll error: {e}")
                    _poll_time.sleep(1)
            else:
                print(f"\n❌ Timed out waiting for event to open.")
                return
        else:
            # ── Immediate mode: go directly to event page ────────
            if selected_event_id:
                event_url = f"https://roseville.miclub.com.au/members/bookings/open/event.msp?booking_event_id={selected_event_id}"
                print(f"\n   Navigating directly to event URL...")
                driver.get(event_url)
            else:
                print(f"\n   No event_id — please refresh rounds and try again.")
                return

        # ── Handle queue if present ──────────────────────────
        import time as _queue_time
        QUEUE_TIMEOUT = 600  # wait up to 10 mins in queue
        queue_start   = _queue_time.time()

        while True:
            # Wait for either the tee time page OR a queue page to load
            _queue_time.sleep(0.5)
            page_src = driver.page_source.lower()
            current_url = driver.current_url

            # Check if we're on the tee time page (success)
            if driver.find_elements(By.CSS_SELECTOR, "div.row-heading-inner"):
                print(f"\n✅ Tee time page loaded!")
                print(f"   Now on: {current_url}")
                break

            # Check for queue indicators
            queue_position = None
            queue_time_left = None

            # Try to extract queue position
            for selector in [
                "[class*='queue'] [class*='position']",
                "[class*='queue'] [class*='number']",
                "[id*='queue']",
                "[class*='waiting']",
            ]:
                els = driver.find_elements(By.CSS_SELECTOR, selector)
                if els:
                    queue_position = els[0].text.strip()
                    break

            # Try common queue text patterns in page source
            import re as _re_q
            pos_match  = _re_q.search(r'position[^0-9]*(\d+)', page_src)
            time_match = _re_q.search(r'(\d+)\s*second', page_src)
            if pos_match:
                queue_position  = pos_match.group(1)
            if time_match:
                queue_time_left = time_match.group(1) + "s"

            elapsed = int(_queue_time.time() - queue_start)

            if queue_position or "queue" in page_src or "waiting" in page_src or "position" in page_src:
                pos_str  = f"position {queue_position}" if queue_position else "in queue"
                time_str = f", ~{queue_time_left} remaining" if queue_time_left else ""
                print(f"   ⏳ {datetime.now().strftime('%H:%M:%S')} — {pos_str}{time_str} ({elapsed}s elapsed)")
            else:
                print(f"   ⏳ {datetime.now().strftime('%H:%M:%S')} — waiting for page ({elapsed}s elapsed), URL: {current_url}")

            if elapsed > QUEUE_TIMEOUT:
                print(f"\n❌ Timed out waiting in queue after {QUEUE_TIMEOUT}s.")
                return

            # If page hasn't loaded anything useful yet, wait and retry
            _queue_time.sleep(0.5)

        # ── Step 4: Read players from GUI ────────────────────
        import os as _os
        import time as _time
        selected_players = [p.strip() for p in _os.environ.get("SELECTED_PLAYERS", "Ross Farrelly").split(",") if p.strip()]
        guests = [p for p in selected_players if p.lower() != "ross farrelly"]
        num_players = len(selected_players)
        print(f"\n👥 Players: {selected_players} ({num_players} total, {len(guests)} guest(s))")

        # Load member preferences (always/never flags)
        import json as _json
        _prefs_file = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), 'member_preferences.json')
        _member_prefs = {}
        try:
            if _os.path.exists(_prefs_file):
                with open(_prefs_file) as _pf:
                    _member_prefs = _json.load(_pf)
        except Exception:
            pass
        _always_members = {k.lower() for k, v in _member_prefs.items() if v == 'always'}
        _never_members  = {k.lower() for k, v in _member_prefs.items() if v == 'never'}
        if _always_members:
            print(f"   ⭐ Always-book members: {', '.join(sorted(_always_members))}")
        if _never_members:
            print(f"   🚫 Never-book members: {', '.join(sorted(_never_members))}")

        # ── Step 5: Find best tee time ───────────────────────
        # "Best" = already has low-handicap players booked + enough empty spots for us.
        # Empty rows score 999 and are last resort.
        #
        # DOM structure (confirmed from live HTML):
        #   data-rowid ONLY on empty Book Me cells.
        #   Booked cells use id="{rowid}_{index}" + class "cell-taken" — NO data-rowid.
        #   Tee time is in div.row-heading-inner > h3, inside div#row-{rowid}.

        import re as _re_hcp
        import os as _os_tw

        spots_needed = num_players
        DEFAULT_HANDICAP = 30.0
        EMPTY_ROW_SCORE  = 999.0

        # Optional time window from env
        tw_from_str = _os_tw.environ.get("SELECTED_TIME_FROM", "").strip()
        tw_to_str   = _os_tw.environ.get("SELECTED_TIME_TO",   "").strip()
        window_from = parse_tee_time(tw_from_str) if tw_from_str else None
        window_to   = parse_tee_time(tw_to_str)   if tw_to_str   else None
        if window_from or window_to:
            wf = window_from.strftime("%I:%M %p") if window_from else "any"
            wt = window_to.strftime("%I:%M %p")   if window_to   else "any"
            print(f"\n⏰ Time window: {wf} → {wt}")
        else:
            print(f"\n⏰ No time window — scanning all available tee times")

        print(f"\nScanning for best tee time with {spots_needed} available spot(s)...")

        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.records-wrapper")))

        # Alert/confirm already suppressed via CDP at browser launch

        # Build rowid → tee time text map via JS (uses Book Me cells to find rowids)
        try:
            row_time_map = driver.execute_script("""
                var result = {};
                var wrappers = document.querySelectorAll('div.records-wrapper');
                wrappers.forEach(function(wrapper) {
                    var parent = wrapper.parentElement;
                    var heading = parent.querySelector('div.row-heading-inner h3');
                    if (!heading) {
                        parent = wrapper.parentElement ? wrapper.parentElement.parentElement : null;
                        heading = parent ? parent.querySelector('div.row-heading-inner h3') : null;
                    }
                    var timeText = heading ? heading.textContent.trim() : null;
                    if (timeText) {
                        var cells = wrapper.querySelectorAll('div.cell[data-rowid]');
                        cells.forEach(function(cell) {
                            var rowid = cell.getAttribute('data-rowid');
                            if (rowid && !result[rowid]) { result[rowid] = timeText; }
                        });
                    }
                });
                return result;
            """)
        except Exception as js_err:
            # If JS crashes (e.g. alert still open), try one more dismiss and retry
            print(f"   ⚠️  JS crashed building time map: {js_err}")
            try:
                driver.switch_to.alert.dismiss()
                _time.sleep(0.5)
            except Exception:
                pass
            row_time_map = driver.execute_script("""
                var result = {};
                document.querySelectorAll('div.cell[data-rowid]').forEach(function(cell) {
                    var rowid = cell.getAttribute('data-rowid');
                    var row = cell.closest('div.row-time') || cell.parentElement.parentElement;
                    var h3 = row ? row.querySelector('h3') : null;
                    if (rowid && h3) result[rowid] = h3.textContent.trim();
                });
                return result;
            """)
        print(f"   Mapped {len(row_time_map)} rowids to tee times.")

        def extract_handicaps_from_row(rowid):
            """
            Get names+handicaps for already-booked players in this tee time row.
            Uses JS querySelectorAll on div#row-{rowid} — single simple call, no complex objects.
            Returns list of floats.
            """
            import re as _re2
            try:
                # Single JS call returning a plain list of name strings
                names = driver.execute_script(
                    "var d=document.getElementById('row-'+arguments[0]);"
                    "if(!d) return [];"
                    "return Array.from(d.querySelectorAll('span.booking-name'))"
                    ".map(function(s){return s.textContent.trim();})"
                    ".filter(function(t){return t.length>0;});",
                    str(rowid)
                )
            except Exception as e:
                print(f"      ⚠️  JS error for row {rowid}: {e}")
                names = []

            if not names:
                print(f"      ℹ️  Row {rowid}: empty")
                return []

            print(f"      ℹ️  Row {rowid}: {len(names)} player(s) → {', '.join(names)[:120]}")
            handicaps = []
            for txt in names:
                i1 = txt.find('[')
                i2 = txt.find(']', i1)
                if i1 >= 0 and i2 > i1:
                    try:
                        handicaps.append(float(txt[i1+1:i2]))
                        continue
                    except ValueError:
                        pass
                handicaps.append(DEFAULT_HANDICAP)
            return handicaps

        # Scan all Book Me cells using a single JS call — avoids ChromeDriver crash if alert is open
        scan_result = driver.execute_script("""
            var rows = {};
            document.querySelectorAll('div.cell[data-rowid]').forEach(function(cell) {
                var rowid = cell.getAttribute('data-rowid');
                if (!rowid) return;
                if (!rows[rowid]) rows[rowid] = {bookMe: 0, locked: false, names: []};
                if (cell.querySelector('p.lockedText')) rows[rowid].locked = true;
                var lbl = cell.querySelector('span.btn-label');
                if (lbl && lbl.textContent.trim() === 'Book Me') rows[rowid].bookMe++;
            });
            // Also grab booked player names per row
            document.querySelectorAll('div[id^="row-"]').forEach(function(rowDiv) {
                var rid = rowDiv.id.replace('row-', '');
                if (!rows[rid]) return;
                rowDiv.querySelectorAll('span.booking-name').forEach(function(s) {
                    var t = s.textContent.trim();
                    if (t) rows[rid].names.push(t);
                });
            });
            return rows;
        """)

        rowid_book_me = {k: v['bookMe'] for k, v in scan_result.items() if v['bookMe'] > 0}
        rowid_locked  = {k for k, v in scan_result.items() if v['locked']}
        rowid_names   = {k: v['names'] for k, v in scan_result.items()}

        candidates = []
        for rowid, book_me_count in rowid_book_me.items():
            if rowid in rowid_locked:
                time_text = row_time_map.get(rowid, rowid)
                print(f"   ⛔ {time_text} — locked by another user")
                continue
            time_text = row_time_map.get(rowid)
            if not time_text:
                continue
            tee_time = parse_tee_time(time_text)
            if tee_time is None:
                continue
            if window_from and tee_time < window_from:
                continue
            if window_to   and tee_time > window_to:
                continue
            if book_me_count < spots_needed:
                print(f"   ⛔ {time_text} — only {book_me_count} spot(s), need {spots_needed}")
                continue
            # Score rows — preference-aware
            names = rowid_names.get(rowid, [])
            handicaps = []
            has_always = False
            has_never  = False
            for txt in names:
                i1, i2 = txt.find('['), txt.find(']')
                if i1 >= 0 and i2 > i1:
                    try: handicaps.append(float(txt[i1+1:i2]))
                    except ValueError: handicaps.append(DEFAULT_HANDICAP)
                else:
                    handicaps.append(DEFAULT_HANDICAP)
                name_lower = txt.lower()
                for an in _always_members:
                    if an in name_lower: has_always = True
                for nn in _never_members:
                    if nn in name_lower: has_never = True

            if names:
                flags = (" ⭐ALWAYS" if has_always else "") + (" 🚫NEVER" if has_never else "")
                print(f"      ℹ️  Row {rowid}: {len(names)} player(s) → {', '.join(names)[:120]}{flags}")

            if has_always and not has_never:
                avg_hcp = -1.0
                hcp_str = f"⭐ ALWAYS member present ({len(names)} booked)"
            elif has_never:
                avg_hcp = 998.0
                hcp_str = f"🚫 NEVER member present — deprioritised"
            elif handicaps:
                avg_hcp = sum(handicaps) / len(handicaps)
                hcp_str = f"avg hcp {avg_hcp:.1f} ({len(handicaps)} player(s) booked)"
            else:
                avg_hcp = EMPTY_ROW_SCORE
                hcp_str = "empty row"
            print(f"   ✅ Eligible: {time_text} — {hcp_str} (row {rowid}, {book_me_count} open spots)")
            candidates.append((avg_hcp, tee_time, rowid, time_text))

        if not candidates:
            print(f"\n❌ No eligible tee times found.")
            return

        # Sort: best avg handicap first, then earliest time
        candidates.sort(key=lambda x: (x[0], x[1]))

        import re as _re
        from selenium.common.exceptions import UnexpectedAlertPresentException

        def dismiss_any_alert():
            try:
                driver.switch_to.alert.dismiss()
            except Exception:
                pass

        def attempt_booking(rowid, time_text):
            """Try to book a specific row. Returns True on success, False if locked/failed."""

            if num_players == 1:
                print(f"\n   Solo booking — clicking 'Book Me' on {time_text}...")
                dismiss_any_alert()
                clicked = driver.execute_script("""
                    var cells = document.querySelectorAll('div.cell[data-rowid="' + arguments[0] + '"]');
                    for (var i=0; i<cells.length; i++) {
                        var btn = cells[i].querySelector('button.btn-book-me');
                        if (btn) { btn.scrollIntoView(true); btn.click(); return true; }
                    }
                    return false;
                """, str(rowid))
                if not clicked:
                    print(f"   ⛔ Could not find Book Me button")
                    return False
                _time.sleep(0.5)
                suppressed = driver.execute_script("var a=window._suppressedAlerts||[]; window._suppressedAlerts=[]; return a;")
                locked_alerts = [a for a in suppressed if a.get('type')=='alert' or a.get('cancelled')]
                if locked_alerts:
                    print(f"   ⛔ Suppressed lock alert: '{locked_alerts[0].get('msg','')}' — skipping")
                    return False
                if suppressed:
                    print(f"   ℹ️  Suppressed confirm (auto-accepted): '{suppressed[0].get('msg','')[:60]}'")
                try:
                    yes_btn = WebDriverWait(driver, 3).until(EC.element_to_be_clickable((
                        By.XPATH, "//button[normalize-space(text())='Yes'] | //span[@class='btn-label' and normalize-space(text())='Yes']"
                    )))
                    driver.execute_script("arguments[0].click();", yes_btn)
                except Exception:
                    pass
                return True

            else:
                print(f"\n   Group booking ({num_players} players) on {time_text}...")

                # Navigate DIRECTLY to makeBooking URL using the rowid we already know.
                # This avoids clicking BOOK GROUP which locks the row on the server
                # even if the booking is never completed.
                make_booking_url = (
                    f"https://roseville.miclub.com.au/views/members/booking/makeBooking.xhtml"
                    f"?booking_row_id={rowid}&compactView=false&fillWithPartners=undefined"
                )
                print(f"   Navigating directly to makeBooking: {make_booking_url}")
                driver.get(make_booking_url)

                # If the row is locked or unavailable the site redirects away or shows an error
                _time.sleep(1.5)
                current = driver.current_url
                page_text = driver.execute_script("return document.body ? document.body.innerText : '';")
                suppressed = driver.execute_script("var a=window._suppressedAlerts||[]; window._suppressedAlerts=[]; return a;")
                locked_alerts = [a for a in suppressed if a.get('type')=='alert' or a.get('cancelled')]

                if locked_alerts:
                    print(f"   ⛔ Lock alert on makeBooking: '{locked_alerts[0].get('msg','')}' — skipping")
                    return False
                if 'makeBooking' not in current:
                    print(f"   ⛔ Redirected away from makeBooking (url={current[:80]}) — row unavailable, skipping")
                    return False
                lock_phrases = ['locked', 'not available', 'cannot be booked', 'error']
                for phrase in lock_phrases:
                    if phrase in page_text.lower()[:500]:
                        print(f"   ⛔ Page contains '{phrase}' — row unavailable, skipping")
                        return False

                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.ui-chkbox")))
                print(f"   ✅ Make Booking page loaded: {driver.current_url}")

                for guest in guests:
                    print(f"\n   Selecting guest: {guest}...")
                    try:
                        label = wait.until(EC.presence_of_element_located((
                            By.XPATH, f"//label[normalize-space(text())='{guest}']"
                        )))
                        input_id = label.get_attribute("for")
                        checkbox_input = driver.find_element(By.ID, input_id)
                        print(f"   Found checkbox id={input_id}, checked={checkbox_input.is_selected()}")
                        if not checkbox_input.is_selected():
                            chkbox_box = driver.find_element(
                                By.XPATH,
                                f"//input[@id='{input_id}']/parent::div/following-sibling::div[contains(@class,'ui-chkbox-box')]"
                            )
                            driver.execute_script("arguments[0].click();", chkbox_box)
                            _time.sleep(0.6)
                        print(f"   ✅ Selected {guest}")
                    except Exception as e:
                        print(f"   ⚠️  Could not find checkbox for {guest}: {e}")

                _time.sleep(1.5)

                print(f"\n   Clicking 'Confirm Booking'...")
                confirm_btn = wait.until(EC.element_to_be_clickable((
                    By.XPATH,
                    "//*[contains(@class,'ui-button-text') and contains(normalize-space(text()),'Confirm Booking')]"
                    "/ancestor::button | "
                    "//*[contains(@class,'ui-button-text') and contains(normalize-space(text()),'Confirm Booking')]"
                    "/ancestor::a"
                )))
                driver.execute_script("arguments[0].scrollIntoView(true);", confirm_btn)
                driver.execute_script("arguments[0].click();", confirm_btn)
                _time.sleep(1.5)
                return True

        # ── Step 6: Try candidates in order until one succeeds ──
        booked_time = None
        for rank, (avg_hcp, tee_time, rowid, time_text) in enumerate(candidates):
            hcp_label = f"avg hcp {avg_hcp:.1f}" if avg_hcp < EMPTY_ROW_SCORE else "empty row"
            print(f"\n   🏌️  Trying #{rank+1}: {time_text} ({hcp_label}, row {rowid})")
            # Clear any suppressed alerts from previous attempt
            driver.execute_script("window._suppressedAlerts=[];")
            if attempt_booking(rowid, time_text):
                booked_time = tee_time
                booked_time_text = time_text
                break
            else:
                print(f"   ↩️  Skipping — trying next candidate...")
                # Dismiss any alert before reloading
                try:
                    driver.switch_to.alert.dismiss()
                except Exception:
                    pass
                driver.get(driver.current_url)
                _time.sleep(1)
                # Dismiss any alert that appears on page load
                try:
                    driver.switch_to.alert.dismiss()
                    print(f"   ⚠️  Dismissed post-reload alert")
                except Exception:
                    pass
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div.records-wrapper")))

        if not booked_time:
            print(f"\n❌ All {len(candidates)} candidate(s) were locked or failed.")
            send_email("All tee times were locked or unavailable", target_date.strftime("%A %d %B %Y"), success=False)
            return

        wait.until(EC.presence_of_element_located((By.TAG_NAME, "body")))
        print(f"\n✅ Booking: {booked_time_text} confirmed!")
        print(f"   Now on : {driver.current_url}")
        print(f"   Title  : {driver.title}")

        # ── Step 7: Send confirmation email ──────────────────
        print(f"\nSending confirmation email...")
        send_email(
            tee_time_str=booked_time.strftime("%I:%M %p"),
            event_date=target_date.strftime("%A %d %B %Y"),
            success=True,
            players=selected_players
        )

    except Exception as e:
        # If a "row locked" alert escaped all inner handlers, dismiss it and report cleanly
        try:
            alert = driver.switch_to.alert
            msg = alert.text
            alert.dismiss()
            print(f"\n⛔ Unhandled alert dismissed: '{msg}'")
            print(f"   This means all candidates were locked. Update the file being run!")
        except Exception:
            pass
        print(f"\n❌ Error: {e}")
        try:
            print(f"   Current URL : {driver.current_url}")
        except Exception:
            pass
        try:
            send_email(str(e), "Unknown date", success=False)
        except Exception:
            pass

    finally:
        driver.quit()

if __name__ == "__main__":
    main()
