# Company-level dataset splits
from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from orggraph_dataset.config import SplitsConfig
from orggraph_dataset.constants import SPLITS
from orggraph_dataset.utils.random_utils import Rng, largest_remainder


@dataclass(frozen=True)
class SplitCandidate:
    industry: str
    size_segment: str
    archetype: str


def assign_splits(candidates: Sequence[SplitCandidate], splits: SplitsConfig, rng: Rng) -> list[str]:
    n = len(candidates)
    targets = dict(zip(SPLITS, largest_remainder(n, [splits.fractions[s] for s in SPLITS]), strict=True))
    assignment: list[str | None] = [None] * n

    holdout = set(splits.holdout_industries)
    for i, cand in enumerate(candidates):
        if cand.industry in holdout:
            assignment[i] = "test"
    targets["test"] = max(0, targets["test"] - sum(1 for a in assignment if a == "test"))

    open_indices = [i for i in range(n) if assignment[i] is None]
    weights = [
        splits.challenge_archetype_weights.get(candidates[i].archetype, 1.0)
        * splits.challenge_size_weights.get(candidates[i].size_segment, 1.0)
        for i in open_indices
    ]
    challenge = set(rng.weighted_sample_without_replacement(open_indices, weights, targets["challenge"]))
    for i in challenge:
        assignment[i] = "challenge"

    remaining = [i for i in open_indices if i not in challenge]
    rng.shuffle(remaining)
    cursor = 0
    for split in ("train", "validation", "test"):
        take = targets[split] if split != "train" else 0
        for i in remaining[cursor : cursor + take]:
            assignment[i] = split
        cursor += take
    for i in remaining[cursor:]:
        assignment[i] = "train"
    return [a or "train" for a in assignment]
