# Deterministic random sources
from __future__ import annotations

import hashlib
import math
import random
from collections.abc import Mapping, Sequence
from typing import TypeVar

import numpy as np

T = TypeVar("T")


def derive_seed(*parts: int | str) -> int:
    payload = "\x1f".join(str(part) for part in parts).encode("utf-8")
    return int.from_bytes(hashlib.sha256(payload).digest()[:8], "big") & ((1 << 63) - 1)


class Rng:
    def __init__(self, seed: int) -> None:
        self.seed = seed
        self.np = np.random.default_rng(seed)
        self._py = random.Random(seed)

    def child(self, *parts: int | str) -> Rng:
        return Rng(derive_seed(self.seed, *parts))

    def random(self) -> float:
        return self._py.random()

    def bernoulli(self, probability: float) -> bool:
        if probability <= 0.0:
            return False
        if probability >= 1.0:
            return True
        return self._py.random() < probability

    def randint(self, low: int, high: int) -> int:
        return self._py.randint(low, high)

    def uniform(self, low: float, high: float) -> float:
        return self._py.uniform(low, high)

    def choice(self, items: Sequence[T]) -> T:
        if not items:
            raise ValueError("choice() from an empty sequence")
        return items[self._py.randrange(len(items))]

    def weighted_choice(self, items: Sequence[T], weights: Sequence[float]) -> T:
        if not items:
            raise ValueError("weighted_choice() from an empty sequence")
        total = float(sum(weights))
        if total <= 0.0:
            return self.choice(items)
        return self._py.choices(items, weights=weights, k=1)[0]

    def weighted_key(self, weights: Mapping[str, float]) -> str:
        keys = list(weights)
        return self.weighted_choice(keys, [weights[k] for k in keys])

    def shuffle(self, items: list[T]) -> None:
        self._py.shuffle(items)

    def sample(self, items: Sequence[T], k: int) -> list[T]:
        return self._py.sample(list(items), k)

    def permutation(self, n: int) -> list[int]:
        values = list(range(n))
        self._py.shuffle(values)
        return values

    def lognormal_factor(self, sigma: float) -> float:
        if sigma <= 0:
            return 1.0
        return math.exp(self._py.gauss(0.0, sigma))

    def log_uniform(self, low: float, high: float) -> float:
        if high <= low:
            return low
        return math.exp(self._py.uniform(math.log(low), math.log(high)))

    def dirichlet(self, alpha: float, k: int) -> list[float]:
        if k <= 0:
            return []
        if k == 1:
            return [1.0]
        return [float(x) for x in self.np.dirichlet([alpha] * k)]

    def weighted_sample_without_replacement(
        self, items: Sequence[T], weights: Sequence[float], k: int
    ) -> list[T]:
        if k <= 0:
            return []
        if k >= len(items):
            return list(items)
        w = np.asarray(weights, dtype=float)
        w = np.where(w > 0, w, 1e-12)
        idx = self.np.choice(len(items), size=k, replace=False, p=w / w.sum())
        return [items[int(i)] for i in idx]


def largest_remainder(total: int, weights: Sequence[float]) -> list[int]:
    if total < 0:
        raise ValueError("total must be non-negative")
    if not weights:
        return []
    weight_sum = float(sum(weights))
    if weight_sum <= 0:
        weights = [1.0] * len(weights)
        weight_sum = float(len(weights))
    raw = [total * w / weight_sum for w in weights]
    parts = [math.floor(x) for x in raw]
    remainder = total - sum(parts)
    order = sorted(range(len(raw)), key=lambda i: (raw[i] - parts[i], -i), reverse=True)
    for i in order[:remainder]:
        parts[i] += 1
    return parts


def split_with_minimum(rng: Rng, total: int, k: int, minimum: int, alpha: float) -> list[int]:
    if k <= 0:
        return []
    if total < k * minimum:
        raise ValueError(f"cannot split {total} into {k} parts of at least {minimum}")
    spare = total - k * minimum
    shares = rng.dirichlet(alpha, k)
    return [minimum + part for part in largest_remainder(spare, shares)]
