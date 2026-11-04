# Streaming JSONL reading/writing with deterministic serialization
from __future__ import annotations

import hashlib
import json
from collections.abc import Iterable, Iterator
from pathlib import Path
from types import TracebackType
from typing import IO, Any


def dumps(record: Any) -> str:
    return json.dumps(record, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as handle:
        json.dump(payload, handle, sort_keys=True, indent=2, ensure_ascii=False)
        handle.write("\n")


def read_json(path: Path) -> Any:
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


class JsonlWriter:
    def __init__(self, path: Path, buffer_lines: int = 5000) -> None:
        self.path = path
        self.count = 0
        self._buffer: list[str] = []
        self._buffer_lines = buffer_lines
        path.parent.mkdir(parents=True, exist_ok=True)
        self._handle: IO[str] = path.open("w", encoding="utf-8", newline="\n")

    def write(self, record: Any) -> None:
        self._buffer.append(dumps(record))
        self.count += 1
        if len(self._buffer) >= self._buffer_lines:
            self.flush()

    def write_many(self, records: Iterable[Any]) -> None:
        for record in records:
            self.write(record)

    def flush(self) -> None:
        if self._buffer:
            self._handle.write("\n".join(self._buffer))
            self._handle.write("\n")
            self._buffer.clear()
        self._handle.flush()

    def close(self) -> None:
        if not self._handle.closed:
            self.flush()
            self._handle.close()

    def __enter__(self) -> JsonlWriter:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        self.close()


class JsonlDecodeError(ValueError):
    def __init__(self, path: Path, line_number: int, message: str) -> None:
        super().__init__(f"{path}:{line_number}: {message}")
        self.path = path
        self.line_number = line_number


def iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    with path.open("r", encoding="utf-8") as handle:
        for line_number, line in enumerate(handle, start=1):
            stripped = line.strip()
            if not stripped:
                continue
            try:
                value = json.loads(stripped)
            except json.JSONDecodeError as exc:
                raise JsonlDecodeError(path, line_number, f"invalid JSON: {exc.msg}") from exc
            if not isinstance(value, dict):
                raise JsonlDecodeError(path, line_number, "each line must be a JSON object")
            yield value


def sha256_file(path: Path, chunk_size: int = 1 << 20) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(chunk_size):
            digest.update(chunk)
    return digest.hexdigest()
