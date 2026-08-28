"""Protocols for turning logical source references into local assets."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from siftforge.extraction.models import MaterializedAsset, SourceRef


class SourceMaterializer(Protocol):
    """Materialize one logical source item as a provider-consumable asset."""

    def materialize(
        self,
        source: SourceRef,
        destination_dir: str | Path,
    ) -> MaterializedAsset:
        """Write or reuse a local asset for the supplied source reference."""
        ...
