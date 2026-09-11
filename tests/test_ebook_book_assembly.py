"""Tests for assembling persisted page runs into a logical book segment."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from PIL import Image

from siftforge.ebook.extraction import EbookPageEvidenceNormalizer
from siftforge.ebook.pipeline import EbookBookAssemblyService, EbookPageRunLoader
from siftforge.ebook.structure import FigureNode, ListNode, ParagraphNode
from siftforge.extraction.models import SourceRef


def _typography() -> dict[str, Any]:
    """Return ordinary v5 source typography."""
    return {
        "posture": "roman",
        "weight": "normal",
        "vertical_position": "baseline",
        "caps_style": "normal",
        "decorations": [],
    }


def _span(text: str) -> dict[str, Any]:
    """Return one ordinary v5 text span."""
    return {
        "text": text,
        "language": "vi",
        "source_typography": _typography(),
        "semantic_line_break_after": False,
    }


def _block(role: str, text: str, **overrides: Any) -> dict[str, Any]:
    """Return one complete v5 provider block."""
    payload: dict[str, Any] = {
        "role_hint": role,
        "content": [_span(text)] if text else [],
        "dominant_language": "vi" if text else None,
        "heading_level_hint": None,
        "heading_role_hint": "unknown",
        "marker": None,
        "region": None,
        "alignment": "left",
    }
    payload.update(overrides)
    return payload


def _write_page_run(
    root: Path,
    page_number: int,
    blocks: list[dict[str, Any]],
) -> Path:
    """Create one canonical v5 page run with a synthetic source image."""
    run_dir = root / f"page-{page_number:04d}"
    (run_dir / "normalized").mkdir(parents=True)
    (run_dir / "assets").mkdir()
    page_id = f"pdf:test:page:{page_number:04d}"
    source = SourceRef(
        source_id=page_id,
        uri=f"fixture://book/page/{page_number}",
        media_type="image/jpeg",
        metadata={"page_number": page_number},
    )
    payload = {
        "page_kind_hint": "text",
        "dominant_language": "vi",
        "printed_page_number": str(page_number),
        "blocks": blocks,
        "warnings": [],
    }
    normalizer = EbookPageEvidenceNormalizer()
    page = normalizer.normalize(page_id, source, payload)
    (run_dir / "normalized" / "page.json").write_text(
        json.dumps(normalizer.to_dict(page), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    image_path = run_dir / "assets" / f"page-{page_number:04d}.jpg"
    Image.new("RGB", (100, 100), (235, 235, 235)).save(
        image_path,
        format="JPEG",
    )
    manifest = {
        "source": {"page_number": page_number},
        "asset": {
            "path": f"assets/{image_path.name}",
            "media_type": "image/jpeg",
        },
    }
    (run_dir / "manifest.json").write_text(
        json.dumps(manifest, indent=2),
        encoding="utf-8",
    )
    return run_dir


def test_page_run_loader_orders_runs_by_physical_page_number(tmp_path: Path) -> None:
    """Directory names must not determine the logical page order."""
    root = tmp_path / "runs"
    root.mkdir()
    _write_page_run(root, 12, [_block("paragraph", "Trang mười hai.")])
    _write_page_run(root, 3, [_block("paragraph", "Trang ba.")])

    runs = EbookPageRunLoader().discover(root)

    assert [run.page_number for run in runs] == [3, 12]


def test_assembly_materializes_figures_and_writes_structure(tmp_path: Path) -> None:
    """Figure evidence should become a PNG asset referenced by BookDocument."""
    root = tmp_path / "runs"
    root.mkdir()
    _write_page_run(
        root,
        116,
        [
            _block(
                "image",
                "",
                region={"x": 0.1, "y": 0.2, "width": 0.5, "height": 0.4},
                alignment="center",
            ),
            _block("caption", "Một chú thích", alignment="center"),
        ],
    )
    output = tmp_path / "book"

    run = EbookBookAssemblyService().assemble(root, output)

    assert len(run.figure_assets) == 1
    figure = run.document.nodes[0]
    assert isinstance(figure, FigureNode)
    assert figure.image.asset_id == run.figure_assets[0].asset_id
    assert (output / figure.image.asset_id).is_file()
    assert (output / "structure" / "book.json").is_file()
    assert (output / "structure" / "analysis.json").is_file()
    assert (output / "manifest.json").is_file()

    book_payload = json.loads(
        (output / "structure" / "book.json").read_text(encoding="utf-8")
    )
    assert book_payload["nodes"][0]["type"] == "figure"
    assert book_payload["nodes"][0]["image"]["asset_id"].endswith(".png")


def test_sparse_page_runs_do_not_group_lists_across_missing_pages(
    tmp_path: Path,
) -> None:
    """Sequential ordinals cannot bridge a missing physical source page."""
    root = tmp_path / "runs"
    root.mkdir()
    _write_page_run(
        root,
        10,
        [
            _block(
                "list_item",
                "Mục mười",
                marker={"kind": "numeric", "raw_text": "10.", "ordinal": 10},
            )
        ],
    )
    _write_page_run(
        root,
        12,
        [
            _block(
                "list_item",
                "Mục mười một",
                marker={"kind": "numeric", "raw_text": "11.", "ordinal": 11},
            )
        ],
    )

    run = EbookBookAssemblyService().assemble(root, tmp_path / "book")

    lists = [node for node in run.document.nodes if isinstance(node, ListNode)]
    assert len(lists) == 2
    assert [item.ordinal for node in lists for item in node.items] == [10, 11]


def test_sparse_page_runs_do_not_create_continuation_candidates(
    tmp_path: Path,
) -> None:
    """Text on pages 10 and 12 must not be stitched across missing page 11."""
    root = tmp_path / "runs"
    root.mkdir()
    _write_page_run(root, 10, [_block("paragraph", "câu còn dang dở")])
    _write_page_run(
        root,
        12,
        [_block("paragraph", "tiếp tục bằng chữ thường")],
    )

    run = EbookBookAssemblyService().assemble(root, tmp_path / "book")

    paragraphs = [
        node for node in run.document.nodes if isinstance(node, ParagraphNode)
    ]
    assert len(paragraphs) == 2
    assert run.analysis.continuation_candidates == ()
