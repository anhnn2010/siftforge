"""Protocols for storing inspectable intermediate pipeline artifacts."""

from __future__ import annotations

from typing import Any, Protocol


class ArtifactStore(Protocol):
    """Persist intermediate values for debugging and reproducibility."""

    def write_json(self, relative_path: str, value: Any) -> None:
        """Persist a JSON-compatible value below the artifact root."""
        ...

    def write_text(self, relative_path: str, value: str) -> None:
        """Persist UTF-8 text below the artifact root."""
        ...
