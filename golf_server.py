#!/usr/bin/env python3
"""
Local server for the Roseville Golf Club booking bot GUI.
Supports multiple users with session-based login and per-user preferences.
"""

from flask import Flask, Response, jsonify, send_file, request, session, redirect, url_for
import subprocess, sys, os, threading, queue, uuid, ssl, certifi, json, functools

app = Flask(__name__)

# ── Secret key for session cookies ──────────────────────────────────────────
# Change this to a fixed random string before hosting online.
# Generate one with: python3 -c "import secrets; print(secrets.token_hex(32))"
app.secret_key = os.environ.get('SECRET_KEY', '8c8c3cb14d3eb9a19082497b1953f2d499ad4b084b3d2634a1f66be26002682d')

# ── Invite code — set INVITE_CODE env var in Render dashboard ───────────────
# Anyone with this code can create an account. Keep it secret.
INVITE_CODE = os.environ.get('INVITE_CODE', 'StriclyNoDickheads')
MAX_USERS   = int(os.environ.get('MAX_USERS', '4'))  # max accounts allowed

BASE_DIR  = os.path.dirname(os.path.abspath(__file__))
# On free Render tier there is no persistent disk — use /tmp for cache files
# so they survive within a session but reset on redeploy (acceptable for free tier)
DATA_DIR  = os.environ.get('DATA_DIR', '/tmp')
MEMBERS_CACHE_FILE = os.path.join(DATA_DIR, 'member_cache.json')

# ── User config ──────────────────────────────────────────────────────────────
# Stored in users.json: { "4291": {"password": "...", "name": "Ross Farrelly"}, ... }
# Falls back to the hardcoded defaults if the file doesn't exist.
USERS_FILE = os.path.join(DATA_DIR, 'users.json')

# Hardcoded fallback — only used if USERS_JSON env var and users.json are both absent.
# Set USERS_JSON env var in Render dashboard instead of relying on this.
HARDCODED_USERS = {}

def load_users():
    # First priority: USERS_JSON environment variable (best for Render free tier)
    env_users = os.environ.get('USERS_JSON', '').strip()
    base = {}
    if env_users:
        try:
            base = json.loads(env_users)
        except Exception as e:
            print(f"[AUTH] Could not parse USERS_JSON env var: {e}")
    # Merge in any runtime-registered users (saved during signup on free tier)
    tmp_file = os.path.join('/tmp', 'users_runtime.json')
    if os.path.exists(tmp_file):
        try:
            with open(tmp_file) as f:
                runtime = json.load(f)
            base.update(runtime)
        except Exception as e:
            print(f"[AUTH] Could not load runtime users: {e}")
    if base:
        return base
    # Fall back to users.json on disk
    try:
        if os.path.exists(USERS_FILE):
            with open(USERS_FILE) as f:
                return json.load(f)
    except Exception as e:
        print(f"[AUTH] Could not load users.json: {e}")
    return HARDCODED_USERS

def get_user(username):
    return load_users().get(str(username))

# ── Session helpers ──────────────────────────────────────────────────────────
def current_user():
    return session.get('username')

def current_password():
    return session.get('password')

def current_name():
    return session.get('name', current_user())

def prefs_file(username=None):
    u = username or current_user() or 'default'
    return os.path.join(DATA_DIR, f'member_preferences_{u}.json')

def creds_env():
    e = os.environ.copy()
    e['CLUB_USERNAME'] = current_user() or ''
    e['CLUB_PASSWORD'] = current_password() or ''
    return e

# ── Auth decorator ───────────────────────────────────────────────────────────
def require_login(f):
    @functools.wraps(f)
    def decorated(*args, **kwargs):
        if not current_user():
            if request.path == '/' or not request.path.startswith('/'):
                return redirect(url_for('login_page'))
            return jsonify({'error': 'Not logged in', 'redirect': '/login'}), 401
        return f(*args, **kwargs)
    return decorated

# jobs[job_id] = { 'queue': Queue, 'process': Popen|None, 'running': bool }
jobs = {}
jobs_lock = threading.Lock()

LOGIN_URL         = "https://www.rosevillegolf.com.au/web/pages/login"
USERNAME_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_login"
PASSWORD_FIELD_ID = "_com_liferay_login_web_portlet_LoginPortlet_password"

EXCLUDE_KEYWORDS = ["ladies", "women's only", "bridge", "9 hole ladies", "women", "womens", "woman"]
INCLUDE_KEYWORDS = [
    "men's comp", "mens comp", "saturday competition", "stableford", "stroke",
    "medley", "championship", "trophy", "2bbb", "4bbb", "ambrose", "pennant",
    "social", "twilight", "friday", "wednesday", "thursday", "tuesday", "monday"
]

# ── Login / logout routes ────────────────────────────────────────────────────
@app.route('/login', methods=['GET'])
def login_page():
    if current_user():
        return redirect('/')
    gui_path = os.path.join(BASE_DIR, 'golf_gui.html')
    return send_file(gui_path)  # GUI handles rendering the login form

@app.route('/login', methods=['POST'])
def do_login():
    data     = request.get_json(silent=True) or {}
    username = str(data.get('username', '')).strip()
    password = str(data.get('password', '')).strip()

    user = get_user(username)
    if not user or user.get('password') != password:
        return jsonify({'error': 'Invalid member number or password'}), 401

    session.permanent = True
    session['username'] = username
    session['password'] = password
    session['name']     = user.get('name', username)
    print(f"[AUTH] Login: {username} ({user.get('name', '')})")
    return jsonify({'status': 'ok', 'name': user.get('name', username)})

@app.route('/logout', methods=['POST'])
def do_logout():
    username = current_user()
    session.clear()
    print(f"[AUTH] Logout: {username}")
    return jsonify({'status': 'ok'})

@app.route('/signup', methods=['POST'])
def do_signup():
    if not INVITE_CODE:
        return jsonify({'error': 'Sign-up is not enabled on this server.'}), 403

    data        = request.get_json(silent=True) or {}
    username    = str(data.get('username', '')).strip()
    password    = str(data.get('password', '')).strip()
    name        = str(data.get('name', '')).strip()
    invite_code = str(data.get('invite_code', '')).strip()

    if not all([username, password, name, invite_code]):
        return jsonify({'error': 'All fields are required.'}), 400
    if invite_code != INVITE_CODE:
        return jsonify({'error': 'Invalid invite code.'}), 403

    users = load_users()
    if str(username) in users:
        return jsonify({'error': 'That member number is already registered.'}), 409
    if len(users) >= MAX_USERS:
        return jsonify({'error': f'Maximum number of users ({MAX_USERS}) reached.'}), 403

    # Save new user — write back to users file or build updated USERS_JSON
    users[str(username)] = {'password': password, 'name': name}

    # Try to persist to users.json (works locally or with a disk mount)
    try:
        os.makedirs(os.path.dirname(USERS_FILE) or '.', exist_ok=True)
        with open(USERS_FILE, 'w') as f:
            json.dump(users, f, indent=2)
        print(f"[AUTH] New user saved to {USERS_FILE}: {username} ({name})")
    except Exception as e:
        # On free Render tier with no disk, save to /tmp as fallback
        tmp_file = os.path.join('/tmp', 'users_runtime.json')
        with open(tmp_file, 'w') as f:
            json.dump(users, f, indent=2)
        print(f"[AUTH] New user saved to {tmp_file}: {username} ({name})")

    # Auto log in
    session.permanent  = True
    session['username'] = username
    session['password'] = password
    session['name']     = name
    print(f"[AUTH] Sign-up + auto-login: {username} ({name})")
    return jsonify({'status': 'ok', 'name': name})


@app.route('/me')
def me():
    if not current_user():
        return jsonify({'logged_in': False})
    return jsonify({'logged_in': True, 'username': current_user(), 'name': current_name()})

# ── Main app routes (all protected) ─────────────────────────────────────────
@app.route('/')
@require_login
def index():
    gui_path = os.path.join(BASE_DIR, 'golf_gui.html')
    return send_file(gui_path)

@app.route('/events')
@require_login
def get_events():
    try:
        import json as _json
        script_path = os.path.join(BASE_DIR, 'golf_fetch_events.py')
        result = subprocess.run([sys.executable, '-u', script_path],
                                capture_output=True, text=True, timeout=120,
                                env=creds_env())
        for line in result.stdout.splitlines():
            if line.startswith('EVENTS_JSON:'):
                return jsonify({'events': _json.loads(line[len('EVENTS_JSON:'):])})
        err = result.stderr.strip() or result.stdout.strip() or 'No output from fetch script'
        return jsonify({'error': err}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timed out fetching events'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/bookings')
@require_login
def get_bookings():
    try:
        import json as _json
        script_path = os.path.join(BASE_DIR, 'golf_fetch_bookings.py')
        result = subprocess.run([sys.executable, '-u', script_path],
                                capture_output=True, text=True, timeout=60,
                                env=creds_env())
        for line in result.stdout.splitlines():
            if line.startswith('BOOKINGS_JSON:'):
                return jsonify({'bookings': _json.loads(line[len('BOOKINGS_JSON:'):])})
            if line.startswith('BOOKINGS_ERROR:'):
                return jsonify({'error': line[len('BOOKINGS_ERROR:'):]}), 500
        return jsonify({'error': result.stderr.strip() or 'No output'}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timed out'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/run', methods=['POST'])
@require_login
def run_script():
    data             = request.get_json(silent=True) or {}
    selected_event   = data.get('event')
    selected_players = data.get('players', [])
    job_id           = data.get('job_id') or str(uuid.uuid4())
    # Capture creds at request time so the thread has them
    env_snapshot = creds_env()

    with jobs_lock:
        if job_id in jobs and jobs[job_id]['running']:
            return jsonify({'error': f'Job {job_id} already running'}), 400
        q = queue.Queue()
        jobs[job_id] = {'queue': q, 'process': None, 'running': True}

    def run():
        script_path = os.path.join(BASE_DIR, 'golf_booking.py')
        env = env_snapshot.copy()
        if selected_event:
            env['SELECTED_EVENT_TITLE']    = selected_event.get('title', '')
            env['SELECTED_EVENT_DATE_ISO'] = selected_event.get('date_iso', '')
            env['SELECTED_EVENT_STATUS']   = selected_event.get('status', 'OPEN')
            env['SELECTED_EVENT_ID']       = selected_event.get('event_id', '')
        if selected_players:
            env['SELECTED_PLAYERS'] = ','.join(selected_players)
        try:
            proc = subprocess.Popen(
                [sys.executable, '-u', script_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env
            )
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]['process'] = proc
            for line in proc.stdout:
                with jobs_lock:
                    if job_id in jobs:
                        jobs[job_id]['queue'].put(line.rstrip())
            proc.wait()
        except Exception as e:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]['queue'].put(f"❌ Failed: {e}")
        finally:
            with jobs_lock:
                if job_id in jobs:
                    jobs[job_id]['queue'].put('__DONE__')
                    jobs[job_id]['running'] = False

    threading.Thread(target=run, daemon=True).start()
    return jsonify({'status': 'started', 'job_id': job_id})

@app.route('/stream/<job_id>')
@require_login
def stream(job_id):
    with jobs_lock:
        job = jobs.get(job_id)

    def empty():
        yield "data: __DONE__\n\n"

    if not job:
        return Response(empty(), mimetype='text/event-stream')

    q = job['queue']
    def generate():
        while True:
            try:
                line = q.get(timeout=700)
                if line == '__DONE__':
                    yield "data: __DONE__\n\n"
                    break
                yield f"data: {line}\n\n"
            except queue.Empty:
                yield "data: __TIMEOUT__\n\n"
                break

    return Response(generate(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/members/cached')
@require_login
def get_members_cached():
    try:
        if os.path.exists(MEMBERS_CACHE_FILE):
            with open(MEMBERS_CACHE_FILE) as f:
                data = json.load(f)
            return jsonify({'members': data.get('members', []), 'cached': True,
                            'cached_at': data.get('cached_at', '')})
        return jsonify({'members': [], 'cached': False})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/members')
@require_login
def get_members():
    try:
        script_path = os.path.join(BASE_DIR, 'golf_fetch_members.py')
        result = subprocess.run(
            [sys.executable, '-u', script_path],
            capture_output=True, text=True, timeout=180,
            env=creds_env()
        )
        for line in result.stdout.splitlines():
            if line.startswith('MEMBERS_JSON:'):
                return jsonify({'members': json.loads(line[len('MEMBERS_JSON:'):])})
            if line.startswith('MEMBERS_ERROR:'):
                return jsonify({'error': line[len('MEMBERS_ERROR:'):]}), 500
        err = result.stderr.strip() or result.stdout.strip() or 'No output from members script'
        return jsonify({'error': err}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timed out fetching members'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/members/stream')
@require_login
def stream_members():
    env_snapshot = creds_env()

    def generate():
        script_path = os.path.join(BASE_DIR, 'golf_fetch_members.py')
        try:
            proc = subprocess.Popen(
                [sys.executable, '-u', script_path],
                stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                text=True, bufsize=1, env=env_snapshot
            )
            for line in proc.stdout:
                line = line.rstrip()
                if line:
                    yield "data: " + line + "\n\n"
            proc.wait()
        except Exception as e:
            yield "data: MEMBERS_ERROR:" + str(e) + "\n\n"
        finally:
            yield "data: __DONE__\n\n"

    def generate_and_cache():
        for chunk in generate():
            if chunk.startswith("data: MEMBERS_JSON:"):
                try:
                    members = json.loads(chunk[len("data: MEMBERS_JSON:"):].rstrip())
                    from datetime import datetime
                    cache = {'members': members, 'cached_at': datetime.now().strftime('%Y-%m-%d %H:%M')}
                    with open(MEMBERS_CACHE_FILE, 'w') as f:
                        json.dump(cache, f)
                    print(f"[MEMBERS] Cached {len(members)} members")
                except Exception as ce:
                    print(f"[MEMBERS] Cache write error: {ce}")
            yield chunk

    return Response(generate_and_cache(), mimetype='text/event-stream',
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no'})

@app.route('/members/search')
@require_login
def search_members():
    q = request.args.get('q', '').strip().lower()
    if not q or len(q) < 2:
        return jsonify({'members': []})
    try:
        if os.path.exists(MEMBERS_CACHE_FILE):
            with open(MEMBERS_CACHE_FILE) as f:
                data = json.load(f)
            members = data.get('members', [])
            matched = [m for m in members if q in (m.get('name') or m).lower()]
            return jsonify({'members': matched[:20]})
        return jsonify({'members': [], 'no_cache': True})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/preferences', methods=['GET', 'POST'])
@require_login
def preferences():
    if request.method == 'GET':
        try:
            if os.path.exists(prefs_file()):
                with open(prefs_file()) as f:
                    return jsonify(json.load(f))
        except Exception as e:
            print(f'[PREFS] GET error: {e}')
        return jsonify({'always': [], 'never': []})
    try:
        data = request.get_json(silent=True) or {}
        prefs = {'always': data.get('always', []), 'never': data.get('never', [])}
        os.makedirs(os.path.dirname(prefs_file()) or '.', exist_ok=True)
        with open(prefs_file(), 'w') as f:
            json.dump(prefs, f, indent=2)
        print(f"[PREFS] Saved for {current_user()}: always={len(prefs['always'])}, never={len(prefs['never'])}")
        return jsonify({'status': 'saved'})
    except Exception as e:
        print(f'[PREFS] POST error: {e}')
        return jsonify({'error': str(e)}), 500

@app.route('/cancel/<job_id>', methods=['POST'])
@require_login
def cancel_job(job_id):
    with jobs_lock:
        job = jobs.get(job_id)
    if not job:
        return jsonify({'error': 'Not found'}), 404
    proc = job.get('process')
    if proc:
        try: proc.terminate()
        except Exception: pass
    with jobs_lock:
        if job_id in jobs:
            jobs[job_id]['running'] = False
            jobs[job_id]['queue'].put('__DONE__')
    return jsonify({'status': 'cancelled'})

@app.route('/debug')
def debug():
    import shutil, traceback
    checks = {}
    checks['CHROME_BIN'] = os.environ.get('CHROME_BIN', 'not set')
    checks['which_chromium'] = shutil.which('chromium') or 'not found'
    checks['which_chromedriver'] = shutil.which('chromedriver') or 'not found'
    # Version strings
    for binary in ['/usr/bin/chromium', '/usr/bin/chromedriver']:
        if os.path.exists(binary):
            try:
                r = subprocess.run([binary, '--version'], capture_output=True, text=True, timeout=5)
                checks[f'{os.path.basename(binary)}_version'] = r.stdout.strip() or r.stderr.strip()
            except Exception as e:
                checks[f'{os.path.basename(binary)}_version'] = f'error: {e}'
    # Try actually launching Chrome via Selenium
    try:
        from selenium import webdriver
        from selenium.webdriver.chrome.options import Options
        opts = Options()
        opts.add_argument('--headless=new')
        opts.add_argument('--no-sandbox')
        opts.add_argument('--disable-dev-shm-usage')
        opts.add_argument('--disable-gpu')
        opts.add_argument('--no-zygote')
        opts.add_argument('--disable-setuid-sandbox')
        opts.binary_location = '/usr/bin/chromium'
        driver = webdriver.Chrome(options=opts)
        driver.quit()
        checks['selenium_launch'] = 'OK'
    except Exception as e:
        checks['selenium_launch'] = f'FAILED: {e}'
        checks['selenium_traceback'] = traceback.format_exc()
    # Check if rosevillegolf.com.au is reachable
    try:
        import urllib.request
        req = urllib.request.urlopen('https://www.rosevillegolf.com.au', timeout=10)
        checks['roseville_reachable'] = f'OK ({req.status})'
    except Exception as e:
        checks['roseville_reachable'] = f'FAILED: {e}'
    return jsonify(checks)

if __name__ == '__main__':
    print("🏌️  Roseville Golf Booking GUI")
    print("   Open http://127.0.0.1:5001 in your browser")
    print("   Press Ctrl+C to stop\n")
    app.run(host='0.0.0.0', port=5001, debug=False, threaded=True)
