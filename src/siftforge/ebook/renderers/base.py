"""Protocols implemented by concrete ebook renderers."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol

from siftforge.ebook.models import Book


class BookRenderer(Protocol):
    """Render a normalized book into a concrete ebook output format."""

    def render(self, book: Book, destination: Path) -> Path:
        """Render a book and return the resulting output path."""
        ...
