# Startup seeding: copy artifacts baked into the image into the (possibly persistent) artifacts directory.
# A missing file is copied; a file still identical to what an earlier deploy seeded is upgraded to the new
# seed; anything else was produced at runtime and is never touched.
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

log = logging.getLogger("firmable.seeding")

MANIFEST = ".seeded.json"


def _digest(path: Path) -> str:
    sha = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            sha.update(chunk)
    return sha.hexdigest()


def seed_artifacts(seed_dir: Path, artifacts_dir: Path) -> dict[str, int]:
    counts = {"copied": 0, "upgraded": 0, "kept": 0}
    if not seed_dir.is_dir():
        return counts
    manifest_path = artifacts_dir / MANIFEST
    try:
        artifacts_dir.mkdir(parents=True, exist_ok=True)
        seeded: dict[str, str] = (
            json.loads(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
        )
        for source in sorted(p for p in seed_dir.rglob("*") if p.is_file()):
            relative = source.relative_to(seed_dir).as_posix()
            target = artifacts_dir / relative
            digest = _digest(source)
            if target.is_file():
                current = _digest(target)
                if current == digest or seeded.get(relative) != current:
                    counts["kept"] += 1
                    continue
                counts["upgraded"] += 1
            else:
                counts["copied"] += 1
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(source, target)
            seeded[relative] = digest
        manifest_path.write_text(json.dumps(seeded, indent=1, sort_keys=True), encoding="utf-8")
    except OSError as exc:
        log.warning("could not seed artifacts into %s: %s", artifacts_dir, exc)
    else:
        log.info("seeded artifacts into %s: %s", artifacts_dir, counts)
    return counts
