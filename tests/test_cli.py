"""Tests for local CLI configuration behavior."""

from pathlib import Path

import pytest

from siftforge.cli import main


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
