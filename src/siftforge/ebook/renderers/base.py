from __future__ import annotations

from pathlib import Path
from typing import Protocol

from siftforge.ebook.models import Book


class BookRenderer(Protocol):
    def render(self, book: Book, destination: Path) -> Path:
        ...
