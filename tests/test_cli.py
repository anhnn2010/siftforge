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
    assert args.work_dir == Path("runs/book-build")
    assert args.validate is True
    assert args.epubcheck_jar == Path("tools/epubcheck.jar")

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

