# Shared vocabulary for the normalizers, built from the DataGenerator config and taxonomy
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from orggraph_dataset.config import OrgGraphConfig, load_config
from orggraph_dataset.taxonomy import TitleTaxonomy

from orggraph_inference.normalization.text import Expander


@dataclass(frozen=True)
class Vocabulary:
    config: OrgGraphConfig
    taxonomy: TitleTaxonomy
    expander: Expander
    industry_keys: dict[str, str]

    @classmethod
    def build(cls, config: OrgGraphConfig) -> Vocabulary:
        taxonomy = TitleTaxonomy(config)
        pairs: list[tuple[str, str]] = []
        for phrase, abbreviations in config.noise.abbreviations.items():
            pairs += [(abbr, phrase) for abbr in abbreviations]
        for family in config.job_families.families.values():
            pairs.append((family.function_abbrev, family.function))
            pairs.append((family.ic_abbrev, family.ic_role))
        pairs += [("mngr", "manager"), ("hr", "human resources"), ("svp", "senior vice president")]
        industry_keys = {ind.name: key for key, ind in config.industries.industries.items()}
        return cls(config=config, taxonomy=taxonomy, expander=Expander(pairs), industry_keys=industry_keys)


@lru_cache(maxsize=4)
def load_vocabulary(config_dir: str | None = None) -> Vocabulary:
    return Vocabulary.build(load_config(Path(config_dir) if config_dir else None))
