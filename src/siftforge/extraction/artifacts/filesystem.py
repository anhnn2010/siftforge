"""Filesystem-backed storage for inspectable extraction artifacts."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


class FilesystemArtifactStore:
    """Persist extraction artifacts below one local run directory.

    Args:
        root: Directory that owns all artifacts for a run.
    """

    def __init__(self, root: str | Path) -> None:
        """Initialize a filesystem artifact store and create its root directory."""
        self.root: Path = Path(root).expanduser().resolve()
        self.root.mkdir(parents=True, exist_ok=True)

    def write_json(self, relative_path: str, value: Any) -> None:
        """Persist a JSON-compatible value using stable readable formatting."""
        destination = self._resolve_destination(relative_path)
        payload = json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        self._write_text_atomic(destination, f"{payload}\n")

    def write_text(self, relative_path: str, value: str) -> None:
        """Persist UTF-8 text below the artifact root."""
        destination = self._resolve_destination(relative_path)
        self._write_text_atomic(destination, value)

    def _resolve_destination(self, relative_path: str) -> Path:
        """Resolve an artifact path while preventing traversal outside the root."""
        destination = (self.root / relative_path).resolve()
        if destination != self.root and self.root not in destination.parents:
            raise ValueError(
                f"artifact path escapes run directory: {relative_path!r}"
            )
        destination.parent.mkdir(parents=True, exist_ok=True)
        return destination

    @staticmethod
    def _write_text_atomic(destination: Path, value: str) -> None:
        """Atomically replace one text artifact after writing a sibling temp file."""
        temporary = destination.with_name(f".{destination.name}.tmp")
        temporary.write_text(value, encoding="utf-8")
        temporary.replace(destination)
