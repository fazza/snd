#!/usr/bin/env python3
"""
Local server for the SND Bookings GUI.
Supports multiple concurrent booking jobs.
"""

from flask import Flask, Response, jsonify, send_file, request, session, redirect, url_for
from functools import wraps
import subprocess, sys, os, threading, queue, uuid, ssl, certifi, hashlib

app = Flask(__name__)
app.secret_key = os.environ.get('SECRET_KEY', 'rg-booking-secret-2024-xk9')

# ── Passwords (env var overrides, default shown) ──────────────
# Set APP_PASSWORD env var on Render to change it
APP_PASSWORD = os.environ.get('APP_PASSWORD', 'rg2024')

def check_password(pw):
    return pw == APP_PASSWORD

def login_required(f):
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('logged_in'):
            if request.path == '/' or not request.path.startswith('/stream'):
                return redirect(url_for('login_page'))
            return jsonify({'error': 'Unauthorised'}), 401
        return f(*args, **kwargs)
    return decorated

# jobs[job_id] = { 'queue': Queue, 'process': Popen|None, 'running': bool }
jobs = {}
jobs_lock = threading.Lock()

LOGIN_URL         = "https://www.rosevillegolf.com.au/web/pages/login"
BOOK_A_ROUND      = "https://www.rosevillegolf.com.au/group/pages/book-a-round"
USERNAME          = "4291"
PASSWORD          = "NewcastleTaree1!"
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
        if ex in t: return False
    for inc in INCLUDE_KEYWORDS:
        if inc in t: return True
    return False

def parse_event_date_text(day_name, day_date):
    from datetime import datetime
    year = datetime.now().year
    try:
        dt = datetime.strptime(f"{day_name} {day_date} {year}", "%a %d %b %Y")
        if dt < datetime.now().replace(hour=0, minute=0, second=0):
            dt = datetime.strptime(f"{day_name} {day_date} {year + 1}", "%a %d %b %Y")
        return dt
    except Exception:
        return None

@app.route('/login', methods=['GET', 'POST'])
def login_page():
    error = None
    if request.method == 'POST':
        pw = request.form.get('password', '')
        if check_password(pw):
            session['logged_in'] = True
            return redirect(url_for('index'))
        error = 'Incorrect password'
    # Inline login page — no external file needed
    return f"""<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>SND Bookings — Login</title>
  <link href="https://fonts.googleapis.com/css2?family=Playfair+Display:wght@600&family=Lato:wght@300;400&display=swap" rel="stylesheet">
  <style>
    *{{box-sizing:border-box;margin:0;padding:0}}
    :root{{--gold:#c9a84c;--green-dark:#1a2e1a;--green-mid:#2d4a2d;--cream:#f5f0e8}}
    body{{background:var(--green-dark);min-height:100vh;display:flex;align-items:center;justify-content:center;font-family:'Lato',sans-serif}}
    .card{{background:linear-gradient(160deg,#1f361f,#162816);border:1px solid rgba(201,168,76,0.25);border-radius:16px;padding:48px 44px;width:360px;box-shadow:0 24px 64px rgba(0,0,0,0.5)}}
    .flag{{font-size:2.4rem;text-align:center;margin-bottom:12px}}
    h1{{font-family:'Playfair Display',serif;color:var(--cream);font-size:1.5rem;text-align:center;margin-bottom:4px}}
    .sub{{font-size:0.72rem;letter-spacing:0.2em;text-transform:uppercase;color:var(--gold);text-align:center;margin-bottom:32px}}
    label{{display:block;font-size:0.65rem;letter-spacing:0.18em;text-transform:uppercase;color:var(--gold);margin-bottom:8px}}
    input[type=password]{{width:100%;background:rgba(0,0,0,0.3);border:1px solid rgba(201,168,76,0.3);border-radius:8px;color:var(--cream);font-size:1rem;padding:12px 14px;outline:none;transition:border 0.2s}}
    input[type=password]:focus{{border-color:var(--gold)}}
    button{{width:100%;margin-top:20px;background:linear-gradient(135deg,var(--green-mid),#3d6b3d);border:1px solid var(--gold);color:var(--cream);font-size:0.8rem;letter-spacing:0.15em;text-transform:uppercase;padding:13px;border-radius:8px;cursor:pointer;transition:all 0.2s}}
    button:hover{{background:linear-gradient(135deg,#3d6b3d,#5aaa70);box-shadow:0 0 20px rgba(74,140,92,0.3)}}
    .error{{margin-top:14px;padding:10px 14px;background:rgba(200,80,80,0.15);border:1px solid rgba(200,80,80,0.4);border-radius:8px;color:#e08080;font-size:0.8rem;text-align:center}}
  </style>
</head>
<body>
  <div class="card">
    <div class="flag">⛳</div>
    <h1>SND Bookings</h1>
    <div class="sub">Tee Time Booking</div>
    <form method="POST" action="/login">
      <label for="pw">Password</label>
      <input type="password" id="pw" name="password" placeholder="Enter password" autofocus>
      <button type="submit">Sign In</button>
      {'<div class="error">' + error + '</div>' if error else ''}
    </form>
  </div>
</body>
</html>"""

@app.route('/logout')
def logout():
    session.clear()
    return redirect(url_for('login_page'))

@app.route('/')
@login_required
def index():
    gui_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_golf_gui.html')
    return send_file(gui_path)

@app.route('/events')
@login_required
def get_events():
    try:
        import json as _json
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_golf_fetch_events.py')
        result = subprocess.run([sys.executable, '-u', script_path],
                                capture_output=True, text=True, timeout=60)
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
@login_required
def get_bookings():
    try:
        import json as _json
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_golf_fetch_bookings.py')
        result = subprocess.run([sys.executable, '-u', script_path],
                                capture_output=True, text=True, timeout=60)
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
@login_required
def run_script():
    data             = request.get_json(silent=True) or {}
    selected_event   = data.get('event')
    selected_players = data.get('players', [])
    job_id           = data.get('job_id') or str(uuid.uuid4())

    with jobs_lock:
        if job_id in jobs and jobs[job_id]['running']:
            return jsonify({'error': f'Job {job_id} already running'}), 400
        q = queue.Queue()
        jobs[job_id] = {'queue': q, 'process': None, 'running': True}

    def run():
        script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_roseville_golf_booking.py')
        env = os.environ.copy()
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
@login_required
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
                    headers={'Cache-Control': 'no-cache', 'X-Accel-Buffering': 'no',
                             'Access-Control-Allow-Origin': '*'})

@app.route('/members')
@login_required
def get_members():
    """Run render_golf_fetch_members.py and return the member list as JSON."""
    script_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'render_golf_fetch_members.py')
    try:
        result = subprocess.run([sys.executable, '-u', script_path],
                                capture_output=True, text=True, timeout=120)
        for line in result.stdout.splitlines():
            if line.startswith('MEMBERS_JSON:'):
                import json
                members = json.loads(line[len('MEMBERS_JSON:'):])
                return jsonify({'members': members})
        return jsonify({'error': 'Could not fetch members', 'detail': result.stderr[-500:]}), 500
    except subprocess.TimeoutExpired:
        return jsonify({'error': 'Timeout fetching members'}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# Preferences stored in a JSON file alongside the server
PREFS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), 'member_preferences.json')

@app.route('/preferences', methods=['GET'])
@login_required
def get_preferences():
    import json
    if os.path.exists(PREFS_FILE):
        with open(PREFS_FILE) as f:
            return jsonify(json.load(f))
    return jsonify({})

@app.route('/preferences', methods=['POST'])
@login_required
def save_preferences():
    import json
    data = request.get_json(silent=True) or {}
    with open(PREFS_FILE, 'w') as f:
        json.dump(data, f, indent=2)
    return jsonify({'status': 'saved'})

@app.route('/cancel/<job_id>', methods=['POST'])
@login_required
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

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5000))
    host = '0.0.0.0'
    print("⛳  SND Bookings")
    print(f"   Open http://{host}:{port} in your browser")
    print(f"   Password: {APP_PASSWORD}")
    print("   Press Ctrl+C to stop\n")
    app.run(host=host, port=port, debug=False, threaded=True)
