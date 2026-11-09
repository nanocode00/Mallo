#!/usr/bin/env python3
"""Start and supervise Mallo's loopback-only STT/NLU/TTS sidecars and gateway."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import shutil
import socket
import subprocess
import sys
import threading
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

ROOT = Path(__file__).resolve().parents[2]
HOST = "127.0.0.1"
PORTS = {"gateway": 8000, "stt": 8001, "nlu": 8002, "tts": 8003}

DEFAULT_STT_MODEL = Path(
    os.environ.get(
        "MALLO_STT_MODEL_PATH",
        str(ROOT / "models" / "stt" / "final-train65-merged-bf16"),
    )
)

DEFAULT_NLU_MODEL = Path(
    os.environ.get(
        "MALLO_NLU_MODEL_PATH",
        str(ROOT / "models" / "nlu" / "final-qwen06b-merged-bf16"),
    )
)

_TTS_DIR = Path(
    os.environ.get(
        "MALLO_TTS_MODEL_DIR",
        str(ROOT / "models" / "tts" / "mallo-friendly"),
    )
)
DEFAULT_TTS_CHECKPOINT = _TTS_DIR / "G_2800.pth"
DEFAULT_TTS_CONFIG = _TTS_DIR / "config.json"


ENVIRONMENT_REQUIREMENTS = {
    "runtime": {
        "requirements": "requirements/runtime.txt",
        "modules": ("torch", "transformers", "melo", "soundfile", "av", "jsonschema"),
        "transformers": "4.27.4",
    },
    "nlu": {
        "requirements": "requirements/nlu.txt",
        "modules": ("torch", "transformers", "accelerate", "safetensors", "tokenizers", "sentencepiece", "jsonschema"),
        "transformers": "5.15.0",
    },
}
TRY_CLOUDFLARE_URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
DEFAULT_CLOUDFLARE_DOMAIN = os.environ.get("CLOUDFLARE_DOMAIN", "")
if DEFAULT_CLOUDFLARE_DOMAIN.startswith("http://") or DEFAULT_CLOUDFLARE_DOMAIN.startswith("https://"):
    _default_public = DEFAULT_CLOUDFLARE_DOMAIN.rstrip("/")
elif DEFAULT_CLOUDFLARE_DOMAIN:
    _default_public = f"https://{DEFAULT_CLOUDFLARE_DOMAIN}".rstrip("/")
else:
    _default_public = ""
DEFAULT_PUBLIC_URL = os.environ.get("MALLO_PUBLIC_URL", _default_public)


@dataclass(frozen=True)
class ChildSpec:
    name: str
    command: list[str]
    health_url: str
    warmup_url: str


def venv_python(name: str) -> Path:
    venv_dir = ROOT / ".venvs" / name
    path = venv_dir / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
    if path.is_file():
        return path

    req_file = ENVIRONMENT_REQUIREMENTS.get(name, {}).get("requirements", f"requirements/{name}.txt")
    target_dir = f".venvs/{name}"
    raise FileNotFoundError(
        f"필수 가상환경 인터프리터를 찾을 수 없습니다 ({name}).\n"
        f"생성 후 설치: python3.11 -m venv {target_dir} && {target_dir}/bin/python -m pip install -r {req_file}"
    )


def assert_environment_ready(kind: str, interpreter: Path) -> None:
    """Check imports/version without importing torch or loading a model in this process."""
    expected = ENVIRONMENT_REQUIREMENTS[kind]
    probe = (
        "import importlib.metadata, importlib.util, json; "
        f"names={expected['modules']!r}; "
        "print(json.dumps({'missing':[n for n in names if importlib.util.find_spec(n) is None], "
        "'transformers': (importlib.metadata.version('transformers') if importlib.util.find_spec('transformers') else None)}))"
    )
    result = subprocess.run(
        [str(interpreter), "-c", probe],
        cwd=ROOT,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise RuntimeError(
            f"{kind.upper()} 환경 검사 실행 실패: {result.stderr.strip()}\n"
            f"다시 설치: {interpreter} -m pip install -r {expected['requirements']}"
        )
    try:
        observed = json.loads(result.stdout)
    except json.JSONDecodeError as error:
        raise RuntimeError(f"{kind.upper()} 환경 검사 결과를 해석할 수 없습니다.") from error
    problems = []
    if observed["missing"]:
        problems.append("누락 패키지: " + ", ".join(observed["missing"]))
    if observed["transformers"] != expected["transformers"]:
        problems.append(
            f"transformers={observed['transformers']!r} (필요: {expected['transformers']})"
        )
    if problems:
        raise RuntimeError(
            f"{kind.upper()} 환경이 production 계약과 다릅니다 ({'; '.join(problems)}).\n"
            f"설치: {interpreter} -m pip install -r {expected['requirements']}"
        )


def port_is_in_use(port: int, host: str = HOST) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.settimeout(0.2)
        return sock.connect_ex((host, port)) == 0


def assert_ports_available(ports: Iterable[int]) -> None:
    used = [port for port in ports if port_is_in_use(port)]
    if used:
        joined = ", ".join(f"{HOST}:{port}" for port in used)
        raise RuntimeError(f"이미 사용 중인 Mallo 포트가 있습니다: {joined}. 해당 프로세스를 종료한 뒤 다시 실행하세요.")


def wait_until_ready(spec: ChildSpec, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        code = process.poll()
        if code is not None:
            raise RuntimeError(f"{spec.name} sidecar가 readiness 전에 비정상 종료했습니다 (exit={code}).")
        try:
            with urllib.request.urlopen(spec.health_url, timeout=1) as response:
                if response.status == 200:
                    return
        except OSError:
            pass
        time.sleep(0.25)
    raise RuntimeError(f"{spec.name} sidecar readiness 시간 초과: {spec.health_url}")


def warmup_sidecar(spec: ChildSpec, process: subprocess.Popen, timeout: float) -> float:
    """Run one real production inference through a sidecar before gateway startup."""
    print(f"[launcher] {spec.name} warmup...", flush=True)
    started = time.perf_counter()
    request = urllib.request.Request(spec.warmup_url, data=b"{}", method="POST")
    request.add_header("Content-Type", "application/json")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.loads(response.read())
    except Exception as error:  # noqa: BLE001
        code = process.poll()
        suffix = f" (exit={code})" if code is not None else ""
        raise RuntimeError(f"{spec.name} warmup 실패{suffix}: {error}") from error
    if response.status != 200 or not isinstance(payload, dict) or not payload.get("ok", False):
        detail = payload.get("error", "invalid warmup response") if isinstance(payload, dict) else "invalid warmup response"
        raise RuntimeError(f"{spec.name} warmup 실패: {detail}")
    elapsed_ms = (time.perf_counter() - started) * 1000
    print(f"[launcher] {spec.name} warmup ready ({elapsed_ms:.1f} ms)", flush=True)
    return elapsed_ms


def _forward_output(name: str, stream, on_line=None) -> None:
    for line in iter(stream.readline, ""):
        print(f"[{name}] {line.rstrip()}", flush=True)
        if on_line is not None:
            on_line(line)
    stream.close()


def start_child(spec: ChildSpec, on_line=None) -> subprocess.Popen:
    env = os.environ.copy()
    src_dir = str(ROOT / "src")
    if "PYTHONPATH" in env and env["PYTHONPATH"]:
        env["PYTHONPATH"] = f"{src_dir}{os.pathsep}{env['PYTHONPATH']}"
    else:
        env["PYTHONPATH"] = src_dir
    process = subprocess.Popen(
        spec.command,
        cwd=ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        text=True,
        bufsize=1,
        start_new_session=True,
    )
    assert process.stdout is not None
    threading.Thread(target=_forward_output, args=(spec.name, process.stdout, on_line), daemon=True).start()
    return process



def tunnel_command(
    mode: str,
    named_tunnel: str | None,
    protocol: str = "auto",
) -> list[str] | None:
    if mode == "none":
        return None
    token = os.environ.get("CLOUDFLARE_TUNNEL_TOKEN") if mode == "named" else None
    if mode == "named" and not token:
        raise RuntimeError(
            "--tunnel named에는 CLOUDFLARE_TUNNEL_TOKEN 환경변수가 필요합니다.\n"
            "설정: export CLOUDFLARE_TUNNEL_TOKEN='…'\n"
            "token 값은 .env 또는 Git에 저장하지 마세요."
        )
    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        raise RuntimeError(
            "cloudflared를 찾을 수 없습니다. 시스템 패키지 또는 공식 binary를 설치한 뒤 "
            "--tunnel quick 또는 --tunnel named를 다시 실행하세요."
        )
    if mode == "quick":
        return [
            cloudflared, "tunnel", "--protocol", protocol,
            "--url", f"http://{HOST}:{PORTS['gateway']}",
        ]
    # --tunnel-name is retained only for CLI compatibility. Remotely-managed
    # tunnels authenticate and select the tunnel solely through this token.
    return [cloudflared, "tunnel", "--protocol", protocol, "run", "--token", token]


def announce_public_url(url: str) -> None:
    """Print only the public URL; never include the Cloudflare tunnel token."""
    print(f"[launcher] Mallo public URL:\n{url}", flush=True)


def wait_for_gateway_ready(spec: ChildSpec, process: subprocess.Popen, timeout: float) -> None:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if (code := process.poll()) is not None:
            raise RuntimeError(f"gateway가 ready 전에 비정상 종료했습니다 (exit={code}).")
        try:
            with urllib.request.urlopen(spec.health_url, timeout=1) as response:
                payload = json.loads(response.read())
            if response.status == 200 and payload.get("status") == "ready" and payload.get("warmed") is True:
                return
        except (OSError, ValueError):
            pass
        time.sleep(0.25)
    raise RuntimeError("gateway health가 ready/warmed 상태가 되지 않았습니다.")


def wait_for_quick_tunnel_url(
    process: subprocess.Popen,
    url_event: threading.Event,
    urls: list[str],
    timeout: float,
) -> str:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if url_event.wait(timeout=0.1):
            return urls[0]
        if (code := process.poll()) is not None:
            raise RuntimeError(f"cloudflared Quick Tunnel이 URL 생성 전에 비정상 종료했습니다 (exit={code}).")
    raise RuntimeError("cloudflared Quick Tunnel URL 감지 시간 초과입니다.")


def terminate_children(children: dict[str, subprocess.Popen]) -> None:
    for process in children.values():
        if process.poll() is None:
            process.terminate()
    deadline = time.monotonic() + 10
    for name, process in children.items():
        if process.poll() is None:
            try:
                process.wait(timeout=max(0.1, deadline - time.monotonic()))
            except subprocess.TimeoutExpired:
                print(f"[launcher] {name} 종료 시간 초과, 강제 종료합니다.", file=sys.stderr, flush=True)
                process.kill()


def build_specs(args: argparse.Namespace) -> tuple[list[ChildSpec], ChildSpec]:
    runtime_interpreter = venv_python("runtime")
    nlu_interpreter = venv_python("nlu")
    assert_environment_ready("runtime", runtime_interpreter)
    assert_environment_ready("nlu", nlu_interpreter)
    runtime_python = str(runtime_interpreter)
    nlu_python = str(nlu_interpreter)
    stt_model = getattr(args, "stt_model", DEFAULT_STT_MODEL)
    stt_cmd = [runtime_python, "-m", "sidecars.stt_server", "--host", HOST, "--port", str(PORTS["stt"])]
    if stt_model is not None:
        stt_cmd.extend(["--model", str(stt_model)])
    stt = ChildSpec("STT", stt_cmd, f"http://{HOST}:{PORTS['stt']}/health", f"http://{HOST}:{PORTS['stt']}/warmup")
    nlu = ChildSpec("NLU", [nlu_python, "-m", "sidecars.nlu_server", "--host", HOST, "--port", str(PORTS["nlu"]), "--model", str(args.nlu_model)], f"http://{HOST}:{PORTS['nlu']}/health", f"http://{HOST}:{PORTS['nlu']}/warmup")
    tts = ChildSpec("TTS", [runtime_python, "-m", "sidecars.tts_server", "--host", HOST, "--port", str(PORTS["tts"]), "--checkpoint", str(args.tts_checkpoint), "--config", str(args.tts_config), "--speaker", args.tts_speaker, "--device", "cuda"], f"http://{HOST}:{PORTS['tts']}/health", f"http://{HOST}:{PORTS['tts']}/warmup")

    gateway = ChildSpec("GATEWAY", [runtime_python, "-m", "app.server", "--host", HOST, "--port", str(PORTS["gateway"]), "--stt", "http", "--stt-model", f"http://{HOST}:{PORTS['stt']}/transcribe", "--nlu", "http", "--nlu-url", f"http://{HOST}:{PORTS['nlu']}/parse", "--tts", "http", "--tts-url", f"http://{HOST}:{PORTS['tts']}/synthesize", "--sidecar-gateway"], f"http://{HOST}:{PORTS['gateway']}/health", "")
    if args.debug_log is not None:
        gateway.command.extend(["--debug-log", str(args.debug_log)])
    return [stt, nlu, tts], gateway


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Mallo multi-service gateway launcher")
    parser.add_argument("--ready-timeout", type=float, default=180.0)
    parser.add_argument("--stt-model", type=Path, default=DEFAULT_STT_MODEL)
    parser.add_argument("--nlu-model", type=Path, default=DEFAULT_NLU_MODEL)
    parser.add_argument("--tts-checkpoint", type=Path, default=DEFAULT_TTS_CHECKPOINT)
    parser.add_argument("--tts-config", type=Path, default=DEFAULT_TTS_CONFIG)
    parser.add_argument("--tts-speaker", default="10")
    parser.add_argument(
        "--tunnel",
        choices=("none", "quick", "named"),
        default="none",
        help="Cloudflare tunnel mode (default: none, so local development is not exposed)",
    )
    parser.add_argument(
        "--tunnel-name",
        default=None,
        help="Deprecated compatibility option; remotely-managed named tunnels use CLOUDFLARE_TUNNEL_TOKEN",
    )
    parser.add_argument(
        "--tunnel-protocol",
        choices=("auto", "http2", "quic"),
        default="auto",
        help=(
            "Cloudflare edge transport (default auto; use http2 when UDP/QUIC is unstable)"
        ),
    )
    parser.add_argument(
        "--public-url",
        default=DEFAULT_PUBLIC_URL,
        help="Public Named Tunnel URL (default: MALLO_PUBLIC_URL or CLOUDFLARE_DOMAIN)",
    )
    parser.add_argument("--tunnel-ready-timeout", type=float, default=30.0)
    parser.add_argument(
        "--debug-log",
        type=Path,
        default=None,
        help="Forward gateway microphone QA JSONL path (e.g. logs/qa-20260826.jsonl)",
    )
    return parser.parse_args(argv)


def main() -> int:
    args = parse_args()

    # Automatically ensure frontend runtime configuration is prepared
    try:
        from scripts.runtime.generate_runtime_config import write_runtime_config
        write_runtime_config()
    except Exception as error:  # noqa: BLE001
        print(f"[launcher] runtime config 준비 건너뜀: {error}", file=sys.stderr)
    def _handle_termination(signum, frame) -> None:
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, _handle_termination)
    children: dict[str, subprocess.Popen] = {}
    try:
        command = tunnel_command(args.tunnel, args.tunnel_name, args.tunnel_protocol)
        assert_ports_available(PORTS.values())
        sidecars, gateway = build_specs(args)
        for spec in sidecars:
            children[spec.name] = start_child(spec)
        for spec in sidecars:
            wait_until_ready(spec, children[spec.name], args.ready_timeout)
            print(f"[launcher] {spec.name} ready", flush=True)
        for spec in sidecars:
            warmup_sidecar(spec, children[spec.name], args.ready_timeout)
        print("[launcher] all models warmed", flush=True)
        children[gateway.name] = start_child(gateway)
        wait_for_gateway_ready(gateway, children[gateway.name], 30)
        print(f"[launcher] Mallo gateway ready at http://{HOST}:{PORTS['gateway']}", flush=True)
        if command is not None:
            quick_urls: list[str] = []
            quick_url_event = threading.Event()

            def detect_quick_url(line: str) -> None:
                match = TRY_CLOUDFLARE_URL_RE.search(line)
                if match and not quick_urls:
                    quick_urls.append(match.group(0))
                    quick_url_event.set()

            tunnel_spec = ChildSpec("TUNNEL", command, "", "")
            children[tunnel_spec.name] = start_child(
                tunnel_spec,
                on_line=detect_quick_url if args.tunnel == "quick" else None,
            )
            if args.tunnel == "quick":
                public_url = wait_for_quick_tunnel_url(
                    children[tunnel_spec.name],
                    quick_url_event,
                    quick_urls,
                    args.tunnel_ready_timeout,
                )
                announce_public_url(public_url)
            else:
                announce_public_url(args.public_url)
        while True:
            for name, process in children.items():
                code = process.poll()
                if code is not None:
                    raise RuntimeError(f"{name} 프로세스가 비정상 종료했습니다 (exit={code}).")
            time.sleep(0.5)
    except KeyboardInterrupt:
        print("[launcher] 종료 신호를 받아 모든 Mallo 프로세스를 종료합니다.", flush=True)
        return 0
    except Exception as error:  # noqa: BLE001
        print(f"[launcher] 시작/감시 실패: {error}", file=sys.stderr, flush=True)
        return 1
    finally:
        terminate_children(children)


if __name__ == "__main__":
    raise SystemExit(main())
