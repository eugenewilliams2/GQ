#!/usr/bin/env python3
"""
GQ Forex Trading Bot — quick launcher.

  python run.py                       # interactive menu
  python run.py --mode safe           # safe mode (default action: scan)
  python run.py --mode aggressive     # high risk / high reward
  python run.py live --mode safe
  python run.py backtest --mode aggressive
"""
from forex_bot.bot import main

if __name__ == "__main__":
    main()
