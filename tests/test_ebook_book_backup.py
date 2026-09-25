"""Tests for compact Git-friendly human book backups."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from siftforge.ebook.pipeline import (
    EbookBookBackupError,
    EbookBookBackupService,
    EbookProofService,
)


def _write_ready_fixture(root: Path) -> None:
    """Create a minimal EPUB-ready tree suitable for proof backup tests."""
    (root / "text").mkdir(parents=True)
    (root / "styles").mkdir(parents=True)
    (root / "text" / "chapter-0001.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" lang="vi">\n'
        "<body><p>Người mẹ nhìn con.</p></body></html>\n",
        encoding="utf-8",
    )
    (root / "styles" / "book.css").write_text(
        ".verse-line { margin: 0; }\n",
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "epub-ready-xhtml",
                "source_assembly": "book",
                "title": "18 Năm Kim Cương",
                "language": "vi",
                "author": "Hồ Thị Hải Âu",
                "content": "text/chapter-0001.xhtml",
                "stylesheet": "styles/book.css",
                "assets": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def _write_build_manifest(path: Path) -> None:
    """Write a representative provider-free build manifest."""
    path.write_text(
        json.dumps(
            {
                "format": "siftforge-ebook-build",
                "runs_root": "/private/local/runs/book",
                "work_dir": "/private/local/runs/book-build",
                "output_epub": "/private/local/dist/book.epub",
                "metadata": {
                    "title": "18 Năm Kim Cương",
                    "language": "vi",
                },
                "excluded_pages": [7, 8, 9, 10],
                "stages": {
                    "package": {
                        "identifier": "urn:uuid:test-book",
                        "modified": "2026-09-24T00:00:00Z",
                        "manifest_items": 4,
                        "toc_entries": 2,
                    },
                    "epubcheck": {
                        "requested": True,
                        "passed": True,
                        "report": "/private/local/report.json",
                    },
                },
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_backup_book_syncs_durable_artifacts_and_preserves_git_tree(
    tmp_path: Path,
) -> None:
    """Repeated backups should update managed files without touching Git data."""
    runs = tmp_path / "runs" / "book"
    ready = tmp_path / "runs" / "book-build" / "epub-ready"
    proof = tmp_path / "runs" / "book-build" / "proof"
    backup = tmp_path / "book-history" / "18-nam-kim-cuong"
    runs.mkdir(parents=True)
    _write_ready_fixture(ready)
    EbookProofService().prepare(ready, proof)

    (runs / "metadata.json").write_text(
        json.dumps({"title": "18 Năm Kim Cương", "language": "vi"}),
        encoding="utf-8",
    )
    (runs / "review").mkdir()
    (runs / "review" / "resolutions.json").write_text(
        json.dumps({"format": "review", "resolutions": []}),
        encoding="utf-8",
    )
    _write_build_manifest(proof.parent / "build-manifest.json")

    (backup / ".git").mkdir(parents=True)
    (backup / ".git" / "HEAD").write_text("ref: refs/heads/main\n", encoding="utf-8")
    (backup / "NOTES.md").write_text("human notes\n", encoding="utf-8")

    service = EbookBookBackupService()
    first = service.backup(runs, proof, backup)

    assert first.editable_count == 1
    assert first.modified_count == 0
    assert (backup / "proof" / "text" / "chapter-0001.xhtml").is_file()
    assert (backup / "metadata.json").is_file()
    assert (backup / "review" / "resolutions.json").is_file()
    assert (backup / ".git" / "HEAD").read_text(encoding="utf-8").startswith("ref:")
    assert (backup / "NOTES.md").read_text(encoding="utf-8") == "human notes\n"

    build_info = json.loads((backup / "build-info.json").read_text(encoding="utf-8"))
    assert build_info["excluded_pages"] == [7, 8, 9, 10]
    assert "runs_root" not in build_info
    assert "work_dir" not in build_info
    assert "output_epub" not in build_info

    source_chapter = proof / "text" / "chapter-0001.xhtml"
    source_chapter.write_text(
        source_chapter.read_text(encoding="utf-8").replace("nhìn", "ngắm"),
        encoding="utf-8",
    )
    second = service.backup(runs, proof, backup)

    assert second.modified_count == 1
    backed_up = (backup / "proof" / "text" / "chapter-0001.xhtml").read_text(
        encoding="utf-8"
    )
    assert "ngắm con" in backed_up
    manifest = json.loads((backup / "backup-manifest.json").read_text(encoding="utf-8"))
    assert manifest["proof"]["modified_xhtml"] == ["text/chapter-0001.xhtml"]
    assert (backup / "NOTES.md").is_file()


def test_backup_book_omits_missing_optional_runs_artifacts(tmp_path: Path) -> None:
    """Metadata, review, and build info should be optional backup additions."""
    runs = tmp_path / "runs" / "book"
    ready = tmp_path / "ready"
    proof = tmp_path / "proof"
    backup = tmp_path / "backup"
    runs.mkdir(parents=True)
    _write_ready_fixture(ready)
    EbookProofService().prepare(ready, proof)

    run = EbookBookBackupService().backup(runs, proof, backup)

    assert run.metadata_path is None
    assert run.review_resolutions_path is None
    assert run.build_info_path is None
    assert (backup / "proof" / "text" / "chapter-0001.xhtml").is_file()


def test_backup_book_rejects_destination_inside_source_tree(tmp_path: Path) -> None:
    """A backup destination must not recursively live inside runs or proof."""
    runs = tmp_path / "runs" / "book"
    ready = tmp_path / "ready"
    proof = tmp_path / "proof"
    runs.mkdir(parents=True)
    _write_ready_fixture(ready)
    EbookProofService().prepare(ready, proof)

    with pytest.raises(EbookBookBackupError, match="must not be inside page-runs"):
        EbookBookBackupService().backup(runs, proof, runs / "backup")
