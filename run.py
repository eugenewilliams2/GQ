#!/usr/bin/env python3
"""
GQ Forex Strategy Research Harness — launcher.

  python run.py compare                       # walk-forward, all strategies, ranked
  python run.py backtest --strategy momentum  # single strategy, with realistic costs
  python run.py backtest -s ict --no-cost     # frictionless, to show cost impact
  python run.py fetch --refresh               # rebuild the data cache

Research tool only — reports whether a strategy has a measurable edge
out-of-sample after costs. It does not place trades.
"""
from forex_bot.cli import main

if __name__ == "__main__":
    main()
