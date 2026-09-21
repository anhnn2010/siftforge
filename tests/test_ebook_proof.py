"""Tests for the human-owned final proofreading layer."""

from __future__ import annotations

import json
import zipfile
from pathlib import Path

import pytest

from siftforge.ebook.pipeline import (
    EbookEpubPackageService,
    EbookProofError,
    EbookProofService,
)


def _write_ready_fixture(root: Path) -> None:
    """Create a minimal packageable EPUB-ready tree with editable XHTML."""
    (root / "text").mkdir(parents=True)
    (root / "styles").mkdir(parents=True)
    (root / "semantic").mkdir(parents=True)
    (root / "text" / "chapter-0001.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="vi">\n'
        "  <head><title>Sách thử</title></head>\n"
        "  <body>\n"
        '    <h1 id="chapter-1">Chương một</h1>\n'
        "    <p>Người mẹ nhin con trong im lặng.</p>\n"
        "  </body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    (root / "styles" / "book.css").write_text(
        "body { line-height: 1.5; }\n",
        encoding="utf-8",
    )
    (root / "semantic" / "document.json").write_text(
        json.dumps(
            {
                "title": "Sách thử",
                "language": "vi",
                "author": "Tác giả",
                "nodes": [
                    {
                        "type": "heading",
                        "node_id": "chapter-1",
                        "role": "chapter_title",
                        "level": 1,
                        "content": [
                            {
                                "text": "Chương một",
                                "language": "vi",
                                "marks": [],
                                "role": "text",
                                "target_id": None,
                                "source_span_id": "span-1",
                            }
                        ],
                    }
                ],
                "relationships": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "epub-ready-xhtml",
                "source_assembly": "book",
                "title": "Sách thử",
                "language": "vi",
                "author": "Tác giả",
                "content": "text/chapter-0001.xhtml",
                "stylesheet": "styles/book.css",
                "assets": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_prepare_proof_freezes_ready_tree_and_tracks_human_edits(
    tmp_path: Path,
) -> None:
    """Proof workspaces should preserve a baseline and detect edited XHTML."""
    ready = tmp_path / "epub-ready"
    proof = tmp_path / "proof"
    _write_ready_fixture(ready)
    service = EbookProofService()

    run = service.prepare(ready, proof)

    assert run.proof_dir == proof.resolve()
    assert run.editable_count == 1
    assert run.manifest_path.is_file()
    status = service.inspect(proof)
    assert status.modified_count == 0

    chapter = proof / "text" / "chapter-0001.xhtml"
    chapter.write_text(
        chapter.read_text(encoding="utf-8").replace("nhin", "nhìn"),
        encoding="utf-8",
    )
    status = service.inspect(proof)
    assert status.modified_count == 1
    assert status.modified_paths == (chapter.resolve(),)


def test_prepare_proof_refuses_to_overwrite_human_workspace(
    tmp_path: Path,
) -> None:
    """A normal prepare run must never erase existing proof edits."""
    ready = tmp_path / "epub-ready"
    proof = tmp_path / "proof"
    _write_ready_fixture(ready)
    service = EbookProofService()
    service.prepare(ready, proof)
    chapter = proof / "text" / "chapter-0001.xhtml"
    chapter.write_text("human edit", encoding="utf-8")

    with pytest.raises(EbookProofError, match="refusing to overwrite human edits"):
        service.prepare(ready, proof)

    assert chapter.read_text(encoding="utf-8") == "human edit"


def test_force_prepare_is_explicit_escape_hatch(tmp_path: Path) -> None:
    """Explicit force should recreate proof from the current generated source."""
    ready = tmp_path / "epub-ready"
    proof = tmp_path / "proof"
    _write_ready_fixture(ready)
    service = EbookProofService()
    service.prepare(ready, proof)
    chapter = proof / "text" / "chapter-0001.xhtml"
    chapter.write_text("human edit", encoding="utf-8")

    service.prepare(ready, proof, force=True)

    assert "Người mẹ nhin con" in chapter.read_text(encoding="utf-8")
    assert service.inspect(proof).modified_count == 0


def test_final_epub_can_be_packaged_directly_from_human_proof(
    tmp_path: Path,
) -> None:
    """Manual XHTML corrections should reach the final EPUB without rerendering."""
    ready = tmp_path / "epub-ready"
    proof = tmp_path / "proof"
    output = tmp_path / "book.epub"
    _write_ready_fixture(ready)
    service = EbookProofService()
    service.prepare(ready, proof)
    chapter = proof / "text" / "chapter-0001.xhtml"
    chapter.write_text(
        chapter.read_text(encoding="utf-8").replace("nhin", "nhìn"),
        encoding="utf-8",
    )

    EbookEpubPackageService().build(
        proof,
        output,
        modified="2026-09-18T10:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        content = archive.read("EPUB/text/chapter-0001.xhtml").decode("utf-8")
    assert "Người mẹ nhìn con" in content
    assert "Người mẹ nhin con" not in content
