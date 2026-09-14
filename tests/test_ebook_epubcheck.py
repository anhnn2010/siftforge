"""Tests for external EPUBCheck standards validation."""

import hashlib
import json
import subprocess
from pathlib import Path

import pytest

from siftforge.ebook.epub import EpubCheckExecutionError, EpubCheckRunner
from siftforge.ebook.pipeline import EbookEpubValidationService


def _write_inputs(tmp_path: Path) -> tuple[Path, Path]:
    """Create small placeholder files for subprocess-free validator tests."""
    epub = tmp_path / "book.epub"
    jar = tmp_path / "epubcheck.jar"
    epub.write_bytes(b"epub-bytes")
    jar.write_bytes(b"jar-bytes")
    return epub, jar


def test_epubcheck_runner_captures_success(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """A zero EPUBCheck exit code should produce a passing result."""
    epub, jar = _write_inputs(tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        command = args[0]
        return subprocess.CompletedProcess(
            args=command,
            returncode=0,
            stdout="No errors or warnings detected.\n",
            stderr="",
        )

    monkeypatch.setattr(
        "siftforge.ebook.epub.epubcheck.subprocess.run",
        fake_run,
    )
    result = EpubCheckRunner().validate(epub, jar)

    assert result.passed is True
    assert result.exit_code == 0
    assert result.command == ("java", "-jar", str(jar), str(epub))
    assert result.stdout == "No errors or warnings detected.\n"
    assert result.epub_sha256 == hashlib.sha256(b"epub-bytes").hexdigest()
    assert result.epubcheck_jar_sha256 == hashlib.sha256(b"jar-bytes").hexdigest()


def test_epubcheck_runner_preserves_validation_failure(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Standards errors should be a failed result, not an execution exception."""
    epub, jar = _write_inputs(tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del kwargs
        return subprocess.CompletedProcess(
            args=args[0],
            returncode=1,
            stdout="",
            stderr="ERROR(RSC-005): invalid XHTML\n",
        )

    monkeypatch.setattr(
        "siftforge.ebook.epub.epubcheck.subprocess.run",
        fake_run,
    )
    result = EpubCheckRunner().validate(epub, jar)

    assert result.passed is False
    assert result.exit_code == 1
    assert "RSC-005" in result.stderr


def test_epubcheck_runner_rejects_missing_jar(tmp_path: Path) -> None:
    """Validation should fail clearly when EPUBCheck is not configured."""
    epub = tmp_path / "book.epub"
    epub.write_bytes(b"epub")

    with pytest.raises(EpubCheckExecutionError, match="JAR does not exist"):
        EpubCheckRunner().validate(epub, tmp_path / "missing.jar")


def test_epubcheck_runner_wraps_missing_java(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """Missing Java should be reported as a tool execution failure."""
    epub, jar = _write_inputs(tmp_path)

    def fake_run(*args: object, **kwargs: object) -> subprocess.CompletedProcess[str]:
        del args, kwargs
        raise FileNotFoundError("java")

    monkeypatch.setattr(
        "siftforge.ebook.epub.epubcheck.subprocess.run",
        fake_run,
    )

    with pytest.raises(EpubCheckExecutionError, match="Java command was not found"):
        EpubCheckRunner(java_command="missing-java").validate(epub, jar)


def test_epubcheck_service_writes_json_report(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
) -> None:
    """CI should be able to retain an exact external validation artifact."""
    epub, jar = _write_inputs(tmp_path)

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
    report = tmp_path / "reports" / "epubcheck.json"
    run = EbookEpubValidationService().validate(
        epub,
        jar,
        report_path=report,
    )

    payload = json.loads(report.read_text(encoding="utf-8"))
    assert run.report_path == report.resolve()
    assert payload["tool"] == "epubcheck"
    assert payload["passed"] is True
    assert payload["exit_code"] == 0
    assert payload["stdout"] == "valid\n"
