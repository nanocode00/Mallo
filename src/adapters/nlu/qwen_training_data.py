"""NLU JSONL을 Qwen3 conversational SFT 입력으로 변환한다."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Protocol


REPOSITORY_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_PROCESSED_DIR = REPOSITORY_ROOT / "data/nlu/processed"
DEFAULT_OUTPUT_DIR = DEFAULT_PROCESSED_DIR / "qwen3"
DEFAULT_MENU_PATH = REPOSITORY_ROOT / "src/config/menu.json"
DEFAULT_COMMAND_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command.schema.json"
DEFAULT_ERROR_SCHEMA_PATH = REPOSITORY_ROOT / "schemas/order-command-error.schema.json"
TRAINING_SPLITS = {"train", "validation"}


class TrainingDataError(ValueError):
    """학습 입력 또는 변환 설정이 계약을 위반했다."""


class ChatTokenizer(Protocol):
    """Transformers tokenizer에서 사용하는 Chat Template 최소 계약."""

    def apply_chat_template(self, conversation: list[dict[str, str]], **kwargs: Any) -> str:
        ...


def canonical_json(value: Any) -> str:
    """학습 정답 비교에 사용할 결정론적 JSON을 반환한다."""

    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise TrainingDataError(f"계약 파일을 읽을 수 없습니다: {path}") from error
    if not isinstance(value, dict):
        raise TrainingDataError(f"JSON 객체가 필요합니다: {path}")
    return value


def build_system_prompt(
    *,
    menu_path: Path = DEFAULT_MENU_PATH,
    command_schema_path: Path = DEFAULT_COMMAND_SCHEMA_PATH,
    error_schema_path: Path = DEFAULT_ERROR_SCHEMA_PATH,
) -> str:
    """Menu DB와 Schema에서 compact한 NLU system prompt를 생성한다."""

    menu = _load_object(menu_path)
    command_schema = _load_object(command_schema_path)
    error_schema = _load_object(error_schema_path)
    try:
        command_properties = command_schema["$defs"]["orderCommand"]["properties"]
        intents = command_properties["intent"]["enum"]
        error_codes = error_schema["properties"]["code"]["enum"]
        catalog = {
            "menu_version": menu["version"],
            "categories": {row["id"]: row["name"] for row in menu["categories"]},
            "menus": {
                row["id"]: {
                    "name": row["name"],
                    "category": row["category_id"],
                    "temperatures": row["temperature_options"],
                }
                for row in menu["items"]
            },
            "tags": {row["id"]: row["name"] for row in menu["tag_definitions"]},
        }
    except (KeyError, TypeError) as error:
        raise TrainingDataError("Menu DB 또는 OrderCommand Schema 구조가 올바르지 않습니다") from error

    semantic_fields = [key for key in command_properties if key != "request_id"]
    rules = [
        "당신은 말로 카페 키오스크의 한국어 NLU다. /no_think",
        "입력의 utterance와 cart_before만 해석하고 설명이나 Markdown 없이 JSON 하나만 출력한다.",
        "정상은 발화 순서의 OrderCommand 배열, 오류는 OrderCommandError 객체다.",
        f"Command 필드={canonical_json(semantic_fields)}; 사용하지 않는 필드는 null이며 request_id는 출력 금지다.",
        f"Intent={canonical_json(intents)}; 오류 code={canonical_json(error_codes)}.",
        "메뉴·카테고리·태그는 아래 공식 ID만 사용한다. 가격과 총액은 만들지 않는다.",
        "같은 메뉴·온도·옵션은 수량을 합치고, 수량 변경은 변경 후 최종 수량을 출력한다.",
        "수정·삭제 대상은 cart_before에 있어야 하며 여러 후보를 특정할 수 없으면 AMBIGUOUS_TARGET이다.",
        "ADD_ITEM 온도 미지정은 temperature=null으로 유지하고 HOT/ICE를 다시 묻거나 임의 선택하지 않는다.",
        "명시된 메뉴가 여러 개인 추가 요청은 메뉴별 수량·온도를 발화 순서대로 각각 ADD_ITEM으로 출력한다. cart_before에 있어도 '추가'는 새 ADD_ITEM이다.",
        "지원되지 않는 혼합 요청은 MIXED_INTENT, 단일 요청은 UNSUPPORTED_UTTERANCE다.",
        f"공식 카탈로그={canonical_json(catalog)}",
    ]
    return "\n".join(rules)


def build_compact_system_prompt(
    *,
    menu_path: Path = DEFAULT_MENU_PATH,
    command_schema_path: Path = DEFAULT_COMMAND_SCHEMA_PATH,
    error_schema_path: Path = DEFAULT_ERROR_SCHEMA_PATH,
) -> str:
    """동일 의미 계약을 짧은 key와 배열로 보존한 추론용 Prompt를 생성한다."""

    menu = _load_object(menu_path)
    command_schema = _load_object(command_schema_path)
    error_schema = _load_object(error_schema_path)
    try:
        properties = command_schema["$defs"]["orderCommand"]["properties"]
        fields = [key for key in properties if key != "request_id"]
        intents = properties["intent"]["enum"]
        error_codes = error_schema["properties"]["code"]["enum"]
        catalog = {
            "c": [[row["id"], row["name"]] for row in menu["categories"]],
            "m": [
                [row["id"], row["name"], row["temperature_options"]]
                for row in menu["items"]
            ],
            "t": [[row["id"], row["name"]] for row in menu["tag_definitions"]],
        }
    except (KeyError, TypeError) as error:
        raise TrainingDataError("Menu DB 또는 OrderCommand Schema 구조가 올바르지 않습니다") from error

    rules = [
        "말로 카페 한국어 NLU. /no_think JSON 하나만 출력; 설명/Markdown 금지.",
        "입력={utterance,cart_before}. 정상=발화순 OrderCommand 배열; 오류=OrderCommandError 객체.",
        f"필드={canonical_json(fields)}; 미사용=null; request_id/가격/총액 금지.",
        f"I={canonical_json(intents)}; E={canonical_json(error_codes)}.",
        "공식 ID만 사용. 동일 메뉴·온도·옵션 수량 합산; 수량 변경은 최종값.",
        "수정/삭제 대상은 cart에 필요; 불특정=AMBIGUOUS_TARGET; ADD 온도 미지정은 null 유지.",
        "여러 명시 메뉴 추가는 발화 순서대로 각각 ADD_ITEM; cart_before에 있어도 추가는 UPDATE가 아니다.",
        "미지원 혼합=MIXED_INTENT; 미지원 단일=UNSUPPORTED_UTTERANCE.",
        f"ID(c=category,m=menu[id,name,temperatures],t=tag)={canonical_json(catalog)}",
    ]
    return "\n".join(rules)


def build_compact_output_system_prompt() -> str:
    """v1 의미 계약을 유지하고 null key 생략만 요청하는 추론용 Prompt다."""

    prompt = build_system_prompt()
    prompt = prompt.replace(
        "사용하지 않는 필드는 null이며 request_id는 출력 금지다.",
        "값이 null인 필드는 JSON에서 생략하고 request_id는 출력 금지다. runtime이 생략 필드를 null로 복원한다.",
    )
    return prompt


def _require_record(record: Any) -> dict[str, Any]:
    if not isinstance(record, dict):
        raise TrainingDataError("JSONL 행은 객체여야 합니다")
    try:
        sample_id = record["sample_id"]
        utterance = record["input"]["utterance"]
        cart_before = record["input"]["cart_before"]
        output_type = record["output"]["type"]
        output_value = record["output"]["value"]
        metadata = record["metadata"]
    except (KeyError, TypeError) as error:
        raise TrainingDataError("processed JSONL 필수 필드가 누락됐습니다") from error
    if not isinstance(sample_id, str) or not isinstance(utterance, str):
        raise TrainingDataError("sample_id와 utterance는 문자열이어야 합니다")
    if not isinstance(cart_before, list):
        raise TrainingDataError("cart_before는 배열이어야 합니다")
    if output_type == "commands":
        if not isinstance(output_value, list) or not output_value:
            raise TrainingDataError("commands 정답은 비어 있지 않은 배열이어야 합니다")
        if any(not isinstance(command, dict) or "request_id" in command for command in output_value):
            raise TrainingDataError("학습 Command에 request_id가 있거나 객체가 아닙니다")
    elif output_type == "error":
        if not isinstance(output_value, dict):
            raise TrainingDataError("error 정답은 객체여야 합니다")
    else:
        raise TrainingDataError(f"지원하지 않는 output.type입니다: {output_type}")
    if not isinstance(metadata, dict):
        raise TrainingDataError("metadata는 객체여야 합니다")
    return record


def to_conversation(record: Any, system_prompt: str) -> dict[str, Any]:
    """processed 한 행을 assistant-only SFT용 대화 레코드로 변환한다."""

    row = _require_record(record)
    user_input = {
        "utterance": row["input"]["utterance"],
        "cart_before": row["input"]["cart_before"],
    }
    return {
        "sample_id": row["sample_id"],
        "messages": [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": canonical_json(user_input)},
            {"role": "assistant", "content": canonical_json(row["output"]["value"])},
        ],
        "metadata": row["metadata"],
    }


def render_chat(record: Any, system_prompt: str, tokenizer: ChatTokenizer) -> str:
    """실제 Qwen tokenizer에 non-thinking Chat Template를 적용한다."""

    conversation = to_conversation(record, system_prompt)
    return tokenizer.apply_chat_template(
        conversation["messages"],
        tokenize=False,
        add_generation_prompt=False,
        enable_thinking=False,
    )


def convert_file(input_path: Path, output_path: Path, *, split: str) -> int:
    """train 또는 validation JSONL을 conversational JSONL로 변환한다."""

    if split not in TRAINING_SPLITS:
        raise TrainingDataError("학습 변환은 train과 validation Split만 허용합니다")
    system_prompt = build_system_prompt()
    output_path.parent.mkdir(parents=True, exist_ok=True)
    count = 0
    with input_path.open("r", encoding="utf-8") as source, output_path.open(
        "w", encoding="utf-8", newline="\n"
    ) as target:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                raise TrainingDataError(f"빈 JSONL 행입니다: {line_number}")
            try:
                record = json.loads(line)
            except json.JSONDecodeError as error:
                raise TrainingDataError(f"JSONL 파싱 오류: {line_number}") from error
            target.write(canonical_json(to_conversation(record, system_prompt)) + "\n")
            count += 1
    if count == 0:
        raise TrainingDataError("입력 JSONL이 비어 있습니다")
    return count


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--split", required=True, choices=("train", "validation", "test"))
    parser.add_argument("--input", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args(argv)
    input_path = args.input or DEFAULT_PROCESSED_DIR / f"{args.split}.jsonl"
    output_path = args.output or DEFAULT_OUTPUT_DIR / f"{args.split}.jsonl"
    count = convert_file(input_path, output_path, split=args.split)
    print(f"{args.split}: {count}개 변환 -> {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
