"""Tests for one-command scanned-PDF to EPUB orchestration."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace

from siftforge.ebook.pipeline import EbookPdfToEpubService


class DummyExtractor:
    """Placeholder extractor because injected services own the test behavior."""

    def extract(self, task: object) -> object:
        """Fail if the placeholder is accidentally used."""
        del task
        raise AssertionError("dummy extractor should not be called")


@dataclass
class FakeExtractionRun:
    """Minimal extraction result surface required by the orchestrator."""

    runs_root: Path
    manifest_path: Path
    failed_count: int
    extracted_count: int = 0
    reused_count: int = 0
    total_usage: dict[str, int] | None = None

    def __post_init__(self) -> None:
        """Populate stable page results and usage defaults."""
        self.page_results = (object(), object())
        if self.total_usage is None:
            self.total_usage = {"total_token_count": 123}


class FakeExtractionService:
    """Return a configured extraction result and record full-book options."""

    def __init__(self, run: FakeExtractionRun) -> None:
        """Store the result returned by every invocation."""
        self.run = run
        self.calls: list[dict[str, object]] = []

    def extract_book(
        self, pdf: Path, root: Path, **kwargs: object
    ) -> FakeExtractionRun:
        """Record orchestration arguments without performing provider work."""
        self.calls.append({"pdf": pdf, "root": root, **kwargs})
        return self.run


class FakeBuildService:
    """Return a minimal provider-free build result and record calls."""

    def __init__(self, workspace: Path, epub: Path) -> None:
        """Configure stable output paths."""
        self.workspace = workspace
        self.epub = epub
        self.calls: list[dict[str, object]] = []

    def build(self, runs_root: Path, output: Path, **kwargs: object) -> object:
        """Record the build and return the surface used by the manifest writer."""
        self.calls.append({"runs_root": runs_root, "output": output, **kwargs})
        return SimpleNamespace(
            manifest_path=self.workspace / "build-manifest.json",
            package=SimpleNamespace(
                package=SimpleNamespace(epub_path=self.epub),
            ),
            validation=None,
        )


def test_pdf_to_epub_builds_only_after_complete_extraction(tmp_path: Path) -> None:
    """A successful full-PDF extraction should flow into the provider-free build."""
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fixture")
    runs = tmp_path / "runs"
    extraction_manifest = runs / "book-extraction.json"
    extraction = FakeExtractionRun(
        runs_root=runs,
        manifest_path=extraction_manifest,
        failed_count=0,
        extracted_count=1,
        reused_count=1,
    )
    extraction_service = FakeExtractionService(extraction)
    workspace = tmp_path / "work"
    epub = tmp_path / "book.epub"
    build_service = FakeBuildService(workspace, epub)
    service = EbookPdfToEpubService(
        DummyExtractor(),
        extraction_service=extraction_service,  # type: ignore[arg-type]
        build_service=build_service,  # type: ignore[arg-type]
    )

    run = service.convert(
        pdf,
        epub,
        model="fixture-model",
        title="Fixture Book",
        runs_root=runs,
        work_dir=workspace,
    )

    assert run.complete is True
    assert len(extraction_service.calls) == 1
    assert "start_page" not in extraction_service.calls[0]
    assert "end_page" not in extraction_service.calls[0]
    assert len(build_service.calls) == 1
    payload = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "complete"
    assert payload["extraction"]["failed"] == 0
    assert payload["build"]["attempted"] is True


def test_pdf_to_epub_skips_build_when_any_page_failed(tmp_path: Path) -> None:
    """Continue-on-error may finish extraction without publishing a partial EPUB."""
    pdf = tmp_path / "book.pdf"
    pdf.write_bytes(b"fixture")
    runs = tmp_path / "runs"
    extraction = FakeExtractionRun(
        runs_root=runs,
        manifest_path=runs / "book-extraction.json",
        failed_count=1,
        extracted_count=1,
        reused_count=0,
    )
    extraction_service = FakeExtractionService(extraction)
    workspace = tmp_path / "work"
    build_service = FakeBuildService(workspace, tmp_path / "book.epub")
    service = EbookPdfToEpubService(
        DummyExtractor(),
        extraction_service=extraction_service,  # type: ignore[arg-type]
        build_service=build_service,  # type: ignore[arg-type]
    )

    run = service.convert(
        pdf,
        tmp_path / "book.epub",
        model="fixture-model",
        title="Fixture Book",
        runs_root=runs,
        work_dir=workspace,
        continue_on_error=True,
    )

    assert run.complete is False
    assert run.build is None
    assert build_service.calls == []
    payload = json.loads(run.manifest_path.read_text(encoding="utf-8"))
    assert payload["status"] == "incomplete"
    assert payload["extraction"]["failed"] == 1
    assert payload["build"]["attempted"] is False
