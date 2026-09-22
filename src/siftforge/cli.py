"""Command-line entry point for SiftForge application workflows."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from siftforge.ebook.metadata_extraction import (
    EbookMetadataExtractionError,
    EbookPDFMetadataExtractionService,
)
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
    EbookProofError,
    RecitationOcrRecoveryError,
    EbookProofService,
    EbookEpubValidationService,
    EbookPDFBookEvidenceExtractionService,
    EbookPDFPageEvidenceExtractionService,
    EbookPDFPageExtractionService,
    EbookPdfToEpubError,
    EbookPdfToEpubService,
)
from siftforge.ebook.review import (
    EbookTextReviewService,
    LocalOcrError,
    ReviewFilterConfig,
    ReviewResolutionError,
    ReviewStatusError,
    ReviewStatusService,
    TesseractOcrConfig,
    TesseractOcrEngine,
    TextReviewError,
    import_review_resolutions,
    review_status_to_dict,
)
from siftforge.extraction.materializers import PDFPageMaterializationError
from siftforge.extraction.providers import (
    Extractor,
    GeminiProvider,
    GeminiProviderConfig,
    GeminiProviderError,
)
from siftforge.extraction.runtime import (
    CostTier,
    ExtractionRoute,
    ExtractionRoutingError,
    FreeFirstRouter,
    GeminiFailureClassifier,
    RoutingPolicy,
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
    _add_gemini_routing_arguments(extract_page)
    _add_recitation_recovery_arguments(extract_page)

    extract_metadata = ebook_actions.add_parser(
        "extract-metadata",
        help=(
            "Suggest book metadata and extract a detected cover from PDF "
            "front matter."
        ),
    )
    extract_metadata.add_argument(
        "--pdf", required=True, type=Path, help="Path to the input scanned PDF."
    )
    extract_metadata.add_argument(
        "--model", required=True, help="Explicit Gemini model ID."
    )
    extract_metadata.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Destination metadata.json. Defaults to runs/<pdf-stem>/metadata.json.",
    )
    extract_metadata.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="First front-matter page. Defaults to 1.",
    )
    extract_metadata.add_argument(
        "--end-page", type=int, default=8, help="Last front-matter page. Defaults to 8."
    )
    _add_gemini_routing_arguments(extract_metadata)

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
    _add_gemini_routing_arguments(extract_book)
    _add_recitation_recovery_arguments(extract_book)


    convert_pdf = ebook_actions.add_parser(
        "convert-pdf",
        help=(
            "Resume full-PDF extraction and build a final EPUB in one command."
        ),
    )
    convert_pdf.add_argument(
        "--pdf",
        required=True,
        type=Path,
        help="Path to the input scanned PDF.",
    )
    convert_pdf.add_argument(
        "--model",
        required=True,
        help="Explicit Gemini model ID used for page extraction.",
    )
    convert_pdf.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination final .epub file.",
    )
    convert_pdf.add_argument(
        "--title",
        default=None,
        help="Optional title override. Otherwise read from metadata.json.",
    )
    convert_pdf.add_argument(
        "--runs-root",
        type=Path,
        default=None,
        help="Canonical page-run root. Defaults to runs/<pdf-stem>.",
    )
    convert_pdf.add_argument(
        "--language",
        default=None,
        help="Optional BCP 47 book language, for example vi or en.",
    )
    convert_pdf.add_argument(
        "--author",
        default=None,
        help="Optional single-author override.",
    )
    convert_pdf.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help=(
            "Optional metadata.json with title, authors, publisher, ISBN, "
            "description, subjects, series, and cover."
        ),
    )
    convert_pdf.add_argument(
        "--cover",
        type=Path,
        default=None,
        help="Optional cover image override (JPEG, PNG, GIF, or SVG).",
    )
    convert_pdf.add_argument(
        "--work-dir",
        type=Path,
        default=None,
        help=(
            "Derived-artifact workspace. Defaults to a sibling "
            "<runs-root-name>-build directory."
        ),
    )
    convert_pdf.add_argument(
        "--force-extract",
        action="store_true",
        help="Re-extract every PDF page even when matching runs exist.",
    )
    convert_pdf.add_argument(
        "--continue-on-error",
        action="store_true",
        help=(
            "Continue page extraction after failures; skip final EPUB build "
            "when any page still fails."
        ),
    )
    convert_pdf.add_argument(
        "--identifier",
        default=None,
        help="Optional publication identifier. Defaults to a stable UUID URN.",
    )
    convert_pdf.add_argument(
        "--modified",
        default=None,
        help=(
            "Optional EPUB UTC modified timestamp "
            "(YYYY-MM-DDTHH:MM:SSZ)."
        ),
    )
    convert_pdf.add_argument(
        "--validate",
        action="store_true",
        help="Run EPUBCheck after packaging the EPUB.",
    )
    convert_pdf.add_argument(
        "--epubcheck-jar",
        type=Path,
        default=None,
        help=(
            "EPUBCheck JAR used with --validate. Defaults to EPUBCHECK_JAR."
        ),
    )
    convert_pdf.add_argument(
        "--java-command",
        default="java",
        help="Java executable used for EPUBCheck. Defaults to java.",
    )
    convert_pdf.add_argument(
        "--timeout",
        type=float,
        default=120.0,
        help="EPUBCheck timeout in seconds. Defaults to 120.",
    )
    convert_pdf.add_argument(
        "--epubcheck-report",
        type=Path,
        default=None,
        help=(
            "Optional EPUBCheck JSON report. With --validate, defaults to "
            "<work-dir>/reports/epubcheck.json."
        ),
    )
    _add_gemini_routing_arguments(convert_pdf)
    _add_recitation_recovery_arguments(convert_pdf)

    review_text = ebook_actions.add_parser(
        "review-text",
        help=(
            "Compare normalized Gemini text with local OCR and produce a "
            "human-readable fidelity review report."
        ),
    )
    review_text.add_argument(
        "--runs-root",
        required=True,
        type=Path,
        help="Directory containing canonical page-* extraction runs.",
    )
    review_text.add_argument(
        "--output",
        type=Path,
        default=None,
        help="Review output directory. Defaults to <runs-root>/review.",
    )
    review_text.add_argument(
        "--start-page",
        type=int,
        default=1,
        help="Inclusive first physical page to review. Defaults to 1.",
    )
    review_text.add_argument(
        "--end-page",
        type=int,
        default=None,
        help="Inclusive final physical page. Defaults to the final page run.",
    )
    review_text.add_argument(
        "--ocr-language",
        default="vie+eng",
        help="Tesseract language expression. Defaults to vie+eng.",
    )
    review_text.add_argument(
        "--tesseract-command",
        default="tesseract",
        help="Tesseract executable. Defaults to tesseract.",
    )
    review_text.add_argument(
        "--ocr-psm",
        type=int,
        default=3,
        help="Tesseract page segmentation mode. Defaults to 3.",
    )
    review_text.add_argument(
        "--minimum-ocr-confidence",
        type=float,
        default=0.0,
        help="Discard OCR words below this confidence. Defaults to 0.",
    )
    review_text.add_argument(
        "--review-min-ocr-confidence",
        type=float,
        default=85.0,
        help=(
            "Hide OCR-only findings below this confidence while retaining "
            "them in JSON. Defaults to 85."
        ),
    )
    review_text.add_argument(
        "--review-heading-min-ocr-confidence",
        type=float,
        default=92.0,
        help=(
            "Stricter confidence threshold for heading-like OCR findings. "
            "Defaults to 92."
        ),
    )
    review_text.add_argument(
        "--show-all-ocr-differences",
        action="store_true",
        help=(
            "Disable OCR noise suppression in the HTML report. Raw findings "
            "are always retained in JSON."
        ),
    )
    review_text.add_argument(
        "--force",
        action="store_true",
        help=(
            "Re-run local OCR even when a current compatible page review "
            "already exists."
        ),
    )

    import_review = ebook_actions.add_parser(
        "import-review",
        help=(
            "Import explicit human review decisions and compile safe text "
            "correction overlays for later EPUB builds."
        ),
    )
    import_review.add_argument(
        "--runs-root",
        required=True,
        type=Path,
        help="Directory containing canonical page-* extraction runs.",
    )
    import_review.add_argument(
        "--resolutions",
        required=True,
        type=Path,
        help="JSON file exported from the text-review HTML report.",
    )

    review_status = ebook_actions.add_parser(
        "review-status",
        help=(
            "Show whether every page has a current text review and all "
            "actionable findings are resolved."
        ),
    )
    review_status.add_argument(
        "--runs-root",
        required=True,
        type=Path,
        help="Directory containing canonical page-* extraction runs.",
    )
    review_status.add_argument(
        "--format",
        choices=("text", "json"),
        default="text",
        help="Output format. Defaults to compact text.",
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
        default=None,
        help="Optional title override. Otherwise read from metadata.json.",
    )
    render_xhtml.add_argument(
        "--language",
        default=None,
        help="Optional BCP 47 book language, for example vi or en.",
    )
    render_xhtml.add_argument(
        "--author",
        default=None,
        help="Optional single-author override.",
    )
    render_xhtml.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help="Optional rich book metadata JSON file.",
    )
    render_xhtml.add_argument(
        "--cover",
        type=Path,
        default=None,
        help="Optional cover image override (JPEG, PNG, GIF, or SVG).",
    )

    prepare_proof = ebook_actions.add_parser(
        "prepare-proof",
        help=(
            "Freeze generated EPUB-ready artifacts into a protected "
            "human-editable proof workspace."
        ),
    )
    prepare_proof.add_argument(
        "--epub-ready",
        required=True,
        type=Path,
        help="Generated EPUB-ready directory to copy into proof ownership.",
    )
    prepare_proof.add_argument(
        "--output",
        required=True,
        type=Path,
        help="Destination proof workspace, for example <build-root>/proof.",
    )
    prepare_proof.add_argument(
        "--force",
        action="store_true",
        help="Explicitly replace an existing proof workspace and human edits.",
    )

    package_epub = ebook_actions.add_parser(
        "package-epub",
        help="Package EPUB-ready or human-proofed XHTML into a final EPUB 3 file.",
    )
    package_source = package_epub.add_mutually_exclusive_group(required=True)
    package_source.add_argument(
        "--epub-ready",
        type=Path,
        help="Generated EPUB-ready directory produced by render-xhtml.",
    )
    package_source.add_argument(
        "--proof",
        type=Path,
        help="Human-owned proof workspace produced by prepare-proof.",
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
        default=None,
        help=(
            "Optional title override. Otherwise use <runs-root>/metadata.json "
            "or --metadata."
        ),
    )
    build_epub.add_argument(
        "--language",
        default=None,
        help="Optional BCP 47 book language, for example vi or en.",
    )
    build_epub.add_argument(
        "--author",
        default=None,
        help="Optional single-author override.",
    )
    build_epub.add_argument(
        "--metadata",
        type=Path,
        default=None,
        help=(
            "Optional metadata.json. Defaults to <runs-root>/metadata.json "
            "when that file exists."
        ),
    )
    build_epub.add_argument(
        "--cover",
        type=Path,
        default=None,
        help="Optional cover image override (JPEG, PNG, GIF, or SVG).",
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
        "--require-reviewed",
        action="store_true",
        help=(
            "Fail the build unless every page has a current review and all "
            "actionable findings have human decisions."
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


def _add_gemini_routing_arguments(parser: argparse.ArgumentParser) -> None:
    """Add shared free-first Gemini routing controls to one AI command."""
    parser.add_argument(
        "--routing-policy",
        choices=(
            RoutingPolicy.FREE_ONLY.value,
            RoutingPolicy.FREE_THEN_PAID.value,
        ),
        default=RoutingPolicy.FREE_ONLY.value,
        help=(
            "Gemini credential routing policy. free-only never uses the paid "
            "profile; free-then-paid allows paid fallback after free retries."
        ),
    )


def _add_recitation_recovery_arguments(parser: argparse.ArgumentParser) -> None:
    """Add conservative local-OCR fallback controls for Gemini RECITATION."""
    parser.add_argument(
        "--recitation-ocr-language",
        default="auto",
        help=(
            "Tesseract language used only when Gemini stops with RECITATION. "
            "Defaults to auto, which prefers nearby extracted-page language."
        ),
    )
    parser.add_argument(
        "--no-recitation-ocr-fallback",
        action="store_true",
        help=(
            "Disable automatic local OCR recovery when Gemini stops with "
            "RECITATION."
        ),
    )


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
    if args.domain == "ebook" and args.action == "extract-metadata":
        return _run_ebook_extract_metadata(args)
    if args.domain == "ebook" and args.action == "extract-book":
        return _run_ebook_extract_book(args)
    if args.domain == "ebook" and args.action == "convert-pdf":
        return _run_ebook_convert_pdf(args)
    if args.domain == "ebook" and args.action == "review-text":
        return _run_ebook_review_text(args)
    if args.domain == "ebook" and args.action == "import-review":
        return _run_ebook_import_review(args)
    if args.domain == "ebook" and args.action == "review-status":
        return _run_ebook_review_status(args)
    if args.domain == "ebook" and args.action == "assemble-book":
        return _run_ebook_assemble_book(args)
    if args.domain == "ebook" and args.action == "render-xhtml":
        return _run_ebook_render_xhtml(args)
    if args.domain == "ebook" and args.action == "prepare-proof":
        return _run_ebook_prepare_proof(args)
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


def _build_gemini_extractor(
    *,
    model: str,
    routing_policy: RoutingPolicy,
) -> Extractor:
    """Build free-first Gemini routes from environment credential profiles."""
    free_key = os.getenv("SIFTFORGE_GEMINI_FREE_API_KEY")
    paid_key = os.getenv("SIFTFORGE_GEMINI_PAID_API_KEY")
    legacy_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")

    if free_key:
        classifier = GeminiFailureClassifier()
        routes: list[ExtractionRoute] = [
            ExtractionRoute(
                name="gemini-free",
                extractor=GeminiProvider(
                    GeminiProviderConfig(
                        model=model,
                        temperature=0.0,
                        api_key=free_key,
                        profile_name="gemini-free",
                        cost_tier=CostTier.FREE.value,
                    )
                ),
                classifier=classifier,
                provider="gemini",
                cost_tier=CostTier.FREE,
                max_attempts=3,
            )
        ]
        if paid_key:
            routes.append(
                ExtractionRoute(
                    name="gemini-paid",
                    extractor=GeminiProvider(
                        GeminiProviderConfig(
                            model=model,
                            temperature=0.0,
                            api_key=paid_key,
                            profile_name="gemini-paid",
                            cost_tier=CostTier.PAID.value,
                        )
                    ),
                    classifier=classifier,
                    provider="gemini",
                    cost_tier=CostTier.PAID,
                    max_attempts=2,
                )
            )
        return FreeFirstRouter(routes, policy=routing_policy)

    if paid_key:
        if routing_policy is RoutingPolicy.FREE_ONLY:
            raise ValueError(
                "free-only routing requires SIFTFORGE_GEMINI_FREE_API_KEY; "
                "the configured paid key was not used"
            )
        return FreeFirstRouter(
            (
                ExtractionRoute(
                    name="gemini-paid",
                    extractor=GeminiProvider(
                        GeminiProviderConfig(
                            model=model,
                            temperature=0.0,
                            api_key=paid_key,
                            profile_name="gemini-paid",
                            cost_tier=CostTier.PAID.value,
                        )
                    ),
                    classifier=GeminiFailureClassifier(),
                    provider="gemini",
                    cost_tier=CostTier.PAID,
                    max_attempts=2,
                ),
            ),
            policy=routing_policy,
        )

    if legacy_key:
        return GeminiProvider(
            GeminiProviderConfig(
                model=model,
                temperature=0.0,
                api_key=legacy_key,
                profile_name="legacy",
                cost_tier=CostTier.UNSPECIFIED.value,
            )
        )

    raise ValueError(
        "set SIFTFORGE_GEMINI_FREE_API_KEY for free-first routing, or "
        "GEMINI_API_KEY/GOOGLE_API_KEY for legacy single-profile Gemini"
    )


def _run_ebook_extract_metadata(args: argparse.Namespace) -> int:
    """Suggest reviewable book-level metadata from selected front matter."""
    pdf_path = args.pdf.expanduser().resolve()
    output = (
        args.output.expanduser().resolve()
        if args.output is not None
        else (Path.cwd() / "runs" / pdf_path.stem / "metadata.json").resolve()
    )
    try:
        provider = _build_gemini_extractor(
            model=args.model,
            routing_policy=RoutingPolicy(args.routing_policy),
        )
        run = EbookPDFMetadataExtractionService(provider).extract(
            pdf_path=pdf_path,
            output_path=output,
            start_page=args.start_page,
            end_page=args.end_page,
        )
    except (
        FileNotFoundError,
        ValueError,
        PDFPageMaterializationError,
        GeminiProviderError,
        ExtractionRoutingError,
        EbookMetadataExtractionError,
    ) as exc:
        _print_extraction_error(exc)
        return 2

    print(f"pages:    {run.selected_pages[0]}-{run.selected_pages[-1]}")
    print(f"metadata: {run.metadata_path}")
    print(f"report:   {run.report_path}")
    print(f"title:    {run.metadata.title or '[unknown]'}")
    print(f"authors:  {', '.join(run.metadata.authors) or '[unknown]'}")
    print(f"language: {run.metadata.language or '[unknown]'}")
    if run.cover_page_number is not None:
        print(f"cover candidate page: {run.cover_page_number}")
    if run.cover_path is not None:
        print(f"cover:    {run.cover_path}")
    else:
        print("cover:    [not extracted]")
    if run.warnings:
        print("review warnings:")
        for warning in run.warnings:
            print(f"- {warning}")
    print("result: review/edit metadata.json before building the EPUB")
    return 0



def _print_extraction_error(error: Exception) -> None:
    """Print a concise provider-safe extraction failure diagnostic."""
    print(f"error: {error}", file=sys.stderr)
    if not isinstance(error, ExtractionRoutingError):
        return

    if error.attempts:
        print("provider attempts:", file=sys.stderr)
        for attempt in error.attempts:
            route = attempt.metadata.get("route", "unknown")
            error_type = attempt.metadata.get("error_type", "unknown")
            reason = attempt.reason or "unknown"
            print(
                f"- {route}: {reason} ({error_type})",
                file=sys.stderr,
            )

    detail = str(error.last_error).strip()
    if detail:
        print(f"provider detail: {detail}", file=sys.stderr)

def _run_ebook_extract_page(args: argparse.Namespace) -> int:
    """Execute one-page Gemini extraction using the selected ebook contract."""
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

    try:
        provider = _build_gemini_extractor(
            model=args.model,
            routing_policy=RoutingPolicy(args.routing_policy),
        )
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
            recitation_ocr_fallback=not args.no_recitation_ocr_fallback,
            recitation_ocr_language=args.recitation_ocr_language,
        )
    except (
        FileNotFoundError,
        ValueError,
        PDFPageMaterializationError,
        GeminiProviderError,
        ExtractionRoutingError,
        EbookPageNormalizationError,
        RecitationOcrRecoveryError,
    ) as exc:
        _print_extraction_error(exc)
        return 2


def _run_ebook_extract_page_v5(
    *,
    provider: Extractor,
    pdf_path: Path,
    page_number: int,
    run_dir: Path,
    recitation_ocr_fallback: bool,
    recitation_ocr_language: str,
) -> int:
    """Run the active v5 page-evidence extraction path."""
    service = EbookPDFPageEvidenceExtractionService(
        provider,
        recitation_ocr_fallback=recitation_ocr_fallback,
        recitation_ocr_language=recitation_ocr_language,
    )
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
    if run.recovery is not None:
        print(f"recovery: {run.recovery}")
        print("review:   REQUIRED - verify OCR text, structure, and typography")
    print("result: typed page evidence saved to normalized/page.json")
    return 0


def _run_ebook_extract_page_v4(
    *,
    provider: Extractor,
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
    pdf_path = args.pdf.expanduser().resolve()
    runs_root = (
        args.runs_root.expanduser().resolve()
        if args.runs_root is not None
        else (Path.cwd() / "runs" / pdf_path.stem).resolve()
    )
    try:
        provider = _build_gemini_extractor(
            model=args.model,
            routing_policy=RoutingPolicy(args.routing_policy),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    service = EbookPDFBookEvidenceExtractionService(
        provider,
        recitation_ocr_fallback=not args.no_recitation_ocr_fallback,
        recitation_ocr_language=args.recitation_ocr_language,
    )

    def print_progress(progress: EbookBookExtractionProgress) -> None:
        """Print one compact line after each selected physical page."""
        result = progress.result
        if result.error_message:
            suffix = f" - {result.error_type}: {result.error_message}"
        elif result.recovery is not None:
            suffix = f" - recovery={result.recovery}; review required"
        else:
            suffix = ""
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
    print(f"recovered: {run.recovered_count}")
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


def _run_ebook_convert_pdf(args: argparse.Namespace) -> int:
    """Resume full-PDF extraction, then build one complete EPUB."""
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
        provider = _build_gemini_extractor(
            model=args.model,
            routing_policy=RoutingPolicy(args.routing_policy),
        )
    except ValueError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    extraction_service = EbookPDFBookEvidenceExtractionService(
        provider,
        recitation_ocr_fallback=not args.no_recitation_ocr_fallback,
        recitation_ocr_language=args.recitation_ocr_language,
    )
    service = EbookPdfToEpubService(
        provider,
        extraction_service=extraction_service,
    )

    def print_progress(progress: EbookBookExtractionProgress) -> None:
        """Print one compact extraction line per physical PDF page."""
        result = progress.result
        if result.error_message:
            suffix = f" - {result.error_type}: {result.error_message}"
        elif result.recovery is not None:
            suffix = f" - recovery={result.recovery}; review required"
        else:
            suffix = ""
        print(
            f"[{progress.completed}/{progress.total}] "
            f"page {result.page_number:04d} {result.status.value}{suffix}"
        )

    try:
        run = service.convert(
            args.pdf.expanduser().resolve(),
            args.output.expanduser().resolve(),
            model=args.model,
            title=args.title,
            runs_root=args.runs_root,
            language=args.language,
            author=args.author,
            metadata_path=args.metadata,
            cover_path=args.cover,
            work_dir=args.work_dir,
            identifier=args.identifier,
            modified=args.modified,
            force_extract=args.force_extract,
            continue_on_error=args.continue_on_error,
            validate=args.validate,
            epubcheck_jar=jar_value,
            java_command=args.java_command,
            timeout_seconds=args.timeout,
            report_path=args.epubcheck_report,
            progress_callback=print_progress,
        )
    except EbookPdfToEpubError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    extraction = run.extraction
    print(f"runs:       {run.runs_root}")
    print(f"extracted:  {extraction.extracted_count}")
    print(f"reused:     {extraction.reused_count}")
    print(f"recovered:  {extraction.recovered_count}")
    print(f"failed:     {extraction.failed_count}")
    if extraction.total_usage:
        total_tokens = extraction.total_usage.get("total_token_count")
        if total_tokens is not None:
            print(f"tokens:     {total_tokens}")
    print(f"manifest:   {run.manifest_path}")

    if run.build is None:
        print("result:     extraction incomplete; EPUB build skipped")
        return 1

    build = run.build
    print(f"pages:      {len(build.assembly.page_runs)}")
    print(f"nodes:      {len(build.assembly.document.nodes)}")
    print(f"figures:    {len(build.assembly.figure_assets)}")
    print(f"epub:       {build.package.package.epub_path}")
    if build.validation is None:
        print("epubcheck:  skipped")
        print("result:     PDF-to-EPUB conversion complete")
        return 0

    result = build.validation.result
    print(f"epubcheck:  {'PASS' if result.passed else 'FAIL'}")
    print(
        "result:     "
        + (
            "PDF-to-EPUB conversion and validation complete"
            if result.passed
            else "EPUB built, but EPUBCheck failed"
        )
    )
    return 0 if result.passed else 1


def _run_ebook_review_text(args: argparse.Namespace) -> int:
    """Run provider-free text fidelity review across canonical page runs."""
    if args.start_page < 1:
        print("error: --start-page must be >= 1", file=sys.stderr)
        return 2
    if args.end_page is not None and args.end_page < args.start_page:
        print(
            "error: --end-page must be >= --start-page",
            file=sys.stderr,
        )
        return 2
    if args.minimum_ocr_confidence < 0:
        print(
            "error: --minimum-ocr-confidence must be >= 0",
            file=sys.stderr,
        )
        return 2
    for option, value in (
        ("--review-min-ocr-confidence", args.review_min_ocr_confidence),
        (
            "--review-heading-min-ocr-confidence",
            args.review_heading_min_ocr_confidence,
        ),
    ):
        if not 0 <= value <= 100:
            print(f"error: {option} must be between 0 and 100", file=sys.stderr)
            return 2
    engine = TesseractOcrEngine(
        TesseractOcrConfig(
            command=args.tesseract_command,
            language=args.ocr_language,
            page_segmentation_mode=args.ocr_psm,
            minimum_confidence=args.minimum_ocr_confidence,
        )
    )
    service = EbookTextReviewService(
        engine,
        filter_config=ReviewFilterConfig(
            enabled=not args.show_all_ocr_differences,
            minimum_ocr_confidence=args.review_min_ocr_confidence,
            minimum_heading_ocr_confidence=(
                args.review_heading_min_ocr_confidence
            ),
        ),
    )
    try:
        run = service.review(
            args.runs_root,
            args.output,
            start_page=args.start_page,
            end_page=args.end_page,
            force=args.force,
        )
    except (TextReviewError, LocalOcrError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"pages:     {len(run.pages)}")
    print(f"processed: {run.processed_pages}")
    print(f"reused:    {run.reused_pages}")
    print(f"flagged:   {run.pages_with_findings}")
    print(f"findings:  {run.finding_count}")
    print(f"suppressed:{run.suppressed_count:>4}")
    print(f"summary:   {run.summary_path}")
    print(f"report:    {run.report_path}")
    if run.manifest_path is not None:
        print(f"manifest:  {run.manifest_path}")
    print("result: text-fidelity review artifacts generated")
    return 0


def _run_ebook_import_review(args: argparse.Namespace) -> int:
    """Import human review choices without modifying normalized page JSON."""
    try:
        result = import_review_resolutions(
            args.runs_root,
            args.resolutions,
        )
    except (ReviewResolutionError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"resolved:    {result.resolved_count}")
    print(f"corrections: {result.correction_count}")
    print(f"pages:       {result.pages_touched}")
    print(f"saved:       {result.aggregate_path}")
    print("result: human review decisions imported")
    return 0


def _run_ebook_review_status(args: argparse.Namespace) -> int:
    """Report review completeness without modifying any artifacts."""
    try:
        status = ReviewStatusService().inspect(args.runs_root)
    except (ReviewStatusError, OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.format == "json":
        print(json.dumps(review_status_to_dict(status), ensure_ascii=False, indent=2))
    else:
        print(f"pages:       {status.total_pages}")
        print(f"findings:    {status.finding_count}")
        print(f"unresolved:  {status.unresolved_count}")
        for state in (
            "not_reviewed",
            "pass",
            "needs_review",
            "resolved",
            "stale",
        ):
            count = sum(page.state.value == state for page in status.pages)
            if count:
                print(f"{state + ':':<12} {count}")
        print(f"complete:    {'yes' if status.complete else 'no'}")
        for page in status.pages:
            if page.state.value in {"needs_review", "not_reviewed", "stale"}:
                detail = f" ({page.stale_reason})" if page.stale_reason else ""
                print(
                    f"page {page.page_number:04d}: {page.state.value}"
                    f" unresolved={page.unresolved_count}{detail}"
                )
    return 0 if status.complete else 1


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
            metadata_path=args.metadata,
            cover_path=args.cover,
        )
    except EbookEpubReadyError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"nodes:    {len(run.document.nodes)}")
    print(f"assets:   {run.asset_count}")
    print(f"warnings: {len(run.warnings)}")
    print(f"output:   {run.output_dir}")
    print("result: EPUB-ready XHTML saved to text/content.xhtml")
    return 0


def _run_ebook_prepare_proof(args: argparse.Namespace) -> int:
    """Freeze generated XHTML into a protected human proofreading workspace."""
    source = args.epub_ready.expanduser().resolve()
    output = args.output.expanduser().resolve()
    try:
        run = EbookProofService().prepare(
            source,
            output,
            force=args.force,
        )
    except EbookProofError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"proof:     {run.proof_dir}")
    print(f"editable:  {run.editable_count} XHTML files")
    print(f"manifest:  {run.manifest_path}")
    print("result: human-owned proof workspace prepared")
    return 0


def _run_ebook_package_epub(args: argparse.Namespace) -> int:
    """Package generated or human-proofed XHTML into one EPUB 3 archive."""
    proof_status = None
    if args.proof is not None:
        package_root = args.proof.expanduser().resolve()
        try:
            proof_status = EbookProofService().inspect(package_root)
        except EbookProofError as exc:
            print(f"error: {exc}", file=sys.stderr)
            return 2
    else:
        package_root = args.epub_ready.expanduser().resolve()
    output = args.output.expanduser().resolve()
    try:
        run = EbookEpubPackageService().build(
            package_root,
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
    if proof_status is not None:
        print(f"proof edits:{proof_status.modified_count:>4} XHTML files")
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
            metadata_path=args.metadata,
            cover_path=args.cover,
            work_dir=args.work_dir,
            identifier=args.identifier,
            modified=args.modified,
            validate=args.validate,
            epubcheck_jar=jar_value,
            java_command=args.java_command,
            timeout_seconds=args.timeout,
            report_path=args.epubcheck_report,
            require_reviewed=args.require_reviewed,
        )
    except EbookBuildError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"pages:      {len(run.assembly.page_runs)}")
    print(f"nodes:      {len(run.assembly.document.nodes)}")
    print(f"figures:    {len(run.assembly.figure_assets)}")
    print(f"assets:     {run.epub_ready.asset_count}")
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
