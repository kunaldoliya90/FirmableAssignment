# Location normalization: observed location string -> city and region (aliases, formats, remote)
from __future__ import annotations

from dataclasses import dataclass

from orggraph_inference.normalization.text import clean
from orggraph_inference.normalization.vocabulary import Vocabulary

_REMOTE = ("remote", "wfh", "home office")


@dataclass(frozen=True)
class LocationInterpretation:
    raw: str
    city: str | None
    region: str | None
    remote: bool


class LocationNormalizer:
    def __init__(self, vocabulary: Vocabulary) -> None:
        locations = vocabulary.config.locations
        self._cities: dict[str, tuple[str, str]] = {}
        self._countries: dict[str, str] = {}
        for city in locations.cities:
            for name in (city.name, *city.aliases):
                self._cities.setdefault(clean(name), (city.name, city.region))
            self._countries.setdefault(clean(city.country), city.region)
            self._countries.setdefault(clean(city.country_code), city.region)
        self._regions: dict[str, str] = {}
        for key, region in locations.regions.items():
            for name in (region.name, *region.aliases):
                self._regions[clean(name)] = key
        self._cache: dict[str, LocationInterpretation] = {}

    def interpret(self, raw: str) -> LocationInterpretation:
        if raw not in self._cache:
            self._cache[raw] = self._interpret(raw)
        return self._cache[raw]

    def _interpret(self, raw: str) -> LocationInterpretation:
        cleaned = clean(raw)
        remote = cleaned.startswith(_REMOTE)
        if cleaned in self._regions:
            return LocationInterpretation(raw, None, self._regions[cleaned], False)
        tokens = cleaned.split()
        for end in range(len(tokens), 0, -1):
            candidate = " ".join(tokens[:end])
            if candidate in self._cities:
                city, region = self._cities[candidate]
                return LocationInterpretation(raw, city, region, remote)
        for start in range(len(tokens)):
            country = " ".join(tokens[start:])
            if country in self._countries:
                return LocationInterpretation(raw, None, self._countries[country], remote)
        return LocationInterpretation(raw, None, None, remote)
