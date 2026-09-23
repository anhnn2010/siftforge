"""Tests for the end-to-end provider-free EPUB build orchestrator."""

from __future__ import annotations

import json
import subprocess
import zipfile
from pathlib import Path
from typing import Any

import pytest
from PIL import Image

from siftforge.ebook.extraction import EbookPageEvidenceNormalizer
from siftforge.ebook.pipeline import EbookBuildError, EbookBuildService
from siftforge.extraction.models import SourceRef


def _typography() -> dict[str, Any]:
    """Return ordinary source typography for one synthetic text span."""
    return {
        "posture": "roman",
        "weight": "normal",
        "vertical_position": "baseline",
        "caps_style": "normal",
        "decorations": [],
    }


def _paragraph(text: str) -> dict[str, Any]:
    """Return one complete paragraph block in the v5 provider contract."""
    return {
        "role_hint": "paragraph",
        "content": [
            {
                "text": text,
                "language": "vi",
                "source_typography": _typography(),
                "semantic_line_break_after": False,
            }
        ],
        "dominant_language": "vi",
        "heading_level_hint": None,
        "heading_role_hint": "unknown",
        "marker": None,
        "region": None,
        "alignment": "left",
    }


def _write_page_run(root: Path, page_number: int, text: str) -> None:
    """Write one canonical page run consumed by the orchestration service."""
    run_dir = root / f"page-{page_number:04d}"
    (run_dir / "normalized").mkdir(parents=True, exist_ok=True)
    (run_dir / "assets").mkdir(parents=True, exist_ok=True)
    page_id = f"pdf:test:page:{page_number:04d}"
    source = SourceRef(
        source_id=page_id,
        uri=f"fixture://book/page/{page_number}",
        media_type="image/jpeg",
        metadata={"page_number": page_number},
    )
    payload = {
        "page_kind_hint": "text",
        "dominant_language": "vi",
        "printed_page_number": str(page_number),
        "blocks": [_paragraph(text)],
        "warnings": [],
    }
    normalizer = EbookPageEvidenceNormalizer()
    page = normalizer.normalize(page_id, source, payload)
    (run_dir / "normalized" / "page.json").write_text(
        json.dumps(normalizer.to_dict(page), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image = run_dir / "assets" / f"page-{page_number:04d}.jpg"
    Image.new("RGB", (100, 100), (235, 235, 235)).save(image, format="JPEG")
    (run_dir / "manifest.json").write_text(
        json.dumps(
            {
                "source": {"page_number": page_number},
                "asset": {
                    "path": f"assets/{image.name}",
                    "media_type": "image/jpeg",
                },
            },
            indent=2,
        ),
        encoding="utf-8",
    )


def test_build_epub_rebuilds_derived_stages_from_page_runs(tmp_path: Path) -> None:
    """A repeated build should not reuse stale assembly or XHTML artifacts."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Phiên bản một.")
    work = tmp_path / "work"
    output = tmp_path / "dist" / "book.epub"
    service = EbookBuildService()

    first = service.build(
        runs,
        output,
        title="Sách thử",
        language="vi",
        work_dir=work,
        modified="2026-09-15T06:00:00Z",
    )

    assert output.is_file()
    assert first.manifest_path == work / "build-manifest.json"
    (work / "assembly" / "stale.txt").write_text("stale", encoding="utf-8")
    (work / "epub-ready" / "stale.txt").write_text("stale", encoding="utf-8")

    _write_page_run(runs, 1, "Phiên bản hai.")
    second = service.build(
        runs,
        output,
        title="Sách thử",
        language="vi",
        work_dir=work,
        modified="2026-09-15T06:00:00Z",
    )

    assert not (work / "assembly" / "stale.txt").exists()
    assert not (work / "epub-ready" / "stale.txt").exists()
    with zipfile.ZipFile(output) as archive:
        content = archive.read("EPUB/text/content.xhtml").decode("utf-8")
    assert "Phiên bản hai." in content
    assert "Phiên bản một." not in content
    manifest = json.loads(second.manifest_path.read_text(encoding="utf-8"))
    assert manifest["policy"] == "clean-derived-stages"
    assert manifest["stages"]["assembly"]["pages"] == 1
    assert manifest["stages"]["epubcheck"]["requested"] is False


def test_build_epub_excludes_selected_physical_pages(tmp_path: Path) -> None:
    """Excluded source pages should remain in runs but not enter the EPUB."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Trang mở đầu.")
    _write_page_run(runs, 2, "Mục lục in sẵn.")
    _write_page_run(runs, 3, "Nội dung chương một.")
    output = tmp_path / "dist" / "book.epub"
    work = tmp_path / "work"

    run = EbookBuildService().build(
        runs,
        output,
        title="Sách thử",
        language="vi",
        work_dir=work,
        modified="2026-09-23T10:00:00Z",
        exclude_page_numbers=(2,),
    )

    assert (runs / "page-0002" / "normalized" / "page.json").is_file()
    assert [page.page_number for page in run.assembly.page_runs] == [1, 3]
    assert run.assembly.excluded_page_numbers == (2,)
    with zipfile.ZipFile(output) as archive:
        content = archive.read("EPUB/text/content.xhtml").decode("utf-8")
    assert "Trang mở đầu." in content
    assert "Nội dung chương một." in content
    assert "Mục lục in sẵn." not in content

    assembly_manifest = json.loads(
        (work / "assembly" / "manifest.json").read_text(encoding="utf-8")
    )
    assert assembly_manifest["excluded_pages"] == [2]
    build_manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert build_manifest["excluded_pages"] == [2]
    assert build_manifest["stages"]["assembly"]["pages"] == 2


def test_build_epub_does_not_bridge_continuations_across_excluded_gap(
    tmp_path: Path,
) -> None:
    """Filtering a middle page must not make nonconsecutive pages adjacent."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Một câu đang dở")
    _write_page_run(runs, 2, "Mục lục in sẵn.")
    _write_page_run(runs, 3, "tiếp tục ở trang sau.")

    run = EbookBuildService().build(
        runs,
        tmp_path / "book.epub",
        title="Sách thử",
        work_dir=tmp_path / "work",
        exclude_page_numbers=(2,),
    )

    assert run.assembly.analysis.resolved_continuations == ()


def test_require_reviewed_ignores_pages_excluded_from_build(tmp_path: Path) -> None:
    """Strict review gating should cover only pages entering the final EPUB."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Nội dung chính.")
    _write_page_run(runs, 2, "Mục lục in sẵn.")
    review_dir = runs / "page-0001" / "review"
    review_dir.mkdir()
    (review_dir / "findings.json").write_text(
        json.dumps({"findings": []}),
        encoding="utf-8",
    )

    run = EbookBuildService().build(
        runs,
        tmp_path / "book.epub",
        title="Sách thử",
        work_dir=tmp_path / "work",
        exclude_page_numbers=(2,),
        require_reviewed=True,
    )

    assert [page.page_number for page in run.assembly.page_runs] == [1]


def test_build_epub_rejects_unavailable_excluded_page(tmp_path: Path) -> None:
    """A typo in page exclusions should fail instead of being ignored."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Nội dung.")

    with pytest.raises(EbookBuildError, match="excluded pages are not available"):
        EbookBuildService().build(
            runs,
            tmp_path / "book.epub",
            title="Sách thử",
            work_dir=tmp_path / "work",
            exclude_page_numbers=(99,),
        )


def test_build_epub_can_run_optional_epubcheck(
    monkeypatch: Any,
    tmp_path: Path,
) -> None:
    """The orchestrator should retain an EPUBCheck report when requested."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Nội dung.")
    jar = tmp_path / "epubcheck.jar"
    jar.write_bytes(b"jar")

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=0,
            stdout="valid\n",
            stderr="",
        )

    monkeypatch.setattr(
        "siftforge.ebook.epub.epubcheck.subprocess.run",
        fake_run,
    )
    run = EbookBuildService().build(
        runs,
        tmp_path / "book.epub",
        title="Sách thử",
        work_dir=tmp_path / "work",
        modified="2026-09-15T06:00:00Z",
        validate=True,
        epubcheck_jar=jar,
    )

    assert run.validation is not None
    assert run.validation.result.passed is True
    assert run.validation.report_path == (
        tmp_path / "work" / "reports" / "epubcheck.json"
    )
    assert run.validation.report_path.is_file()
    manifest = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert manifest["stages"]["epubcheck"]["requested"] is True
    assert manifest["stages"]["epubcheck"]["passed"] is True


def test_build_epub_auto_discovers_metadata_and_cover(tmp_path: Path) -> None:
    """Builds should consume runs-root metadata.json without repeated CLI flags."""
    runs = tmp_path / "runs" / "book"
    runs.mkdir(parents=True)
    _write_page_run(runs, 1, "Nội dung sách.")
    cover = runs / "cover.jpg"
    cover.write_bytes(b"fake-jpeg")
    (runs / "metadata.json").write_text(
        json.dumps(
            {
                "title": "Sách tự động",
                "language": "vi",
                "authors": ["Tác giả"],
                "publisher": "Nhà xuất bản",
                "cover": "cover.jpg",
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    run = EbookBuildService().build(
        runs,
        output,
        work_dir=tmp_path / "work",
        modified="2026-09-18T05:00:00Z",
    )

    assert run.epub_ready.metadata.title == "Sách tự động"
    assert run.epub_ready.cover_image_path is not None
    with zipfile.ZipFile(output) as archive:
        opf = archive.read("EPUB/package.opf").decode("utf-8")
        assert "Sách tự động" in opf
        assert "Tác giả" in opf
        assert "Nhà xuất bản" in opf
        assert 'properties="cover-image"' in opf
