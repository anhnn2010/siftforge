"""Ebook output-rendering interfaces and concrete renderers."""

from .base import BookRenderer
from .xhtml import EpubReadyXhtmlRenderer, XhtmlRenderResult

__all__: list[str] = [
    "BookRenderer",
    "EpubReadyXhtmlRenderer",
    "XhtmlRenderResult",
]
