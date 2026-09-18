"""Cover-image extraction helpers for book-level EPUB metadata."""

from __future__ import annotations

import shutil
from dataclasses import dataclass
from pathlib import Path

from PIL import Image

from siftforge.extraction.models import MaterializedAsset


class EbookCoverExtractionError(RuntimeError):
    """Raised when a detected cover asset cannot be persisted safely."""


@dataclass(frozen=True, slots=True)
class ExtractedBookCover:
    """One persisted book cover derived from a materialized PDF page.

    Attributes:
        path: Final filesystem path written for EPUB packaging.
        source_page_number: Physical PDF page used as the cover.
        source_media_type: Media type of the materialized source asset.
        transcoded: Whether SiftForge re-encoded the source image.
    """

    path: Path
    source_page_number: int
    source_media_type: str
    transcoded: bool


def persist_cover_asset(
    asset: MaterializedAsset,
    *,
    destination_dir: str | Path,
) -> ExtractedBookCover:
    """Persist one materialized PDF-page image as ``cover.jpg``.

    Existing JPEG bytes are copied directly to avoid an unnecessary quality loss.
    Other image encodings supported by Pillow are converted to RGB JPEG so the
    result is immediately usable by the EPUB packager.
    """
    page_number = asset.source.metadata.get("page_number")
    if not isinstance(page_number, int) or isinstance(page_number, bool):
        raise EbookCoverExtractionError(
            "cover source asset is missing a valid physical page number"
        )

    output_dir = Path(destination_dir).expanduser().resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    destination = output_dir / "cover.jpg"

    if asset.media_type == "image/jpeg":
        shutil.copyfile(asset.path, destination)
        return ExtractedBookCover(
            path=destination,
            source_page_number=page_number,
            source_media_type=asset.media_type,
            transcoded=False,
        )

    try:
        with Image.open(asset.path) as image:
            if image.mode != "RGB":
                image = image.convert("RGB")
            image.save(destination, format="JPEG", quality=95)
    except (OSError, ValueError) as exc:
        raise EbookCoverExtractionError(
            f"could not convert detected cover image {asset.path.name!r} to JPEG"
        ) from exc

    return ExtractedBookCover(
        path=destination,
        source_page_number=page_number,
        source_media_type=asset.media_type,
        transcoded=True,
    )
