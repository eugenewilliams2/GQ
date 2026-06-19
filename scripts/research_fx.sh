#!/bin/bash
# GQ FX research bot — advances the forex paper sessions + runs forex self-test
# learn rounds, building fx_bot's own knowledge (fx_bot/.leaderboard.json).
REPO="/Users/Geno/Documents/GitHub/GQ"; PY="/usr/local/bin/python3"
LOG="$HOME/.gq-research-fx.log"
cd "$REPO" || exit 1; export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
M="Balance|Closed trades|Total P&L|Costs paid|Open positions"; L="candidates ever|VERDICT|No candidate|⚑"
{
  echo ""; echo "═══════ GQ FX RESEARCH — $(date '+%Y-%m-%d %H:%M %Z') ═══════"
  echo "· paper: fvg";      "$PY" run_fx.py paper 2>&1 | grep -E "$M"
  echo "· paper: ml-agg";   "$PY" run_fx.py paper --name ml-agg 2>&1 | grep -E "$M"
  echo "· learn: forex 1d"; "$PY" run_fx.py learn --interval 1d 2>&1 | grep -E "$L"
} >> "$LOG" 2>&1
echo "FX research complete -> $LOG"
