# ATR (Average True Range) - Complete Guide

## What is ATR?

**ATR (Average True Range)** is a volatility indicator that measures **how much a stock typically moves** in a given time period (usually 14 candles).

Think of it as: **"On average, this stock moves X rupees per 5-minute candle"**

---

## How to Read ATR Values

### Example 1: Low Volatility Stock
```
Symbol: WIPRO
Current Price: ₹450
ATR (14): 1.20
```

**What this means:**
- On average, WIPRO moves about **₹1.20 per 5-minute candle**
- This is **relatively calm** movement
- Expected daily range: ~₹10-15 (if markets are open 6.25 hours = 75 candles)

### Example 2: High Volatility Stock
```
Symbol: ADANIPORTS
Current Price: ₹1,250
ATR (14): 8.50
```

**What this means:**
- On average, ADANIPORTS moves about **₹8.50 per 5-minute candle**
- This is **much more volatile**
- Expected daily range: ~₹60-70

### Example 3: Very High Volatility
```
Symbol: TATAPOWER
Current Price: ₹420
ATR (14): 15.00
```

**What this means:**
- Moving **₹15 per 5-minute candle** on average
- **Very volatile** - high risk and high reward
- Expected daily range: ~₹100-120

---

## ATR as Percentage (More Useful)

**Raw ATR number doesn't tell the full story** - you need to compare it to the stock's price.

### Formula:
```
ATR% = (ATR / Current Price) × 100
```

### Examples:

| Stock | Price | ATR | ATR% | Interpretation |
|-------|-------|-----|------|----------------|
| WIPRO | ₹450 | 1.20 | **0.27%** | Very calm |
| RELIANCE | ₹2,800 | 10.50 | **0.37%** | Calm |
| TATAPOWER | ₹420 | 15.00 | **3.57%** | Very volatile! |
| ADANIPORTS | ₹1,250 | 8.50 | **0.68%** | Moderate |

**General Guidelines:**
- **< 0.5%** = Low volatility (boring but safer)
- **0.5% - 1.0%** = Moderate volatility (balanced)
- **1.0% - 2.0%** = High volatility (good for day trading)
- **> 2.0%** = Very high volatility (risky but profitable if timed right)

---

## How ATR is Used in Your System

### 1. **Risk Management** 
ATR helps set realistic stop losses:
```
Stop Loss Distance = 1.5 × ATR to 2.0 × ATR
```

**Example:**
- RELIANCE at ₹2,800, ATR = 10.50
- Stop loss: 1.5 × 10.50 = **15.75 points away**
- Buy at ₹2,800 → Stop at ₹2,784.25

### 2. **Target Setting**
ATR helps set achievable targets:
```
Target Distance = 2.0 × ATR to 3.0 × ATR
```

**Example:**
- RELIANCE at ₹2,800, ATR = 10.50
- Target: 2.5 × 10.50 = **26.25 points**
- Buy at ₹2,800 → Target at ₹2,826.25

### 3. **Opportunity Filtering**
Your SMC engine uses ATR to understand if price movements are significant:
```python
# In smc_engine.py
state.atr = calculate_atr(state.candles)
```

When price approaches a key level:
- **Move = 0.5 × ATR** → Minor reaction (ignore)
- **Move = 1.0 × ATR** → Normal reaction (watch)
- **Move = 2.0+ × ATR** → Strong reaction (trade it!)

---

## Real Trading Scenarios

### Scenario 1: Strong High Test
```
Stock: TATASTEEL
Price: ₹1,150
ATR: 5.50
Strong High: ₹1,160

Distance to Strong High: ₹10
Distance in ATR terms: 10 / 5.50 = 1.82 ATR

Interpretation: Price is 1.82 ATR away from resistance.
This is a normal distance - not too close, not too far.
Wait for price to reach 0.5 ATR (₹2.75) from resistance.
```

### Scenario 2: Order Block Reaction
```
Stock: INFY
Price: ₹1,650
ATR: 4.20
Order Block: ₹1,645-₹1,648

Price drops to ₹1,647 (inside OB):
- Initial reaction: +₹2 (0.48 ATR) → Weak, ignore
- Second attempt: +₹5 (1.19 ATR) → Normal, watch
- Third attempt: +₹10 (2.38 ATR) → Strong, take trade!
```

### Scenario 3: Volatility Comparison
```
Morning Session:
  TCS ATR: 3.20 (calm)
  ADANIPORTS ATR: 12.50 (volatile)

Afternoon Session:
  TCS ATR: 5.80 (volatility increased! ⚠️)
  ADANIPORTS ATR: 18.00 (even more wild)

Interpretation: News event or market-wide volatility spike.
Be extra cautious with stop losses.
```

---

## Common Questions

### Q1: Is higher ATR better?
**Not necessarily!**
- **Higher ATR** = More profit potential BUT more risk
- **Lower ATR** = Less risk BUT smaller profits
- **Best**: Match your risk appetite

### Q2: What's a "good" ATR value?
**Depends on the stock price:**
```
For ₹100 stock:  ATR of 1.0-2.0 is normal (1-2%)
For ₹1,000 stock: ATR of 5.0-10.0 is normal (0.5-1%)
For ₹3,000 stock: ATR of 10.0-20.0 is normal (0.3-0.7%)
```

**Better question: What's a good ATR%?**
- Day trading: Look for **0.8% - 1.5%**
- Swing trading: Look for **0.5% - 1.0%**

### Q3: Can ATR predict direction?
**No!** ATR only measures **how much** the stock moves, not **which direction**.

Think of it like:
- ATR = Speed of a car (30 km/h vs 100 km/h)
- Direction = North/South (bullish/bearish)

### Q4: Why does ATR change during the day?
ATR is calculated on the **last 14 candles**, so:
- **Morning**: Less volatile (wider bid-ask, less liquidity)
- **10:30-14:30**: Most volatile (peak trading hours)
- **Afternoon**: Moderate (some traders exit positions)

---

## ATR in Your Debug Tab

When you see:
```
ATR (14): 8.25
```

**Check:**
1. **Is it high or low for this stock?**
   - Calculate: (8.25 / Current Price) × 100 = ATR%
   
2. **Has it increased recently?**
   - Compare to yesterday's ATR
   - Big jump? → Something unusual happening
   
3. **How does it affect my trade?**
   - Stop loss: 1.5 × 8.25 = 12.38 points away
   - Target: 2.5 × 8.25 = 20.63 points away

---

## Pro Tips

### 1. **Compare ATR to Stock's Normal Range**
```python
# Rule of thumb:
Normal ATR% for stock = (52-week high - 52-week low) / 252 days / stock price

If current ATR% is:
  > 2× normal → Extremely volatile (event happening)
  1-2× normal → High volatility (good for trading)
  < 1× normal → Low volatility (might be consolidating)
```

### 2. **Use ATR for Position Sizing**
```
Risk per trade = ₹1,000
Stop loss = 2 × ATR = 2 × 8.50 = 17 points

Shares to buy = ₹1,000 / 17 = 58 shares

This way, you risk the same ₹1,000 regardless of stock volatility.
```

### 3. **ATR Expansion = Opportunity**
```
Normal ATR: 5.50
Suddenly jumps to: 12.00

Meaning: Volatility spike → Price might be breaking out/down
Action: Look for high-scoring SMC opportunities
```

---

## Summary

| Aspect | What It Tells You |
|--------|-------------------|
| **Raw ATR** | Rupee movement per candle |
| **ATR%** | Movement relative to price (more useful) |
| **Low ATR** | Calm, safer, smaller profits |
| **High ATR** | Volatile, riskier, bigger profits |
| **For Stop Loss** | 1.5-2.0 × ATR |
| **For Target** | 2.0-3.0 × ATR |
| **Direction?** | No - ATR doesn't predict up or down |

**Golden Rule:** 
> Don't just look at the number - calculate ATR% and compare it to the stock's typical behavior!

---

## Quick Reference Table

```
ATR% Range     | Volatility | Trading Style      | Risk Level
---------------|------------|-------------------|------------
< 0.3%         | Very Low   | Long-term hold    | Very Low
0.3% - 0.5%    | Low        | Swing trading     | Low
0.5% - 1.0%    | Moderate   | Day trading       | Moderate
1.0% - 2.0%    | High       | Active scalping   | High
> 2.0%         | Very High  | Event-driven only | Very High
```

---

**Next time you see ATR in Debug tab:**
1. Note the value (e.g., 8.50)
2. Calculate ATR% = (8.50 / Price) × 100
3. Use it to set proper stop loss and target
4. Compare to stock's normal volatility

ATR is your **volatility ruler** - it helps you measure risk before entering a trade! 📏
