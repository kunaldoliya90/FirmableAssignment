# Offline LLM pass: map observed job titles the rule-based matcher struggles with to canonical titles.
#
# Run from Backend/:  uv run python Inference/scripts/llm_title_aliases.py [--dry-run]
# Needs OPENAI_API_KEY (env or Backend/.env); OPENAI_MODEL defaults to gpt-5.5; OPENAI_ENDPOINT is optional
# (OpenAI by default, or an Azure AI Foundry / Azure OpenAI URL). Reads observed data only.
# Every answer is cached in llm_cache/title_aliases_cache.json, so re-runs cost nothing and the result is
# reproducible. Review the diff of normalization/title_aliases.json, re-evaluate, then commit both files.
# Production never calls the LLM: the engine just reads the committed alias file.
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from typing import Any

import httpx
from orggraph_dataset.utils.jsonl import iter_jsonl
from orggraph_inference.normalization import load_vocabulary
from orggraph_inference.normalization.text import clean
from orggraph_inference.normalization.titles import TITLE_ALIASES_PATH, TitleNormalizer

BACKEND = Path(__file__).resolve().parents[2]
CACHE_PATH = Path(__file__).with_name("llm_cache") / "title_aliases_cache.json"
API_URL = "https://api.openai.com/v1/chat/completions"
# methods whose seniority is wrong far more often than exact matches (see Inference TRD, section 8)
DEFAULT_METHODS = ("fuzzy", "keyword", "unknown", "exact_ambiguous", "fuzzy_ambiguous", "stripped_ambiguous")

SYSTEM_PROMPT = """You normalize messy job titles from HR systems, directories and public profiles.
Each input title may be abbreviated, misspelled, reordered or carry a team/location suffix.
Map each one to exactly one canonical title from the list below, or null if you cannot tell with
confidence (for example a bare "Lead" or "Manager" with no function). Never invent titles; copy the
canonical title exactly as written. Seniority matters most: do not upgrade or downgrade it.

Canonical titles (title | job family | seniority):
{catalog}"""

RESPONSE_FORMAT: dict[str, Any] = {
    "type": "json_schema",
    "json_schema": {
        "name": "title_mapping",
        "strict": True,
        "schema": {
            "type": "object",
            "properties": {
                "results": {
                    "type": "array",
                    "items": {
                        "type": "object",
                        "properties": {
                            "raw": {"type": "string"},
                            "canonical_title": {"type": ["string", "null"]},
                        },
                        "required": ["raw", "canonical_title"],
                        "additionalProperties": False,
                    },
                }
            },
            "required": ["results"],
            "additionalProperties": False,
        },
    },
}

Post = Callable[[dict[str, Any]], dict[str, Any]]


def read_env_file(path: Path) -> dict[str, str]:
    if not path.is_file():
        return {}
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and not key.startswith("#"):
            values[key.strip()] = value.strip().strip("'\"")
    return values


def target_titles(dataset_dir: Path, normalizer: TitleNormalizer, methods: set[str]) -> list[str]:
    seen: dict[str, str] = {}
    for path in sorted((dataset_dir / "observed").glob("*/observations.jsonl")):
        for row in iter_jsonl(path):
            raw = row.get("observed_title")
            if raw and clean(raw) not in seen and normalizer.interpret(raw).method in methods:
                seen[clean(raw)] = raw
    return [seen[key] for key in sorted(seen)]


def catalog(normalizer: TitleNormalizer) -> str:
    entries = sorted(normalizer.vocab.taxonomy.all_titles(), key=lambda e: e.canonical_title)
    return "\n".join(f"{e.canonical_title} | {e.job_family} | {e.seniority_level}" for e in entries)


def chat_endpoint(endpoint: str | None, api_key: str) -> tuple[str, dict[str, str]]:
    # OPENAI_ENDPOINT may be an Azure AI Foundry project URL (…/api/projects/<name>), an Azure resource
    # URL, or any OpenAI-compatible base URL; Azure serves the OpenAI v1 API under /openai/v1 with `api-key`
    if not endpoint:
        return API_URL, {"Authorization": f"Bearer {api_key}"}
    base = endpoint.split("/api/projects/")[0].rstrip("/")
    if ".azure.com" in base:
        if not base.endswith("/openai/v1"):
            base += "/openai/v1"
        return f"{base}/chat/completions", {"api-key": api_key}
    return f"{base}/chat/completions", {"Authorization": f"Bearer {api_key}"}


def openai_post(url: str, headers: dict[str, str], client: httpx.Client) -> Post:
    def post(body: dict[str, Any]) -> dict[str, Any]:
        for attempt in range(5):
            response = client.post(url, json=body, headers=headers)
            if response.status_code in (429, 500, 502, 503) and attempt < 4:
                time.sleep(2**attempt)
                continue
            if response.is_error:
                raise RuntimeError(f"OpenAI API {response.status_code}: {response.text[:500]}")
            result: dict[str, Any] = response.json()
            return result
        raise RuntimeError("unreachable")

    return post


def map_batch(
    post: Post, model: str, system: str, batch: list[str], valid: set[str], reasoning_effort: str | None
) -> dict[str, str | None]:
    body: dict[str, Any] = {
        "model": model,
        "messages": [
            {"role": "system", "content": system},
            {"role": "user", "content": json.dumps({"titles": batch}, ensure_ascii=False)},
        ],
        "response_format": RESPONSE_FORMAT,
    }
    if reasoning_effort:
        body["reasoning_effort"] = reasoning_effort
    content = post(body)["choices"][0]["message"]["content"]
    answers: dict[str, str | None] = dict.fromkeys(batch)
    for item in json.loads(content)["results"]:
        if item["raw"] in answers and item["canonical_title"] in valid:
            answers[item["raw"]] = item["canonical_title"]
    return answers


def run(
    titles: list[str],
    normalizer: TitleNormalizer,
    post: Post,
    model: str,
    batch_size: int,
    cache: dict[str, str | None],
    reasoning_effort: str | None = None,
    on_batch: Callable[[int, int], None] | None = None,
    workers: int = 1,
) -> dict[str, str | None]:
    valid = {e.canonical_title for e in normalizer.vocab.taxonomy.all_titles()}
    system = SYSTEM_PROMPT.format(catalog=catalog(normalizer))
    todo = [t for t in titles if t not in cache]
    batches = [todo[start : start + batch_size] for start in range(0, len(todo), batch_size)]
    done = 0
    with ThreadPoolExecutor(max_workers=workers) as pool:
        futures = [
            pool.submit(map_batch, post, model, system, batch, valid, reasoning_effort) for batch in batches
        ]
        for future in as_completed(futures):
            answers = future.result()
            cache.update(answers)
            done += len(answers)
            if on_batch:
                on_batch(done, len(todo))
    return cache


def write_aliases(cache: dict[str, str | None], model: str, path: Path) -> int:
    aliases = {clean(raw): canonical for raw, canonical in sorted(cache.items()) if canonical}
    payload = {
        "model": model,
        "source": "scripts/llm_title_aliases.py",
        "aliases": dict(sorted(aliases.items())),
    }
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    return len(aliases)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Map hard observed job titles to canonical titles with an LLM."
    )
    parser.add_argument(
        "--dataset-dir", type=Path, default=BACKEND / "DataGenerator/datasets/FirmableAssignmentDataset"
    )
    parser.add_argument("--methods", nargs="+", default=list(DEFAULT_METHODS))
    parser.add_argument("--batch-size", type=int, default=80)
    parser.add_argument("--reasoning-effort", default="low", help="empty string to omit the parameter")
    parser.add_argument("--workers", type=int, default=4, help="parallel API calls")
    parser.add_argument("--limit", type=int, default=None, help="only the first N titles (a cheap trial)")
    parser.add_argument("--dry-run", action="store_true", help="count titles and batches, call nothing")
    args = parser.parse_args()

    env = {**read_env_file(BACKEND / ".env"), **os.environ}
    model = env.get("OPENAI_MODEL", "gpt-5.5")
    # aliases={} so the current alias file never hides titles from the pass
    normalizer = TitleNormalizer(load_vocabulary(), aliases={})
    titles = target_titles(args.dataset_dir, normalizer, set(args.methods))[: args.limit]
    cache: dict[str, str | None] = (
        json.loads(CACHE_PATH.read_text(encoding="utf-8")) if CACHE_PATH.is_file() else {}
    )
    todo = sum(1 for t in titles if t not in cache)
    print(
        f"{len(titles)} titles to map, {todo} not cached, {-(-todo // args.batch_size)} API calls ({model})"
    )
    if args.dry_run or not titles:
        return 0
    if todo and not env.get("OPENAI_API_KEY"):
        print("OPENAI_API_KEY is not set (environment or Backend/.env)", file=sys.stderr)
        return 1

    CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)

    def save(done: int, total: int) -> None:
        CACHE_PATH.write_text(
            json.dumps(dict(sorted(cache.items())), indent=1, ensure_ascii=False), encoding="utf-8"
        )
        print(f"  mapped {done}/{total}")

    url, headers = chat_endpoint(env.get("OPENAI_ENDPOINT"), env.get("OPENAI_API_KEY", ""))
    with httpx.Client(timeout=300) as client:
        post = openai_post(url, headers, client)
        run(
            titles,
            normalizer,
            post,
            model,
            args.batch_size,
            cache,
            args.reasoning_effort or None,
            save,
            args.workers,
        )
    count = write_aliases({t: cache[t] for t in titles if t in cache}, model, TITLE_ALIASES_PATH)
    print(f"wrote {count} aliases to {TITLE_ALIASES_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
