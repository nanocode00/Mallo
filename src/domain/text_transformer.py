from __future__ import annotations

import re

from domain.korean_normalizer import normalize_korean_text_for_tts


class AdaptiveTextTransformer:
    """Adaptive TTS Level 0, 1, 2에 따라 응답 문장을 고령자 친화적으로 변환하는 엔진."""

    LEVEL_GAPS: dict[int, int] = {
        0: 0,
        1: 280,
        2: 480,
    }

    @classmethod
    def get_gap_ms(cls, level: int = 0) -> int:
        """해당 레벨의 실제 침묵(Silence gap) 밀리초 반환."""
        return cls.LEVEL_GAPS.get(level, 0)

    @classmethod
    def transform(cls, text: str, level: int = 0) -> str:
        """주어진 텍스트를 level(0: 기본, 1: Pause 분절, 2: 단문 분절 및 핵심 강조)에 맞게 변환합니다."""
        chunks = cls.transform_to_chunks(text, level=level)
        return " ".join(chunks)

    @classmethod
    def transform_to_chunks(cls, text: str, level: int = 0) -> list[str]:
        """주어진 텍스트를 문법 왜곡 및 가짜 문장부호 없이 순수 자연어 TTS chunk 리스트로 분절합니다."""
        if not text or not text.strip():
            return []

        normalized = normalize_korean_text_for_tts(text)

        if level == 0:
            return cls._chunks_level_0(normalized)
        elif level == 1:
            return cls._chunks_level_1(normalized)
        elif level == 2:
            return cls._chunks_level_2(normalized)
        else:
            raise ValueError(f"Invalid TTS level: {level}. Allowed levels are 0, 1, 2.")

    @classmethod
    def _chunks_level_0(cls, text: str) -> list[str]:
        """Level 0: 원본 문장 유지 (숫자 및 단위 수사 정규화 완료)."""
        return [text]

    @classmethod
    def _chunks_level_1(cls, text: str) -> list[str]:
        """Level 1: canonical 문장의 기존 문장/쉼표 경계만 사용한다.

        Chunk 자체는 원문의 연속 부분문자열이다. 문장을 다시 쓰거나 조사와
        문장부호를 보완하지 않으며, ``" ".join(chunks)``는 정규화된 canonical
        text와 같아야 한다.
        """
        return cls._split_at_boundaries(text, split_conjunctions=False)

    @classmethod
    def _chunks_level_2(cls, text: str) -> list[str]:
        """Level 2: L1보다 작은 원문 의미 경계만 사용한다.

        과거의 ``...입니다``/``장바구니에 담았습니다`` 재작성은 출력 계약을
        깨므로 제거한다. 가격 수사 정규화 외에는 원문 내용을 바꾸지 않는다.
        """
        return cls._split_at_boundaries(text, split_conjunctions=True)

    @classmethod
    def _split_at_boundaries(cls, text: str, *, split_conjunctions: bool) -> list[str]:
        boundaries = r"(?<=[,.?!])\s+"
        if split_conjunctions:
            # 기존 원문에 있는 접속 어미 뒤 공백만 경계로 사용한다.
            boundaries += r"|(?<=과)\s+|(?<=와)\s+|(?<=그리고)\s+|(?<=이며)\s+"
        chunks = [part.strip() for part in re.split(boundaries, text) if part.strip()]
        return chunks or [text]


def transform_text_by_level(text: str, level: int = 0) -> str:
    """AdaptiveTextTransformer의 편의 함수."""
    return AdaptiveTextTransformer.transform(text, level=level)
