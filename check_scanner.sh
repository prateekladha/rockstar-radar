#!/bin/bash
# Quick scanner diagnostic script

echo ""
echo "═══════════════════════════════════════════════════════════"
echo "  Scanner Diagnostic Check"
echo "═══════════════════════════════════════════════════════════"
echo ""

# Check scanner process
echo -n "1. Scanner process: "
if ps aux | grep -q "[l]aunch.py run"; then
    echo "✓ Running"
    PID=$(ps aux | grep "[l]aunch.py run" | awk '{print $2}')
    echo "   PID: $PID"
else
    echo "✗ NOT RUNNING"
    echo "   → Start with: python3 launch.py run"
fi

echo ""

# Check port 8765
echo -n "2. Port 8765: "
if lsof -i :8765 > /dev/null 2>&1; then
    echo "✓ Open"
else
    echo "✗ Closed"
    echo "   → Scanner not listening"
fi

echo ""

# Check ORB API
echo -n "3. ORB API: "
if timeout 2 curl -s http://127.0.0.1:8765/api/state > /dev/null 2>&1; then
    echo "✓ Responding"
    COUNT=$(curl -s http://127.0.0.1:8765/api/state 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('all', [])))" 2>/dev/null || echo "0")
    echo "   Signals: $COUNT"
else
    echo "✗ Not responding"
fi

echo ""

# Check SMC API
echo -n "4. SMC API: "
if timeout 2 curl -s http://127.0.0.1:8765/api/smc-state > /dev/null 2>&1; then
    echo "✓ Responding"
    COUNT=$(curl -s http://127.0.0.1:8765/api/smc-state 2>/dev/null | python3 -c "import json,sys; d=json.load(sys.stdin); print(len(d.get('opportunities', [])))" 2>/dev/null || echo "0")
    echo "   Opportunities: $COUNT"

    if [ "$COUNT" -gt 0 ]; then
        echo ""
        echo "   Top opportunities:"
        curl -s http://127.0.0.1:8765/api/smc-state 2>/dev/null | python3 -c "
import json, sys
data = json.load(sys.stdin)
for opp in data.get('opportunities', [])[:5]:
    symbol = opp['symbol'].replace('NSE:', '').replace('-EQ', '')
    print(f\"     • {symbol}: {opp['score']} pts ({opp['zone']})\")
" 2>/dev/null
    fi
else
    echo "✗ Not responding"
    echo "   → SMC engine not initialized"
fi

echo ""
echo "═══════════════════════════════════════════════════════════"

# Recommendations
if ! ps aux | grep -q "[l]aunch.py run"; then
    echo ""
    echo "❌ Scanner is NOT running!"
    echo ""
    echo "To start scanner:"
    echo "  cd /Users/raunakladha/Documents/rockstar-radar"
    echo "  python3 launch.py run"
    echo ""
elif ! timeout 2 curl -s http://127.0.0.1:8765/api/smc-state > /dev/null 2>&1; then
    echo ""
    echo "⚠️  Scanner running but SMC API not responding"
    echo ""
    echo "Possible causes:"
    echo "  - Scanner still warming up (wait 30-60 seconds)"
    echo "  - Scanner crashed (check logs)"
    echo "  - SMC engine not initialized (bug)"
    echo ""
    echo "Check logs:"
    echo "  tail -50 data/scanner*.out"
    echo ""
else
    echo ""
    echo "✓ Scanner is running correctly!"
    echo ""
    echo "Next steps:"
    echo "  1. Open http://127.0.0.1:8765 in browser"
    echo "  2. Go to SMC Radar tab"
    echo "  3. You should see opportunities!"
    echo ""
fi

echo "═══════════════════════════════════════════════════════════"
echo ""
