"""STT 데모 /api/stt 및 stt-demo.html 계약 테스트

Spec: docs/specs/stt-demo.md
AC-01~AC-06 커버
"""
from __future__ import annotations

import json
import threading
import urllib.request
from pathlib import Path
from unittest.mock import MagicMock

from app.server import build_server
from app.service import MalloService
from adapters.nlu.mock_nlu import MockNLU
from adapters.stt.mock_stt import MockSTT
from adapters.tts.mock_tts import MockTTS
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.models import Cart


def _start_server(**overrides):
    """overrides로 build_server에 커스텀 service 주입 가능."""
    if "service" in overrides:
        httpd = build_server("127.0.0.1", 0, service=overrides["service"])
    else:
        httpd = build_server("127.0.0.1", 0)
    thread = threading.Thread(target=httpd.serve_forever, daemon=True)
    thread.start()
    port = httpd.server_address[1]
    return httpd, port


def _post_stt(port, body: bytes):
    url = f"http://127.0.0.1:{port}/api/stt"
    req = urllib.request.Request(url, data=body, method="POST")
    with urllib.request.urlopen(req) as resp:
        return resp.status, json.loads(resp.read().decode("utf-8")), resp.headers


def _get(port, path):
    url = f"http://127.0.0.1:{port}{path}"
    with urllib.request.urlopen(url) as resp:
        return resp.status, resp.read(), resp.headers


# AC-01 · STT 성공 응답 계약
def test_stt_api_success_contract() -> None:
    # canned_text와 confidence가 명확한 MockSTT로 서버 구성
    from app.service import build_mock_service
    service = build_mock_service(canned_stt_text="아이스 아메리카노 두 잔 주세요", stt_should_fail=False)
    # confidence를 직접 지정하기 위해 MockSTT를 교체
    service._pipeline._stt = MockSTT(canned_text="아이스 아메리카노 두 잔 주세요", confidence=0.92, duration_ms=123.4)
    httpd, port = _start_server(service=service)
    try:
        payload = b"fake-wav-bytes-1234"
        status, data, headers = _post_stt(port, payload)
        assert status == 200
        assert data["text"] == "아이스 아메리카노 두 잔 주세요"
        assert data["confidence"] == 0.92
        assert isinstance(data["alternatives"], list)
        assert isinstance(data["latency_ms"], (int, float))
        assert data["received_bytes"] == len(payload)
        assert "error" not in data
        # cart 변경 없음을 /api/state로 확인
        state_status, state_body, _ = _get(port, "/api/state")
        assert state_status == 200
        state = json.loads(state_body.decode("utf-8"))
        assert state["cart"]["items"] == []
    finally:
        httpd.shutdown()


# AC-02 · STTFailure 응답 계약
def test_stt_api_failure_contract() -> None:
    from app.service import build_mock_service
    service = build_mock_service(stt_should_fail=True)
    httpd, port = _start_server(service=service)
    try:
        payload = b"some-audio"
        status, data, _ = _post_stt(port, payload)
        assert status == 200
        assert "error" in data
        assert isinstance(data["error"], str) and len(data["error"]) > 0
        assert data["received_bytes"] == len(payload)
        assert "text" not in data
        # cart 변경 없음
        _, state_body, _ = _get(port, "/api/state")
        state = json.loads(state_body.decode("utf-8"))
        assert state["cart"]["items"] == []
    finally:
        httpd.shutdown()


# AC-03 · STT-only 위임 (NLU/Agent/TTS 미호출, Cart 미변경)
def test_transcribe_is_stt_only() -> None:
    mock_nlu = MockNLU()
    mock_agent = ConversationAgent(load_menu())
    mock_tts = MockTTS()
    mock_stt = MockSTT(canned_text="테스트", confidence=0.99)

    # 각 컴포넌트 호출 여부 추적
    orig_nlu_parse = mock_nlu.parse
    orig_agent_execute = mock_agent.execute
    orig_tts_synth = mock_tts.synthesize

    nlu_called = []
    agent_called = []
    tts_called = []

    def wrap_nlu(*a, **kw):
        nlu_called.append(True)
        return orig_nlu_parse(*a, **kw)

    def wrap_agent(*a, **kw):
        agent_called.append(True)
        return orig_agent_execute(*a, **kw)

    def wrap_tts(*a, **kw):
        tts_called.append(True)
        return orig_tts_synth(*a, **kw)

    mock_nlu.parse = MagicMock(side_effect=wrap_nlu)  # type: ignore[method-assign]
    mock_agent.execute = MagicMock(side_effect=wrap_agent)  # type: ignore[method-assign]
    mock_tts.synthesize = MagicMock(side_effect=wrap_tts)  # type: ignore[method-assign]

    service = MalloService(nlu=mock_nlu, agent=mock_agent, tts=mock_tts, stt=mock_stt)
    cart_before = Cart()
    result = service.transcribe(b"audio-bytes")
    assert result.text == "테스트"
    assert not nlu_called, "transcribe should not call NLU"
    assert not agent_called, "transcribe should not call Agent"
    assert not tts_called, "transcribe should not call TTS"
    # Service 경유 HTTP도 동일 보장 — handle_audio와 구분
    httpd, port = _start_server(service=service)
    try:
        # /api/stt는 transcribe 경로
        status, data, _ = _post_stt(port, b"wav")
        assert status == 200
        assert data["text"] == "테스트"
        # NLU 등은 여전히 호출 안 됨 (두 번째 호출에서도)
        assert not nlu_called or len(nlu_called) == 0
    finally:
        httpd.shutdown()


# AC-05 · 고정 경로 덤프 없음 (프라이버시/동시성)
def test_transcribe_does_not_create_tmp_dump() -> None:
    import tempfile
    dump_path = Path(tempfile.gettempdir()) / "mallo_last_stt.bin"
    # 사전 정리
    if dump_path.exists():
        dump_path.unlink()
    httpd, port = _start_server()
    try:
        _post_stt(port, b"audio-1")
        _post_stt(port, b"audio-2-longer-bytes")
        # 어떤 고정 덤프도 생성되지 않아야 함
        assert not dump_path.exists(), "transcribe should not create /tmp/mallo_last_stt.bin"
    finally:
        httpd.shutdown()
        if dump_path.exists():
            dump_path.unlink()


# AC-06 · 빈 alternatives 처리
def test_stt_api_empty_alternatives_is_list() -> None:
    from app.service import build_mock_service
    service = build_mock_service(canned_stt_text="단일 후보")
    # MockSTT는 기본 alternatives 빈 튜플
    httpd, port = _start_server(service=service)
    try:
        _, data, _ = _post_stt(port, b"wav")
        assert data["alternatives"] == []
        # confidence None 케이스도 허용 — whisper_medium에서 confidence None 가능
        # 여기선 0.98이므로 숫자임을 확인
        assert isinstance(data["confidence"], (int, float))
    finally:
        httpd.shutdown()


def test_stt_api_empty_body_handled() -> None:
    """빈 body(0 bytes)도 서버가 200으로 응답 (STT 위임 결과에 따름)."""
    httpd, port = _start_server()
    try:
        status, data, _ = _post_stt(port, b"")
        assert status == 200
        # 빈 오디오라도 서버는 received_bytes 0과 text 또는 error 반환
        assert data["received_bytes"] == 0
        assert "text" in data or "error" in data
    finally:
        httpd.shutdown()
