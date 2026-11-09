#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from app.launcher import *  # noqa: F401, F403
from app.launcher import main  # noqa: E402

if __name__ == "__main__":
    main()
