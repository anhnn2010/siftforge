"""End-to-end provider-free EPUB build orchestration."""

from __future__ import annotations

import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path

from siftforge.ebook.review.status import (
    ReviewStatusError,
    ReviewStatusService,
)

from .book_assembly import (
    EbookBookAssemblyError,
    EbookBookAssemblyRun,
    EbookBookAssemblyService,
)
from .epub_package import (
    EbookEpubPackageError,
    EbookEpubPackageRun,
    EbookEpubPackageService,
)
from .epub_ready import (
    EbookEpubReadyError,
    EbookEpubReadyRun,
    EbookEpubReadyService,
)
from .epub_validation import (
    EbookEpubValidationError,
    EbookEpubValidationRun,
    EbookEpubValidationService,
)


class EbookBuildError(ValueError):
    """Raised when the end-to-end EPUB build workflow cannot complete."""


@dataclass(frozen=True, slots=True)
class EbookBuildRun:
    """Artifacts and stage results from one complete EPUB build."""

    runs_root: Path
    work_dir: Path
    assembly: EbookBookAssemblyRun
    epub_ready: EbookEpubReadyRun
    package: EbookEpubPackageRun
    validation: EbookEpubValidationRun | None
    manifest_path: Path


class EbookBuildService:
    """Build an EPUB from persisted page runs through isolated pipeline stages."""

    def __init__(self) -> None:
        """Initialize deterministic stage services used by the orchestrator."""
        self._assembly = EbookBookAssemblyService()
        self._epub_ready = EbookEpubReadyService()
        self._package = EbookEpubPackageService()
        self._validation = EbookEpubValidationService()

    def build(
        self,
        runs_root: str | Path,
        output_path: str | Path,
        *,
        title: str,
        language: str | None = None,
        author: str | None = None,
        work_dir: str | Path | None = None,
        identifier: str | None = None,
        modified: str | None = None,
        validate: bool = False,
        epubcheck_jar: str | Path | None = None,
        java_command: str = "java",
        timeout_seconds: float = 120.0,
        report_path: str | Path | None = None,
        require_reviewed: bool = False,
    ) -> EbookBuildRun:
        """Build one EPUB from existing page runs without calling a provider.

        Derived assembly and EPUB-ready directories are rebuilt from scratch on
        every invocation. This deliberately favors correctness over incremental
        caching so stale intermediate artifacts cannot leak into the final EPUB.

        Args:
            runs_root: Directory containing canonical ``page-*`` extraction runs.
            output_path: Destination final ``.epub`` archive.
            title: Publication title.
            language: Optional BCP 47 language tag.
            author: Optional author metadata.
            work_dir: Optional derived-artifact workspace. Defaults to a sibling
                ``<runs-root-name>-build`` directory.
            identifier: Optional publication identifier.
            modified: Optional deterministic EPUB modified timestamp.
            validate: Whether to run EPUBCheck after packaging.
            epubcheck_jar: EPUBCheck JAR path when validation is requested.
            java_command: Java executable used for EPUBCheck.
            timeout_seconds: EPUBCheck timeout in seconds.
            report_path: Optional EPUBCheck JSON report destination.
            require_reviewed: Fail unless every page has a current complete
                text-fidelity review.

        Returns:
            Typed results for every completed build stage.

        Raises:
            EbookBuildError: If configuration or any stage fails.
        """
        runs = Path(runs_root).expanduser().resolve()
        output = Path(output_path).expanduser().resolve()
        if not runs.is_dir():
            raise EbookBuildError(f"page-runs root is not a directory: {runs}")
        if not title.strip():
            raise EbookBuildError("book title must not be empty")
        if output.suffix.lower() != ".epub":
            raise EbookBuildError("EPUB output path must end with .epub")

        workspace = (
            Path(work_dir).expanduser().resolve()
            if work_dir is not None
            else (runs.parent / f"{runs.name}-build").resolve()
        )
        if workspace == runs:
            raise EbookBuildError("build work directory must differ from runs root")

        assembly_dir = workspace / "assembly"
        epub_ready_dir = workspace / "epub-ready"
        _reset_derived_directory(assembly_dir)
        _reset_derived_directory(epub_ready_dir)

        resolved_jar = _resolve_epubcheck_jar(
            validate=validate,
            epubcheck_jar=epubcheck_jar,
        )
        validation_report = _resolve_report_path(
            validate=validate,
            report_path=report_path,
            workspace=workspace,
        )

        if require_reviewed:
            try:
                ReviewStatusService().require_complete(runs)
            except ReviewStatusError as exc:
                raise EbookBuildError(str(exc)) from exc

        try:
            assembly = self._assembly.assemble(runs, assembly_dir)
            epub_ready = self._epub_ready.build(
                assembly_dir,
                epub_ready_dir,
                title=title,
                language=language,
                author=author,
            )
            package = self._package.build(
                epub_ready_dir,
                output,
                identifier=identifier,
                modified=modified,
            )
            validation = None
            if validate:
                if resolved_jar is None:
                    raise EbookBuildError(
                        "validation requires --epubcheck-jar or EPUBCHECK_JAR"
                    )
                validation = self._validation.validate(
                    package.package.epub_path,
                    resolved_jar,
                    java_command=java_command,
                    timeout_seconds=timeout_seconds,
                    report_path=validation_report,
                )
        except (
            EbookBookAssemblyError,
            EbookEpubReadyError,
            EbookEpubPackageError,
            EbookEpubValidationError,
        ) as exc:
            raise EbookBuildError(str(exc)) from exc

        manifest_path = _write_build_manifest(
            workspace=workspace,
            runs_root=runs,
            output_path=output,
            title=title,
            language=language,
            author=author,
            assembly=assembly,
            epub_ready=epub_ready,
            package=package,
            validation=validation,
        )
        return EbookBuildRun(
            runs_root=runs,
            work_dir=workspace,
            assembly=assembly,
            epub_ready=epub_ready,
            package=package,
            validation=validation,
            manifest_path=manifest_path,
        )


def _reset_derived_directory(path: Path) -> None:
    """Remove one derived-stage directory before recreating it empty."""
    if path.exists():
        if path.is_symlink():
            raise EbookBuildError(f"refusing to replace symlinked build path: {path}")
        if not path.is_dir():
            raise EbookBuildError(f"build stage path is not a directory: {path}")
        shutil.rmtree(path)
    path.mkdir(parents=True, exist_ok=True)


def _resolve_epubcheck_jar(
    *,
    validate: bool,
    epubcheck_jar: str | Path | None,
) -> Path | None:
    """Resolve explicit or environment EPUBCheck configuration when requested."""
    if not validate:
        return None
    value: str | Path | None = epubcheck_jar
    if value is None:
        env_value = os.getenv("EPUBCHECK_JAR")
        if env_value:
            value = env_value
    if value is None:
        return None
    return Path(value).expanduser().resolve()


def _resolve_report_path(
    *,
    validate: bool,
    report_path: str | Path | None,
    workspace: Path,
) -> Path | None:
    """Choose a stable default EPUBCheck report path for validated builds."""
    if not validate:
        if report_path is not None:
            raise EbookBuildError(
                "EPUBCheck report requires validation to be enabled"
            )
        return None
    if report_path is not None:
        return Path(report_path).expanduser().resolve()
    return workspace / "reports" / "epubcheck.json"


def _write_build_manifest(
    *,
    workspace: Path,
    runs_root: Path,
    output_path: Path,
    title: str,
    language: str | None,
    author: str | None,
    assembly: EbookBookAssemblyRun,
    epub_ready: EbookEpubReadyRun,
    package: EbookEpubPackageRun,
    validation: EbookEpubValidationRun | None,
) -> Path:
    """Persist inspectable provenance for the complete orchestration run."""
    workspace.mkdir(parents=True, exist_ok=True)
    manifest = workspace / "build-manifest.json"
    payload = {
        "format": "siftforge-ebook-build",
        "policy": "clean-derived-stages",
        "runs_root": str(runs_root),
        "work_dir": str(workspace),
        "output_epub": str(output_path),
        "title": title,
        "language": language,
        "author": author,
        "stages": {
            "assembly": {
                "output": "assembly",
                "pages": len(assembly.page_runs),
                "nodes": len(assembly.document.nodes),
                "figures": len(assembly.figure_assets),
            },
            "epub_ready": {
                "output": "epub-ready",
                "nodes": len(epub_ready.document.nodes),
                "assets": len(epub_ready.render.copied_assets),
                "warnings": list(epub_ready.warnings),
            },
            "package": {
                "identifier": package.package.identifier,
                "modified": package.package.modified,
                "manifest_items": package.package.manifest_item_count,
                "toc_entries": package.package.toc_entry_count,
            },
            "epubcheck": _validation_manifest(validation),
        },
    }
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _validation_manifest(
    validation: EbookEpubValidationRun | None,
) -> dict[str, object]:
    """Serialize optional EPUBCheck status without duplicating its full report."""
    if validation is None:
        return {"requested": False, "passed": None, "report": None}
    report = (
        str(validation.report_path)
        if validation.report_path is not None
        else None
    )
    return {
        "requested": True,
        "passed": validation.result.passed,
        "exit_code": validation.result.exit_code,
        "report": report,
    }
