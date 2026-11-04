# Text cleaning and abbreviation expansion shared by all normalizers
from __future__ import annotations

import itertools
import re
import unicodedata
from collections.abc import Iterable

_PUNCT = re.compile(r"[.,;:|/()\[\]\-_+]+")
_WS = re.compile(r"\s+")


def clean(text: str) -> str:
    folded = unicodedata.normalize("NFKD", text)
    folded = "".join(ch for ch in folded if not unicodedata.combining(ch))
    folded = folded.lower().replace("&", " & ")
    folded = _PUNCT.sub(" ", folded)
    return _WS.sub(" ", folded).strip()


class Expander:
    def __init__(self, pairs: Iterable[tuple[str, str]], max_variants: int = 8) -> None:
        self._map: dict[str, list[str]] = {}
        for abbreviation, phrase in pairs:
            key, value = clean(abbreviation), clean(phrase)
            if not key or not value or key == value or " " in key:
                continue
            options = self._map.setdefault(key, [])
            if value not in options:
                options.append(value)
        self._max = max_variants

    def has(self, token: str) -> bool:
        return token in self._map

    def expand(self, cleaned: str) -> list[str]:
        tokens = cleaned.split()
        options = [[t, *self._map[t]] if t in self._map else [t] for t in tokens]
        variants: list[str] = []
        for combo in itertools.product(*options):
            variant = " ".join(combo)
            if variant != cleaned and variant not in variants:
                variants.append(variant)
            if len(variants) >= self._max:
                break
        return variants
