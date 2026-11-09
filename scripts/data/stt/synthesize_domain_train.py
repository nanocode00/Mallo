"""
도메인 학습 데이터 합성
======================

TTS를 이용하여 카페 주문 도메인 학습 음성을 합성한다.
STT 모델 추가 파인튜닝용 데이터를 생성한다.

출력:
    - stt_data/domain_train/ 디렉토리에 WAV 파일 저장
    - domain_train.csv: 학습셋 메타데이터 (text, audio_path, menu, quantity, option, voice)

사용법:
    python synthesize_domain_train.py
    python synthesize_domain_train.py --num-samples 2000
    python synthesize_domain_train.py --output-dir ./my_train_set

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

DEFAULT_OUTPUT_DIR = STT_DIR / "stt_data" / "domain_train"

VOICES = [
    "ko-KR-SunHiNeural",
    "ko-KR-InJoonNeural",
    "ko-KR-HyunsuMultilingualNeural",
]

SEED = 42


# ============================================================
# 주문 표현 템플릿 (학습용 - 더 다양하게)
# ============================================================

# 1. 기본 주문 (메뉴명 + 수량)
BASIC_ORDER_TEMPLATES = [
    "{menu} 주세요",
    "{menu} 하나 주세요",
    "{menu} 한 잔 주세요",
    "{menu} 두 잔 주세요",
    "{menu} 세 잔 주세요",
    "{menu} 네 잔 주세요",
    "{menu} 다섯 잔 주세요",
    "{menu} 하나요",
    "{menu} 두 잔이요",
    "{menu} 주문할게요",
    "{menu} 하나 주문할게요",
    "{menu} 두 잔 주문할게요",
    "{menu} 하나 시켜주세요",
    "{menu} 두 잔 시켜주세요",
    "하나 {menu} 주세요",
    "두 잔 {menu} 주세요",
    "세 잔 {menu} 주세요",
    "{menu} 하나요PLEASE",
    "{menu} 두 잔이요",
]

# 2. 옵션 포함 주문
OPTION_ORDER_TEMPLATES = [
    "아이스 {menu} 주세요",
    "핫 {menu} 주세요",
    "{menu} 아이스로 주세요",
    "{menu} 핫으로 주세요",
    "아이스 {menu} 하나 주세요",
    "핫 {menu} 두 잔 주세요",
    "{menu} 아이스 두 잔 주세요",
    "{menu} 핫 세 잔 주세요",
    "아이스 {menu} 두 잔요",
    "핫 {menu} 하나요",
    "{menu} 아이스로 하나요",
    "{menu} 핫으로 두 잔요",
    "따뜻한 {menu} 주세요",
    "차가운 {menu} 주세요",
    "{menu} 차가운 걸로 주세요",
    "{menu} 따뜻한 걸로 주세요",
]

# 3. 수정/변경 표현
MODIFY_TEMPLATES = [
    "{menu} 빼줘",
    "{menu} 취소해줘",
    "{menu} 삭제해줘",
    "{menu} 수량 변경해줘",
    "{menu} {quantity}로 바꿔줘",
    "{menu} {quantity}으로 변경해줘",
    "{menu}에서 {quantity}로 바꿔줘",
    "{menu} 아이스에서 핫으로 바꿔줘",
    "{menu} 핫에서 아이스로 바꿔줘",
    "{menu} 온도 변경해줘",
    "{menu} 따뜻한 걸로 바꿔줘",
    "{menu} 차가운 걸로 바꿔줘",
]

# 4. 확인/조회 표현
CONFIRM_TEMPLATES = [
    "장바구니 보여줘",
    "뭐 담았어",
    "주문 내역 보여줘",
    "현재 주문 확인해줘",
    "총 얼마야",
    "주문할게요",
    "결제할게요",
    "이렇게 해주세요",
    "네 맞아요",
    "그래 그렇게 해줘",
    "확인해주세요",
    "주문 확정해줘",
]

# 5. 전체 취소
CANCEL_TEMPLATES = [
    "다 취소해줘",
    "전부 취소해줘",
    "모두 취소해줘",
    "주문 취소해줘",
    "취소해줘",
]

# 6. 자연스러운 대화체 (filler 포함)
CASUAL_TEMPLATES = [
    "어 {menu} 하나 주세요",
    "어 아이스 {menu} 두 잔 주세요",
    "음 {menu} 하나요",
    "어음 {menu} 두 잔이요",
    "그니까 {menu} 하나 주세요",
    "아 {menu} 아이스 하나요",
    "어 핫 {menu} 두 잔요",
    "음 {menu} 세 잔 주세요",
    "어 {menu} 하나하고 {menu2} 하나 주세요",
    "음 아이스 {menu} 하나하고 핫 {menu} 하나 주세요",
]

QUANTITIES = ["한 잔", "두 잔", "세 잔", "네 잔", "다섯 잔", "1잔", "2잔", "3잔", "4잔", "5잔"]

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
# 학습 데이터 생성
# ============================================================

def load_menu() -> list[dict]:
    with open(MENU_PATH, encoding="utf-8") as f:
        data = json.load(f)
    return data["items"]


def generate_train_sentences(
    menu_items: list[dict],
    num_samples: int,
) -> list[dict]:
    """학습용 주문 문장 생성."""
    sentences = []
    sentence_id = 0

    for item in menu_items:
        menu_id = item["id"]
        menu_name = item["name"]
        options = OPTIONS.get(menu_id, [])

        # 1. 기본 주문
        for template in BASIC_ORDER_TEMPLATES:
            text = template.format(menu=menu_name)
            sentences.append({
                "id": f"train_{sentence_id:04d}",
                "text": text,
                "menu": menu_name,
                "quantity": None,
                "option": None,
                "template_type": "basic_order",
            })
            sentence_id += 1

        # 2. 옵션 포함 주문
        if options:
            for template in OPTION_ORDER_TEMPLATES:
                text = template.format(menu=menu_name)
                sentences.append({
                    "id": f"train_{sentence_id:04d}",
                    "text": text,
                    "menu": menu_name,
                    "quantity": None,
                    "option": options[0] if options else None,
                    "template_type": "option_order",
                })
                sentence_id += 1

        # 3. 수정/변경
        for template in MODIFY_TEMPLATES:
            for qty in random.sample(QUANTITIES, min(3, len(QUANTITIES))):
                text = template.format(menu=menu_name, quantity=qty)
                sentences.append({
                    "id": f"train_{sentence_id:04d}",
                    "text": text,
                    "menu": menu_name,
                    "quantity": qty,
                    "option": None,
                    "template_type": "modify",
                })
                sentence_id += 1

    # 4. 확인/조회 (메뉴 무관)
    for template in CONFIRM_TEMPLATES:
        sentences.append({
            "id": f"train_{sentence_id:04d}",
            "text": template,
            "menu": None,
            "quantity": None,
            "option": None,
            "template_type": "confirm",
        })
        sentence_id += 1

    # 5. 전체 취소
    for template in CANCEL_TEMPLATES:
        sentences.append({
            "id": f"train_{sentence_id:04d}",
            "text": template,
            "menu": None,
            "quantity": None,
            "option": None,
            "template_type": "cancel",
        })
        sentence_id += 1

    # 6. 자연스러운 대화체 (메뉴 쌍 조합)
    for item1 in menu_items:
        for item2 in menu_items:
            if item1["id"] >= item2["id"]:
                continue
            for template in CASUAL_TEMPLATES:
                text = template.format(
                    menu=item1["name"],
                    menu2=item2["name"],
                )
                sentences.append({
                    "id": f"train_{sentence_id:04d}",
                    "text": text,
                    "menu": f"{item1['name']}, {item2['name']}",
                    "quantity": None,
                    "option": None,
                    "template_type": "casual_multi",
                })
                sentence_id += 1

    # 목표 수량만큼 랜덤 샘플링
    random.shuffle(sentences)
    if len(sentences) > num_samples:
        sentences = sentences[:num_samples]

    return sentences


# ============================================================
# TTS 합성
# ============================================================

async def synthesize_audio(
    text: str,
    output_path: Path,
    voice: str,
) -> bool:
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
) -> list[dict]:
    output_dir.mkdir(parents=True, exist_ok=True)
    results = []

    for i, sentence in enumerate(sentences):
        voice = random.choice(VOICES)
        audio_filename = f"{sentence['id']}.wav"
        audio_path = output_dir / audio_filename

        success = await synthesize_audio(
            sentence["text"],
            audio_path,
            voice,
        )

        results.append({
            **sentence,
            "audio_path": str(audio_path) if success else None,
            "voice": voice,
            "status": "success" if success else "failed",
        })

        if (i + 1) % 100 == 0 or i == len(sentences) - 1:
            print(f"진행: {i + 1}/{len(sentences)}")

    return results


# ============================================================
# CSV 저장
# ============================================================

def save_csv(results: list[dict], output_path: Path) -> None:
    fieldnames = [
        "id", "text", "audio_path", "menu", "quantity", "option",
        "template_type", "voice", "status",
    ]
    with open(output_path, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(results)


# ============================================================
# 메인
# ============================================================

async def main() -> None:
    parser = argparse.ArgumentParser(description="도메인 학습 데이터 합성")
    parser.add_argument("--output-dir", type=str, default=str(DEFAULT_OUTPUT_DIR))
    parser.add_argument("--num-samples", type=int, default=1500, help="목표 합성 수")
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args()

    random.seed(args.seed)
    output_dir = Path(args.output_dir)

    print("=" * 60)
    print("도메인 학습 데이터 합성")
    print("=" * 60)
    print(f"출력: {output_dir}")
    print(f"목표 수: {args.num_samples}")
    print()

    menu_items = load_menu()
    print(f"메뉴 수: {len(menu_items)}")

    sentences = generate_train_sentences(menu_items, args.num_samples)
    print(f"생성된 문장 수: {len(sentences)}")

    print("\n합성 시작...")
    results = await synthesize_all(sentences, output_dir)

    success_count = sum(1 for r in results if r["status"] == "success")
    failed_count = sum(1 for r in results if r["status"] == "failed")
    print(f"\n합성 완료: 성공 {success_count}, 실패 {failed_count}")

    csv_path = output_dir / "domain_train.csv"
    save_csv(results, csv_path)
    print(f"메타데이터 저장: {csv_path}")

    print("\n" + "=" * 60)
    print("완료")
    print("=" * 60)


if __name__ == "__main__":
    asyncio.run(main())
