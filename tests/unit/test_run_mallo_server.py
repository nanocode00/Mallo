from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from app import launcher as run_mallo_server
from app.launcher import (
    ChildSpec,
    assert_environment_ready,
    assert_ports_available,
    build_specs,
    announce_public_url,
    terminate_children,
    wait_until_ready,
    tunnel_command,
    wait_for_quick_tunnel_url,
    warmup_sidecar,
)


def test_assert_ports_available_reports_conflicting_loopback_port(monkeypatch) -> None:
    monkeypatch.setattr(run_mallo_server, "port_is_in_use", lambda port: port == 8002)
    with pytest.raises(RuntimeError, match=r"127\.0\.0\.1:8002"):
        assert_ports_available([8001, 8002, 8003])


def test_wait_until_ready_names_child_that_exits_before_healthcheck() -> None:
    class ExitedProcess:
        def poll(self):
            return 19

    spec = ChildSpec("NLU", ["python"], "http://127.0.0.1:9/health", "http://127.0.0.1:9/warmup")
    with pytest.raises(RuntimeError, match=r"NLU sidecar.*exit=19"):
        wait_until_ready(spec, ExitedProcess(), timeout=0.01)  # type: ignore[arg-type]


def test_environment_check_instructs_the_matching_requirements_file(monkeypatch, tmp_path) -> None:
    class Result:
        returncode = 0
        stdout = '{"missing": ["melo"], "transformers": "4.27.4"}'
        stderr = ""

    monkeypatch.setattr(run_mallo_server.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(RuntimeError, match=r"requirements/runtime\.txt"):
        assert_environment_ready("runtime", tmp_path / "python")


def test_environment_check_rejects_transformers_cross_install(monkeypatch, tmp_path) -> None:
    class Result:
        returncode = 0
        stdout = '{"missing": [], "transformers": "5.15.0"}'
        stderr = ""

    monkeypatch.setattr(run_mallo_server.subprocess, "run", lambda *args, **kwargs: Result())
    with pytest.raises(RuntimeError, match=r"필요: 4\.27\.4"):
        assert_environment_ready("runtime", tmp_path / "python")


def test_warmup_sidecar_reports_success_and_elapsed_time(monkeypatch) -> None:
    class Response:
        status = 200

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return None

        def read(self):
            return b'{"ok": true, "warmed": true}'

    class Process:
        def poll(self):
            return None

    monkeypatch.setattr(run_mallo_server.urllib.request, "urlopen", lambda *args, **kwargs: Response())
    spec = ChildSpec("STT", ["python"], "http://127.0.0.1:9/health", "http://127.0.0.1:9/warmup")
    assert warmup_sidecar(spec, Process(), timeout=1) >= 0  # type: ignore[arg-type]


def test_quick_tunnel_requires_cloudflared_binary(monkeypatch) -> None:
    monkeypatch.setattr(run_mallo_server.shutil, "which", lambda _: None)
    with pytest.raises(RuntimeError, match="cloudflared"):
        tunnel_command("quick", None)


def test_named_tunnel_requires_remotely_managed_token(monkeypatch) -> None:
    monkeypatch.setattr(run_mallo_server.shutil, "which", lambda _: "/usr/bin/cloudflared")
    monkeypatch.delenv("CLOUDFLARE_TUNNEL_TOKEN", raising=False)
    with pytest.raises(RuntimeError, match="CLOUDFLARE_TUNNEL_TOKEN"):
        tunnel_command("named", "mallo-gateway")


def test_named_tunnel_passes_token_only_to_child_argv_without_logging(monkeypatch, capsys) -> None:
    token = "secret-token-must-not-be-logged"
    monkeypatch.setattr(run_mallo_server.shutil, "which", lambda _: "/usr/bin/cloudflared")
    monkeypatch.setenv("CLOUDFLARE_TUNNEL_TOKEN", token)

    assert tunnel_command("named", "mallo-gateway") == [
        "/usr/bin/cloudflared", "tunnel", "--protocol", "auto", "run", "--token", token,
    ]
    captured = capsys.readouterr()
    assert token not in captured.out
    assert token not in captured.err


def test_none_tunnel_remains_disabled() -> None:
    assert tunnel_command("none", None) is None


def test_http2_tunnel_protocol_is_available_for_udp_quic_fallback(monkeypatch) -> None:
    monkeypatch.setattr(run_mallo_server.shutil, "which", lambda _: "/usr/bin/cloudflared")

    assert tunnel_command("quick", None, "http2") == [
        "/usr/bin/cloudflared", "tunnel", "--protocol", "http2",
        "--url", "http://127.0.0.1:8000",
    ]


def test_named_public_url_announcement_never_contains_tunnel_token(capsys) -> None:
    token = "never-print-this-token"
    test_url = "https://mallo-api.example.com"
    announce_public_url(test_url)
    output = capsys.readouterr().out
    assert "[launcher] Mallo public URL:" in output
    assert test_url in output
    assert token not in output


def test_terminate_children_includes_tunnel_child() -> None:
    class Process:
        def __init__(self) -> None:
            self.terminated = False

        def poll(self):
            return None if not self.terminated else 0

        def terminate(self) -> None:
            self.terminated = True

        def wait(self, timeout: float) -> int:
            return 0

    tunnel = Process()
    gateway = Process()
    terminate_children({"TUNNEL": tunnel, "GATEWAY": gateway})  # type: ignore[arg-type]
    assert tunnel.terminated is True
    assert gateway.terminated is True


def test_quick_tunnel_url_wait_returns_detected_trycloudflare_url() -> None:
    class Process:
        def poll(self):
            return None

    event = run_mallo_server.threading.Event()
    urls = ["https://mallo-test.trycloudflare.com"]
    event.set()
    assert wait_for_quick_tunnel_url(Process(), event, urls, timeout=1) == urls[0]  # type: ignore[arg-type]


def test_quick_tunnel_url_pattern_extracts_cloudflare_output() -> None:
    line = "INF Your quick Tunnel has been created! https://mallo-123.trycloudflare.com"
    assert run_mallo_server.TRY_CLOUDFLARE_URL_RE.search(line).group(0) == "https://mallo-123.trycloudflare.com"


def test_debug_log_argument_is_parsed_as_path() -> None:
    args = run_mallo_server.parse_args(
        ["--tunnel", "named", "--debug-log", "logs/qa-20260826.jsonl"]
    )

    assert args.tunnel == "named"
    assert args.debug_log == Path("logs/qa-20260826.jsonl")


@pytest.mark.parametrize("debug_log", [None, Path("logs/qa-20260826.jsonl")])
def test_build_specs_forwards_debug_log_only_when_specified(monkeypatch, debug_log) -> None:
    interpreters = iter((Path("/runtime/python"), Path("/nlu/python")))
    monkeypatch.setattr(run_mallo_server, "venv_python", lambda _: next(interpreters))
    monkeypatch.setattr(run_mallo_server, "assert_environment_ready", lambda *args: None)
    args = argparse.Namespace(
        nlu_model=Path("models/nlu"),
        tts_checkpoint=Path("logs/tts.pth"),
        tts_config=Path("logs/config.json"),
        tts_speaker="10",
        debug_log=debug_log,
    )

    _, gateway = build_specs(args)

    if debug_log is None:
        assert gateway.command[-1] == "--sidecar-gateway"
        assert "--debug-log" not in gateway.command
    else:
        assert gateway.command[-2:] == ["--debug-log", str(debug_log)]
