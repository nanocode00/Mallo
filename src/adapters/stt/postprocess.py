"""
STT 메뉴명 후처리 (Candidate Matching)
=====================================

STT 오인식된 메뉴명을 메뉴 DB(`src/config/menu.json`) 후보와 비교해
정규 메뉴명으로 교정한다.

- 공백·대소문자를 무시한 정규화 위에서 탐색한다.
- 정확 일치(부분 문자열)를 우선, 없으면 정규화 길이 합이 후보 길이와 같은
  연속 토큰 그룹에 대해 정규화 편집 거리(Levenshtein) 유사도를 측정한다.
- threshold 미만이면 교정하지 않아 환각 보정을 막는다 (S-16).

사용 예:
    from postprocess import CandidateMatcher

    matcher = CandidateMatcher(threshold=0.65)
    result = matcher.correct("자몽에이들 한 잔 주세요")
    print(result.text, result.changed, result.changes)
"""

from __future__ import annotations

import json
from collections.abc import Iterator
from dataclasses import dataclass, field
from pathlib import Path


def normalize(text: str) -> str:
    """공백·대소문자를 무시하는 정규화 (metrics._normalize와 동일 정책)."""
    return "".join(text.strip().lower().split())


def normalize_wer(text: str) -> str:
    """WER 계산용 정규화 — 단어 경계를 보존한다.

    CER과 달리 공백을 제거하지 않고, 앞뒤 공백 제거·연속 공백 축약·
    대소문자 정규화만 적용한다. 공백을 지우면 문장 전체가 단어 하나가 되어
    WER이 "문장 전체 일치 여부"에 가까워지므로, 단어 단위 오류율로 계산하기
    위해 사용한다.
    """
    return " ".join(text.strip().lower().split())


def normalized_offsets(text: str) -> tuple[str, list[int]]:
    """normalize() 결과와 원문 인덱스 매핑을 함께 반환한다.

    반환된 목록의 i번째 값은 normalized[i]가 원문의 어느 위치에 있는지
    가리킨다. 교정 후 원문의 공백·대소문자·비메뉴 텍스트를 보존하기 위해
    사용한다.
    """
    normalized_chars: list[str] = []
    original_indices: list[int] = []
    for index, char in enumerate(text):
        if char.isspace():
            continue
        normalized_chars.append(char.lower())
        original_indices.append(index)
    return "".join(normalized_chars), original_indices


def levenshtein_distance(left: str, right: str) -> int:
    """두 문자열의 편집 거리 (substitution / insertion / deletion = 1)."""
    if left == right:
        return 0
    if not left:
        return len(right)
    if not right:
        return len(left)

    previous = list(range(len(right) + 1))
    for left_index, left_char in enumerate(left, start=1):
        current = [left_index]
        for right_index, right_char in enumerate(right, start=1):
            substitution_cost = 0 if left_char == right_char else 1
            current.append(
                min(
                    previous[right_index] + 1,
                    current[right_index - 1] + 1,
                    previous[right_index - 1] + substitution_cost,
                )
            )
        previous = current

    return previous[-1]


def similarity(left: str, right: str) -> float:
    """정규화 편집 거리 유사도 (0.0 ~ 1.0). 1이 완전 일치."""
    if left == right:
        return 1.0
    max_length = max(len(left), len(right))
    if max_length == 0:
        return 1.0
    return 1.0 - levenshtein_distance(left, right) / max_length


@dataclass
class CandidateMatch:
    item_id: str
    canonical: str
    original: str
    score: float
    start: int
    end: int


@dataclass
class CorrectedText:
    text: str
    changes: list[CandidateMatch] = field(default_factory=list)

    @property
    def changed(self) -> bool:
        return any(
            match.original != normalize(match.canonical)
            for match in self.changes
        )


class CandidateMatcher:
    """메뉴 DB 후보와 STT 가설을 대조해 메뉴명을 교정한다."""

    DEFAULT_THRESHOLD = 0.65

    def __init__(
        self,
        threshold: float = DEFAULT_THRESHOLD,
        menu_path: Path | None = None,
    ) -> None:
        self._threshold = threshold
        if menu_path is None:
            menu_path = (
                Path(__file__).resolve().parents[2] / "config" / "menu.json"
            )
        self._menu_path = menu_path
        self._candidates = self._load_candidates(menu_path)

    @property
    def threshold(self) -> float:
        return self._threshold

    @property
    def menu_path(self) -> Path:
        return self._menu_path

    @property
    def candidates(self) -> list[tuple[str, str, str]]:
        """(item_id, canonical, normalized) 목록 — 길이 내림차순."""
        return self._candidates

    @staticmethod
    def _load_candidates(
        menu_path: Path,
    ) -> list[tuple[str, str, str]]:
        with open(menu_path, encoding="utf-8") as menu_file:
            menu = json.load(menu_file)

        candidates = []
        for item in menu["items"]:
            canonical = item["name"]
            candidates.append(
                (item["id"], canonical, normalize(canonical))
            )

        candidates.sort(key=lambda candidate: len(candidate[2]), reverse=True)
        return candidates

    def match(self, text: str) -> CorrectedText:
        """가설 텍스트에서 메뉴 후보를 찾아 정규 메뉴명으로 교정한다.

        교정은 메뉴 구간만 바꾸며 원문의 공백·대소문자·비메뉴 텍스트는
        그대로 보존한다.
        """
        normalized, original_indices = normalized_offsets(text)
        if not normalized:
            return CorrectedText(text=text)

        tokens = [normalize(token) for token in text.split()]
        token_offsets: list[int] = []
        offset = 0
        for token in tokens:
            token_offsets.append(offset)
            offset += len(token)

        matches = self._find_matches(normalized, tokens, token_offsets)
        matches.sort(key=lambda match: (-match.score, match.start))
        selected = self._pick_non_overlapping(matches)

        corrected = self._rebuild(text, original_indices, selected)
        return CorrectedText(text=corrected, changes=selected)

    correct = match

    def _find_matches(
        self,
        normalized: str,
        tokens: list[str],
        token_offsets: list[int],
    ) -> list[CandidateMatch]:
        matches: list[CandidateMatch] = []

        for item_id, canonical, candidate in self._candidates:
            candidate_len = len(candidate)
            if candidate_len > len(normalized):
                continue

            exact_spans = self._find_exact_spans(normalized, candidate)
            if exact_spans:
                for start, end in exact_spans:
                    matches.append(
                        CandidateMatch(
                            item_id=item_id,
                            canonical=canonical,
                            original=normalized[start:end],
                            score=1.0,
                            start=start,
                            end=end,
                        )
                    )
                continue

            best = self._find_best_fuzzy_match(
                tokens,
                token_offsets,
                item_id,
                canonical,
                candidate,
            )
            if best is not None:
                matches.append(best)

        return matches

    @staticmethod
    def _find_exact_spans(
        normalized: str,
        candidate: str,
    ) -> list[tuple[int, int]]:
        spans = []
        start = 0
        while True:
            index = normalized.find(candidate, start)
            if index == -1:
                break
            spans.append((index, index + len(candidate)))
            start = index + len(candidate)
        return spans

    def _find_best_fuzzy_match(
        self,
        tokens: list[str],
        token_offsets: list[int],
        item_id: str,
        canonical: str,
        candidate: str,
    ) -> CandidateMatch | None:
        candidate_len = len(candidate)
        best_score = 0.0
        best_token: str | None = None
        best_span: tuple[int, int] | None = None

        for token, start in self._token_groups(tokens, token_offsets, candidate_len):
            score = similarity(candidate, token)
            if score > best_score:
                best_score = score
                best_token = token
                best_span = (start, start + candidate_len)

        if best_span is None or best_token is None or best_score < self._threshold:
            return None

        start, end = best_span
        return CandidateMatch(
            item_id=item_id,
            canonical=canonical,
            original=best_token,
            score=best_score,
            start=start,
            end=end,
        )

    @staticmethod
    def _token_groups(
        tokens: list[str],
        token_offsets: list[int],
        target_len: int,
    ) -> Iterator[tuple[str, int]]:
        """정규화 길이 합이 target_len과 일치하는 연속 토큰 그룹을 만든다.

        단일 토큰이 target_len이면 그대로, 복수 단어 메뉴명(예: 크로플 아이스크림)은
        인접 토큰을 묶어 후보로 삼는다. 부분 단어(아이스크 ↔ 아이스티)는 합이
        맞지 않아 제외되어 환각 보정을 막는다.
        """
        lengths = [len(token) for token in tokens]

        for index in range(len(tokens)):
            total = 0
            cursor = index
            while cursor < len(tokens) and total < target_len:
                total += lengths[cursor]
                cursor += 1
            if total == target_len:
                yield "".join(tokens[index:cursor]), token_offsets[index]

    @staticmethod
    def _pick_non_overlapping(
        matches: list[CandidateMatch],
    ) -> list[CandidateMatch]:
        selected: list[CandidateMatch] = []
        for match in matches:
            if any(
                not (match.end <= picked.start or match.start >= picked.end)
                for picked in selected
            ):
                continue
            selected.append(match)
        return selected

    @staticmethod
    def _rebuild(
        original: str,
        original_indices: list[int],
        matches: list[CandidateMatch],
    ) -> str:
        """메뉴 구간만 정규 메뉴명으로 교체하고 나머지 원문을 보존한다.

        normalized offsets(match.start/end)를 원문 인덱스로 역매핑해
        교체 구간을 원문에서 잘라낸다. 원문의 공백·대소문자·비메뉴 텍스트는
        그대로 유지된다.
        """
        if not matches:
            return original

        spans = []
        for match in sorted(matches, key=lambda m: m.start):
            if normalize(match.canonical) == match.original:
                continue
            if match.start >= len(original_indices):
                continue
            start = original_indices[match.start]
            end = (
                original_indices[match.end - 1] + 1
                if match.end <= len(original_indices)
                else len(original)
            )
            if any(not (end <= s or start >= e) for s, e in spans):
                continue
            spans.append((start, end, match.canonical))

        parts = []
        cursor = 0
        for start, end, canonical in sorted(spans):
            if start < cursor:
                continue
            parts.append(original[cursor:start])
            parts.append(canonical)
            cursor = end
        parts.append(original[cursor:])
        return "".join(parts)
