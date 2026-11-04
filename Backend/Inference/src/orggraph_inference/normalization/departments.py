# Department normalization: observed department string -> catalog department and segment hint
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass

from orggraph_inference.normalization.text import clean
from orggraph_inference.normalization.vocabulary import Vocabulary

_SEGMENT_SPLIT = re.compile(r"\s+-\s+|\s*/\s*|\s*\(\s*|\)")
_SEGMENT_WORDS = {
    "bu",
    "business",
    "unit",
    "group",
    "division",
    "div",
    "region",
    "regional",
    "office",
    "market",
    "product",
    "line",
    "products",
}


@dataclass(frozen=True)
class DepartmentInterpretation:
    raw: str
    key: str | None
    top_key: str | None
    segment: str | None
    score: float


class DepartmentNormalizer:
    def __init__(self, vocabulary: Vocabulary, fuzzy_threshold: float = 0.86) -> None:
        self.catalog = vocabulary.taxonomy.departments
        self.fuzzy_threshold = fuzzy_threshold
        self._keys: dict[str, set[str]] = defaultdict(set)
        for entry in self.catalog.entries():
            for text in (entry.name, *entry.abbreviations, *entry.aliases):
                self._keys[clean(text)].add(entry.key)
        self._cache: dict[tuple[str, frozenset[str]], DepartmentInterpretation] = {}

    def top_key(self, key: str) -> str:
        return self.catalog.entry(key).parent_key or key

    def interpret(self, raw: str, allowed: frozenset[str]) -> DepartmentInterpretation:
        cache_key = (raw, allowed)
        if cache_key not in self._cache:
            self._cache[cache_key] = self._interpret(raw, allowed)
        return self._cache[cache_key]

    def _match(self, cleaned: str, allowed: frozenset[str]) -> tuple[str | None, float]:
        cleaned = cleaned.removeprefix("dept of ").strip()
        keys = self._keys.get(cleaned)
        if keys:
            preferred = sorted(k for k in keys if k in allowed or self.top_key(k) in allowed) or sorted(keys)
            preferred.sort(key=lambda k: (self.catalog.entry(k).parent_key is not None, k))
            return preferred[0], 1.0 if len(preferred) == 1 else 0.8
        close = difflib.get_close_matches(cleaned, self._keys.keys(), n=1, cutoff=self.fuzzy_threshold)
        if close:
            return self._match(close[0], allowed)[0], 0.75
        return None, 0.0

    def _interpret(self, raw: str, allowed: frozenset[str]) -> DepartmentInterpretation:
        cleaned = clean(raw)
        if not cleaned:
            return DepartmentInterpretation(raw, None, None, None, 0.0)
        key, score = self._match(cleaned, allowed)
        if key:
            return DepartmentInterpretation(raw, key, self.top_key(key), None, score)

        parts = [clean(p) for p in _SEGMENT_SPLIT.split(raw) if clean(p)]
        if len(parts) > 1:
            for i, part in enumerate(parts):
                key, score = self._match(part, allowed)
                if key:
                    segment = " ".join(p for j, p in enumerate(parts) if j != i)
                    return DepartmentInterpretation(
                        raw, key, self.top_key(key), _segment_label(segment), score * 0.9
                    )
        tokens = cleaned.split()
        for split_at in range(1, len(tokens)):
            key, score = self._match(" ".join(tokens[split_at:]), allowed)
            if key:
                return DepartmentInterpretation(
                    raw, key, self.top_key(key), _segment_label(" ".join(tokens[:split_at])), score * 0.85
                )
        return DepartmentInterpretation(raw, None, None, _segment_label(cleaned), 0.3)


def _segment_label(text: str) -> str | None:
    tokens = [t for t in text.split() if t not in _SEGMENT_WORDS]
    return " ".join(tokens) or None
