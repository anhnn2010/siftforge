"""Tests for final EPUB 3 archive packaging."""

import json
import zipfile
from pathlib import Path
from xml.etree import ElementTree

import pytest

from siftforge.ebook.epub import EpubPackageBuilder, EpubPackageError
from siftforge.ebook.pipeline import EbookEpubPackageService


def _write_ready_fixture(root: Path, *, with_heading: bool = True) -> None:
    """Create a minimal persisted EPUB-ready directory for package tests."""
    (root / "text").mkdir(parents=True)
    (root / "styles").mkdir(parents=True)
    (root / "semantic").mkdir(parents=True)
    asset = root / "assets" / "figures" / "figure.png"
    asset.parent.mkdir(parents=True)
    asset.write_bytes(b"fake-png")
    (root / "text" / "content.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        'lang="vi" xml:lang="vi">\n'
        "  <head><title>Sách thử</title></head>\n"
        "  <body><h1 id=\"chapter-1\">Chương một</h1></body>\n"
        "</html>\n",
        encoding="utf-8",
    )
    (root / "styles" / "book.css").write_text(
        "body { line-height: 1.5; }\n",
        encoding="utf-8",
    )
    nodes = []
    if with_heading:
        nodes.append(
            {
                "type": "heading",
                "node_id": "chapter-1",
                "role": "chapter_title",
                "level": 1,
                "content": [
                    {
                        "text": "Chương một",
                        "language": "vi",
                        "marks": [],
                        "role": "text",
                        "target_id": None,
                        "source_span_id": "span-1",
                    }
                ],
            }
        )
    (root / "semantic" / "document.json").write_text(
        json.dumps(
            {
                "title": "Sách thử",
                "language": "vi",
                "author": "Tác giả",
                "nodes": nodes,
                "relationships": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (root / "manifest.json").write_text(
        json.dumps(
            {
                "format": "epub-ready-xhtml",
                "source_assembly": "book",
                "title": "Sách thử",
                "language": "vi",
                "author": "Tác giả",
                "content": "text/content.xhtml",
                "stylesheet": "styles/book.css",
                "assets": ["assets/figures/figure.png"],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )


def test_package_service_creates_required_epub_members(tmp_path: Path) -> None:
    """Final package should follow mandatory EPUB ZIP/container rules."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    output = tmp_path / "book.epub"

    run = EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-11T10:00:00Z",
    )

    assert run.package.epub_path == output.resolve()
    assert run.package.identifier.startswith("urn:uuid:")
    assert run.package.modified == "2026-09-11T10:00:00Z"
    assert run.package.manifest_item_count == 4
    assert run.package.toc_entry_count == 1
    with zipfile.ZipFile(output) as archive:
        infos = archive.infolist()
        assert infos[0].filename == "mimetype"
        assert infos[0].compress_type == zipfile.ZIP_STORED
        assert archive.read("mimetype") == b"application/epub+zip"
        assert "META-INF/container.xml" in archive.namelist()
        assert "EPUB/package.opf" in archive.namelist()
        assert "EPUB/nav.xhtml" in archive.namelist()
        assert "EPUB/text/content.xhtml" in archive.namelist()
        assert "EPUB/styles/book.css" in archive.namelist()
        assert "EPUB/assets/figures/figure.png" in archive.namelist()


def test_package_opf_contains_epub3_metadata_and_manifest(tmp_path: Path) -> None:
    """OPF should contain stable metadata, nav, spine, and figure entries."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    output = tmp_path / "book.epub"
    identifier = "urn:isbn:9780000000000"

    EbookEpubPackageService().build(
        ready,
        output,
        identifier=identifier,
        modified="2026-09-11T10:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        root = ElementTree.fromstring(archive.read("EPUB/package.opf"))
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "opf": "http://www.idpf.org/2007/opf",
    }
    assert root.get("version") == "3.0"
    assert root.findtext("opf:metadata/dc:identifier", namespaces=ns) == identifier
    assert root.findtext("opf:metadata/dc:title", namespaces=ns) == "Sách thử"
    assert root.findtext("opf:metadata/dc:language", namespaces=ns) == "vi"
    assert root.findtext("opf:metadata/dc:creator", namespaces=ns) == "Tác giả"
    items = root.findall("opf:manifest/opf:item", ns)
    assert {item.get("id") for item in items} == {
        "nav",
        "content",
        "css",
        "asset-0001",
    }
    image = next(item for item in items if item.get("id") == "asset-0001")
    assert image.get("media-type") == "image/png"
    spine = root.findall("opf:spine/opf:itemref", ns)
    assert [item.get("idref") for item in spine] == ["content"]


def test_navigation_uses_semantic_headings(tmp_path: Path) -> None:
    """Navigation should link semantic heading labels to content fragments."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-11T10:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
    assert "Chương một" in nav
    assert 'href="text/content.xhtml#chapter-1"' in nav
    assert 'epub:type="toc"' in nav



def test_navigation_omits_footnote_references_from_heading_label(
    tmp_path: Path,
) -> None:
    """TOC labels should omit noterefs while preserving readable boundaries."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    semantic_path = ready / "semantic" / "document.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic["nodes"][0]["content"] = [
        {
            "text": "Thứ Sáu ngày 13",
            "language": "vi",
            "marks": [],
            "role": "text",
            "target_id": None,
            "source_span_id": "span-1",
        },
        {
            "text": "1",
            "language": None,
            "marks": [],
            "role": "footnote_ref",
            "target_id": "note-1",
            "source_span_id": "span-ref-1",
        },
        {
            "text": "Cá chép vượt vũ môn!",
            "language": "vi",
            "marks": [],
            "role": "text",
            "target_id": None,
            "source_span_id": "span-2",
        },
        {
            "text": "2",
            "language": None,
            "marks": [],
            "role": "footnote_ref",
            "target_id": "note-2",
            "source_span_id": "span-ref-2",
        },
    ]
    semantic_path.write_text(
        json.dumps(semantic, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-11T10:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
    assert "Thứ Sáu ngày 13 Cá chép vượt vũ môn!" in nav
    assert "Thứ Sáu ngày 131Cá chép vượt vũ môn!2" not in nav

def test_navigation_falls_back_to_book_title_without_headings(
    tmp_path: Path,
) -> None:
    """Books without resolved headings should still have a valid TOC entry."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready, with_heading=False)
    output = tmp_path / "book.epub"

    run = EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-11T10:00:00Z",
    )

    assert run.package.toc_entry_count == 0
    with zipfile.ZipFile(output) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
    assert '<a href="text/content.xhtml">Sách thử</a>' in nav


def test_default_identifier_is_stable_for_same_ready_content(
    tmp_path: Path,
) -> None:
    """Omitted identifiers should be content-derived and repeatable."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    service = EbookEpubPackageService()

    first = service.build(
        ready,
        tmp_path / "one.epub",
        modified="2026-09-11T10:00:00Z",
    )
    second = service.build(
        ready,
        tmp_path / "two.epub",
        modified="2026-09-11T10:00:00Z",
    )

    assert first.package.identifier == second.package.identifier
    assert (tmp_path / "one.epub").read_bytes() == (
        tmp_path / "two.epub"
    ).read_bytes()


def test_package_rejects_unsafe_manifest_asset_path(tmp_path: Path) -> None:
    """Persisted manifest paths must not escape the EPUB-ready root."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    manifest_path = ready / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["assets"] = ["../outside.png"]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    with pytest.raises(EpubPackageError, match="unsafe EPUB-ready path"):
        EpubPackageBuilder().build(
            ready,
            tmp_path / "book.epub",
            modified="2026-09-11T10:00:00Z",
        )


def test_package_rejects_invalid_modified_timestamp(tmp_path: Path) -> None:
    """EPUB modified metadata must use the required UTC timestamp syntax."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)

    with pytest.raises(EpubPackageError, match="modified must use UTC format"):
        EpubPackageBuilder().build(
            ready,
            tmp_path / "book.epub",
            modified="2026-09-11",
        )


def test_navigation_excludes_supporting_subtitle_headings(tmp_path: Path) -> None:
    """Subtitle labels should render in body without becoming standalone TOC entries."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    semantic_path = ready / "semantic" / "document.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic["nodes"].append(
        {
            "type": "heading",
            "node_id": "subtitle-1",
            "role": "subtitle",
            "level": None,
            "content": [
                {
                    "text": "Thứ Sáu ngày 13",
                    "language": "vi",
                    "marks": [],
                    "role": "text",
                    "target_id": None,
                    "source_span_id": "span-subtitle-1",
                }
            ],
        }
    )
    semantic_path.write_text(
        json.dumps(semantic, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-14T11:45:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")

    assert "Chương một" in nav
    assert "Thứ Sáu ngày 13" not in nav
