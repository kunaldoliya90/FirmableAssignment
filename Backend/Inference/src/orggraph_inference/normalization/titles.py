# Title normalization: observed title string -> canonical title, job family and seniority
from __future__ import annotations

import difflib
import re
from collections import defaultdict
from dataclasses import dataclass

from orggraph_dataset.constants import SENIORITY_RANK

from orggraph_inference.normalization.text import clean
from orggraph_inference.normalization.vocabulary import Vocabulary

_SUFFIX_SPLIT = re.compile(r"\s+-\s+|,\s+|\s+\||\s*\(")
_KEYWORD_SENIORITY: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(ceo|chief executive)\b"), "c_level"),
    (re.compile(r"\bchief\b|\bc[a-z]o\b|general counsel"), "c_level"),
    (
        re.compile(
            r"\bpresident\b|\bgeneral manager\b|\bgm\b|\bhead of business unit\b|\bmanaging director\b"
        ),
        "executive",
    ),
    (re.compile(r"\bsvp\b|senior vice president|\bevp\b"), "svp"),
    (re.compile(r"\bvp\b|vice president|\bprovost\b|\bpartner\b"), "vp"),
    (re.compile(r"senior director|\bsr director\b|\bdean\b"), "senior_director"),
    (re.compile(r"\bdirector\b|\bhead\b|\bdir\b"), "director"),
    (re.compile(r"senior manager|\bsr manager\b|\bsr mgr\b"), "senior_manager"),
    (re.compile(r"\bmanager\b|\bmgr\b|team lead|\bsupervisor\b"), "manager"),
    (re.compile(r"\bintern\b"), "intern"),
    (re.compile(r"\bjunior\b|\bjr\b|\bassistant\b|\bassociate\b"), "junior"),
    (re.compile(r"\bprincipal\b|\bdistinguished\b"), "principal"),
    (re.compile(r"\bstaff\b|\blead\b"), "staff"),
    (re.compile(r"\bsenior\b|\bsr\b"), "senior_ic"),
]


@dataclass(frozen=True)
class TitleInterpretation:
    raw: str
    canonical_title: str | None
    job_family: str | None
    seniority: str | None
    executive_role: str | None
    score: float
    method: str
    generic: bool = False
    suffix: str | None = None

    @property
    def rank(self) -> int | None:
        return SENIORITY_RANK[self.seniority] if self.seniority else None


class TitleNormalizer:
    def __init__(self, vocabulary: Vocabulary, fuzzy_threshold: float = 0.84) -> None:
        self.vocab = vocabulary
        self.fuzzy_threshold = fuzzy_threshold
        tax = vocabulary.taxonomy
        self._entries = {t.canonical_title: t for t in tax.all_titles()}
        self._keys: dict[str, set[str]] = defaultdict(set)
        for entry in tax.all_titles():
            for text in (*entry.title_variants, *entry.legacy_titles):
                key = clean(text)
                self._keys[key].add(entry.canonical_title)
        for key, canonicals in list(self._keys.items()):
            for variant in vocabulary.expander.expand(key):
                if variant not in self._keys:
                    self._keys[variant] = set(canonicals)
        self._token_index: dict[str, set[str]] = defaultdict(set)
        for key in self._keys:
            for token in dict.fromkeys(key.split()):
                self._token_index[token].add(key)
        tier_levels = {
            "executive": "executive",
            "vp": "vp",
            "director": "director",
            "manager": "manager",
            "individual": None,
        }
        self._generic: dict[str, str | None] = {
            clean(t): tier_levels[tier]
            for tier, titles in vocabulary.config.noise.generic_titles.items()
            for t in titles
        }
        self._cache: dict[str, TitleInterpretation] = {}

    def interpret(self, raw: str) -> TitleInterpretation:
        cached = self._cache.get(raw)
        if cached is None:
            cached = self._interpret(raw)
            if len(self._cache) < 500_000:
                self._cache[raw] = cached
        return cached

    def _from_canonicals(
        self, raw: str, canonicals: set[str], score: float, method: str, suffix: str | None
    ) -> TitleInterpretation:
        entries = [self._entries[c] for c in sorted(canonicals)]
        if len(entries) == 1:
            e = entries[0]
            return TitleInterpretation(
                raw,
                e.canonical_title,
                e.job_family,
                e.seniority_level,
                e.executive_role,
                score,
                method,
                suffix=suffix,
            )
        levels = {e.seniority_level for e in entries}
        families = {e.job_family for e in entries}
        return TitleInterpretation(
            raw,
            None,
            families.pop() if len(families) == 1 else None,
            levels.pop() if len(levels) == 1 else None,
            None,
            score * 0.6,
            f"{method}_ambiguous",
            suffix=suffix,
        )

    def _lookup(self, cleaned: str) -> set[str] | None:
        if cleaned in self._keys:
            return self._keys[cleaned]
        for variant in self.vocab.expander.expand(cleaned):
            if variant in self._keys:
                return self._keys[variant]
        return None

    def _interpret(self, raw: str) -> TitleInterpretation:
        cleaned = clean(raw)
        if not cleaned:
            return TitleInterpretation(raw, None, None, None, None, 0.0, "unknown")
        if cleaned in self._generic:
            level = self._generic[cleaned]
            return TitleInterpretation(
                raw, None, None, level, None, 0.35 if level else 0.1, "generic", generic=True
            )
        found = self._keys.get(cleaned)
        if found:
            return self._from_canonicals(raw, found, 1.0, "exact", None)

        heads = [
            (raw[: m.start()], raw[m.end() :])
            for m in reversed(list(_SUFFIX_SPLIT.finditer(raw)))
            if m.start() > 0
        ]
        for head, rest in heads:
            found = self._lookup(clean(head))
            if found:
                return self._from_canonicals(raw, found, 0.93, "stripped", clean(rest) or None)
        found = self._lookup(cleaned)
        if found:
            return self._from_canonicals(raw, found, 0.9, "expanded", None)
        for head, rest in heads:
            head_fuzzy = self._fuzzy(clean(head), suffix=clean(rest) or None)
            if head_fuzzy is not None:
                return head_fuzzy
        fuzzy = self._fuzzy(cleaned)
        if fuzzy is not None:
            return fuzzy
        return self._keywords(raw, cleaned)

    def _fuzzy(self, cleaned: str, suffix: str | None = None) -> TitleInterpretation | None:
        tokens = cleaned.split()
        if not tokens:
            return None
        expanded = [cleaned, *self.vocab.expander.expand(cleaned)[:3]]
        candidates: set[str] = set()
        for text in expanded:
            for token in text.split():
                keys = self._token_index.get(token)
                if keys and len(keys) < 400:
                    candidates |= keys
        if not candidates:
            for token in tokens:
                for close in difflib.get_close_matches(token, self._token_index.keys(), n=2, cutoff=0.8):
                    candidates |= self._token_index[close]
        best_key, best_score = None, 0.0
        for key in sorted(candidates):
            for text in expanded:
                score = difflib.SequenceMatcher(None, text, key).ratio()
                if len(text) >= 8 and key.startswith(text):
                    score = max(score, 0.9)
                if score > best_score:
                    best_key, best_score = key, score
        if best_key is None or best_score < self.fuzzy_threshold:
            return None
        return self._from_canonicals(
            cleaned, self._keys[best_key], round(best_score * 0.85, 3), "fuzzy", suffix
        )

    def _keywords(self, raw: str, cleaned: str) -> TitleInterpretation:
        expanded = " ".join([cleaned, *self.vocab.expander.expand(cleaned)[:2]])
        level = next((lvl for pattern, lvl in _KEYWORD_SENIORITY if pattern.search(expanded)), None)
        family = self._family_from_tokens(expanded)
        if level is None and family is None:
            return TitleInterpretation(raw, None, None, None, None, 0.0, "unknown")
        return TitleInterpretation(raw, None, family, level or "ic", None, 0.3 if level else 0.15, "keyword")

    def _family_from_tokens(self, text: str) -> str | None:
        tokens = set(text.split())
        best, best_overlap = None, 0.0
        for key, fam in self.vocab.config.job_families.families.items():
            vocab = set(clean(fam.ic_role).split()) | set(clean(fam.function).split())
            vocab -= {"senior", "manager", "specialist", "of", "&"}
            if not vocab:
                continue
            overlap = len(tokens & vocab) / len(vocab)
            if overlap > best_overlap:
                best, best_overlap = key, overlap
        return best if best_overlap >= 0.5 else None
