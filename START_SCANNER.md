# Start the Scanner - Complete Guide

## ✅ Issue Identified

**Scanner is NOT running!**

- Debug tab works ✓ (on-demand analysis)
- SMC Radar empty ✗ (needs live scanner)
- ORB Radar empty ✗ (needs live scanner)

```
Port 8765: Connection refused
Port 8080: Connection refused
```

---

## 🚀 How to Start the Scanner

### Option 1: Start via Web UI (Recommended)

**If using the web application:**

1. **Start backend server:**
   ```bash
   cd /Users/raunakladha/Documents/rockstar-radar
   python3 launch.py app
   ```

2. **Open browser:** http://127.0.0.1:8765

3. **Login** with your Google account

4. **Connect broker** (FYERS)
   - Go to Settings → Broker
   - Login to FYERS
   - Authorization happens automatically

5. **Scanner auto-starts** when you open:
   - ORB Radar tab, OR
   - SMC Radar tab

6. **Wait for warmup** (30-60 seconds)
   - Status shows "Warming up..."
   - Then "Live" appears

---

### Option 2: Start via CLI (For local dev)

**If testing locally:**

```bash
cd /Users/raunakladha/Documents/rockstar-radar

# Step 1: Login to FYERS (if not already logged in today)
python3 launch.py login

# Step 2: Start the scanner
python3 launch.py run
```

**Expected output:**
```
Universe: NIFTY 500
Selection: 100 stocks prepared
Warming up — 0/100 symbols ready
Warming up — 50/100 symbols ready
✓ All systems ready
Listening on http://127.0.0.1:8765
```

---

## 🔍 Verify Scanner is Running

### Check 1: Process Check
```bash
ps aux | grep "launch.py run" | grep -v grep
```

**Should show:**
```
raunakladha  12345  python3 launch.py run
```

### Check 2: Port Check
```bash
lsof -i :8765
```

**Should show:**
```
COMMAND   PID         USER
Python    12345       raunakladha
```

### Check 3: API Check
```bash
curl http://127.0.0.1:8765/api/state
```

**Should return JSON** with ORB signals.

### Check 4: SMC Check
```bash
curl http://127.0.0.1:8765/api/smc-state
```

**Should return JSON** with SMC opportunities.

---

## 📊 What Happens When Scanner Starts

### 1. Selection Phase (10-20 seconds)
```
Fetching NIFTY 500 universe...
Filtering by liquidity and ATR...
Selected 100 stocks for scanning
```

### 2. Warmup Phase (30-60 seconds)
```
Loading historical data for SMC analysis...
Detecting swing pivots...
Identifying order blocks...
Calculating SMC scores...

Warming up — 0/100 symbols ready
Warming up — 25/100 symbols ready
Warming up — 50/100 symbols ready
Warming up — 75/100 symbols ready
✓ All symbols ready
```

### 3. Live Phase
```
✓ Scanner is live
✓ SMC engine active
✓ Processing ticks...

SMC opportunities: 8 found
ORB signals: 3 found
```

---

## 🎯 Expected Results After Starting

### SMC Radar Tab
```
Before: Empty (no scanner)
After:  5-15 opportunities showing
        Scores: 32, 45, 58, 73, 81
        Updates every ~2 seconds
```

### ORB Radar Tab
```
Before: Empty (no scanner)
After:  Shows CONFIRMED, RETEST_READY signals
        Updates in real-time
```

### Debug Tab
```
Before: Works (on-demand)
After:  Still works (independent)
```

---

## ⚠️ Common Issues

### Issue 1: "Token expired"
```bash
# Re-login to FYERS
python3 launch.py login
```

### Issue 2: "Selection not found"
```bash
# Prepare selection first
python3 launch.py prepare
# Then start
python3 launch.py run
```

### Issue 3: "Port already in use"
```bash
# Find what's using port 8765
lsof -i :8765
# Kill it
kill <PID>
# Then restart
python3 launch.py run
```

### Issue 4: "No data available"
```bash
# Market closed or outside hours
# Wait for market open (9:15 AM IST)
```

### Issue 5: Scanner crashes on startup
```bash
# Check logs
tail -f data/scanner*.out

# Common causes:
# - No internet connection
# - FYERS API down
# - Rate limited (wait 1 minute)
```

---

## 🔧 Troubleshooting Script

Run this to diagnose scanner issues:

```bash
#!/bin/bash
echo "Scanner Diagnostic"
echo "=================="

echo -n "Scanner process: "
if ps aux | grep -q "[l]aunch.py run"; then
    echo "✓ Running"
else
    echo "✗ Not running"
fi

echo -n "Port 8765: "
if lsof -i :8765 > /dev/null 2>&1; then
    echo "✓ Open"
else
    echo "✗ Closed"
fi

echo -n "ORB API: "
if curl -s http://127.0.0.1:8765/api/state > /dev/null 2>&1; then
    echo "✓ Responding"
else
    echo "✗ Not responding"
fi

echo -n "SMC API: "
if curl -s http://127.0.0.1:8765/api/smc-state > /dev/null 2>&1; then
    echo "✓ Responding"
    COUNT=$(curl -s http://127.0.0.1:8765/api/smc-state | python3 -c "import json,sys; print(len(json.load(sys.stdin).get('opportunities', [])))")
    echo "  Opportunities: $COUNT"
else
    echo "✗ Not responding"
fi
```

Save as `check_scanner.sh` and run:
```bash
chmod +x check_scanner.sh
./check_scanner.sh
```

---

## 📝 Start Scanner Checklist

- [ ] Stop any old scanner process
- [ ] Login to FYERS (if new day)
- [ ] Check internet connection
- [ ] Check market hours (9:15-15:30 IST)
- [ ] Run: `python3 launch.py run`
- [ ] Wait for "All symbols ready"
- [ ] Open browser to SMC Radar tab
- [ ] Verify opportunities showing
- [ ] Check console for errors

---

## 🎬 Quick Start Commands

### Fresh Start (New Day)
```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 launch.py login
python3 launch.py run
# Open http://127.0.0.1:8765
```

### Restart (Already logged in)
```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 launch.py run
```

### Web App (Production)
```bash
cd /Users/raunakladha/Documents/rockstar-radar
python3 launch.py app
# Open http://127.0.0.1:8080
# Login → Connect broker → Scanner auto-starts
```

---

## 📞 Still Not Working?

If scanner won't start after following these steps:

1. **Check logs:**
   ```bash
   tail -100 data/scanner*.out
   ```

2. **Check FYERS status:**
   ```bash
   python3 launch.py doctor
   ```

3. **Force clean restart:**
   ```bash
   # Kill everything
   pkill -f "launch.py"
   
   # Remove locks
   rm data/.fyers_api*.lock
   
   # Remove PID files
   rm data/.scanner*.pid
   
   # Start fresh
   python3 launch.py run
   ```

4. **Share the error:**
   - Copy the error message from terminal
   - Check `data/scanner*.out` for stack traces
   - Share with developer

---

## ✅ Success Indicators

When scanner is working correctly:

```
Terminal:
  ✓ "All symbols ready"
  ✓ No error messages
  ✓ Process stays running

Browser SMC Radar:
  ✓ Shows 5-15 opportunities
  ✓ Scores visible (25-100)
  ✓ Updates every 2-3 seconds
  ✓ No "offline" message

Browser ORB Radar:
  ✓ Shows signals
  ✓ Live feed connected
  ✓ Ticks updating

Debug Tab:
  ✓ Stock analysis works
  ✓ Scores showing
  ✓ Pivots detected
```

---

**TL;DR:** Run `python3 launch.py run` and wait for "All symbols ready" message! 🚀
