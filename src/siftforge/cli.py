"""Command-line entry point for SiftForge application workflows."""

from __future__ import annotations

import argparse
import os
import sys
from collections.abc import Sequence
from pathlib import Path

from siftforge.ebook.pipeline import EbookPDFPageExtractionService
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
        "--run-dir",
        type=Path,
        default=None,
        help=(
            "Artifact directory. Defaults to runs/<pdf-stem>/page-NNNN."
        ),
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

    parser.error("unsupported command")
    return 2


def _run_ebook_extract_page(args: argparse.Namespace) -> int:
    """Execute the one-page Gemini ebook smoke-run command."""
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
    service = EbookPDFPageExtractionService(provider)

    try:
        run = service.extract_page(
            pdf_path=pdf_path,
            page_number=args.page,
            run_dir=run_dir,
        )
    except (
        FileNotFoundError,
        ValueError,
        PDFPageMaterializationError,
        GeminiProviderError,
    ) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    print(f"source: {run.source.source_id}")
    print(f"asset:  {run.asset.path}")
    print(f"run:    {run.run_dir}")
    print("result: structured response saved to normalized/page.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
