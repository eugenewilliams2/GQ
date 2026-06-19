#!/bin/bash
# GQ Crypto research bot — advances the crypto paper sessions + runs crypto
# self-test learn rounds, building crypto_bot's own knowledge.
REPO="/Users/Geno/Documents/GitHub/GQ"; PY="/usr/local/bin/python3"
LOG="$HOME/.gq-research-crypto.log"
cd "$REPO" || exit 1; export PATH="/usr/local/bin:/opt/homebrew/bin:/usr/bin:/bin"
M="Balance|Closed trades|Total P&L|Costs paid|Open positions"; L="candidates ever|VERDICT|No candidate|⚑"
{
  echo ""; echo "═══════ GQ CRYPTO RESEARCH — $(date '+%Y-%m-%d %H:%M %Z') ═══════"
  echo "· paper: crypto-NN"; "$PY" run_crypto.py paper 2>&1 | grep -E "$M"
  echo "· paper: momentum";  "$PY" run_crypto.py paper --name mom 2>&1 | grep -E "$M"
  echo "· learn: crypto 1d"; "$PY" run_crypto.py learn --interval 1d 2>&1 | grep -E "$L"
} >> "$LOG" 2>&1
echo "Crypto research complete -> $LOG"
