# 🔧 Local Development Setup Guide

## ⚠️ Security First

**NEVER commit or share your credentials!**
- ✅ `.env` is already in `.gitignore` (safe)
- ✅ Edit `.env` file directly on your machine
- ❌ Do NOT paste credentials in chat/email/Slack
- ❌ Do NOT commit `.env` to git

---

## 📋 Prerequisites

1. **FYERS Account** with API access
2. **FYERS App Created** on [FYERS API Dashboard](https://myapi.fyers.in/dashboard)
3. Python 3.9+ installed
4. Node.js 16+ installed (for frontend)

---

## 🔑 Step 1: Get Your FYERS Credentials

### A. Login to FYERS API Dashboard
1. Go to: https://myapi.fyers.in/dashboard
2. Login with your FYERS credentials

### B. Create or View Your App
1. Click "Create App" or select existing app
2. You'll need these 3 values:

```
App ID:          e.g., ABCD1234-100
App Secret:      e.g., XYZ789ABC...
Redirect URL:    http://127.0.0.1:8765/
```

**Important:** The redirect URL should be `http://127.0.0.1:8765/` for local development.

---

## 📝 Step 2: Update Your `.env` File

Edit your local `.env` file and add/update these lines:

```bash
# Open .env file
nano .env   # or use any text editor
```

Add these variables (replace with YOUR actual values):

```bash
# --- FYERS Broker Credentials ---
FYERS_APP_ID=YOUR_APP_ID_HERE
FYERS_APP_SECRET=YOUR_APP_SECRET_HERE
FYERS_REDIRECT_URI=http://127.0.0.1:8765/

# Keep DEV_LOGIN enabled for local development
DEV_LOGIN=1
```

**Example (DO NOT use these values - they're fake):**
```bash
FYERS_APP_ID=ABCD1234-100
FYERS_APP_SECRET=XYZ789ABCDEF123456
FYERS_REDIRECT_URI=http://127.0.0.1:8765/
DEV_LOGIN=1
```

Save and close the file.

---

## 🚀 Step 3: Run the Login Flow

### A. Generate Login URL
```bash
python launch.py login-url
```

This will output a URL like:
```
https://api-t1.fyers.in/api/v3/generate-authcode?client_id=ABCD1234-100&...
```

### B. Complete Login in Browser
1. Copy the entire URL from terminal
2. Paste it in your browser
3. Login with your FYERS credentials
4. FYERS will redirect you to: `http://127.0.0.1:8765/?auth_code=...`
5. **Copy the ENTIRE redirect URL** (including `?auth_code=...`)

### C. Finish Login
```bash
python launch.py login-finish "PASTE_THE_FULL_REDIRECT_URL_HERE"
```

Example:
```bash
python launch.py login-finish "http://127.0.0.1:8765/?auth_code=eyJ0eXAiOiJKV1..."
```

This will:
- Exchange the auth code for an access token
- Save `FYERS_ACCESS_TOKEN` to your `.env` file
- Token expires daily (need to re-login each trading day)

---

## ✅ Step 4: Verify Setup

```bash
# Test FYERS connection
python launch.py doctor

# Should show:
# ✓ FYERS connection OK
# ✓ Can fetch data
```

---

## 🏃 Step 5: Start the Application

### Option 1: Start Everything (Recommended)
```bash
# This starts both backend and frontend
python launch.py app
```

Then open: http://localhost:5173

### Option 2: Manual Start (Advanced)

**Terminal 1 - Backend:**
```bash
python launch.py app --port 8000
```

**Terminal 2 - Frontend:**
```bash
cd web
npm install  # First time only
npm run dev
```

Then open: http://localhost:5173

---

## 🧪 Step 6: Test the Features

### A. Test ORB Radar
1. Go to: http://localhost:5173/radar
2. Should show "Broker connected" or "Need login"

### B. Test SMC Radar
1. Go to: http://localhost:5173/smc-radar
2. Should load when scanner is running

### C. Test Debug Radar (NEW)
1. Go to: http://localhost:5173/debug
2. Enter stock symbol: `RELIANCE`
3. Click "Analyze Stock"
4. Should fetch and analyze data

---

## 🔄 Daily Login (SEBI Requirement)

FYERS tokens expire daily. Each trading day:

```bash
# Quick login (interactive)
python launch.py login

# Or 2-step process:
python launch.py login-url
# ... complete in browser ...
python launch.py login-finish "REDIRECT_URL"
```

---

## 🐛 Troubleshooting

### Error: "Missing FYERS_APP_ID"
- Make sure you edited `.env` file
- Remove any comments from env variables
- Check there are no typos in variable names

### Error: "SSL Certificate Verification Error"
- macOS issue with FYERS API
- Run: `pip install --upgrade certifi`
- Or use simulation mode (set `DEV_LOGIN=1`)

### Error: "Invalid redirect URI"
- Check FYERS dashboard: redirect URL must be exactly `http://127.0.0.1:8765/`
- No trailing slashes, no https, no localhost

### Port Already in Use
```bash
# Kill process on port 8000
lsof -ti:8000 | xargs kill -9

# Or use different port
python launch.py app --port 8001
```

---

## 📂 Your `.env` File Template

Here's what your complete `.env` should look like:

```bash
# --- Core (local dev) ---
SESSION_SECRET=change-me-to-a-long-random-string
DEV_LOGIN=1

# --- FYERS Broker Credentials ---
FYERS_APP_ID=YOUR_APP_ID_HERE
FYERS_APP_SECRET=YOUR_APP_SECRET_HERE
FYERS_REDIRECT_URI=http://127.0.0.1:8765/
# FYERS_ACCESS_TOKEN will be auto-filled by login command

# --- Optional (can leave blank for local dev) ---
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
PUBLIC_BASE_URL=
SUPPORT_TELEGRAM_BOT_TOKEN=
SUPPORT_TELEGRAM_CHAT_ID=
```

---

## 🎯 Quick Start Checklist

- [ ] Get FYERS App ID, Secret from dashboard
- [ ] Edit `.env` file with your credentials
- [ ] Run `python launch.py login`
- [ ] Verify with `python launch.py doctor`
- [ ] Start app: `python launch.py app`
- [ ] Open browser: http://localhost:5173
- [ ] Test Debug Radar tab

---

## 🔒 Security Reminders

✅ **DO:**
- Keep `.env` file local only
- Use `DEV_LOGIN=1` for local testing
- Re-login daily (token expires)
- Check `.env` is in `.gitignore`

❌ **DON'T:**
- Commit `.env` to git
- Share credentials in chat
- Push `.env` to GitHub
- Use production tokens locally

---

## 📞 Need Help?

If you encounter issues:
1. Check error message in terminal
2. Verify `.env` file has all required variables
3. Try `python launch.py doctor` to diagnose
4. Check FYERS API dashboard for app status

Happy coding! 🚀
