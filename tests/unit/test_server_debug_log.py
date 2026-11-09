from __future__ import annotations

import json
import threading
import urllib.request

from app.server import build_server
from utils.schema_validation import validate_session_log


def _start_server(**kwargs):
    httpd = build_server("127.0.0.1", 0, **kwargs)
    worker = threading.Thread(target=httpd.serve_forever, daemon=True)
    worker.start()
    return httpd, httpd.server_address[1]


def _post_audio(port: int, session_id: str) -> dict:
    request = urllib.request.Request(
        f"http://127.0.0.1:{port}/api/audio",
        data=b"microphone-bytes",
        method="POST",
        headers={
            "Content-Type": "application/octet-stream",
            "X-Mallo-Session-ID": session_id,
        },
    )
    with urllib.request.urlopen(request) as response:
        return json.loads(response.read().decode("utf-8"))


def test_audio_request_does_not_create_log_without_debug_log(tmp_path) -> None:
    path = tmp_path / "logs" / "qa.jsonl"
    httpd, port = _start_server()
    try:
        _post_audio(port, "qa-session")
    finally:
        httpd.shutdown()
        httpd.server_close()

    assert not path.exists()


def test_debug_log_appends_utf8_jsonl_for_each_audio_request(tmp_path) -> None:
    path = tmp_path / "logs" / "qa.jsonl"
    httpd, port = _start_server(debug_log_path=path)
    try:
        _post_audio(port, "qa-session")
        _post_audio(port, "qa-session")
    finally:
        httpd.shutdown()
        httpd.server_close()

    raw_lines = path.read_text(encoding="utf-8").splitlines()
    assert len(raw_lines) == 2
    assert "아이스 아메리카노" in raw_lines[0]

    events = [json.loads(line) for line in raw_lines]
    assert [event["step_index"] for event in events] == [1, 2]
    assert all(event["session_id"] == "qa-session" for event in events)
    assert all(event["stt_confidence"] == 0.98 for event in events)
    assert all(event["order_state_before"] is not None for event in events)
    assert all(event["order_state_after"] is not None for event in events)
    assert all(event["tts_output_text"] for event in events)
    assert events[1]["order_state_before"]["items"][0]["temperature"] == "iced"
    assert events[1]["order_commands"][0]["temperature"] == "iced"
    for event in events:
        validate_session_log(event)
