#!/usr/bin/env python3
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from sidecars.stt_server import *  # noqa: F401, F403
from sidecars.stt_server import _warmup_audio  # noqa: F401
from sidecars.stt_server import main  # noqa: E402

if __name__ == "__main__":
    main()
