from __future__ import annotations

import json
import threading
from pathlib import Path

from domain.session_log import SessionLogEvent


class FileInteractionLogger:
    """인터랙션 이벤트를 JSONL 형태로 파일에 append 기록한다."""

    def __init__(self, path: Path) -> None:
        self._path = Path(path)
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()

    def log_event(self, event: SessionLogEvent) -> None:
        line = json.dumps(event.to_dict(), ensure_ascii=False)
        with self._lock:
            with self._path.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")


__all__ = ["FileInteractionLogger"]
