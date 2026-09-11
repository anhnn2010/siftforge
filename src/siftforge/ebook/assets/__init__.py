"""Derived ebook assets materialized from page-level source evidence."""

from .figures import FigureAsset, FigureAssetMaterializer, FigureSourcePage

__all__: list[str] = [
    "FigureAsset",
    "FigureAssetMaterializer",
    "FigureSourcePage",
]
