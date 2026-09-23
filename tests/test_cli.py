"""Tests for local CLI configuration behavior."""

import json
from pathlib import Path

import pytest

from siftforge.cli import build_parser, main


def test_extract_page_requires_gemini_api_key(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CLI should fail before network access when no API key is configured."""
    del tmp_path
    monkeypatch.delenv("SIFTFORGE_GEMINI_FREE_API_KEY", raising=False)
    monkeypatch.delenv("SIFTFORGE_GEMINI_PAID_API_KEY", raising=False)
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    status = main(
        [
            "ebook",
            "extract-page",
            "--pdf",
            "missing.pdf",
            "--page",
            "1",
            "--model",
            "test-model",
        ]
    )

    assert status == 2


def test_extract_page_defaults_to_v5_contract() -> None:
    """The canonical smoke command should use page-evidence v5 by default."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "extract-page",
            "--pdf",
            "book.pdf",
            "--page",
            "18",
            "--model",
            "gemini-3.6-flash",
        ]
    )

    assert args.contract_version == "5"


def test_extract_page_defaults_to_free_only_routing() -> None:
    """Paid fallback should require explicit opt-in on AI extraction commands."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "extract-page",
            "--pdf",
            "book.pdf",
            "--page",
            "18",
            "--model",
            "gemini-3.6-flash",
        ]
    )

    assert args.routing_policy == "free-only"


def test_extract_book_accepts_explicit_paid_fallback_policy() -> None:
    """Whole-book extraction should expose explicit paid fallback opt-in."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "extract-book",
            "--pdf",
            "book.pdf",
            "--model",
            "gemini-3.6-flash",
            "--routing-policy",
            "free-then-paid",
        ]
    )

    assert args.routing_policy == "free-then-paid"


def test_extract_page_allows_explicit_v4_regression_contract() -> None:
    """A/B regression runs should retain an explicit v4 escape hatch."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "extract-page",
            "--pdf",
            "book.pdf",
            "--page",
            "18",
            "--model",
            "gemini-3.6-flash",
            "--contract-version",
            "4",
        ]
    )

    assert args.contract_version == "4"


def test_cli_evaluate_golden_text_report(capsys: pytest.CaptureFixture[str]) -> None:
    """Golden evaluation should be runnable without provider credentials."""
    exit_code = main(
        [
            "ebook",
            "evaluate-golden",
            "--fixtures",
            "tests/fixtures/ebook/golden/v5",
        ]
    )

    captured = capsys.readouterr()
    assert exit_code == 0
    assert "result: PASS" in captured.out
    assert "checks: 22/22 passed" in captured.out
    assert captured.err == ""


def test_cli_evaluate_golden_can_write_json_report(tmp_path: Path) -> None:
    """CI can persist the machine-readable report as an artifact."""
    output = tmp_path / "golden-report.json"
    exit_code = main(
        [
            "ebook",
            "evaluate-golden",
            "--fixtures",
            "tests/fixtures/ebook/golden/v5",
            "--format",
            "json",
            "--output",
            str(output),
        ]
    )

    payload = json.loads(output.read_text(encoding="utf-8"))
    assert exit_code == 0
    assert payload["passed"] is True
    assert payload["summary"]["cases_total"] == 9



def test_extract_book_parser_accepts_resume_range_options() -> None:
    """Whole-book extraction should expose safe resume and page-range controls."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "extract-book",
            "--pdf",
            "book.pdf",
            "--model",
            "gemini-3.6-flash",
            "--runs-root",
            "runs/book",
            "--start-page",
            "10",
            "--end-page",
            "20",
            "--continue-on-error",
        ]
    )

    assert args.pdf == Path("book.pdf")
    assert args.model == "gemini-3.6-flash"
    assert args.runs_root == Path("runs/book")
    assert args.start_page == 10
    assert args.end_page == 20
    assert args.force is False
    assert args.continue_on_error is True


def test_convert_pdf_parser_accepts_full_pipeline_options() -> None:
    """One command should compose resumable extraction and EPUB building."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "convert-pdf",
            "--pdf",
            "book.pdf",
            "--model",
            "gemini-3.6-flash",
            "--output",
            "dist/book.epub",
            "--title",
            "18 Năm Kim Cương",
            "--runs-root",
            "runs/book",
            "--work-dir",
            "runs/book-build",
            "--continue-on-error",
        ]
    )

    assert args.pdf == Path("book.pdf")
    assert args.model == "gemini-3.6-flash"
    assert args.output == Path("dist/book.epub")
    assert args.title == "18 Năm Kim Cương"
    assert args.runs_root == Path("runs/book")
    assert args.work_dir == Path("runs/book-build")
    assert args.force_extract is False
    assert args.continue_on_error is True

def test_assemble_book_parser_requires_runs_root_and_output() -> None:
    """Book assembly should be exposed as a provider-free ebook CLI action."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "assemble-book",
            "--runs-root",
            "runs/book",
            "--output",
            "runs/book-assembly",
        ]
    )

    assert args.runs_root == Path("runs/book")
    assert args.output == Path("runs/book-assembly")


def test_render_xhtml_parser_accepts_assembly_metadata() -> None:
    """EPUB-ready XHTML should be exposed as a provider-free CLI action."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "render-xhtml",
            "--assembly",
            "runs/book-assembly",
            "--output",
            "runs/book-xhtml",
            "--title",
            "18 Năm Kim Cương",
            "--language",
            "vi",
            "--author",
            "Hồ Thị Hải Âu",
        ]
    )

    assert args.assembly == Path("runs/book-assembly")
    assert args.output == Path("runs/book-xhtml")
    assert args.title == "18 Năm Kim Cương"
    assert args.language == "vi"
    assert args.author == "Hồ Thị Hải Âu"


def test_package_epub_parser_accepts_ready_root_and_metadata() -> None:
    """Final EPUB packaging should be a provider-free ebook CLI action."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "package-epub",
            "--epub-ready",
            "runs/book-xhtml",
            "--output",
            "dist/book.epub",
            "--identifier",
            "urn:isbn:9780000000000",
            "--modified",
            "2026-09-11T10:00:00Z",
        ]
    )

    assert args.epub_ready == Path("runs/book-xhtml")
    assert args.output == Path("dist/book.epub")
    assert args.identifier == "urn:isbn:9780000000000"
    assert args.modified == "2026-09-11T10:00:00Z"


def test_build_epub_parser_accepts_end_to_end_options() -> None:
    """One command should orchestrate all provider-free EPUB build stages."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "build-epub",
            "--runs-root",
            "runs/book",
            "--output",
            "dist/book.epub",
            "--title",
            "18 Năm Kim Cương",
            "--language",
            "vi",
            "--author",
            "Hồ Thị Hải Âu",
            "--exclude-pages",
            "7-10,14",
            "--work-dir",
            "runs/book-build",
            "--validate",
            "--epubcheck-jar",
            "tools/epubcheck.jar",
        ]
    )

    assert args.runs_root == Path("runs/book")
    assert args.output == Path("dist/book.epub")
    assert args.title == "18 Năm Kim Cương"
    assert args.language == "vi"
    assert args.author == "Hồ Thị Hải Âu"
    assert args.exclude_pages == "7-10,14"
    assert args.work_dir == Path("runs/book-build")
    assert args.validate is True
    assert args.epubcheck_jar == Path("tools/epubcheck.jar")


def test_build_epub_rejects_invalid_exclude_page_range(
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Malformed physical-page ranges should fail before build discovery."""
    status = main(
        [
            "ebook",
            "build-epub",
            "--runs-root",
            "runs/book",
            "--output",
            "dist/book.epub",
            "--exclude-pages",
            "10-7",
        ]
    )

    assert status == 2
    assert "invalid --exclude-pages" in capsys.readouterr().err

def test_validate_epub_parser_accepts_external_tool_configuration() -> None:
    """EPUBCheck validation should remain an explicit provider-free stage."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "validate-epub",
            "--epub",
            "dist/book.epub",
            "--epubcheck-jar",
            "tools/epubcheck.jar",
            "--java-command",
            "java",
            "--timeout",
            "90",
            "--report",
            "artifacts/epubcheck.json",
        ]
    )

    assert args.epub == Path("dist/book.epub")
    assert args.epubcheck_jar == Path("tools/epubcheck.jar")
    assert args.java_command == "java"
    assert args.timeout == 90.0
    assert args.report == Path("artifacts/epubcheck.json")



def test_review_text_parser_accepts_local_ocr_options() -> None:
    """Text review should expose page range and local Tesseract controls."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "review-text",
            "--runs-root",
            "runs/book",
            "--output",
            "runs/book/review",
            "--start-page",
            "13",
            "--end-page",
            "152",
            "--ocr-language",
            "vie+eng",
            "--ocr-psm",
            "3",
            "--force",
        ]
    )

    assert args.runs_root == Path("runs/book")
    assert args.output == Path("runs/book/review")
    assert args.start_page == 13
    assert args.end_page == 152
    assert args.ocr_language == "vie+eng"
    assert args.ocr_psm == 3
    assert args.force is True
    assert args.quiet is False


def test_review_text_parser_accepts_quiet_progress_mode() -> None:
    """Long review runs should allow explicit progress suppression."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "review-text",
            "--runs-root",
            "runs/book",
            "--quiet",
        ]
    )

    assert args.quiet is True


def test_import_review_parser_accepts_exported_resolutions() -> None:
    """Human review exports should have a dedicated provider-free CLI step."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "import-review",
            "--runs-root",
            "runs/book",
            "--resolutions",
            "review.json",
        ]
    )

    assert args.runs_root == Path("runs/book")
    assert args.resolutions == Path("review.json")


def test_build_epub_parser_accepts_metadata_without_title_flag() -> None:
    """Persisted book metadata should make repeated title flags unnecessary."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "build-epub",
            "--runs-root",
            "runs/book",
            "--output",
            "dist/book.epub",
            "--metadata",
            "runs/book/metadata.json",
            "--cover",
            "covers/replacement.jpg",
        ]
    )

    assert args.title is None
    assert args.metadata == Path("runs/book/metadata.json")
    assert args.cover == Path("covers/replacement.jpg")


def test_prepare_proof_parser_exposes_protected_workspace_options() -> None:
    """Proof preparation should require generated input and explicit output."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "prepare-proof",
            "--epub-ready",
            "runs/book-build/epub-ready",
            "--output",
            "runs/book-build/proof",
        ]
    )

    assert args.epub_ready == Path("runs/book-build/epub-ready")
    assert args.output == Path("runs/book-build/proof")
    assert args.force is False


def test_package_epub_parser_accepts_human_proof_source() -> None:
    """Final packaging should accept proof as an alternative to generated XHTML."""
    parser = build_parser()
    args = parser.parse_args(
        [
            "ebook",
            "package-epub",
            "--proof",
            "runs/book-build/proof",
            "--output",
            "dist/book.epub",
        ]
    )

    assert args.proof == Path("runs/book-build/proof")
    assert args.epub_ready is None
    assert args.output == Path("dist/book.epub")
