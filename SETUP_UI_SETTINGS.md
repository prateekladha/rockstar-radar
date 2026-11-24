# How to Access RVOL and Prerequisite Settings in UI

## ✅ Changes ARE Merged to Main

The changes are committed and merged to main branch (commit 479837b). However, you need to follow these steps to see them in the UI.

---

## 🚀 Step-by-Step Setup

### Step 1: Start the Backend Server

The backend must be running to access the web UI.

```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 launch.py app
```

**Expected Output:**
```
Rockstar Radar Control Center on 127.0.0.1:8765 (this computer only)
INFO:     Started server process [12345]
INFO:     Waiting for application startup.
INFO:     Application startup complete.
```

**Keep this terminal running!**

---

### Step 2: Open Web Browser

```
http://127.0.0.1:8765
```

**You should see:**
- Login page (if first time)
- OR Main dashboard (if already logged in)

---

### Step 3: Login (If Needed)

1. Click **"Sign in with Google"**
2. Complete Google authentication
3. You'll be redirected to the dashboard

---

### Step 4: Open Settings Page

**Option 1: Click the Settings Icon**
- Look for the ⚙️ (gear) icon in the top navigation
- Click it to open Settings page

**Option 2: Direct URL**
```
http://127.0.0.1:8765/settings
```

---

### Step 5: Scroll to Find the New Panels

You should see **THREE new panels** at the bottom of the Settings page:

#### Panel 1: Pre-requisite Checks
```
┌─────────────────────────────────────────┐
│ Pre-requisite Checks                     │
│ Mandatory checks before strategy eval... │
├─────────────────────────────────────────┤
│                                          │
│ Enable RVOL Check         [ON  ]        │
│                                          │
│ Minimum RVOL             [1.0  ]        │
│   Stocks with RVOL below this...        │
│                                          │
│ [Save prerequisite settings]            │
└─────────────────────────────────────────┘
```

#### Panel 2: RVOL Calculation Settings
```
┌─────────────────────────────────────────┐
│ RVOL Calculation Settings                │
│ Configure how Relative Volume is calc... │
├─────────────────────────────────────────┤
│                                          │
│ Anchor Timeframe    [Day (Default)  ▼] │
│   Time period for volume comparison...  │
│                                          │
│ Length (Lookback Period)  [10      ]   │
│   Number of previous periods to...      │
│                                          │
│ Calculation Mode    [Cumulative ▼]     │
│   How to aggregate volume data...       │
│                                          │
│ [Save RVOL settings]                    │
│   ⚠ Scanner restart required            │
└─────────────────────────────────────────┘
```

---

## 📸 Where to Find These Settings

### Full Settings Page Layout:

```
Settings Page
─────────────────────────────────────────

┌─────────────────────────────────────────┐
│ Stocks to scan                           │
│ The group of stocks the radar watches... │
├─────────────────────────────────────────┤
│ Scan this group: [Large caps - Nifty...▼]│
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Strategy & risk                          │
│ Your personal settings                   │
├─────────────────────────────────────────┤
│ Open Range Start: [09:15]               │
│ Watch Start: [09:20]                    │
│ Min Confirm Rvol: [1.5]                 │
│ ... (other strategy settings)           │
│                                          │
│ [Save settings]                         │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ Pre-requisite Checks              ← NEW │
│ Mandatory checks before strategy eval... │
├─────────────────────────────────────────┤
│ Enable RVOL Check: [ON]                 │
│ Minimum RVOL: [1.0]                     │
│ [Save prerequisite settings]            │
└─────────────────────────────────────────┘

┌─────────────────────────────────────────┐
│ RVOL Calculation Settings         ← NEW │
│ Configure how Relative Volume is calc... │
├─────────────────────────────────────────┤
│ Anchor Timeframe: [Day]                 │
│ Length: [10]                            │
│ Calculation Mode: [Cumulative]          │
│ [Save RVOL settings]                    │
└─────────────────────────────────────────┘
```

**Location:** Scroll down to the **bottom** of the Settings page!

---

## 🔧 Troubleshooting

### Issue 1: Backend Not Starting

**Error:** `Address already in use`

**Solution:**
```bash
# Kill existing process
pkill -f "launch.py app"

# Try again
python3 launch.py app
```

---

### Issue 2: Can't See New Panels

**Symptoms:** Settings page doesn't show new panels

**Solutions:**

#### A. Clear Browser Cache
```
Chrome: Ctrl+Shift+R (Windows) or Cmd+Shift+R (Mac)
Firefox: Ctrl+F5 (Windows) or Cmd+Shift+R (Mac)
Safari: Cmd+Option+R
```

#### B. Force Reload
```
1. Open: http://127.0.0.1:8765/settings
2. Press: Ctrl+Shift+R (or Cmd+Shift+R on Mac)
3. Wait for page to fully reload
```

#### C. Check Backend Logs
```bash
# Look for errors in the terminal where backend is running
# You should see:
INFO:     127.0.0.1:XXXXX - "GET /api/prerequisites HTTP/1.1" 200 OK
INFO:     127.0.0.1:XXXXX - "GET /api/rvol-settings HTTP/1.1" 200 OK
```

---

### Issue 3: Settings Won't Save

**Error:** "Failed to load prerequisites" or "Failed to load RVOL settings"

**Cause:** Database tables not created yet

**Solution:**

The backend should auto-create tables on first run. If not, manually run migrations:

```bash
# First, make sure backend has run at least once to create base tables
# Then run migrations:

cd /Users/raunakladha/Documents/rockstar-radar

# Run prerequisite migration
sqlite3 data/app.db < server/migrations/add_prereq_config.sql

# Run RVOL settings migration
sqlite3 data/app.db < server/migrations/add_rvol_settings.sql

# Restart backend
pkill -f "launch.py app"
python3 launch.py app
```

---

### Issue 4: Old UI Still Showing

**Symptoms:** Settings page looks old, no new panels

**Cause:** Browser cached old JavaScript files

**Solution:**
```bash
# 1. Close all browser tabs with the app
# 2. Clear browser cache completely
# 3. Restart browser
# 4. Open app fresh: http://127.0.0.1:8765
```

---

## 🎯 Quick Test

After starting the backend and opening Settings:

### Test 1: Check Pre-requisite Panel Exists
```
1. Scroll down on Settings page
2. Look for "Pre-requisite Checks" heading
3. You should see toggle and input
```

### Test 2: Check RVOL Panel Exists
```
1. Scroll down further
2. Look for "RVOL Calculation Settings" heading
3. You should see 3 dropdowns/inputs
```

### Test 3: Try Saving
```
1. Change Minimum RVOL to 1.5
2. Click "Save prerequisite settings"
3. Should see: "Pre-requisite settings saved"
```

---

## 📸 Visual Guide

### Where to Click:

```
Browser: http://127.0.0.1:8765
         ↓
   [Navigation Bar]
   Dashboard | Radar | Settings ← Click here
         ↓
   [Settings Page]
   - Stocks to scan
   - Strategy & risk
   - Pre-requisite Checks      ← Scroll here (NEW!)
   - RVOL Calculation Settings ← Scroll here (NEW!)
```

---

## ✅ Verification Checklist

After following all steps:

- [ ] Backend is running (`python3 launch.py app`)
- [ ] Browser opened to: http://127.0.0.1:8765
- [ ] Logged in successfully
- [ ] Clicked Settings (gear icon) or went to /settings
- [ ] Scrolled to bottom of Settings page
- [ ] Can see "Pre-requisite Checks" panel
- [ ] Can see "RVOL Calculation Settings" panel
- [ ] Can change values and save
- [ ] Success message appears after save

---

## 🆘 Still Can't See It?

If you've followed all steps and still can't see the new panels:

### Check 1: Verify Code is on Main

```bash
cd /Users/raunakladha/Documents/rockstar-radar
git log --oneline -1

# Should show:
# 479837b feat: add user-configurable RVOL calculation settings
```

### Check 2: Verify Files Exist

```bash
ls server/migrations/add_prereq_config.sql
ls server/migrations/add_rvol_settings.sql

# Both files should exist
```

### Check 3: Check Backend is Responding

```bash
# In another terminal:
curl http://127.0.0.1:8765/api/prerequisites

# Should return JSON with settings
```

### Check 4: Check Browser Console

```
1. Open Settings page
2. Press F12 (open DevTools)
3. Go to Console tab
4. Look for errors (red text)
5. Look for failed API calls
```

---

## 📞 Debug Output

If still having issues, provide this output:

```bash
# 1. Check git status
git log --oneline -1

# 2. Check backend status
ps aux | grep "launch.py app"

# 3. Check if files exist
ls -la server/migrations/*.sql

# 4. Check database
sqlite3 data/app.db ".tables"

# 5. Test API endpoint
curl http://127.0.0.1:8765/api/prerequisites
curl http://127.0.0.1:8765/api/rvol-settings
```

---

## 🎉 Success!

Once you see the panels, you can configure:

**Pre-requisite Checks:**
- Enable/disable RVOL filtering
- Set minimum RVOL threshold (default: 1.0)

**RVOL Calculation:**
- Anchor Timeframe (session/day/week/month)
- Length (1-100, default: 10)
- Calculation Mode (cumulative/per_bar/mean/median)

**Remember:** RVOL settings require scanner restart to apply!

---

**The settings ARE there, just need to:**
1. ✅ Start backend
2. ✅ Open browser
3. ✅ Go to Settings
4. ✅ Scroll down
5. ✅ Configure and save!
