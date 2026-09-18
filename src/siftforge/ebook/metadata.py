"""Book-level bibliographic metadata for EPUB packaging."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from pathlib import Path
from typing import Any


class BookMetadataError(ValueError):
    """Raised when persisted or supplied book metadata is invalid."""


@dataclass(frozen=True, slots=True)
class BookMetadata:
    """Bibliographic metadata independent from page extraction structure.

    Attributes:
        title: Main publication title.
        subtitle: Optional subtitle.
        language: Optional BCP 47 publication language.
        authors: Ordered author names.
        publisher: Optional publisher name.
        publication_date: Optional publication date as source text/ISO date.
        isbn: Optional ISBN identifier.
        description: Optional publication description or summary.
        subjects: Ordered subject/category labels.
        rights: Optional rights/copyright statement.
        series: Optional series/collection name.
        series_index: Optional position within the series.
        contributors: Ordered non-author contributor names.
        cover: Optional cover image path as written in ``metadata.json``.
    """

    title: str | None = None
    subtitle: str | None = None
    language: str | None = None
    authors: tuple[str, ...] = ()
    publisher: str | None = None
    publication_date: str | None = None
    isbn: str | None = None
    description: str | None = None
    subjects: tuple[str, ...] = ()
    rights: str | None = None
    series: str | None = None
    series_index: str | None = None
    contributors: tuple[str, ...] = ()
    cover: str | None = None

    @property
    def primary_author(self) -> str | None:
        """Return the first author for legacy single-author consumers."""
        return self.authors[0] if self.authors else None


def load_book_metadata(path: str | Path) -> BookMetadata:
    """Load and validate one UTF-8 ``metadata.json`` file."""
    source = Path(path).expanduser().resolve()
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise BookMetadataError(f"metadata file does not exist: {source}") from exc
    except json.JSONDecodeError as exc:
        raise BookMetadataError(f"invalid metadata JSON: {source}") from exc
    if not isinstance(payload, dict):
        raise BookMetadataError("metadata JSON root must be an object")
    return book_metadata_from_dict(payload)


def book_metadata_from_dict(payload: dict[str, Any]) -> BookMetadata:
    """Parse one metadata mapping into a typed ``BookMetadata`` value."""
    authors_value = payload.get("authors")
    if authors_value is None and payload.get("author") is not None:
        authors_value = [payload.get("author")]
    return BookMetadata(
        title=_optional_text(payload, "title"),
        subtitle=_optional_text(payload, "subtitle"),
        language=_optional_text(payload, "language"),
        authors=_string_sequence(authors_value, "authors"),
        publisher=_optional_text(payload, "publisher"),
        publication_date=_optional_text(payload, "publication_date"),
        isbn=_optional_text(payload, "isbn"),
        description=_optional_text(payload, "description"),
        subjects=_string_sequence(payload.get("subjects"), "subjects"),
        rights=_optional_text(payload, "rights"),
        series=_optional_text(payload, "series"),
        series_index=_optional_scalar_text(payload, "series_index"),
        contributors=_string_sequence(
            payload.get("contributors"),
            "contributors",
        ),
        cover=_optional_text(payload, "cover"),
    )


def book_metadata_to_dict(metadata: BookMetadata) -> dict[str, object]:
    """Serialize metadata into stable JSON-compatible values."""
    return {
        "title": metadata.title,
        "subtitle": metadata.subtitle,
        "language": metadata.language,
        "authors": list(metadata.authors),
        "publisher": metadata.publisher,
        "publication_date": metadata.publication_date,
        "isbn": metadata.isbn,
        "description": metadata.description,
        "subjects": list(metadata.subjects),
        "rights": metadata.rights,
        "series": metadata.series,
        "series_index": metadata.series_index,
        "contributors": list(metadata.contributors),
        "cover": metadata.cover,
    }


def merge_book_metadata(
    base: BookMetadata | None,
    *,
    title: str | None = None,
    language: str | None = None,
    author: str | None = None,
) -> BookMetadata:
    """Overlay legacy CLI values on optional persisted metadata.

    Explicit command-line values win over values loaded from ``metadata.json``.
    A legacy single ``author`` override replaces the complete author list.
    """
    current = base or BookMetadata()
    updates: dict[str, object] = {}
    if title is not None:
        updates["title"] = _clean_override(title, "title")
    if language is not None:
        updates["language"] = _clean_override(language, "language")
    if author is not None:
        updates["authors"] = (_clean_override(author, "author"),)
    return replace(current, **updates)


def resolve_book_metadata(
    *,
    metadata_path: str | Path | None = None,
    title: str | None = None,
    language: str | None = None,
    author: str | None = None,
) -> BookMetadata:
    """Load optional JSON, apply explicit overrides, and require a title."""
    base = load_book_metadata(metadata_path) if metadata_path is not None else None
    metadata = merge_book_metadata(
        base,
        title=title,
        language=language,
        author=author,
    )
    if metadata.title is None:
        raise BookMetadataError(
            "book title is required via --title or metadata.json"
        )
    return metadata


def resolve_metadata_cover(
    metadata: BookMetadata,
    *,
    metadata_path: str | Path | None,
) -> Path | None:
    """Resolve a metadata-declared cover relative to its JSON file."""
    if metadata.cover is None:
        return None
    cover = Path(metadata.cover).expanduser()
    if not cover.is_absolute():
        if metadata_path is None:
            cover = Path.cwd() / cover
        else:
            cover = Path(metadata_path).expanduser().resolve().parent / cover
    return cover.resolve()


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    """Return an optional non-empty string field."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise BookMetadataError(f"metadata field {key!r} must be a non-empty string")
    return value.strip()


def _optional_scalar_text(payload: dict[str, Any], key: str) -> str | None:
    """Return an optional string/number scalar normalized as text."""
    value = payload.get(key)
    if value is None:
        return None
    if isinstance(value, bool) or not isinstance(value, str | int | float):
        raise BookMetadataError(
            f"metadata field {key!r} must be a string or number"
        )
    text = str(value).strip()
    if not text:
        raise BookMetadataError(f"metadata field {key!r} must not be empty")
    return text


def _string_sequence(value: Any, key: str) -> tuple[str, ...]:
    """Return one optional JSON string list as a normalized tuple."""
    if value is None:
        return ()
    if not isinstance(value, list):
        raise BookMetadataError(f"metadata field {key!r} must be a list")
    result: list[str] = []
    for item in value:
        if not isinstance(item, str) or not item.strip():
            raise BookMetadataError(
                f"metadata field {key!r} must contain non-empty strings"
            )
        result.append(item.strip())
    return tuple(result)


def _clean_override(value: str, key: str) -> str:
    """Validate one explicitly supplied legacy metadata override."""
    cleaned = value.strip()
    if not cleaned:
        raise BookMetadataError(f"book {key} must not be empty")
    return cleaned
