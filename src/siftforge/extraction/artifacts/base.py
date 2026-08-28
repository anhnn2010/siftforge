from __future__ import annotations

from typing import Any, Protocol


class ArtifactStore(Protocol):
    """Persists inspectable intermediate artifacts."""

    def write_json(self, relative_path: str, value: Any) -> None:
        ...

    def write_text(self, relative_path: str, value: str) -> None:
        ...
