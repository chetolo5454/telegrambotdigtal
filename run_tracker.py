#!/usr/bin/env python3
"""
Digital Egypt Case Tracker - Launcher
متتبع دعاوى منصة مصر الرقمية
"""

import sys
import os

# Ensure project root is in sys.path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from case_tracker_py.cli import run_cli

if __name__ == "__main__":
    run_cli()
