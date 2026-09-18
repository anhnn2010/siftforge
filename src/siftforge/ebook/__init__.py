"""Ebook application domain built on top of generic extraction primitives."""

from .metadata import (
    BookMetadata,
    BookMetadataError,
    book_metadata_from_dict,
    book_metadata_to_dict,
    load_book_metadata,
    merge_book_metadata,
    resolve_book_metadata,
    resolve_metadata_cover,
    write_book_metadata,
)

__all__: list[str] = [
    "BookMetadata",
    "BookMetadataError",
    "book_metadata_from_dict",
    "book_metadata_to_dict",
    "load_book_metadata",
    "merge_book_metadata",
    "resolve_book_metadata",
    "resolve_metadata_cover",
    "write_book_metadata",
]
