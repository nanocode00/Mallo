from __future__ import annotations

import pytest

from app.server import _SYSTEM_MESSAGES, _SessionApp
from app.service import build_mock_service
from config.settings import load_menu
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.models import Cart, OrderCommand
from domain.models import Temperature


def _normalized(text: str) -> str:
    return normalize_korean_text_for_tts(text)


@pytest.mark.parametrize("level", [0, 1, 2])
def test_fixed_messages_preserve_canonical_content_in_tts_chunks(level: int) -> None:
    app = _SessionApp(build_mock_service())
    app.service.set_tts_level(level)
    for message_id, (canonical, _) in _SYSTEM_MESSAGES.items():
        payload = app.system_message(message_id)
        chunks = payload["tts_segments"]
        assert " ".join(chunk["synthesis_text"] for chunk in chunks) == _normalized(canonical)
        assert payload["display_segments"]
        assert all(0 <= chunk["segment_index"] < len(payload["display_segments"]) for chunk in chunks)
        assert {chunk["gap_ms"] for chunk in chunks} == ({0} if level == 0 else ({280} if level == 1 else {480}))


@pytest.mark.parametrize("level", [0, 1, 2])
def test_all_menu_payload_has_complete_display_segments_and_canonical_tts(level: int) -> None:
    app = _SessionApp(build_mock_service())
    app.service.set_tts_level(level)
    command = OrderCommand.create(Intent.QUERY_MENU)
    result = app.service.handle_commands([command], Cart())
    payload = app._order_payload(result, level=level)

    assert result.response_text.startswith("커피 메뉴는")
    assert "전체 메뉴는" not in result.response_text
    expected_segment_count = 14 if level == 2 else 8
    assert len(payload["display_segments"]) == expected_segment_count
    assert " ".join(chunk["synthesis_text"] for chunk in payload["tts_segments"]) == _normalized(payload["response_text"])
    assert {chunk["segment_index"] for chunk in payload["tts_segments"]} == set(range(expected_segment_count))


@pytest.mark.parametrize("category", ["coffee", "non_coffee", "tea", "dessert"])
@pytest.mark.parametrize("level", [0, 1, 2])
def test_category_menu_chunks_only_split_canonical_substrings(category: str, level: int) -> None:
    agent = ConversationAgent(load_menu())
    result = agent.execute([OrderCommand.create(Intent.QUERY_MENU, category_id=category)], Cart())
    app = _SessionApp(build_mock_service())
    payload = app._order_payload(result, level=level)
    assert " ".join(chunk["synthesis_text"] for chunk in payload["tts_segments"]) == _normalized(result.response_text)
    assert " ".join(payload["display_segments"]) == result.response_text


@pytest.mark.parametrize("level", [0, 1, 2])
def test_service_mode_repeat_keeps_canonical_source_across_speed_changes(level: int) -> None:
    app = _SessionApp(build_mock_service())
    initial = app.system_message("SERVICE_MODE")
    repeated = app.accessibility_action(
        "REPEAT",
        level=level,
        replay_source={
            "message_id": initial["message_id"],
            "response_text": initial["response_text"],
        },
    )
    assert repeated["message_id"] == "SERVICE_MODE"
    assert repeated["response_text"] == initial["response_text"]
    assert repeated["display_segments"] == initial["display_segments"]
    assert repeated["tts_level"] == level
    assert "안녕하세요" not in repeated["response_text"]


def test_repeat_never_falls_back_to_legacy_pipeline_last_response() -> None:
    app = _SessionApp(build_mock_service())
    # A new session has no replay source even though the pipeline has its own
    # historical default ``last_response`` value.
    assert app.accessibility_action("REPEAT") == {"error": "no replayable message"}


@pytest.mark.parametrize("repeat_level", [0, 1, 2])
def test_dynamic_repeat_rebuilds_from_the_same_semantic_order_source(repeat_level: int) -> None:
    app = _SessionApp(build_mock_service())
    commands = [
        OrderCommand.create(Intent.ADD_ITEM, "americano", quantity=2, temperature=Temperature.ICED),
        OrderCommand.create(Intent.ADD_ITEM, "cafe_latte", quantity=1, temperature=Temperature.HOT),
    ]
    result = app.service.handle_commands(commands, Cart())
    initial = app._order_payload(result, level=2)
    repeated = app.accessibility_action("REPEAT", level=repeat_level)

    assert initial["response_text"] == (
        "아이스 아메리카노 두 잔입니다. 따뜻한 카페라떼 한 잔입니다. 장바구니에 담았습니다."
    )
    assert repeated["tts_level"] == repeat_level
    assert "안녕하세요" not in repeated["response_text"]
    if repeat_level == 2:
        assert repeated["response_text"] == initial["response_text"]
    else:
        assert repeated["response_text"] == (
            "아이스 아메리카노 두 잔과 따뜻한 카페라떼 한 잔을 장바구니에 담았습니다."
        )
