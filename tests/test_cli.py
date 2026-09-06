"""Tests for local CLI configuration behavior."""

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
