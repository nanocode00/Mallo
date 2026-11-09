from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.runtime.generate_runtime_config import (
    generate_runtime_config,
    normalize_api_base_url,
    parse_env_file,
    write_runtime_config,
)


def test_normalize_api_base_url_variations() -> None:
    assert normalize_api_base_url("") == ""
    assert normalize_api_base_url(None) == ""
    assert normalize_api_base_url("   ") == ""
    assert normalize_api_base_url("example.com") == "https://example.com"
    assert normalize_api_base_url("example.com/") == "https://example.com"
    assert normalize_api_base_url("https://example.com") == "https://example.com"
    assert normalize_api_base_url("https://example.com/") == "https://example.com"
    assert normalize_api_base_url("http://127.0.0.1:8000") == "http://127.0.0.1:8000"


def test_generate_runtime_config_with_empty_domain() -> None:
    content = generate_runtime_config(domain="")
    assert "const configuredBaseUrl = '';" in content or 'const configuredBaseUrl = "";' in content
    assert "window.MALLO_RUNTIME_CONFIG = Object.freeze({" in content
    assert "apiBaseUrl: resolvedBaseUrl," in content
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in content
    assert "AIHUB_API_KEY" not in content


def test_generate_runtime_config_with_configured_domain() -> None:
    content = generate_runtime_config(domain="test-kiosk.example.com")
    assert "'https://test-kiosk.example.com'" in content or '"https://test-kiosk.example.com"' in content
    assert "window.MALLO_RUNTIME_CONFIG = Object.freeze({" in content
    assert "CLOUDFLARE_TUNNEL_TOKEN" not in content
    assert "AIHUB_API_KEY" not in content


def test_write_runtime_config_writes_file(tmp_path: Path) -> None:
    target = tmp_path / "runtime-config.js"
    written = write_runtime_config(target_path=target, domain="custom.dev")
    assert written == target
    text = target.read_text(encoding="utf-8")
    assert "https://custom.dev" in text
