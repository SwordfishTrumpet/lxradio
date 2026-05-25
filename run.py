#!/usr/bin/env python3
"""Development runner — no install required."""
import sys
from pathlib import Path

# Add src/ to path so lxradio can be imported without installation.
src = Path(__file__).parent / "src"
sys.path.insert(0, str(src))

from lxradio.__main__ import main

if __name__ == "__main__":
    sys.exit(main())
