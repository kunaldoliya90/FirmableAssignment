# Controlled noise operations for titles, departments, locations and job families
from __future__ import annotations

import re
from collections.abc import Callable
from dataclasses import dataclass, field

from orggraph_dataset.config import CityConfig, NoiseConfig, NoiseProfileConfig, RegionConfig
from orggraph_dataset.constants import SENIORITY_RANK
from orggraph_dataset.taxonomy import CanonicalTitle
from orggraph_dataset.utils.random_utils import Rng

_REPLACEMENT_OPS = ("variant", "legacy_title", "generic_replacement")
_SUFFIX_OPS = ("department_suffix", "regional_suffix", "business_unit_suffix")
_STRING_OPS = (
    "abbreviation",
    "seniority_removal",
    "truncation",
    "punctuation",
    "capitalization",
    "typo",
)
_WS = re.compile(r"\s+")


def generic_tier(seniority: str) -> str:
    rank = SENIORITY_RANK[seniority]
    if rank >= SENIORITY_RANK["executive"]:
        return "executive"
    if rank >= SENIORITY_RANK["vp"]:
        return "vp"
    if rank >= SENIORITY_RANK["director"]:
        return "director"
    if rank >= SENIORITY_RANK["manager"]:
        return "manager"
    return "individual"


@dataclass(frozen=True)
class NoiseContext:
    department_name: str | None
    department_abbreviations: tuple[str, ...] = ()
    department_aliases: tuple[str, ...] = ()
    parent_department_name: str | None = None
    segment_name: str | None = None
    region: RegionConfig | None = None
    city: CityConfig | None = None
    remote: bool = False


@dataclass
class NoiseResult:
    value: str | None
    operations: list[str] = field(default_factory=list)


def _clean(text: str) -> str:
    return _WS.sub(" ", text).strip(" ,-|/")


class NoiseEngine:
    def __init__(self, noise: NoiseConfig, profile: NoiseProfileConfig) -> None:
        self.noise = noise
        self.profile = profile
        phrases = sorted(noise.abbreviations, key=len, reverse=True)
        self._abbrev = [
            (re.compile(rf"\b{re.escape(p)}\b", re.IGNORECASE), noise.abbreviations[p]) for p in phrases
        ]
        markers = sorted(noise.seniority_markers, key=len, reverse=True)
        self._markers = re.compile(r"(?<![\w.])(" + "|".join(re.escape(m) for m in markers) + r")(?![\w])")
        self._title_ops: dict[str, Callable[[str, CanonicalTitle, NoiseContext, Rng], str | None]] = {
            "variant": self._variant,
            "legacy_title": self._legacy,
            "generic_replacement": self._generic,
            "department_suffix": self._department_suffix,
            "regional_suffix": self._regional_suffix,
            "business_unit_suffix": self._business_unit_suffix,
            "abbreviation": self._abbreviation,
            "seniority_removal": self._seniority_removal,
            "truncation": self._truncation,
            "punctuation": self._punctuation,
            "capitalization": self._capitalization,
            "typo": self._typo,
        }

    def corrupt_title(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> NoiseResult:
        count = 1
        while count < self.profile.max_title_operations and rng.bernoulli(
            self.noise.chained_operation_probability
        ):
            count += 1
        weights = dict(self.noise.title_noise_weights)
        chosen: list[str] = []
        for _ in range(count):
            if not weights:
                break
            op = rng.weighted_key(weights)
            chosen.append(op)
            del weights[op]
            if op in _REPLACEMENT_OPS:
                for other in _REPLACEMENT_OPS:
                    weights.pop(other, None)
        ordered = [
            op for group in (_REPLACEMENT_OPS, _SUFFIX_OPS, _STRING_OPS) for op in group if op in chosen
        ]
        result = NoiseResult(title)
        current = title
        for op in ordered:
            updated = self._title_ops[op](current, entry, ctx, rng)
            if updated and updated != current:
                current = updated
                result.operations.append(f"title_{op}")
        result.value = current
        return result

    def generic_leadership_title(self, seniority: str, rng: Rng) -> str:
        return rng.choice(self.noise.generic_titles[generic_tier(seniority)])

    def remove_seniority(self, title: str) -> str | None:
        stripped = _clean(self._markers.sub("", title))
        return stripped if stripped and stripped != title else None

    def _variant(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        options = [v for v in entry.title_variants if v != title]
        return rng.choice(options) if options else None

    def _legacy(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        return rng.choice(entry.legacy_titles) if entry.legacy_titles else None

    def _generic(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        return self.generic_leadership_title(entry.seniority_level, rng)

    def _suffix(self, title: str, value: str | None, formats: list[str], rng: Rng) -> str | None:
        if not value:
            return None
        return title + rng.choice(formats).format(value=value)

    def _department_suffix(
        self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng
    ) -> str | None:
        options = [v for v in (ctx.department_name, *ctx.department_abbreviations) if v]
        value = rng.choice(options) if options else None
        return self._suffix(title, value, self.noise.department_suffix_formats, rng)

    def _regional_suffix(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        options: list[str] = []
        if ctx.region:
            options += [ctx.region.name, *ctx.region.aliases]
        if ctx.city and not ctx.remote:
            options += [ctx.city.name, *ctx.city.aliases]
        value = rng.choice(options) if options else None
        return self._suffix(title, value, self.noise.regional_suffix_formats, rng)

    def _business_unit_suffix(
        self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng
    ) -> str | None:
        return self._suffix(title, ctx.segment_name, self.noise.department_suffix_formats, rng)

    def _abbreviation(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        matches = [(pattern, options) for pattern, options in self._abbrev if pattern.search(title)]
        if not matches:
            return None
        applied = False
        current = title
        for pattern, options in matches:
            if not applied or rng.bernoulli(0.6):
                replacement = rng.choice(options).replace("\\", "\\\\")
                updated = pattern.sub(replacement, current, count=1)
                applied = applied or updated != current
                current = updated
        return current

    def _seniority_removal(
        self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng
    ) -> str | None:
        return self.remove_seniority(title)

    def _truncation(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        limit = self.noise.truncation_max_chars
        if len(title) > limit:
            return title[:limit].rstrip(" ,-")
        words = title.split()
        if len(words) >= 2:
            return " ".join(words[:-1])
        return None

    def _punctuation(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        transforms: list[Callable[[str], str]] = [
            lambda t: t.replace(", ", " - "),
            lambda t: t.replace(" - ", ", "),
            lambda t: t.replace(".", ""),
            lambda t: re.sub(r"\b(Sr|Jr|Mgr|Dir|Assoc|Asst)\b(?!\.)", r"\1.", t),
            lambda t: t.replace(" of ", ", "),
            lambda t: t.replace(" & ", " and "),
            lambda t: t + ".",
            lambda t: t.replace(" ", "  ", 1),
        ]
        options = [out for transform in transforms if (out := transform(title)) != title]
        return rng.choice(options) if options else None

    def _capitalization(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        words = title.split(" ")
        options = [title.lower(), title.upper(), title.title()]
        if len(words) > 1:
            i = rng.randint(0, len(words) - 1)
            options.append(" ".join(w.lower() if j == i else w for j, w in enumerate(words)))
        options = [o for o in options if o != title]
        return rng.choice(options) if options else None

    def _typo(self, title: str, entry: CanonicalTitle, ctx: NoiseContext, rng: Rng) -> str | None:
        words = title.split(" ")
        candidates = [i for i, w in enumerate(words) if len(w) >= 4 and w.isalpha()]
        if not candidates:
            return None
        i = rng.choice(candidates)
        word = words[i]
        pos = rng.randint(1, len(word) - 2)
        kind = rng.randint(0, 2)
        if kind == 0:
            word = word[:pos] + word[pos + 1] + word[pos] + word[pos + 2 :]
        elif kind == 1:
            word = word[:pos] + word[pos + 1 :]
        else:
            word = word[:pos] + word[pos] + word[pos:]
        words[i] = word
        return " ".join(words)

    def corrupt_department(self, ctx: NoiseContext, rng: Rng) -> NoiseResult:
        name = ctx.department_name
        if not name:
            return NoiseResult(name)
        available: dict[str, float] = {}
        weights = self.noise.department_noise_weights
        abbreviations = [v for v in ctx.department_abbreviations if v != name]
        aliases = [v for v in ctx.department_aliases if v != name]
        if abbreviations:
            available["abbreviation"] = weights.get("abbreviation", 0)
        if aliases:
            available["alias"] = weights.get("alias", 0)
        if ctx.parent_department_name:
            available["parent_department"] = weights.get("parent_department", 0)
        if ctx.segment_name and ctx.segment_name != name:
            available["segment_prefix"] = weights.get("segment_prefix", 0)
        available["case_format"] = weights.get("case_format", 0)
        available = {k: v for k, v in available.items() if v > 0}
        if not available:
            return NoiseResult(name)
        op = rng.weighted_key(available)
        if op == "abbreviation":
            value = rng.choice(abbreviations)
        elif op == "alias":
            value = rng.choice(aliases)
        elif op == "parent_department":
            value = ctx.parent_department_name or name
        elif op == "segment_prefix":
            value = rng.choice(self.noise.segment_prefix_formats).format(
                segment=ctx.segment_name, department=name
            )
        else:
            value = rng.choice([name.lower(), name.upper(), name.replace("&", "and"), f"Dept. of {name}"])
        if value == name:
            return NoiseResult(name)
        return NoiseResult(value, [f"department_{op}"])

    def base_location(self, ctx: NoiseContext) -> str | None:
        if ctx.city is None:
            return None
        if ctx.remote:
            return f"Remote - {ctx.city.country}"
        return f"{ctx.city.name}, {ctx.city.country}"

    def corrupt_location(self, ctx: NoiseContext, rng: Rng) -> NoiseResult:
        base = self.base_location(ctx)
        city = ctx.city
        if base is None or city is None:
            return NoiseResult(base)
        op = rng.weighted_key(self.noise.location_noise_weights)
        if op == "region_instead" and ctx.region is not None:
            value = rng.choice([ctx.region.name, *ctx.region.aliases])
        elif op == "city_alias":
            if ctx.remote:
                value = rng.choice(["Remote", "WFH", f"Remote ({city.country_code})", "Home Office"])
            elif city.aliases:
                alias = rng.choice(city.aliases)
                value = rng.choice([alias, f"{alias}, {city.country_code}"])
            else:
                value = city.name
        else:
            label = "Remote" if ctx.remote else city.name
            value = rng.choice(
                [
                    base.lower(),
                    base.upper(),
                    f"{label} - {city.country_code}",
                    f"{label} ({city.country})",
                    label,
                    f"{label},{city.country_code}",
                ]
            )
        if value == base:
            return NoiseResult(base)
        return NoiseResult(value, [f"location_{op}"])
