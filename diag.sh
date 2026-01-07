#!/bin/sh

RUN_ID=$(ls -1t runs | head -n1)
echo "=== RUN: $RUN_ID ==="
echo ""
echo "=== Summary ==="
cat runs/$RUN_ID/summary.json | jq '.mode, .diagnostics'
echo ""
echo "=== Market Selection ==="
grep "Market Selection Summary" runs/$RUN_ID/logs.txt -A 15
echo ""
echo "=== Decisions ==="
wc -l runs/$RUN_ID/decisions.csv
echo ""
echo "=== Would Trade ==="
wc -l runs/$RUN_ID/would_trade.csv
