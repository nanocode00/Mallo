"""
도메인 평가 음성 합성 (S-10)
============================

TTS를 이용하여 카페 주문 도메인 평가 음성을 합성한다.

출력:
    - stt_data/domain_eval/ 디렉토리에 WAV 파일 저장
    - domain_eval.csv: 평가셋 메타데이터 (text, audio_path, menu, quantity, option)

사용법:
    python synthesize_domain_eval.py
    python synthesize_domain_eval.py --output-dir ./my_eval_set
    python synthesize_domain_eval.py --voice ko-YunhiNeural

주의:
    - edge-tts 온라인 연결 필요
    - 합성 음성 편향은 추후 실측 데이터로 교차 검증 가능
"""

from __future__ import annotations

import argparse
import asyncio
import csv
import json
import random
from pathlib import Path

import edge_tts

# ============================================================
# 설정
# ============================================================

STT_DIR = Path(__file__).resolve().parent
MENU_PATH = Path(__file__).resolve().parent.parent.parent / "config" / "menu.json"

# 기본 출력 디렉토리
DEFAULT_OUTPUT_DIR = STT_DIR / "stt_data" / "domain_eval"

# 한국어 TTS 음성 (여러 화자 지원)
VOICES = [
    "ko-KR-SunHiNeural",    # 여성 (기본)
    "ko-KR-InJoonNeural",   # 남성
    "ko-KR-HyunsuMultilingualNeural",  # 남성 (멀티링구얼)
]

DEFAULT_VOICE = "ko-KR-SunHiNeural"

# 시드
SEED = 42


# ============================================================
# 주문 표현 템플릿
# ============================================================

# 메뉴 주문 템플릿
MENU_TEMPLATES = [
    "{menu} 주세요",
    "{menu} 하나 주세요",
    "{menu} 한 잔 주세요",
    "{menu} 두 잔 주세요",
    "{menu} 세 잔 주세요",
    "{menu} 아이스로 주세요",
    "{menu} 핫으로 주세요",
    "아이스 {menu} 주세요",
    "핫 {menu} 주세요",
    "{menu} 아이스 하나 주세요",
    "{menu} 핫 두 잔 주세요",
    "{menu} 한 잔 아이스로",
    "{menu} 두 잔 핫으로",
    "{menu} 포장해주세요",
    "{menu} 여기서 마실게요",
]

# 수량 템플릿
QUANTITY_TEMPLATES = [
    "{menu} {quantity} 주세요",
    "{menu} {quantity} 아이스로 주세요",
    "{menu} {quantity} 핫으로 주세요",
    "아이스 {menu} {quantity}",
    "핫 {menu} {quantity}",
    "{quantity} {menu} 주문할게요",
]

QUANTITIES = ["한 잔", "두 잔", "세 잔", "네 잔", "다섯 잔"]

# 옵션 템플릿
OPTION_TEMPLATES = [
    "{menu} {option}로 주세요",
    "{option} {menu} 주세요",
    "{menu} {option} 하나 주세요",
    "{option}로 {menu} 두 잔 주세요",
]

OPTIONS = {
    "americano": ["아이스", "핫"],
    "cafe_latte": ["아이스", "핫"],
    "vanilla_latte": ["아이스", "핫"],
    "grapefruit_ade": ["아이스"],
    "matcha_latte": ["아이스", "핫"],
    "milk_tea": ["아이스", "핫"],
    "chamomile_tea": ["아이스", "핫"],
    "iced_tea": ["아이스"],
    "croffle_icecream": [],
    "basque_cheesecake": [],
}


# ============================================================
# 평가 데이터 생성
# ============================================================

def load_menu() -> list[dict]:
    """메뉴 데이터 로드."""
    with open(MENU_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["items"]


def generate_eval_sentences(menu_items: list[dict]) -> list[dict]:
    """평가용 주문 문장 생성."""
    sentences = []
    sentence_id = 0

    for item in menu_items:
        menu_id = item["id"]
        menu_name = item["name"]
        options = OPTIONS.get(menu_id, [])

        # 1. 기본 메뉴 주문
        for template in MENU_TEMPLATES:
            text = template.format(menu=menu_name)
            sentences.append({
                "id": f"eval_{sentence_id:04d}",
                "text": text,
                "menu": menu_name,
                "quantity": None,
                "option": None,
                "template_type": "menu_basic",
            })
            sentence_id += 1

        # 2. 수량 포함 주문
        for template in QUANTITY_TEMPLATES:
            for quantity in QUANTITIES:
                text = template.format(menu=menu_name, quantity=quantity)
                sentences.append({
                    "id": f"eval_{sentence_id:04d}",
                    "text": text,
                    "menu": menu_name,
                    "quantity": quantity,
                    "option": None,
                    "template_type": "quantity",
                })
                sentence_id += 1

        # 3. 옵션 포함 주문
        if options:
            for template in OPTION_TEMPLATES:
                for option in options:
                    text = template.format(menu=menu_name, option=option)
                    sentences.append({
                        "id": f"eval_{sentence_id:04d}",
                        "text": text,
                        "menu": menu_name,
                        "quantity": None,
                        "option": option,
                        "template_type": "option",
                    })
                    sentence_id += 1

    return sentences


# ============================================================
# TTS 합성
# ============================================================

async def synthesize_audio(
    text: str,
    output_path: Path,
    voice: str = DEFAULT_VOICE,
) -> bool:
    """edge-tts로 텍스트를 음성으로 합성한다."""
    try:
        communicate = edge_tts.Communicate(text, voice)
        await communicate.save(str(output_path))
        return True
    except Exception as e:
        print(f"합성 실패: {text} - {e}")
        return False


async def synthesize_all(
    sentences: list[dict],
    output_dir: Path,
    voice: str = DEFAULT_VOICE,
) -> list[dict]:
    """전체 문장을 합성하고 메타데이터를 반환한다."""
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, sentence in enumerate(sentences):
        audio_filename = f"{sentence['id']}.wav"
        audio_path = output_dir / audio_filename

        success = await synthesize_audio(
            sentence["text"],
            audio_path,
            voice,
        )

        if success:
            results.append({
                **sentence,
                "audio_path": str(audio_path),
                "voice": voice,
                "status": "success",
            })
        else:
            results.append({
                **sentence,
                "audio_path": None,
                "voice": voice,
                "status": "failed",
            })

        # 진행률 출력
        if (i + 1) % 50 == 0 or i == len(sentences) - 1:
            print(f"진행: {i + 1}/{len(sentences)}")

    return results


# ============================================================
# CSV 저장
# ============================================================

def save_csv(results: list[dict], output_path: Path) -> None:
    """평가 결과를 CSV로 저장한다."""
    fieldnames = [
        "id",
        "text",
        "audio_path",
        "menu",
        "quantity",
        "option",
        "template_type",
        "voice",
        "status",
    ]

    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


# ============================================================
# 메인
# ============================================================

async def main() -> None:
    parser = argparse.ArgumentParser(
        description="도메인 평가 음성 합성 (S-10)"
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default=str(DEFAULT_OUTPUT_DIR),
        help="출력 디렉토리 경로",
    )
    parser.add_argument(
        "--voice",
        type=str,
        default=DEFAULT_VOICE,
        help="TTS 음성 (ko-YunhiNeural, ko-SunHiNeural, ko-InJoonNeural)",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=SEED,
        help="랜덤 시드",
    )
    args = parser.parse_args()

    random.seed(args.seed)
    output_dir = Path(args.output_dir)

    print("=" * 60)
    print("도메인 평가 음성 합성 (S-10)")
    print("=" * 60)
    print(f"음성: {args.voice}")
    print(f"출력: {output_dir}")
    print()

    # 메뉴 로드
    menu_items = load_menu()
    print(f"메뉴 수: {len(menu_items)}")

    # 평가 문장 생성
    sentences = generate_eval_sentences(menu_items)
    print(f"생성된 문장 수: {len(sentences)}")

    # 합성
    print("\n합성 시작...")
    results = await synthesize_all(sentences, output_dir, args.voice)

    # 결과 통계
    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    print(f"\n합성 완료: 성공 {success_count}, 실패 {failed_count}")

    # CSV 저장
    csv_path = output_dir / "domain_eval.csv"
    save_csv(results, csv_path)
    print(f"메타데이터 저장: {csv_path}")

    print("\n" + "=" * 60)
    print("완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
