#!/usr/bin/env python3
"""Refresh Mallo's Adaptive TTS showcase without touching model comparison."""

from __future__ import annotations

import argparse
import html
import io
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

sys.path.insert(0, "src")
sys.path.insert(0, "data/tts/repos/MeloTTS")

from config.settings import load_menu
from app.server import _SessionApp
from domain.adaptive_response_realizer import AdaptiveResponseRealizer
from domain.conversation import ConversationAgent
from domain.intents import Intent
from domain.korean_normalizer import normalize_korean_text_for_tts
from domain.models import Cart, FulfillmentType, OrderCommand, OrderResult, Temperature
from domain.text_transformer import AdaptiveTextTransformer
from domain.tts_result import TTSResult


# Historical representatives remain visible for comparison. Their audible
# counterpart is an actual QUERY_CART response so L2 realization is truthful.
SAMPLES = [
    {"id": "quantity-price", "title": "장바구니 요약", "original": "매장 이용 주문으로 현재 아이스 아메리카노 한 잔과 따뜻한 카페라떼 두 잔이 담겨 있으며, 총 15,100원입니다.", "kind": "cart"},
    {"id": "unit", "title": "복수 메뉴 추가 결과", "original": "아이스 아메리카노 한 잔과 바스크 치즈 케이크 한 개를 담았습니다.", "kind": "multi_add"},
    {"id": "price", "title": "가격 안내", "original": "카페라떼 한 잔은 5,200원입니다.", "kind": "price"},
]

LEVEL_POLICY = {
    0: {"speed": 1.0, "gap_ms": 0, "purpose": "기본 속도로 원문 응답을 안내합니다."},
    1: {"speed": 0.85, "gap_ms": 280, "purpose": "속도를 낮추고 원문 문장·쉼표 경계에서 호흡을 둡니다."},
    2: {"speed": 0.75, "gap_ms": 480, "purpose": "가장 느린 속도와 더 짧은 원문 의미 경계로 재안내합니다."},
}


class Synthesizer(Protocol):
    def synthesize(self, text: str, level: int = 0) -> TTSResult | None: ...


def _melo_adapter() -> Synthesizer:
    from adapters.tts.melotts_adapter import MeloTTSAdapter

    return MeloTTSAdapter(
        device="cpu", config_path="models/tts/mallo-friendly/config.json",
        ckpt_path="models/tts/mallo-friendly/G_2800.pth", speaker="10",
    )


def _scenario_result(sample: dict[str, Any]):
    """Create production response shapes for the three approved representatives."""
    menu = load_menu()
    agent = ConversationAgent(menu)
    menu_by_id = {item.id: item for item in menu}
    if sample["kind"] == "cart":
        cart = Cart()
        for command in (
            OrderCommand.create(Intent.ADD_ITEM, "americano", quantity=1, temperature=Temperature.ICED),
            OrderCommand.create(Intent.ADD_ITEM, "cafe_latte", quantity=2, temperature=Temperature.HOT),
            OrderCommand.create(Intent.SET_FULFILLMENT, fulfillment_type=FulfillmentType.DINE_IN),
        ):
            cart = agent.execute([command], cart).cart
        commands = [OrderCommand.create(Intent.QUERY_CART)]
        return agent.execute(commands, cart), commands, menu_by_id
    if sample["kind"] == "multi_add":
        commands = [
            OrderCommand.create(Intent.ADD_ITEM, "americano", quantity=1, temperature=Temperature.ICED),
            OrderCommand.create(Intent.ADD_ITEM, "basque_cheesecake", quantity=1),
        ]
        return agent.execute(commands, Cart()), commands, menu_by_id
    # The price announcement is an authoritative catalog response.  The
    # realizer deliberately preserves this non-cart response at every level.
    return OrderResult(True, Cart(), sample["original"]), [], menu_by_id


def _production_chunks(text: str, *, level: int) -> list[str]:
    """Use the same server-side chunk selection as the browser contract."""
    if level == 0:
        # `_display_segments` has no instance state; this preserves the
        # Level-0 display-boundary exception in `_SessionApp._synthesize_segments`.
        return [
            AdaptiveTextTransformer.transform_to_chunks(segment, level=0)[0]
            for segment in _SessionApp._display_segments(None, text)
        ]
    return AdaptiveTextTransformer.transform_to_chunks(text, level=level)


def _synthesize_joined_chunks(
    adapter: Synthesizer, chunks: list[str], *, level: int, gap_ms: int, output_path: Path,
) -> dict[str, Any]:
    """Match production browser playback in one listening WAV.

    Production synthesizes each ``tts_segment`` separately then waits after a
    non-final segment. This combines the same chunk audio with zero frames.
    """
    import numpy as np
    import soundfile as sf

    parts: list[Any] = []
    sample_rate: int | None = None
    channels: int | None = None
    chunk_durations: list[float] = []
    latency_ms = 0.0
    for index, chunk in enumerate(chunks):
        started = time.perf_counter()
        result = adapter.synthesize(chunk, level=level)
        latency_ms += (time.perf_counter() - started) * 1000.0
        if result is None or result.audio is None:
            raise RuntimeError(f"TTS chunk synthesis failed: level={level}, chunk={index}")
        data, rate = sf.read(io.BytesIO(result.audio), dtype="float32", always_2d=True)
        if sample_rate is None:
            sample_rate, channels = rate, data.shape[1]
        elif rate != sample_rate or data.shape[1] != channels:
            raise RuntimeError("All synthesized chunks must use the same WAV format.")
        parts.append(data)
        chunk_durations.append(len(data) / rate)
        if index < len(chunks) - 1 and gap_ms:
            parts.append(np.zeros((round(rate * gap_ms / 1000), data.shape[1]), dtype="float32"))
    if sample_rate is None:
        raise RuntimeError("Adaptive showcase requires at least one TTS chunk.")
    combined = np.concatenate(parts, axis=0)
    sf.write(output_path, combined, sample_rate, format="WAV", subtype="PCM_16")
    return {
        "latency_ms": round(latency_ms, 3),
        "duration_s": round(len(combined) / sample_rate, 3),
        "sample_rate": sample_rate,
        "chunk_durations_s": [round(value, 3) for value in chunk_durations],
        "silence_duration_s": round((gap_ms / 1000) * (len(chunks) - 1), 3),
    }


def _adaptive_page(rows: list[dict[str, Any]]) -> str:
    cards: list[str] = []
    for number, sample in enumerate(rows, start=1):
        panes: list[str] = []
        for item in sample["levels"]:
            chunks = "<br>".join(html.escape(chunk) for chunk in item["chunks"])
            panes.append(f'''<div class="comparison-pane"><div class="pane-header"><span class="pane-model-badge badge-lvl{item['level']}">Level {item['level']} · {item['speed']:.2f}x</span></div><p class="pane-text">{html.escape(item['realized_text'])}</p><dl class="adaptive-detail"><dt>실제 speed</dt><dd>{item['speed']:.2f}x</dd><dt>silence gap</dt><dd>{item['gap_ms']} ms × {max(len(item['chunks']) - 1, 0)}</dd><dt>chunk 방식</dt><dd>{html.escape(item['chunk_policy'])}</dd><dt>적용 목적</dt><dd>{html.escape(item['purpose'])}</dd><dt>실제 합성 chunk</dt><dd class="chunk-list">{chunks}</dd></dl><div class="audio-player-box-compact"><audio controls preload="metadata" src="{html.escape(item['audio_file'])}"></audio></div><div class="pane-meta"><span>합성 {item['latency_ms']:.1f} ms</span><span>재생 {item['duration_s']:.2f} 초</span></div></div>''')
        cards.append(f'''<article class="sample-card"><div class="sample-header"><div class="sample-title-group"><span class="case-badge">문장 {number:02d}</span><h3 class="sample-title">{html.escape(sample['title'])}</h3><span class="meta-pill">실제 주문 엔진 장바구니 요약 응답</span></div></div><div class="sentence-meta-box"><div class="sentence-row"><span class="sentence-label">이전 대표 문장</span><span class="text-original">{html.escape(sample['original'])}</span></div><div class="sentence-row"><span class="sentence-label">L0/L1 원본 응답</span><span class="text-normalized">{html.escape(sample['canonical_response'])}</span></div><div class="sentence-row"><span class="sentence-label">L2 semantic response</span><span class="text-normalized">{html.escape(sample['level_2_response'])}</span></div></div><div class="comparison-grid comparison-3col">{''.join(panes)}</div></article>''')
    return f'''<!DOCTYPE html><html lang="ko"><head><meta charset="UTF-8"><meta name="viewport" content="width=device-width, initial-scale=1.0"><title>말로 TTS Adaptive Speed 비교 — Level 0 · 1 · 2</title><meta name="description" content="production Adaptive TTS 정책과 같은 chunk 단위 합성·silence gap 비교"><link rel="icon" type="image/png" sizes="32x32" href="./assets/favicon-32.png"><link rel="icon" type="image/png" sizes="192x192" href="./assets/favicon-192.png"><link rel="icon" type="image/x-icon" href="./favicon.ico"><link rel="apple-touch-icon" sizes="180x180" href="./assets/apple-touch-icon.png"><meta name="theme-color" content="#1e3932"><link rel="stylesheet" href="https://cdn.jsdelivr.net/gh/orioncactus/pretendard@v1.3.9/dist/web/variable/pretendardvariable-dynamic-subset.min.css"><link rel="stylesheet" href="./styles/showcase.css"><style>.adaptive-detail{{display:grid;grid-template-columns:105px 1fr;gap:.35rem .6rem;margin:.8rem 0;font-size:.82rem}}.adaptive-detail dt{{font-weight:700;color:var(--ink-muted)}}.adaptive-detail dd{{margin:0;overflow-wrap:anywhere}}.chunk-list{{padding:.5rem;background:#f5f8f6;border-radius:6px}}</style></head><body><header class="site-header"><div class="container header-inner"><a class="brand" href="./" aria-label="TTS 쇼케이스 홈으로 이동"><span class="brand-mark">mallo</span><span class="brand-ko">말로</span></a><nav class="header-nav" aria-label="메인 네비게이션"><a class="nav-link" href="./">통합 쇼케이스</a><a class="nav-link" href="model-comparison.html">모델별 비교</a><a class="nav-link active" href="speed-levels.html" aria-current="page">Adaptive Speed</a></nav></div></header><section class="hero"><div class="container hero-content"><div class="hero-badge-wrap"><span class="hero-badge">Mallo · Production Adaptive Policy</span><span class="hero-badge-sub">Level 0 · 1 · 2 Comparison</span></div><h1>말로 TTS <strong>Adaptive Speed 비교</strong></h1><p class="hero-desc">production과 동일하게 각 chunk를 Level별로 합성하고, 다음 chunk 전 실제 silence gap을 WAV에 넣었습니다.</p><ul class="keyword-chips"><li>Level 0: 1.00x · gap 0ms</li><li>Level 1: 0.85x · gap 280ms</li><li>Level 2: 0.75x · gap 480ms</li><li>모델: Fine-tuned G_2800</li></ul></div></section><nav class="subnav-container" aria-label="TTS 쇼케이스 세부 메뉴"><div class="container subnav-inner"><a href="./" class="subnav-tab">통합 쇼케이스</a><a href="model-comparison.html" class="subnav-tab">모델별 비교 (Baseline vs G_2800)</a><a href="speed-levels.html" class="subnav-tab active" aria-current="page">Adaptive Speed (Level 0·1·2)</a><a href="results.json" class="subnav-tab subnav-json" target="_blank" rel="noopener noreferrer">메타데이터 (JSON) ↗</a></div></nav><main class="main-content container"><div class="policy-guide-box"><h2 style="font-size:1.15rem;font-weight:800;color:var(--green-dark);margin-bottom:.4rem">현재 production Adaptive TTS 정책</h2><div class="policy-grid"><div class="policy-card policy-card-lvl0"><div class="policy-header"><span class="policy-title">Level 0</span><span class="policy-speed">1.00x / 0ms</span></div><p class="policy-desc">정규화된 원문을 기본 속도로 안내합니다.</p></div><div class="policy-card policy-card-lvl1"><div class="policy-header"><span class="policy-title">Level 1</span><span class="policy-speed">0.85x / 280ms</span></div><p class="policy-desc">`transform_to_chunks()`의 문장·쉼표 경계를 사용합니다.</p></div><div class="policy-card policy-card-lvl2"><div class="policy-header"><span class="policy-title">Level 2</span><span class="policy-speed">0.75x / 480ms</span></div><p class="policy-desc">허용된 주문 결과만 semantic realization 후 더 작은 원문 의미 경계를 사용합니다.</p></div></div><p class="section-desc">자동 감속은 성공적으로 해석된 최근 4 turn 안의 두 번째 `REQUEST_CLARIFICATION`에서 한 단계만 올립니다. 명시적 `REQUEST_SLOWER`는 0→1→2로 올리고, 기본 속도 요청 또는 세션 reset은 Level 0으로 돌립니다. 반복 요청만으로는 레벨이 바뀌지 않습니다.</p></div><section class="section"><div class="section-header"><span class="section-tag">Chunk-by-Chunk Listening</span><h2 class="section-title">문장별 Level 0 · 1 · 2 청취 비교</h2><p class="section-desc">실제 합성에 사용된 텍스트와 chunk를 각 플레이어에 함께 표시합니다.</p></div>{''.join(cards)}</section><section class="cta-banner"><h2>Baseline과 Fine-tuned G_2800 비교는 <strong>별도 페이지에서 유지합니다</strong></h2><div class="cta-actions"><a class="btn btn-primary" href="model-comparison.html">MeloTTS 모델별 비교 보기</a></div></section></main><footer class="site-footer"><div class="container"><p>AI Human 7기 · D조 프로젝트 <strong>말로</strong> TTS Showcase</p><p style="margin-top:.3rem;font-size:.8rem;color:var(--ink-muted)">Adaptive Speed Levels (1.00x / 0.85x / 0.75x · 0ms / 280ms / 480ms)</p></div></footer></body></html>'''


def build_adaptive_showcase(
    output_dir: Path, adapter: Synthesizer | None = None, *, write_speed_levels_html: bool = False,
) -> list[dict[str, Any]]:
    """Refresh Adaptive WAV/metadata without replacing the curated showcase UI."""
    if not output_dir.is_dir():
        raise FileNotFoundError(f"Existing showcase directory is required: {output_dir}")
    results_path = output_dir / "results.json"
    if not results_path.is_file():
        raise FileNotFoundError(f"Existing showcase metadata is required: {results_path}")
    audio_dir = output_dir / "audio"
    audio_dir.mkdir(exist_ok=True)
    model = adapter or _melo_adapter()
    rows: list[dict[str, Any]] = []
    for sample in SAMPLES:
        result, commands, menu_by_id = _scenario_result(sample)
        realizer = AdaptiveResponseRealizer(menu_by_id)
        levels: list[dict[str, Any]] = []
        for level, policy in LEVEL_POLICY.items():
            realized = realizer.realize(result, commands, level=level)
            chunks = _production_chunks(realized.text, level=level)
            wav_name = f"speed-{sample['id']}-level-{level}.wav"
            metrics = _synthesize_joined_chunks(model, chunks, level=level, gap_ms=policy["gap_ms"], output_path=audio_dir / wav_name)
            levels.append({"level": level, "speed": policy["speed"], "gap_ms": policy["gap_ms"], "purpose": policy["purpose"], "realized_text": realized.text, "chunks": chunks, "chunk_policy": ("_SessionApp display segment 후 Level 0 정규화 (gap 없음)" if level == 0 else "AdaptiveTextTransformer: 문장·쉼표 경계" if level == 1 else "AdaptiveResponseRealizer 후 AdaptiveTextTransformer: 문장·접속 어미 경계"), "audio_file": f"audio/{wav_name}", **metrics})
        rows.append({"id": sample["id"], "title": sample["title"], "original": sample["original"], "canonical_response": realizer.realize(result, commands, level=0).text, "level_2_response": realizer.realize(result, commands, level=2).text, "source": "QUERY_CART after ADD_ITEM", "levels": levels})
    metadata = json.loads(results_path.read_text(encoding="utf-8"))
    metadata["generated_at"] = datetime.now(timezone.utc).isoformat()
    metadata["speed_comparison"] = rows
    metadata["adaptive_policy"] = {"source_of_truth": ["adapters.tts.melotts_adapter.MeloTTSAdapter", "domain.text_transformer.AdaptiveTextTransformer", "domain.adaptive_response_realizer.AdaptiveResponseRealizer"], "levels": LEVEL_POLICY, "audio_assembly": "Each production chunk is synthesized independently; silence is inserted only between non-final chunks."}
    if write_speed_levels_html:
        (output_dir / "speed-levels.html").write_text(_adaptive_page(rows), encoding="utf-8")
    results_path.write_text(json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return rows


def _render_page(title: str, description: str, rows: list[str]) -> str:
    return f"<!doctype html><html lang=\"ko\"><meta charset=\"utf-8\"><title>{html.escape(title)}</title><body><h1>{html.escape(title)}</h1><p>{html.escape(description)}</p>{''.join(rows)}</body></html>"


def main() -> None:
    parser = argparse.ArgumentParser(description="Mallo TTS 쇼케이스 생성기")
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--adaptive-only", action="store_true", help="Adaptive TTS 산출물만 갱신")
    parser.add_argument(
        "--write-speed-levels-html", action="store_true",
        help="명시적으로 요청한 경우에만 metadata 기반 HTML을 생성합니다.",
    )
    args = parser.parse_args()
    if not args.adaptive_only:
        raise SystemExit("모델 비교를 보호하기 위해 --adaptive-only를 명시해야 합니다.")
    rows = build_adaptive_showcase(
        args.output_dir, write_speed_levels_html=args.write_speed_levels_html,
    )
    print(f"Adaptive TTS 쇼케이스 갱신 완료: {args.output_dir} ({len(rows) * 3}개 WAV)")


if __name__ == "__main__":
    main()
