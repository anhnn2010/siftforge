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



def test_navigation_builds_nested_semantic_hierarchy_and_excludes_unknown(
    tmp_path: Path,
) -> None:
    """TOC should nest chapter/section/subsection and omit unresolved headings."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    content = ready / "text" / "content.xhtml"
    content.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="vi">\n'
        "  <head><title>Sách thử</title></head>\n"
        "  <body>\n"
        '    <h1 id="frontmatter">HỒ THỊ HẢI ÂU</h1>\n'
        '    <h1 id="chapter-1">Chương một</h1>\n'
        '    <h2 id="section-1">Phần một</h2>\n'
        '    <h3 id="subsection-1">Mục nhỏ</h3>\n'
        '    <h2 id="section-2">Phần hai</h2>\n'
        '    <h1 id="chapter-2">Chương hai</h1>\n'
        "  </body>\n"
        "</html>\n",
        encoding="utf-8",
    )

    def heading(node_id: str, role: str, label: str, level: int) -> dict[str, object]:
        return {
            "type": "heading",
            "node_id": node_id,
            "role": role,
            "level": level,
            "content": [
                {
                    "text": label,
                    "language": "vi",
                    "marks": [],
                    "role": "text",
                    "target_id": None,
                    "source_span_id": f"span-{node_id}",
                }
            ],
        }

    semantic_path = ready / "semantic" / "document.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic["nodes"] = [
        heading("frontmatter", "unknown", "HỒ THỊ HẢI ÂU", 1),
        heading("chapter-1", "chapter_title", "Chương một", 4),
        heading("section-1", "section_title", "Phần một", 1),
        heading("subsection-1", "subsection_title", "Mục nhỏ", 1),
        heading("section-2", "section_title", "Phần hai", 6),
        heading("chapter-2", "chapter_title", "Chương hai", 2),
    ]
    semantic_path.write_text(
        json.dumps(semantic, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    run = EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-25T03:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = ElementTree.fromstring(archive.read("EPUB/nav.xhtml"))
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    toc = nav.find(".//x:nav[@id='toc']", ns)
    assert toc is not None
    root_list = toc.find("x:ol", ns)
    assert root_list is not None
    root_items = root_list.findall("x:li", ns)
    assert [item.findtext("x:a", namespaces=ns) for item in root_items] == [
        "Chương một",
        "Chương hai",
    ]

    chapter_children = root_items[0].find("x:ol", ns)
    assert chapter_children is not None
    sections = chapter_children.findall("x:li", ns)
    assert [item.findtext("x:a", namespaces=ns) for item in sections] == [
        "Phần một",
        "Phần hai",
    ]

    subsection_list = sections[0].find("x:ol", ns)
    assert subsection_list is not None
    subsections = subsection_list.findall("x:li", ns)
    assert [item.findtext("x:a", namespaces=ns) for item in subsections] == [
        "Mục nhỏ"
    ]
    assert "HỒ THỊ HẢI ÂU" not in ElementTree.tostring(
        toc, encoding="unicode"
    )
    assert run.package.toc_entry_count == 5


def test_navigation_normalizes_missing_parent_levels(tmp_path: Path) -> None:
    """A subsection without a section parent should remain valid navigation."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    content = ready / "text" / "content.xhtml"
    content.write_text(
        content.read_text(encoding="utf-8").replace(
            "</body>", '<h3 id="subsection-1">Mục nhỏ</h3></body>'
        ),
        encoding="utf-8",
    )
    semantic_path = ready / "semantic" / "document.json"
    semantic = json.loads(semantic_path.read_text(encoding="utf-8"))
    semantic["nodes"].append(
        {
            "type": "heading",
            "node_id": "subsection-1",
            "role": "subsection_title",
            "level": 3,
            "content": [
                {
                    "text": "Mục nhỏ",
                    "language": "vi",
                    "marks": [],
                    "role": "text",
                    "target_id": None,
                    "source_span_id": "span-subsection-1",
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
        modified="2026-09-25T03:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = ElementTree.fromstring(archive.read("EPUB/nav.xhtml"))
    ns = {"x": "http://www.w3.org/1999/xhtml"}
    toc = nav.find(".//x:nav[@id='toc']", ns)
    assert toc is not None
    root_list = toc.find("x:ol", ns)
    assert root_list is not None
    chapter = root_list.find("x:li", ns)
    assert chapter is not None
    children = chapter.find("x:ol", ns)
    assert children is not None
    assert children.findtext("x:li/x:a", namespaces=ns) == "Mục nhỏ"


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


def test_package_supports_multiple_xhtml_spine_documents(tmp_path: Path) -> None:
    """Multi-document ready artifacts should become an ordered EPUB spine."""
    ready = tmp_path / "ready"
    (ready / "text").mkdir(parents=True)
    (ready / "styles").mkdir(parents=True)
    (ready / "semantic").mkdir(parents=True)
    for index in (1, 2):
        (ready / "text" / f"section-{index:04d}.xhtml").write_text(
            '<?xml version="1.0" encoding="utf-8"?>\n'
            '<html xmlns="http://www.w3.org/1999/xhtml" '
            'xmlns:epub="http://www.idpf.org/2007/ops" lang="vi">\n'
            f"<head><title>Chương {index}</title></head>\n"
            f'<body><h1 id="chapter-{index}">Chương {index}</h1></body>\n'
            "</html>\n",
            encoding="utf-8",
        )
    (ready / "styles" / "book.css").write_text("body {}\n", encoding="utf-8")
    (ready / "semantic" / "document.json").write_text(
        json.dumps(
            {
                "title": "Sách thử",
                "language": "vi",
                "author": None,
                "nodes": [
                    {
                        "type": "heading",
                        "node_id": f"chapter-{index}",
                        "role": "chapter_title",
                        "level": 1,
                        "content": [
                            {
                                "text": f"Chương {index}",
                                "language": "vi",
                                "marks": [],
                                "role": "text",
                                "target_id": None,
                                "source_span_id": None,
                            }
                        ],
                    }
                    for index in (1, 2)
                ],
                "relationships": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ready / "manifest.json").write_text(
        json.dumps(
            {
                "format": "epub-ready-xhtml",
                "source_assembly": "book",
                "title": "Sách thử",
                "language": "vi",
                "author": None,
                "content": "text/section-0001.xhtml",
                "contents": [
                    "text/section-0001.xhtml",
                    "text/section-0002.xhtml",
                ],
                "stylesheet": "styles/book.css",
                "assets": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-15T08:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        package = ElementTree.fromstring(archive.read("EPUB/package.opf"))
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        assert "EPUB/text/section-0001.xhtml" in archive.namelist()
        assert "EPUB/text/section-0002.xhtml" in archive.namelist()
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    spine = package.findall("opf:spine/opf:itemref", ns)
    assert [item.get("idref") for item in spine] == [
        "content-0001",
        "content-0002",
    ]
    assert 'href="text/section-0001.xhtml#chapter-1"' in nav
    assert 'href="text/section-0002.xhtml#chapter-2"' in nav


def test_navigation_includes_body_and_endnotes_landmarks(tmp_path: Path) -> None:
    """Dedicated endnotes should be discoverable through EPUB landmarks."""
    ready = tmp_path / "ready"
    (ready / "text").mkdir(parents=True)
    (ready / "styles").mkdir(parents=True)
    (ready / "semantic").mkdir(parents=True)
    (ready / "text" / "chapter-0001.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="vi">\n'
        "<head><title>Chương một</title></head>\n"
        '<body epub:type="bodymatter">'
        '<h1 id="chapter-1">Chương một</h1>'
        '<p>Text<sup><a id="ref-1" epub:type="noteref" '
        'href="endnotes.xhtml#note-1">1</a></sup></p>'
        "</body></html>\n",
        encoding="utf-8",
    )
    (ready / "text" / "endnotes.xhtml").write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" lang="vi">\n'
        "<head><title>Notes</title></head>\n"
        '<body epub:type="backmatter">'
        '<section id="endnotes" epub:type="endnotes"><ol>'
        '<li id="note-1" epub:type="endnote"><p>Note '
        '<a epub:type="backlink" href="chapter-0001.xhtml#ref-1">↩</a>'
        "</p></li></ol></section></body></html>\n",
        encoding="utf-8",
    )
    (ready / "styles" / "book.css").write_text("body {}\n", encoding="utf-8")
    (ready / "semantic" / "document.json").write_text(
        json.dumps(
            {
                "title": "Sách thử",
                "language": "vi",
                "author": None,
                "nodes": [
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
                                "source_span_id": None,
                            }
                        ],
                    }
                ],
                "relationships": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    (ready / "manifest.json").write_text(
        json.dumps(
            {
                "format": "epub-ready-xhtml",
                "source_assembly": "book",
                "title": "Sách thử",
                "language": "vi",
                "author": None,
                "content": "text/chapter-0001.xhtml",
                "contents": [
                    "text/chapter-0001.xhtml",
                    "text/endnotes.xhtml",
                ],
                "endnotes": "text/endnotes.xhtml",
                "stylesheet": "styles/book.css",
                "assets": [],
                "warnings": [],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-16T03:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        package = ElementTree.fromstring(archive.read("EPUB/package.opf"))

    assert '<nav epub:type="landmarks" id="landmarks">' in nav
    assert 'epub:type="bodymatter" href="text/chapter-0001.xhtml"' in nav
    assert (
        'epub:type="endnotes" href="text/endnotes.xhtml#endnotes"' in nav
    )
    ns = {"opf": "http://www.idpf.org/2007/opf"}
    spine = package.findall("opf:spine/opf:itemref", ns)
    assert [item.get("idref") for item in spine] == [
        "content-0001",
        "content-0002",
    ]


def test_package_preserves_rich_metadata_and_epub3_cover(tmp_path: Path) -> None:
    """OPF should expose rich metadata and mark the cover image semantically."""
    ready = tmp_path / "ready"
    _write_ready_fixture(ready)
    cover_image = ready / "assets" / "cover.jpg"
    cover_image.write_bytes(b"fake-jpeg")
    cover_xhtml = ready / "text" / "cover.xhtml"
    cover_xhtml.write_text(
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops">\n'
        '  <body epub:type="cover"><img src="../assets/cover.jpg" '
        'alt="Cover" /></body>\n'
        '</html>\n',
        encoding="utf-8",
    )
    manifest_path = ready / "manifest.json"
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["contents"] = ["text/cover.xhtml", "text/content.xhtml"]
    manifest["cover"] = {
        "image": "assets/cover.jpg",
        "content": "text/cover.xhtml",
    }
    manifest["assets"].append("assets/cover.jpg")
    manifest["metadata"] = {
        "title": "Sách thử",
        "subtitle": "Phụ đề",
        "language": "vi",
        "authors": ["Tác giả A", "Tác giả B"],
        "publisher": "Nhà xuất bản",
        "publication_date": "2026-09-18",
        "isbn": "9780000000000",
        "description": "Mô tả.",
        "subjects": ["Kỹ năng", "Giáo dục"],
        "rights": "© 2026",
        "series": "Bộ sách",
        "series_index": "2",
        "contributors": ["Người dịch"],
        "cover": "cover.jpg",
    }
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False),
        encoding="utf-8",
    )
    output = tmp_path / "book.epub"

    EbookEpubPackageService().build(
        ready,
        output,
        modified="2026-09-18T05:00:00Z",
    )

    with zipfile.ZipFile(output) as archive:
        opf = ElementTree.fromstring(archive.read("EPUB/package.opf"))
        nav = archive.read("EPUB/nav.xhtml").decode("utf-8")
        assert "EPUB/text/cover.xhtml" in archive.namelist()
        assert "EPUB/assets/cover.jpg" in archive.namelist()
    ns = {
        "dc": "http://purl.org/dc/elements/1.1/",
        "opf": "http://www.idpf.org/2007/opf",
    }
    assert [
        item.text for item in opf.findall("opf:metadata/dc:title", ns)
    ] == ["Sách thử", "Phụ đề"]
    assert [
        item.text for item in opf.findall("opf:metadata/dc:creator", ns)
    ] == ["Tác giả A", "Tác giả B"]
    assert opf.findtext("opf:metadata/dc:publisher", namespaces=ns) == (
        "Nhà xuất bản"
    )
    assert opf.findtext("opf:metadata/dc:date", namespaces=ns) == "2026-09-18"
    identifiers = [
        item.text for item in opf.findall("opf:metadata/dc:identifier", ns)
    ]
    assert "urn:isbn:9780000000000" in identifiers
    assert [
        item.text for item in opf.findall("opf:metadata/dc:subject", ns)
    ] == ["Kỹ năng", "Giáo dục"]
    items = opf.findall("opf:manifest/opf:item", ns)
    cover_item = next(item for item in items if item.get("id") == "cover-image")
    assert cover_item.get("properties") == "cover-image"
    spine = opf.findall("opf:spine/opf:itemref", ns)
    assert spine[0].get("idref") == "cover"
    assert 'epub:type="cover" href="text/cover.xhtml"' in nav
    assert 'epub:type="bodymatter" href="text/content.xhtml"' in nav
