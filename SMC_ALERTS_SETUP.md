# SMC Alerts Setup Guide

## Overview

SMC (Smart Money Concepts) alerts notify you on Telegram when high-scoring SMC opportunities are detected in the SMC Radar. These alerts are separate from ORB breakout alerts but use the same Telegram bot and channel.

---

## Features

✅ **Separate from ORB alerts** - SMC and ORB alerts work independently  
✅ **Configurable threshold** - Set your own minimum score (default: 70)  
✅ **Same Telegram channel** - Uses your existing Telegram bot setup  
✅ **Automatic deduplication** - One alert per stock per day  
✅ **Quiet hours support** - Respects your configured quiet time  
✅ **Real-time notifications** - Alert arrives within ~20 seconds of detection  

---

## Setup Instructions

### Step 1: Database Migration

Run the migration to add SMC alert columns:

```bash
sqlite3 data/app.db < server/migrations/add_smc_alerts.sql
```

**What this does:**
- Adds `smc_alerts_enabled` column (default: OFF)
- Adds `smc_min_score` column (default: 70)

### Step 2: Restart Backend Server

```bash
# Stop your current server
# Then restart it
python3 launch.py run
# Or however you normally start the server
```

### Step 3: Configure in UI

1. **Navigate to Alerts page** in your app
2. Find the **"SMC Alerts"** panel
3. **Turn ON** the toggle switch
4. **Set minimum score** (recommended: 70-85)
   - 70-75: More alerts, includes good setups
   - 75-85: Fewer alerts, only very strong setups
   - 85+: Very rare, only exceptional opportunities
5. Click **"Save SMC alerts"**

### Step 4: Test (Optional)

The regular "Send test" button sends an ORB alert. To verify SMC alerts work:

1. Make sure SMC Radar tab is showing opportunities
2. Wait for the alert sweep (runs every ~20 seconds)
3. Check your Telegram for SMC opportunity alerts

---

## Alert Message Format

```
🚨 SMC OPPORTUNITY ALERT

📈 RELIANCE
💰 Price: ₹2,815.50
🔴 Zone: PREMIUM
⭐ Score: 78/100
📊 Structure: BEARISH BOS
📍 Levels: Strong High: 2,820.00, Weak Low: 2,780.00
📦 Order Blocks: 2 detected

💡 In premium zone near strong high - potential reversal

🕐 20 Nov 2026, 02:30 PM IST
```

**Icons:**
- 🔴 = Premium zone (bearish opportunity)
- 🟢 = Discount zone (bullish opportunity)
- 🟡 = Equilibrium zone (neutral)

---

## How It Works

### Detection Flow

```
1. SMC Engine detects opportunity (score ≥ 35)
   ↓
2. Alert scheduler checks every 20 seconds
   ↓
3. Filters opportunities by user's smc_min_score
   ↓
4. Checks if already alerted today (dedup)
   ↓
5. Sends Telegram message
   ↓
6. Records in alert_deliveries table
```

### Deduplication

- **One alert per stock per day**
- Uses `symbol` + `SMC` as the dedup key
- Stored in `alert_deliveries` table
- Resets daily at midnight IST

### Freshness

Only fresh opportunities trigger alerts:
- Opportunity must be currently active
- SMC opportunities don't age out like ORB signals
- As long as score ≥ threshold, it's eligible

---

## Configuration Options

### Minimum Score Settings

| Score Range | Description | Use Case |
|-------------|-------------|----------|
| **35-50** | Low threshold | Testing/learning mode |
| **50-65** | Moderate | Active day trading |
| **70-80** | High quality | Recommended for most users ✅ |
| **80-90** | Very selective | Conservative traders |
| **90-100** | Exceptional only | Rare, perfect setups |

### Score Components

SMC score is calculated from 6 factors:
- Zone Proximity (0-35 pts)
- Key Level Proximity (0-30 pts)
- Order Blocks (0-20 pts)
- Fair Value Gap (0-15 pts)
- Structure (0-10 pts)
- Recency (-5 to +15 pts)

**Total: 0-100 (capped)**

---

## Troubleshooting

### No Alerts Received

**Check 1: Is SMC alerts enabled?**
```
- Go to Alerts page
- Check if SMC Alerts toggle is ON
- Verify smc_min_score is reasonable (70-80)
```

**Check 2: Are there qualifying opportunities?**
```
- Open SMC Radar tab
- Check if any stocks show score ≥ your threshold
- If all scores < 70 and your threshold is 70, no alerts will fire
```

**Check 3: Already alerted today?**
```
- Check "Recently sent" section in Alerts page
- If you see the stock with state='SMC', it already alerted
- Each stock only alerts once per day
```

**Check 4: Telegram setup correct?**
```
- Test with regular ORB alert first
- If ORB alerts work, SMC alerts will too (same channel)
- Check bot is still in the Telegram group
```

**Check 5: Scanner running?**
```
- SMC alerts only work when scanner is running
- Check if SMC Radar tab shows "offline"
- Restart scanner if needed
```

### Too Many Alerts

**Solution 1: Raise the threshold**
```
Current: 70 → Try: 80
This will cut alerts significantly
```

**Solution 2: Use quiet hours**
```
Set quiet_from: "09:00"
Set quiet_to: "10:00"
No alerts during opening volatility
```

**Solution 3: Temporarily disable**
```
Turn OFF the SMC Alerts toggle
Alerts pause immediately
No need to change Telegram setup
```

---

## Database Schema

### alert_configs table

```sql
-- New columns added by migration
smc_alerts_enabled INTEGER DEFAULT 0   -- 0=OFF, 1=ON
smc_min_score INTEGER DEFAULT 70       -- Threshold (35-100)
```

### alert_deliveries table

```sql
-- Reuses existing table structure
-- For SMC alerts:
-- - symbol: stock symbol (e.g. "NSE:RELIANCE-EQ")
-- - side: empty string ""
-- - state: "SMC"
-- - day: trading day YYYY-MM-DD
-- Unique constraint prevents duplicate alerts
```

---

## API Endpoints

### GET /api/alerts
```json
{
  "smc_alerts_enabled": false,
  "smc_min_score": 70,
  ...other alert config...
}
```

### PUT /api/alerts
```json
{
  "smc_alerts_enabled": true,
  "smc_min_score": 75,
  ...other fields...
}
```

---

## Code Changes Summary

### Backend

1. **server/models.py**
   - Added `smc_alerts_enabled` column
   - Added `smc_min_score` column

2. **server/alerting.py**
   - Added `_format_smc_alert()` function
   - Updated `dispatch()` to send SMC alerts
   - Updated `sweep()` to fetch SMC opportunities

3. **server/routers/alerts.py**
   - Updated GET endpoint to return SMC config
   - Updated PUT endpoint to save SMC config

### Frontend

4. **web/src/Alerts.jsx**
   - Added SMC Alerts panel
   - Added toggle switch
   - Added score input field
   - Updated payload to include SMC config

### Migration

5. **server/migrations/add_smc_alerts.sql**
   - SQL script to add new columns

---

## Best Practices

### For Day Traders

```
smc_min_score: 70-75
quiet_hours: None (or during lunch 12:00-13:00)
Result: ~5-10 alerts per day
```

### For Swing Traders

```
smc_min_score: 80-85
quiet_hours: 09:00-10:00 (avoid opening noise)
Result: ~2-5 alerts per day
```

### For Conservative Traders

```
smc_min_score: 85-90
quiet_hours: Full day except 14:00-15:00
Result: ~1-2 alerts per day
```

---

## Example Workflow

**Morning:**
1. Enable SMC alerts at 9:00 AM
2. Set threshold to 75
3. Scanner starts, detects opportunities

**During Trading:**
1. RELIANCE hits Premium zone, score 78
2. Alert fires to Telegram within 20 seconds
3. You review the setup in SMC Radar tab
4. Decide whether to trade

**End of Day:**
1. Check "Recently sent" to see all alerts
2. Review which ones you traded
3. Adjust threshold for tomorrow if needed

---

## FAQ

**Q: Can I use different Telegram channels for ORB and SMC?**  
A: Not yet. Both use the same channel configured in Telegram settings.

**Q: Will I get duplicate alerts?**  
A: No. Each stock only alerts once per day for SMC opportunities.

**Q: What happens if score drops below threshold after alert?**  
A: Nothing. Alert was sent when score was high. No "cancel" alert is sent.

**Q: Can I alert on score changes (e.g., score went from 65 to 80)?**  
A: Not yet. Current logic only alerts once when score first crosses threshold.

**Q: Does this work in simulation mode?**  
A: Yes! Alerts include "🧪 PRACTICE MODE" banner when in simulation.

**Q: Can I disable ORB alerts but keep SMC alerts?**  
A: Yes! Use the ORB "Alerts" toggle for ORB, SMC toggle for SMC. Independent.

---

## Support

If you encounter issues:
1. Check the troubleshooting section above
2. Verify migration ran successfully
3. Check browser console for errors
4. Check server logs for alert sweep errors

---

## Future Enhancements

Potential features to add later:
- [ ] Separate Telegram channel for SMC alerts
- [ ] Alert on specific zones only (Premium/Discount)
- [ ] Alert on score increase (e.g., +10 points)
- [ ] Custom message templates
- [ ] Email/SMS channels
- [ ] Per-stock score thresholds
- [ ] Time-of-day filters (e.g., only afternoon)

---

**Last Updated:** 20 Nov 2026  
**Version:** 1.0
