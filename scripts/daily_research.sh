#!/bin/bash
# GQ daily research run — advances all paper sessions and runs a self-test learn
# round, appending results to ~/.gq-research.log. Designed to be driven by a
# launchd agent (real OS timer, no app needed). Simulation only; no real orders.
REPO="/Users/Geno/Documents/GitHub/GQ"
PY="/usr/local/bin/python3"          # interpreter that has the harness deps
LOG="$HOME/.gq-research.log"
cd "$REPO" || exit 1
export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"

{
  echo ""
  echo "════════════════════════════════════════════════════════════"
  echo "  GQ RESEARCH RUN — $(date '+%Y-%m-%d %H:%M %Z')"
  echo "════════════════════════════════════════════════════════════"

  echo "── paper: fvg (forex) ──"
  "$PY" run.py paper 2>&1 | grep -E "Balance|Closed trades|Total P&L|Costs paid|Open positions"

  echo "── paper: ml-agg (forex NN, aggressive) ──"
  "$PY" run.py paper --name ml-agg 2>&1 | grep -E "Balance|Closed trades|Total P&L|Costs paid|Open positions"

  echo "── paper: crypto-nn (intraday NN) ──"
  "$PY" run.py paper --name crypto-nn 2>&1 | grep -E "Balance|Closed trades|Total P&L|Costs paid|Open positions"

  echo "── learn round: crypto daily ──"
  "$PY" run.py learn --asset crypto --source coinbase --interval 1d 2>&1 | grep -E "candidates ever|VERDICT|No candidate|⚑"

  echo "── learn round: forex daily ──"
  "$PY" run.py learn --asset forex --source yfinance --interval 1d 2>&1 | grep -E "candidates ever|VERDICT|No candidate|⚑"

  echo "── leaderboard top 5 ──"
  "$PY" run.py learn --show 2>&1 | grep -vE "Warning|^$" | sed -n '6,11p'
} >> "$LOG" 2>&1

echo "research run complete -> $LOG"
