"""Protocols implemented by source-discovery components."""

from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from siftforge.extraction.models import SourceRef


class Source(Protocol):
    """Discover logical source items without performing extraction."""

    def iter_items(self) -> Iterable[SourceRef]:
        """Yield independently processable source references."""
        ...
