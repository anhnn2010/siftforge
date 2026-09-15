"""Command-line entry point for SiftForge application workflows."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from siftforge.ebook.evaluation import (
    GoldenFixtureError,
    GoldenRegressionEvaluator,
)
from siftforge.ebook.extraction import EbookPageNormalizationError
from siftforge.ebook.pipeline import (
    EbookBookAssemblyError,
    EbookBookAssemblyService,
    EbookBookExtractionError,
    EbookBookExtractionProgress,
    EbookBuildError,
    EbookBuildService,
    EbookEpubPackageError,
    EbookEpubPackageService,
    EbookEpubReadyError,
    EbookEpubReadyService,
    EbookEpubValidationError,
    EbookEpubValidationService,
    EbookPDFBookEvidenceExtractionService,
    EbookPDFPageEvidenceExtractionService,
    EbookPDFPageExtractionService,
)
from siftforge.extraction.materializers import PDFPageMaterializationError
from siftforge.extraction.providers import (
    GeminiProvider,
    GeminiProviderConfig,
    GeminiProviderError,
)


def build_parser() -> argparse.ArgumentParser:
    """Build the SiftForge command-line parser."""
    parser = argparse.ArgumentParser(
        prog="siftforge",
        description="Reusable data extraction workflows.",
    )
    domains = parser.add_subparsers(dest="domain", required=True)

    ebook_parser = domains.add_parser(
        "ebook",
        help="Scanned-book and ebook workflows.",
    )
    ebook_actions = ebook_parser.add_subparsers(dest="action", required=True)

    extract_page = ebook_actions.add_parser(
        "extract-page",
        help="Extract one PDF page with a structured AI provider.",
    )
    extract_page.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Path to the input scanned PDF.",
    )
    extract_page.add_argument(
        "--page",
        required=True,
        type=int,
        help="One-based physical PDF page number.",
    )
    extract_page.add_argument(
        "--model",
        required=True,
        help="Explicit Gemini model ID selected for this smoke run.",
    )
    extract_page.add_argument(
        "--contract-version",
        choices=("4", "5"),
        default="5",
        help="Ebook extraction contract. Defaults to active page-evidence v5.",
    )
    extract_page.add_argument(
        "--run-dir",
        type=Path,
        default=None,
        help="Artifact directory. Defaults to runs/<pdf-stem>/page-NNNN.",
    )

    extract_book = ebook_actions.add_parser(
        "extract-book",
        help=(
            "Extract a PDF page range into resumable canonical v5 page runs."
        ),
    )
    extract_book.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Path to the input scanned PDF.",
    )
    extract_book.add_argument(
        "--model",
        required=True,
        help="Explicit Gemini model ID used for every selected page.",
    )
    extract_book.add_argument(
        "--runs-root",
        type=Path,
        default=None,
        help=(
            "Canonical page-run root. Defaults to runs/<pdf-stem>."
        ),
    )
    extract_book.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Inclusive first physical PDF page. Defaults to 1.",
    )
    extract_book.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Inclusive last physical PDF page. Defaults to the final page.",
    )
    extract_book.add_argument(
        "--force",
        action="store_true",
        help="Re-extract selected pages even when matching runs already exist.",
    )
    extract_book.add_argument(
        "--continue-on-error",
        action="store_true",
        help="Record failed pages and continue instead of stopping immediately.",
    )

    assemble_book = ebook_actions.add_parser(
        "assemble-book",
        help="Assemble existing v5 page runs into logical book structure.",
    )
    assemble_book.add_argument(
        "--runs-root",
        required=True,
        type=Path,
        help="Directory containing page-* v5 extraction run directories.",
    )
    assemble_book.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Assembly directory for structure and derived figure assets.",
    )

    render_xhtml = ebook_actions.add_parser(
        "render-xhtml",
        help="Render an assembled BookDocument as EPUB-ready XHTML.",
    )
    render_xhtml.add_argument(
        "--assembly",
        required=True,
        type=Path,
        help="Book assembly directory containing structure/book.json.",
    )
    render_xhtml.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Output directory for semantic XHTML, CSS, and assets.",
    )
    render_xhtml.add_argument(
        "--title",
        required=True,
        help="Book title used by the semantic XHTML document.",
    )
    render_xhtml.add_argument(
        "--language",
        default=None,
        help="Optional BCP 47 book language, for example vi or en.",
    )
    render_xhtml.add_argument(
        "--author",
        default=None,
        help="Optional book author metadata.",
    )

    package_epub = ebook_actions.add_parser(
        "package-epub",
        help="Package EPUB-ready XHTML artifacts into a final EPUB 3 file.",
    )
    package_epub.add_argument(
        "--epub-ready",
        required=True,
        type=Path,
        help="Directory produced by the render-xhtml command.",
    )
    package_epub.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination .epub file.",
    )
    package_epub.add_argument(
        "--identifier",
        default=None,
        help="Optional publication identifier. Defaults to a stable UUID URN.",
    )
    package_epub.add_argument(
        "--modified",
        default=None,
        help=(
            "Optional EPUB UTC modified timestamp "
            "(YYYY-MM-DDTHH:MM:SSZ)."
        ),
    )

    build_epub = ebook_actions.add_parser(
        "build-epub",
        help=(
            "Build a final EPUB from existing page runs through all "
            "provider-free stages."
        ),
    )
    build_epub.add_argument(
        "--runs-root",
        required=True,
        type=Path,
        help="Directory containing canonical page-* extraction runs.",
    )
    build_epub.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination final .epub file.",
    )
    build_epub.add_argument(
        "--title",
        required=True,
        help="Book title used by semantic XHTML and EPUB metadata.",
    )
    build_epub.add_argument(
        "--language",
        default=None,
        help="Optional BCP 47 book language, for example vi or en.",
    )
    build_epub.add_argument(
        "--author",
        default=None,
        help="Optional book author metadata.",
    )
    build_epub.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help=(
            "Derived-artifact workspace. Defaults to a sibling "
            "<runs-root-name>-build directory."
        ),
    )
    build_epub.add_argument(
        "--identifier",
        default=None,
        help="Optional publication identifier. Defaults to a stable UUID URN.",
    )
    build_epub.add_argument(
        "--modified",
        default=None,
        help=(
            "Optional EPUB UTC modified timestamp "
            "(YYYY-MM-DDTHH:MM:SSZ)."
        ),
    )
    build_epub.add_argument(
        "--validate",
        action="store_true",
        help="Run EPUBCheck after packaging the EPUB.",
    )
    build_epub.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=None,
        help=(
            "EPUBCheck JAR used with --validate. Defaults to EPUBCHECK_JAR."
        ),
    )
    build_epub.add_argument(
        "--java-command",
        default="java",
        help="Java executable used for EPUBCheck. Defaults to java.",
    )
    build_epub.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="EPUBCheck timeout in seconds. Defaults to 120.",
    )
    build_epub.add_argument(
        "--epubcheck-report",
        type=Path,
        default=None,
        help=(
            "Optional EPUBCheck JSON report. With --validate, defaults to "
            "<work-dir>/reports/epubcheck.json."
        ),
    )

    validate_epub = ebook_actions.add_parser(
        "validate-epub",
        help="Validate a final EPUB archive with the official EPUBCheck JAR.",
    )
    validate_epub.add_argument(
        "--epub",
        required=True,
        type=Path,
        help="EPUB archive to validate.",
    )
    validate_epub.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=None,
        help=(
            "Path to epubcheck.jar. Defaults to the EPUBCHECK_JAR "
            "environment variable."
        ),
    )
    validate_epub.add_argument(
        "--java-command",
        default="java",
        help="Java executable used to launch EPUBCheck. Defaults to java.",
    )
    validate_epub.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="Validation timeout in seconds. Defaults to 120.",
    )
    validate_epub.add_argument(
        "--report",
        type=Path,
        default=None,
        help="Optional JSON report path for CI or artifact retention.",
    )

    evaluate_golden = ebook_actions.add_parser(
        "evaluate-golden",
        help="Evaluate real-run ebook golden fixtures and report regressions.",
    )
    evaluate_golden.add_argument(
        "--fixtures",
        required=True,
        type=Path,
        help="Golden fixture root containing page-* directories.",
    )
    evaluate_golden.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Report format. Defaults to compact text.",
    )
    evaluate_golden.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Optional report file. Without it, print to stdout.",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the SiftForge command-line interface.

    Args:
        argv: Optional explicit arguments, excluding executable name.

    Returns:
        Process exit status.
    """
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.domain == "ebook" and args.action == "extract-page":
        return _run_ebook_extract_page(args)
    if args.domain == "ebook" and args.action == "extract-book":
        return _run_ebook_extract_book(args)
    if args.domain == "ebook" and args.action == "assemble-book":
        return _run_ebook_assemble_book(args)
    if args.domain == "ebook" and args.action == "render-xhtml":
        return _run_ebook_render_xhtml(args)
    if args.domain == "ebook" and args.action == "package-epub":
        return _run_ebook_package_epub(args)
    if args.domain == "ebook" and args.action == "build-epub":
        return _run_ebook_build_epub(args)
    if args.domain == "ebook" and args.action == "validate-epub":
        return _run_ebook_validate_epub(args)
    if args.domain == "ebook" and args.action == "evaluate-golden":
        return _run_ebook_evaluate_golden(args)

    parser.error("unsupported command")
    return 2


def _run_ebook_extract_page(args: argparse.Namespace) -> int:
    """Execute one-page Gemini extraction using the selected ebook contract."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print(
            "error: set GEMINI_API_KEY or GOOGLE_API_KEY before calling Gemini",
            file=sys.stderr,
        )
        return 2

    pdf_path = args.pdf.expanduser().resolve()
    run_dir = (
        args.run_dir.expanduser().resolve()
        if args.run_dir is not None
        else (
            Path.cwd()
            / "runs"
            / pdf_path.stem
            / f"page-{args.page:04d}"
        ).resolve()
    )

    provider = GeminiProvider(
        GeminiProviderConfig(
            model=args.model,
            temperature=0.0,
        )
    )

    try:
        if args.contract_version == "4":
            return _run_ebook_extract_page_v4(
                provider=provider,
                pdf_path=pdf_path,
                page_number=args.page,
                run_dir=run_dir,
            )
        return _run_ebook_extract_page_v5(
            provider=provider,
            pdf_path=pdf_path,
            page_number=args.page,
            run_dir=run_dir,
        )
    except (
        FileNotFoundError,
        ValueError,
        PDFPageMaterializationError,
        GeminiProviderError,
        EbookPageNormalizationError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2


def _run_ebook_extract_page_v5(
    *,
    provider: GeminiProvider,
    pdf_path: Path,
    page_number: int,
    run_dir: Path,
) -> int:
    """Run the active v5 page-evidence extraction path."""
    service = EbookPDFPageEvidenceExtractionService(provider)
    run = service.extract_page(
        pdf_path=pdf_path,
        page_number=page_number,
        run_dir=run_dir,
    )

    print(f"source:   {run.source.source_id}")
    print(f"asset:    {run.asset.path}")
    print(f"run:      {run.run_dir}")
    print("contract: v5 page evidence (prompt 5.2)")
    print(f"kind:     {run.page_evidence.page_kind_hint.value}")
    print(f"blocks:   {len(run.page_evidence.blocks)}")
    print("result: typed page evidence saved to normalized/page.json")
    return 0


def _run_ebook_extract_page_v4(
    *,
    provider: GeminiProvider,
    pdf_path: Path,
    page_number: int,
    run_dir: Path,
) -> int:
    """Run the retained v4 page-content path for regression comparison."""
    service = EbookPDFPageExtractionService(provider)
    run = service.extract_page(
        pdf_path=pdf_path,
        page_number=page_number,
        run_dir=run_dir,
    )

    print(f"source:   {run.source.source_id}")
    print(f"asset:    {run.asset.path}")
    print(f"run:      {run.run_dir}")
    print("contract: v4 page content")
    print(f"kind:     {run.page_content.page_kind.value}")
    print(f"blocks:   {len(run.page_content.blocks)}")
    print("result: typed page content saved to normalized/page.json")
    return 0


def _run_ebook_extract_book(args: argparse.Namespace) -> int:
    """Extract a PDF page range with resumable canonical v5 page runs."""
    if not (os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")):
        print(
            "error: set GEMINI_API_KEY or GOOGLE_API_KEY before calling Gemini",
            file=sys.stderr,
        )
        return 2

    pdf_path = args.pdf.expanduser().resolve()
    runs_root = (
        args.runs_root.expanduser().resolve()
        if args.runs_root is not None
        else (Path.cwd() / "runs" / pdf_path.stem).resolve()
    )
    provider = GeminiProvider(
        GeminiProviderConfig(
            model=args.model,
            temperature=0.0,
        )
    )
    service = EbookPDFBookEvidenceExtractionService(provider)

    def print_progress(progress: EbookBookExtractionProgress) -> None:
        """Print one compact line after each selected physical page."""
        result = progress.result
        suffix = (
            f" - {result.error_type}: {result.error_message}"
            if result.error_message
            else ""
        )
        print(
            f"[{progress.completed}/{progress.total}] "
            f"page {result.page_number:04d} {result.status.value}{suffix}"
        )

    try:
        run = service.extract_book(
            pdf_path,
            runs_root,
            model=args.model,
            start_page=args.start_page,
            end_page=args.end_page,
            force=args.force,
            continue_on_error=args.continue_on_error,
            progress_callback=print_progress,
        )
    except (FileNotFoundError, EbookBookExtractionError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"runs:      {run.runs_root}")
    print(f"extracted: {run.extracted_count}")
    print(f"reused:    {run.reused_count}")
    print(f"failed:    {run.failed_count}")
    print(f"manifest:  {run.manifest_path}")
    if run.total_usage:
        total_tokens = run.total_usage.get("total_token_count")
        if total_tokens is not None:
            print(f"tokens:    {total_tokens}")
    if run.failed_count:
        print("result: completed with failed pages")
        return 1
    print("result: resumable page extraction complete")
    return 0


def _run_ebook_assemble_book(args: argparse.Namespace) -> int:
    """Assemble persisted page evidence into book-level logical structure."""
    runs_root = args.runs_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    try:
        run = EbookBookAssemblyService().assemble(runs_root, output)
    except EbookBookAssemblyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"pages:    {len(run.page_runs)}")
    print(f"nodes:    {len(run.document.nodes)}")
    print(f"figures:  {len(run.figure_assets)}")
    print(f"output:   {run.output_dir}")
    print("result: logical book structure saved to structure/book.json")
    return 0


def _run_ebook_render_xhtml(args: argparse.Namespace) -> int:
    """Render one persisted book assembly into EPUB-ready XHTML artifacts."""
    assembly = args.assembly.expanduser().resolve()
    output = args.output.expanduser().resolve()
    try:
        run = EbookEpubReadyService().build(
            assembly,
            output,
            title=args.title,
            language=args.language,
            author=args.author,
        )
    except EbookEpubReadyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"nodes:    {len(run.document.nodes)}")
    print(f"assets:   {len(run.render.copied_assets)}")
    print(f"warnings: {len(run.warnings)}")
    print(f"output:   {run.output_dir}")
    print("result: EPUB-ready XHTML saved to text/content.xhtml")
    return 0


def _run_ebook_package_epub(args: argparse.Namespace) -> int:
    """Package persisted EPUB-ready XHTML into one EPUB 3 archive."""
    epub_ready = args.epub_ready.expanduser().resolve()
    output = args.output.expanduser().resolve()
    try:
        run = EbookEpubPackageService().build(
            epub_ready,
            output,
            identifier=args.identifier,
            modified=args.modified,
        )
    except EbookEpubPackageError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"epub:       {run.package.epub_path}")
    print(f"identifier: {run.package.identifier}")
    print(f"modified:   {run.package.modified}")
    print(f"manifest:   {run.package.manifest_item_count} items")
    print(f"toc:        {run.package.toc_entry_count} entries")
    print("result: structurally checked EPUB 3 package created")
    return 0


def _run_ebook_build_epub(args: argparse.Namespace) -> int:
    """Build a final EPUB from page runs through all provider-free stages."""
    runs_root = args.runs_root.expanduser().resolve()
    output = args.output.expanduser().resolve()
    jar_value = args.epubcheck_jar
    if args.validate and jar_value is None:
        env_value = os.getenv("EPUBCHECK_JAR")
        if env_value:
            jar_value = Path(env_value)
    if args.validate and jar_value is None:
        print(
            "error: --validate requires --epubcheck-jar or EPUBCHECK_JAR",
            file=sys.stderr,
        )
        return 2
    if not args.validate and args.epubcheck_report is not None:
        print(
            "error: --epubcheck-report requires --validate",
            file=sys.stderr,
        )
        return 2

    try:
        run = EbookBuildService().build(
            runs_root,
            output,
            title=args.title,
            language=args.language,
            author=args.author,
            work_dir=args.work_dir,
            identifier=args.identifier,
            modified=args.modified,
            validate=args.validate,
            epubcheck_jar=jar_value,
            java_command=args.java_command,
            timeout_seconds=args.timeout,
            report_path=args.epubcheck_report,
        )
    except EbookBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"pages:      {len(run.assembly.page_runs)}")
    print(f"nodes:      {len(run.assembly.document.nodes)}")
    print(f"figures:    {len(run.assembly.figure_assets)}")
    print(f"assets:     {len(run.epub_ready.render.copied_assets)}")
    print(f"work:       {run.work_dir}")
    print(f"epub:       {run.package.package.epub_path}")
    print(f"identifier: {run.package.package.identifier}")
    print(f"manifest:   {run.manifest_path}")
    if run.validation is None:
        print("epubcheck:  skipped")
        print("result:     EPUB build complete")
        return 0

    result = run.validation.result
    print(f"epubcheck:  {'PASS' if result.passed else 'FAIL'}")
    if run.validation.report_path is not None:
        print(f"report:     {run.validation.report_path}")
    build_result = (
        "EPUB build and validation complete"
        if result.passed
        else "EPUBCheck failed"
    )
    print(f"result:     {build_result}")
    return 0 if result.passed else 1


def _run_ebook_validate_epub(args: argparse.Namespace) -> int:
    """Validate one packaged EPUB with the external EPUBCheck JAR."""
    jar_value = args.epubcheck_jar
    if jar_value is None:
        env_value = os.getenv("EPUBCHECK_JAR")
        if env_value:
            jar_value = Path(env_value)
    if jar_value is None:
        print(
            "error: pass --epubcheck-jar or set EPUBCHECK_JAR",
            file=sys.stderr,
        )
        return 2

    try:
        run = EbookEpubValidationService().validate(
            args.epub.expanduser().resolve(),
            jar_value,
            java_command=args.java_command,
            timeout_seconds=args.timeout,
            report_path=args.report,
        )
    except EbookEpubValidationError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    result = run.result
    print(f"epub:     {result.epub_path}")
    print(f"jar:      {result.epubcheck_jar}")
    print(f"exit:     {result.exit_code}")
    print(f"duration: {result.duration_seconds:.3f}s")
    if run.report_path is not None:
        print(f"report:   {run.report_path}")
    print(f"result:   {'PASS' if result.passed else 'FAIL'}")
    if result.stdout:
        print("stdout:")
        print(result.stdout, end="" if result.stdout.endswith("\n") else "\n")
    if result.stderr:
        print("stderr:", file=sys.stderr)
        print(
            result.stderr,
            end="" if result.stderr.endswith("\n") else "\n",
            file=sys.stderr,
        )
    return 0 if result.passed else 1


def _run_ebook_evaluate_golden(args: argparse.Namespace) -> int:
    """Evaluate golden fixtures and emit a human or machine-readable report."""
    fixture_root = args.fixtures.expanduser().resolve()
    if not fixture_root.is_dir():
        print(
            f"error: fixture root is not a directory: {fixture_root}",
            file=sys.stderr,
        )
        return 2

    try:
        report = GoldenRegressionEvaluator().evaluate_root(fixture_root)
    except GoldenFixtureError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    rendered = report.to_json() if args.format == "json" else report.to_text()
    if args.output is None:
        print(rendered, end="")
    else:
        output = args.output.expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered, encoding="utf-8")
        print(f"report: {output}")

    return 0 if report.passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
