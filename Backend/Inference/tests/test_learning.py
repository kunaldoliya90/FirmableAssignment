# Learned weights and LLM title aliases: scorer/trainer agreement, logit fit, alias lookup, alias script
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Any

import pytest
from orggraph_inference.config import ScoringWeights
from orggraph_inference.evaluation.training import best_threshold, fit_conditional_logit
from orggraph_inference.normalization import Vocabulary
from orggraph_inference.normalization.titles import TitleNormalizer
from orggraph_inference.pipeline import InferenceEngine
from orggraph_inference.scoring import feature_terms, linear_score, weights_from_terms

SCRIPT = Path(__file__).parents[1] / "scripts" / "llm_title_aliases.py"


def test_linear_score_equals_weighted_feature_terms(engine: InferenceEngine, noisy_dataset: Path) -> None:
    from orggraph_inference.data import ObservedDatasetReader

    reader = ObservedDatasetReader(noisy_dataset)
    split = reader.splits()[0]
    data = reader.load_company(reader.company_ids(split)[0], split)
    scalars = ScoringWeights().model_dump(exclude={"level_step_exact", "ic_reports_to", "load_balance"})
    flat = {**scalars, "level_step_exact.0": -0.4, "level_step_exact.1": 0.7, "ic_reports_to.manager": 1.3}
    weights = weights_from_terms(flat)
    assert weights.level_step_exact == {"0": -0.4, "1": 0.7}
    assert weights.ic_reports_to == {"manager": 1.3}
    checked = 0
    for scored in engine.score_company(data).scored.values():
        for cand in scored.candidates:
            expected = sum(
                flat.get(name, 0.0) * value for name, value in feature_terms(cand.features).items()
            )
            assert linear_score(cand.features, weights) == pytest.approx(expected)
            checked += 1
    assert checked > 50


def test_conditional_logit_recovers_the_informative_feature() -> None:
    groups, labels = [], []
    for i in range(200):
        true = i % 3
        groups.append([{"signal": float(k == true), "noise": float((i + k) % 2)} for k in range(3)])
        labels.append(true)
    weights = fit_conditional_logit(groups, labels, epochs=200)
    assert weights["signal"] > 2.0
    assert abs(weights["noise"]) < 0.5


def test_best_threshold_maximizes_penalized_score() -> None:
    decisions = [(0.9, True), (0.8, True), (0.7, False), (0.6, True), (0.5, False), (0.4, False)]
    threshold, metrics = best_threshold(decisions, true_edges=4, penalty=2.0, grid=[0.4, 0.5, 0.6, 0.7, 0.8])
    assert threshold == 0.8
    assert metrics == {"precision": 1.0, "recall": 0.5, "penalized_score": 0.5}


def test_alias_resolves_title_the_matchers_miss(vocabulary: Vocabulary) -> None:
    raw = "Snr Dta Platfrm Engnr, Payments"
    plain = TitleNormalizer(vocabulary, aliases={}).interpret(raw)
    target = next(e for e in vocabulary.taxonomy.all_titles() if e.seniority_level == "senior_ic")
    aliased = TitleNormalizer(vocabulary, aliases={raw: target.canonical_title}).interpret(raw)
    assert plain.method != "alias"
    assert aliased.method == "alias"
    assert aliased.canonical_title == target.canonical_title
    assert aliased.seniority == "senior_ic"
    assert aliased.suffix == "payments"


def test_alias_to_unknown_canonical_is_ignored(vocabulary: Vocabulary) -> None:
    normalizer = TitleNormalizer(vocabulary, aliases={"Zzq Wizard": "Chief Wizard Officer"})
    assert normalizer.interpret("Zzq Wizard").method != "alias"


def _load_script() -> Any:
    spec = importlib.util.spec_from_file_location("llm_title_aliases", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_alias_script_validates_answers_and_writes_aliases(vocabulary: Vocabulary, tmp_path: Path) -> None:
    script = _load_script()
    normalizer = TitleNormalizer(vocabulary, aliases={})
    real = next(iter(vocabulary.taxonomy.all_titles())).canonical_title
    bodies: list[dict[str, Any]] = []

    def fake_post(body: dict[str, Any]) -> dict[str, Any]:
        bodies.append(body)
        titles = json.loads(body["messages"][1]["content"])["titles"]
        results = [
            {"raw": t, "canonical_title": real if i == 0 else "Made Up Title"} for i, t in enumerate(titles)
        ]
        results.append({"raw": "not asked", "canonical_title": real})
        return {"choices": [{"message": {"content": json.dumps({"results": results})}}]}

    cache: dict[str, str | None] = {"Cached Title": real}
    out = script.run(["Cached Title", "Foo Bar", "Baz Qux"], normalizer, fake_post, "gpt-test", 2, cache)
    assert len(bodies) == 1
    assert bodies[0]["response_format"]["json_schema"]["strict"] is True
    assert out == {"Cached Title": real, "Foo Bar": real, "Baz Qux": None}

    path = tmp_path / "aliases.json"
    assert script.write_aliases({"Foo Bar": real, "Nope": None}, "gpt-test", path) == 1
    assert json.loads(path.read_text(encoding="utf-8"))["aliases"] == {"foo bar": real}


def test_alias_script_endpoint_resolution() -> None:
    script = _load_script()
    assert script.chat_endpoint(None, "k") == (
        "https://api.openai.com/v1/chat/completions",
        {"Authorization": "Bearer k"},
    )
    project = "https://res.services.ai.azure.com/api/projects/my-project"
    assert script.chat_endpoint(project, "k") == (
        "https://res.services.ai.azure.com/openai/v1/chat/completions",
        {"api-key": "k"},
    )
    assert script.chat_endpoint("https://res.openai.azure.com/openai/v1/", "k")[0] == (
        "https://res.openai.azure.com/openai/v1/chat/completions"
    )
    assert script.chat_endpoint("https://proxy.example/v1", "k") == (
        "https://proxy.example/v1/chat/completions",
        {"Authorization": "Bearer k"},
    )
