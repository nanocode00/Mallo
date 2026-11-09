from __future__ import annotations

import json
from pathlib import Path

from jsonschema import Draft202012Validator

from domain.models import (
    MenuAliasDefinition,
    MenuItem,
    MenuOptionPolicy,
    MenuTagDefinition,
    Temperature,
)


# ============================================================
# Menu DB
# ============================================================

MENU_PATH = Path(__file__).with_name("menu.json")
MENU_SCHEMA_PATH = Path(__file__).parents[2] / "schemas" / "menu.schema.json"


def load_menu(path: Path = MENU_PATH, schema_path: Path = MENU_SCHEMA_PATH) -> list[MenuItem]:
    with path.open(encoding="utf-8") as menu_file:
        catalog = json.load(menu_file)
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    Draft202012Validator(schema).validate(catalog)

    return [
        MenuItem(
            **{
                **item,
                "temperature_options": tuple(
                    Temperature(value) for value in item["temperature_options"]
                ),
                "tags": tuple(item["tags"]),
                "option_policy": MenuOptionPolicy(**item["option_policy"]),
            }
        )
        for item in catalog["items"]
    ]


def load_menu_tag_definitions(
    path: Path = MENU_PATH,
    schema_path: Path = MENU_SCHEMA_PATH,
) -> tuple[MenuTagDefinition, ...]:
    with path.open(encoding="utf-8") as menu_file:
        catalog = json.load(menu_file)
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    Draft202012Validator(schema).validate(catalog)
    return tuple(
        MenuTagDefinition(
            id=definition["id"],
            name=definition["name"],
            aliases=tuple(definition["aliases"]),
        )
        for definition in catalog["tag_definitions"]
    )


def load_menu_alias_definitions(
    path: Path = MENU_PATH,
    schema_path: Path = MENU_SCHEMA_PATH,
) -> tuple[MenuAliasDefinition, ...]:
    with path.open(encoding="utf-8") as menu_file:
        catalog = json.load(menu_file)
    with schema_path.open(encoding="utf-8") as schema_file:
        schema = json.load(schema_file)

    Draft202012Validator(schema).validate(catalog)
    menu_items = {item["id"]: item for item in catalog["items"]}
    definitions = tuple(
        MenuAliasDefinition(
            alias=definition["alias"],
            target_item_id=definition["target_item_id"],
            temperature=(
                Temperature(definition["temperature"])
                if definition["temperature"] is not None
                else None
            ),
        )
        for definition in catalog["menu_aliases"]
    )
    for definition in definitions:
        menu_item = menu_items.get(definition.target_item_id)
        if menu_item is None:
            raise ValueError(f"존재하지 않는 별칭 Menu ID: {definition.target_item_id}")
        if (
            definition.temperature is not None
            and definition.temperature.value not in menu_item["temperature_options"]
        ):
            raise ValueError(f"메뉴에서 지원하지 않는 별칭 온도: {definition.alias}")
    return definitions


# ============================================================
# Canonical Model Paths (STT / NLU / TTS)
# ============================================================

import os

PROJECT_ROOT = Path(__file__).resolve().parents[2]

# STT 설정
WHISPER_MODEL_ID = "openai/whisper-medium"

DEFAULT_STT_MODEL_PATH = Path(
    os.environ.get(
        "MALLO_STT_MODEL_PATH",
        str(PROJECT_ROOT / "models" / "stt" / "final-train65-merged-bf16"),
    )
)

STT_DIR = Path(__file__).resolve().parent.parent / "adapters" / "stt"
QLORA_MERGED_PATH = (
    PROJECT_ROOT / "models" / "stt" / "archive" / "team-handoff-domain" / "merged-bf16"
)

DEFAULT_STT_VARIANT = "train65"

# NLU 설정
DEFAULT_NLU_MODEL_PATH = Path(
    os.environ.get(
        "MALLO_NLU_MODEL_PATH",
        str(PROJECT_ROOT / "models" / "nlu" / "final-qwen06b-merged-bf16"),
    )
)

# TTS 설정
TTS_MODEL_DIR = Path(
    os.environ.get(
        "MALLO_TTS_MODEL_DIR",
        str(PROJECT_ROOT / "models" / "tts" / "mallo-friendly"),
    )
)
DEFAULT_TTS_CHECKPOINT_PATH = TTS_MODEL_DIR / "G_2800.pth"
DEFAULT_TTS_CONFIG_PATH = TTS_MODEL_DIR / "config.json"


