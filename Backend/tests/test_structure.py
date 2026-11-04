# Repository layout contract and Makefile sanity
from __future__ import annotations

import re
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[1]
ROOT = BACKEND.parent


def test_repository_root_has_exactly_two_projects() -> None:
    entries = {p.name for p in ROOT.iterdir() if p.name not in {".git", ".claude", ".vscode", ".idea"}}
    assert entries == {"Frontend", "Backend", ".gitignore", "README.md"}


def test_backend_layout() -> None:
    for relative in (
        "DataGenerator/src/orggraph_dataset",
        "DataGenerator/config",
        "DataGenerator/pyproject.toml",
        "Inference/src/orggraph_inference/normalization",
        "Inference/src/orggraph_inference/candidates",
        "Inference/src/orggraph_inference/features",
        "Inference/src/orggraph_inference/scoring",
        "Inference/src/orggraph_inference/graph",
        "Inference/src/orggraph_inference/evaluation",
        "Inference/src/orggraph_inference/pipeline",
        "Application/src/firmable/main.py",
        "Application/src/firmable/api",
        "Application/src/firmable/core",
        "Application/src/firmable/schemas",
        "Application/src/firmable/services",
        "Application/src/firmable/tests",
        "Infra/Common/BaseSettings.py",
        "Infra/Common/Logging.py",
        "Infra/Local/LocalSettings.py",
        "Infra/Local/docker-compose.yaml",
        "Infra/Production/ProductionSettings.py",
        "Infra/Production/DockerfileProd",
        "scripts",
        "Makefile",
        "pyproject.toml",
        "uv.lock",
        ".env.example",
        ".gitignore",
    ):
        assert (BACKEND / relative).exists(), relative


def test_docs_are_one_trd_per_section() -> None:
    skip = {".git", ".claude", ".venv", "node_modules", ".next", "datasets", ".pytest_cache"}
    found = {
        p.relative_to(ROOT).as_posix()
        for p in ROOT.rglob("*.md")
        if not skip.intersection(p.relative_to(ROOT).parts)
    }
    assert found == {
        "README.md",
        "Backend/DataGenerator/TRD.md",
        "Backend/Inference/TRD.md",
        "Backend/Application/TRD.md",
        "Backend/Infra/TRD.md",
        "Frontend/TRD.md",
    }


def test_makefile_references_existing_paths() -> None:
    text = (BACKEND / "Makefile").read_text(encoding="utf-8")
    referenced = set(re.findall(r"((?:DataGenerator/)?scripts/[\w./-]+\.py|Infra/[\w./-]+)", text))
    assert referenced
    for path in referenced:
        assert (BACKEND / path).exists(), path
    for directory in re.findall(r"cd (\w+) &&", text):
        assert (BACKEND / directory).is_dir(), directory
    for script in ("orggraph-dataset", "orggraph-infer"):
        assert script in text


def test_frontend_has_no_backend_code() -> None:
    frontend = ROOT / "Frontend"
    assert (frontend / "package.json").exists()
    assert not list(frontend.glob("**/*.py"))
