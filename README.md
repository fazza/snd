# Golf Booking Bot

## Deploying to Render (Free Tier)

### 1. Push to a private GitHub repo
```bash
git init
git add .
git commit -m "Initial deploy"
git remote add origin https://github.com/YOUR_USERNAME/YOUR_REPO.git
git push -u origin main
```

### 2. Create the Render service
1. Go to https://render.com and sign in
2. Click **New → Blueprint**
3. Connect your GitHub account and select your repo
4. Render detects `render.yaml` automatically — click **Apply**
5. First build takes ~5 minutes (installing Chrome)

### 3. Add your users
In the Render dashboard → your service → **Environment** tab, find `USERS_JSON` and set its value to:
```json
{"4291": {"password": "YourPassword", "name": "Your Name"}, "1234": {"password": "theirpassword", "name": "Their Name"}}
```
Then click **Save Changes** — the service will redeploy automatically.

### 4. Open the app
Render gives you a URL like `https://golf-booking-bot.onrender.com`

---

## Free tier trade-offs
- App **sleeps after 15 min** of inactivity — first load after sleeping takes ~30 sec to wake up
- Member cache and preferences are stored in `/tmp` and **reset on each redeploy**
  - Rebuild the member cache from the preferences modal after each redeploy
  - Preferences also reset — re-enter them after each redeploy
- For $7/month the Starter plan adds a persistent disk and avoids all of this

## Running locally
```bash
pip install -r requirements.txt
python3 local_golf_server.py
# Open http://127.0.0.1:5001
```

## Sign-up / Invite codes

Set these two extra environment variables in the Render dashboard:

- `INVITE_CODE` — a secret word/phrase you give to people you want to let in (e.g. `sunday4ball`). Without this set, sign-up is disabled entirely.
- `MAX_USERS` — maximum accounts allowed (default: 4). Sign-up is blocked once this is reached.

New users click **"Create account"** on the login page, enter their member number, club password, name, and your invite code. They're logged in automatically on success.

**Note:** On the free tier (no persistent disk), newly signed-up accounts are stored in `/tmp/users_runtime.json` and will be lost on redeploy. Add them to `USERS_JSON` manually afterwards to make them permanent.
