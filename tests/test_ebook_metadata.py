"""Tests for book-level EPUB metadata loading and overrides."""

import json
from pathlib import Path

import pytest

from siftforge.ebook.metadata import (
    BookMetadataError,
    load_book_metadata,
    merge_book_metadata,
    resolve_metadata_cover,
)


def test_metadata_json_loads_rich_fields_and_relative_cover(tmp_path: Path) -> None:
    """Metadata should preserve ordered rich fields and resolve local cover paths."""
    cover = tmp_path / "images" / "cover.jpg"
    cover.parent.mkdir()
    cover.write_bytes(b"jpeg")
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "title": "Sách thử",
                "subtitle": "Phụ đề",
                "language": "vi",
                "authors": ["Tác giả A", "Tác giả B"],
                "publisher": "Nhà xuất bản",
                "publication_date": "2026-09-18",
                "isbn": "9780000000000",
                "description": "Mô tả sách.",
                "subjects": ["Kỹ năng", "Giáo dục"],
                "rights": "© 2026",
                "series": "Bộ sách thử",
                "series_index": 2,
                "contributors": ["Người dịch"],
                "cover": "images/cover.jpg",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    metadata = load_book_metadata(metadata_path)

    assert metadata.title == "Sách thử"
    assert metadata.subtitle == "Phụ đề"
    assert metadata.authors == ("Tác giả A", "Tác giả B")
    assert metadata.series_index == "2"
    assert metadata.subjects == ("Kỹ năng", "Giáo dục")
    assert resolve_metadata_cover(
        metadata,
        metadata_path=metadata_path,
    ) == cover.resolve()


def test_legacy_overrides_win_over_metadata_json(tmp_path: Path) -> None:
    """Explicit CLI-compatible fields should override persisted metadata."""
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps(
            {
                "title": "Tên cũ",
                "language": "en",
                "authors": ["Tác giả cũ", "Đồng tác giả"],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    metadata = merge_book_metadata(
        load_book_metadata(metadata_path),
        title="Tên mới",
        language="vi",
        author="Tác giả mới",
    )

    assert metadata.title == "Tên mới"
    assert metadata.language == "vi"
    assert metadata.authors == ("Tác giả mới",)


def test_metadata_rejects_non_list_authors(tmp_path: Path) -> None:
    """The rich authors field should use an explicit ordered JSON list."""
    metadata_path = tmp_path / "metadata.json"
    metadata_path.write_text(
        json.dumps({"title": "Sách", "authors": "Tác giả"}),
        encoding="utf-8",
    )

    with pytest.raises(BookMetadataError, match="authors.*list"):
        load_book_metadata(metadata_path)
