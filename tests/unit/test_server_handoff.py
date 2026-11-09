import json
import pytest
from app.server import MalloServerApp
from app.service import build_mock_service
from domain.models import FulfillmentType, Temperature


def test_session_handoff_reconstructs_cart_and_calculates_official_price():
    service = build_mock_service()
    app = MalloServerApp(service)
    session_id = 'test-session-handoff-1'

    handoff_payload = {
        'fulfillment_type': 'dine_in',
        'confirmed': False,
        'items': [
            {
                'menu_id': 'americano',
                'quantity': 2,
                'temperature': 'iced',
                'unit_price': 100,
                'total_price': 200,
                'options': {},
            }
        ],
    }

    result = app.dispatch(session_id, 'session_handoff', handoff_payload)
    assert result['success'] is True
    assert result['response_text'] == ""
    assert result['cart']['fulfillment_type'] == 'dine_in'
    assert result['cart']['confirmed'] is False
    assert len(result['cart']['items']) == 1

    item = result['cart']['items'][0]
    assert item['menu_id'] == 'americano'
    assert item['quantity'] == 2
    assert item['temperature'] == 'iced'
    assert item['unit_price'] == 4700
    assert item['total_price'] == 9400
    assert result['cart']['total_price'] == 9400

    subsequent = app.dispatch(session_id, 'handle_text', '따뜻한 카페라떼 한 잔 주세요')
    assert subsequent['success'] is True
    cart = subsequent['cart']
    assert len(cart['items']) == 2
    assert cart['total_price'] == 9400 + 5200


def test_session_handoff_rejects_unknown_menu_id():
    service = build_mock_service()
    app = MalloServerApp(service)
    session_id = 'test-session-handoff-2'

    handoff_payload = {
        'fulfillment_type': 'takeout',
        'items': [
            {
                'menu_id': 'non_existent_drink',
                'quantity': 1,
                'temperature': 'iced',
            }
        ],
    }

    result = app.dispatch(session_id, 'session_handoff', handoff_payload)
    assert result['success'] is False
    assert result['error'] == 'invalid_menu_id'


def test_session_handoff_rejects_invalid_quantity():
    service = build_mock_service()
    app = MalloServerApp(service)
    session_id = 'test-session-handoff-3'

    handoff_payload = {
        'fulfillment_type': 'dine_in',
        'items': [
            {
                'menu_id': 'americano',
                'quantity': 0,
                'temperature': 'iced',
            }
        ],
    }

    result = app.dispatch(session_id, 'session_handoff', handoff_payload)
    assert result['success'] is False
    assert result['error'] == 'invalid_quantity'


def test_session_handoff_rejects_unsupported_temperature():
    service = build_mock_service()
    app = MalloServerApp(service)
    session_id = 'test-session-handoff-4'

    handoff_payload = {
        'fulfillment_type': 'dine_in',
        'items': [
            {
                'menu_id': 'grapefruit_ade',
                'quantity': 1,
                'temperature': 'hot',
            }
        ],
    }

    result = app.dispatch(session_id, 'session_handoff', handoff_payload)
    assert result['success'] is False
    assert result['error'] == 'unsupported_temperature'
