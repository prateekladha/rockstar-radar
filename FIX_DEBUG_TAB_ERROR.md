# Fix Debug Tab -99 Error

## 🔍 Error

```
❌ Error: ApiProviderError: FYERS history returned generic -99: 
Bad request; may be a provider/transport block. Do not retry in a loop.
```

---

## 🎯 Root Cause

**Debug tab needs FYERS credentials from the web app database.**

The error means one of:
1. ❌ Broker not connected in web app
2. ❌ Backend server not running
3. ❌ Token expired (need to re-login)
4. ❌ SSL/transport issue

---

## ✅ Complete Fix (Step by Step)

### Step 1: Start Backend Server

```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 launch.py app
```

**Expected output:**
```
Rockstar Radar Control Center on 127.0.0.1:8765 (this computer only)
INFO:     Started server process [12345]
```

**Keep this terminal running!**

---

### Step 2: Open Web App

Open browser: **http://127.0.0.1:8765**

---

### Step 3: Login with Google

Click **"Sign in with Google"**

---

### Step 4: Connect FYERS Broker

1. Go to **Settings** page
2. Click **"Broker"** section
3. Click **"Connect FYERS"**
4. You'll be redirected to FYERS login
5. Login with your FYERS credentials
6. Authorize the app
7. You'll be redirected back

**Expected:** "✓ FYERS Connected" message

---

### Step 5: Try Debug Tab Again

1. Go to **Debug** tab
2. Search for stock (e.g., "RELIANCE")
3. Should work now! ✅

---

## 🔧 Troubleshooting

### Issue A: "Backend not running"

**Check:**
```bash
ps aux | grep "launch.py app"
```

**If empty:**
```bash
python3 launch.py app
```

---

### Issue B: "Broker connection failed"

**Re-connect:**
1. Settings → Broker → Disconnect
2. Then Connect again
3. Complete FYERS authorization

---

### Issue C: "Still getting -99 error"

**Token expired - re-authorize:**

1. **In web app:**
   - Settings → Broker → Disconnect
   - Settings → Broker → Connect FYERS
   - Complete fresh authorization

2. **Check logs:**
```bash
tail -50 data/scanner*.out
```

3. **Check SSL fix is working:**
```bash
ls ssl_fix.py
# Should exist for local dev

echo $DEV_LOGIN
# Should be "1"
```

---

### Issue D: "SSL certificate error"

**For local development:**

```bash
cd /Users/raunakladha/Documents/rockstar-radar

# Check if ssl_fix.py exists
ls ssl_fix.py

# If missing, you need to create it
# (You had this before, should still be git-ignored)
```

**Then restart backend:**
```bash
# Kill existing
pkill -f "launch.py app"

# Start fresh
export DEV_LOGIN=1
python3 launch.py app
```

---

## 📋 Quick Checklist

- [ ] Backend running (`python3 launch.py app`)
- [ ] Opened http://127.0.0.1:8765
- [ ] Logged in with Google
- [ ] Connected FYERS broker (Settings → Broker)
- [ ] Authorized FYERS (green checkmark visible)
- [ ] Tried debug tab again

---

## 🎯 Understanding How It Works

### CLI Mode (Standalone):
```bash
python3 launch.py login     # Stores token in data/.fyers_access_token
python3 launch.py run       # Uses token from file
```

### Web App Mode (Multi-user):
```
1. User logs in with Google
2. User connects FYERS (stored in database, encrypted)
3. Debug tab uses user's FYERS credentials from database
4. Each user has their own FYERS connection
```

**Debug tab ONLY works in web app mode!**

---

## 💡 Alternative: Use CLI for Testing

If you just want to test locally without the web app:

```bash
# 1. Login via CLI
python3 launch.py login
# Follow prompts, paste redirect URL

# 2. Test debug directly
python3 << 'EOF'
from radar.fyers import FyersAdapter
from radar.debug_analysis import analyze_single_stock
from radar.utils import load_config

adapter = FyersAdapter(load_config())
result = analyze_single_stock(adapter, "RELIANCE", load_config())

if result['success']:
    print(f"✓ Score: {result.get('score_breakdown', {}).get('final_score', 'N/A')}")
    if result.get('opportunity'):
        print(f"  Zone: {result['opportunity']['zone']}")
else:
    print(f"✗ Error: {result.get('error')}")
EOF
```

**This uses CLI credentials, not web app.**

---

## 🚀 Recommended Setup

### For Development:

```bash
# Terminal 1: Backend
cd /Users/raunakladha/Documents/rockstar-radar
export DEV_LOGIN=1
python3 launch.py app

# Browser: http://127.0.0.1:8765
# Login → Connect Broker → Use Debug tab
```

### For Production:

```bash
# Deploy backend (Render/Railway/etc.)
# Users login via Google
# Users connect their own FYERS accounts
# Each user gets isolated debug analysis
```

---

## 📊 Diagnostic Tool

Run this to check everything:

```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 diagnose_fyers.py
```

**Expected output:**
```
1. Environment Check:
   FYERS_APP_ID: ✓ Set
   FYERS_ACCESS_TOKEN: ✓ Set

2. Config Check:
   ✓ Config loaded

3. Adapter Initialization:
   ✓ FyersAdapter created

4. Testing Quotes API:
   ✓ Quotes API working

5. Testing History API:
   ✓ History API working - 150 candles
```

**If you see ✗ marks:** Follow the troubleshooting steps above.

---

## 🎓 Summary

**Debug tab error -99 = Broker not connected in web app**

**Fix:**
1. Start backend: `python3 launch.py app`
2. Open: http://127.0.0.1:8765
3. Login with Google
4. Connect FYERS (Settings → Broker)
5. Try Debug tab again

**Done!** ✅
