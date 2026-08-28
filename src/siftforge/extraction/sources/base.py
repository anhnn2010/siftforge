from __future__ import annotations

from collections.abc import Iterable
from typing import Protocol

from siftforge.extraction.models import SourceRef


class Source(Protocol):
    """Produces generic source references for extraction tasks."""

    def iter_items(self) -> Iterable[SourceRef]:
        ...
