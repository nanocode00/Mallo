from __future__ import annotations

import time

from app.server import MalloServerApp
from app.service import build_mock_service


def test_startup_warmup_does_not_create_user_session() -> None:
    app = MalloServerApp(build_mock_service())

    app.service.warmup_tts()

    assert app.session_count == 0


def test_idle_sessions_are_removed_during_later_requests() -> None:
    app = MalloServerApp(build_mock_service(), session_ttl_seconds=0)

    app.dispatch("11111111-1111-4111-8111-111111111111", "state")
    time.sleep(0.001)
    app.dispatch("22222222-2222-4222-8222-222222222222", "state")

    assert app.session_count == 1
