"""Create and validate deterministic EPUB 3 package archives."""

from __future__ import annotations

import hashlib
import html
import json
import re
import uuid
import zipfile
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any
from xml.etree import ElementTree

_EPUB_MIMETYPE = b"application/epub+zip"
_FIXED_ZIP_TIMESTAMP = (1980, 1, 1, 0, 0, 0)
_MODIFIED_PATTERN = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class EpubPackageError(ValueError):
    """Raised when EPUB-ready artifacts cannot form a valid EPUB package."""


@dataclass(frozen=True, slots=True)
class EpubTocEntry:
    """One flat navigation entry derived from a semantic heading."""

    label: str
    target_id: str


@dataclass(frozen=True, slots=True)
class EpubPackageResult:
    """Metadata describing one successfully built EPUB archive."""

    epub_path: Path
    identifier: str
    modified: str
    manifest_item_count: int
    toc_entry_count: int


class EpubPackageBuilder:
    """Package EPUB-ready XHTML artifacts into a validated EPUB 3 archive."""

    def build(
        self,
        epub_ready_root: str | Path,
        output_path: str | Path,
        *,
        identifier: str | None = None,
        modified: str | None = None,
    ) -> EpubPackageResult:
        """Build one EPUB archive from a persisted EPUB-ready directory.

        Args:
            epub_ready_root: Root produced by ``render-xhtml``.
            output_path: Destination ``.epub`` file.
            identifier: Optional publication identifier. A stable UUID URN is
                derived from package inputs when omitted.
            modified: Optional EPUB 3 ``dcterms:modified`` timestamp in UTC
                ``YYYY-MM-DDTHH:MM:SSZ`` form. Current UTC time is used when
                omitted.

        Returns:
            Result describing the generated EPUB archive.

        Raises:
            EpubPackageError: If source artifacts or package metadata are invalid.
        """
        root = Path(epub_ready_root).expanduser().resolve()
        destination = Path(output_path).expanduser().resolve()
        if not root.is_dir():
            raise EpubPackageError(
                f"EPUB-ready root is not a directory: {root}"
            )
        if destination.suffix.lower() != ".epub":
            raise EpubPackageError("EPUB output path must end with .epub")

        manifest = _load_json_object(root / "manifest.json")
        if manifest.get("format") != "epub-ready-xhtml":
            raise EpubPackageError(
                "EPUB-ready manifest has unsupported or missing format"
            )
        title = _required_nonempty_string(manifest, "title")
        language = _optional_nonempty_string(manifest, "language") or "und"
        author = _optional_nonempty_string(manifest, "author")
        content_relative = _safe_relative_path(
            _required_nonempty_string(manifest, "content")
        )
        stylesheet_relative = _safe_relative_path(
            _required_nonempty_string(manifest, "stylesheet")
        )
        asset_relatives = _manifest_asset_paths(manifest)
        package_paths = (
            content_relative,
            stylesheet_relative,
            *asset_relatives,
        )
        if len(set(package_paths)) != len(package_paths):
            raise EpubPackageError(
                "EPUB-ready manifest paths must not overlap"
            )

        content_source = _require_file(root, content_relative)
        stylesheet_source = _require_file(root, stylesheet_relative)
        asset_sources = tuple(
            (relative, _require_file(root, relative))
            for relative in asset_relatives
        )
        semantic_payload = _load_json_object(root / "semantic" / "document.json")
        toc_entries = _collect_toc_entries(semantic_payload)

        resolved_identifier = identifier or _derive_identifier(
            root=root,
            title=title,
            language=language,
            author=author,
            content_relative=content_relative,
            stylesheet_relative=stylesheet_relative,
            asset_relatives=asset_relatives,
        )
        if not resolved_identifier.strip():
            raise EpubPackageError("publication identifier must not be empty")
        resolved_modified = _normalize_modified(modified)

        package_items = _build_manifest_items(
            content_relative=content_relative,
            stylesheet_relative=stylesheet_relative,
            asset_relatives=asset_relatives,
        )
        package_opf = _render_package_opf(
            title=title,
            language=language,
            author=author,
            identifier=resolved_identifier,
            modified=resolved_modified,
            items=package_items,
        )
        nav_xhtml = _render_nav_xhtml(
            title=title,
            language=language,
            content_relative=content_relative,
            entries=toc_entries,
        )
        container_xml = _render_container_xml()

        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary = destination.with_name(f".{destination.name}.tmp")
        try:
            with zipfile.ZipFile(temporary, "w") as archive:
                _write_zip_bytes(
                    archive,
                    "mimetype",
                    _EPUB_MIMETYPE,
                    compression=zipfile.ZIP_STORED,
                )
                _write_zip_text(
                    archive,
                    "META-INF/container.xml",
                    container_xml,
                )
                _write_zip_text(archive, "EPUB/package.opf", package_opf)
                _write_zip_text(archive, "EPUB/nav.xhtml", nav_xhtml)
                _write_zip_bytes(
                    archive,
                    f"EPUB/{content_relative.as_posix()}",
                    content_source.read_bytes(),
                )
                _write_zip_bytes(
                    archive,
                    f"EPUB/{stylesheet_relative.as_posix()}",
                    stylesheet_source.read_bytes(),
                )
                for relative, source in asset_sources:
                    _write_zip_bytes(
                        archive,
                        f"EPUB/{relative.as_posix()}",
                        source.read_bytes(),
                    )
            _validate_epub_archive(temporary)
            temporary.replace(destination)
        except (OSError, zipfile.BadZipFile, ElementTree.ParseError) as exc:
            temporary.unlink(missing_ok=True)
            raise EpubPackageError(f"EPUB package build failed: {exc}") from exc
        except EpubPackageError:
            temporary.unlink(missing_ok=True)
            raise

        return EpubPackageResult(
            epub_path=destination,
            identifier=resolved_identifier,
            modified=resolved_modified,
            manifest_item_count=len(package_items) + 1,
            toc_entry_count=len(toc_entries),
        )


def _load_json_object(path: Path) -> dict[str, Any]:
    """Load one UTF-8 JSON object with packaging-specific errors."""
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EpubPackageError(f"missing EPUB-ready artifact: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EpubPackageError(f"invalid JSON artifact: {path}") from exc
    if not isinstance(payload, dict):
        raise EpubPackageError(f"JSON artifact must be an object: {path}")
    return payload


def _required_nonempty_string(payload: dict[str, Any], key: str) -> str:
    """Return one required non-empty string field."""
    value = payload.get(key)
    if not isinstance(value, str) or not value.strip():
        raise EpubPackageError(f"manifest field {key!r} must be a non-empty string")
    return value.strip()


def _optional_nonempty_string(
    payload: dict[str, Any], key: str
) -> str | None:
    """Return one optional non-empty string field."""
    value = payload.get(key)
    if value is None:
        return None
    if not isinstance(value, str) or not value.strip():
        raise EpubPackageError(
            f"manifest field {key!r} must be null or a non-empty string"
        )
    return value.strip()


def _manifest_asset_paths(payload: dict[str, Any]) -> tuple[PurePosixPath, ...]:
    """Load and validate persisted asset paths from an EPUB-ready manifest."""
    values = payload.get("assets")
    if not isinstance(values, list):
        raise EpubPackageError("manifest field 'assets' must be a list")
    result: list[PurePosixPath] = []
    for value in values:
        if not isinstance(value, str) or not value.strip():
            raise EpubPackageError("manifest assets must be non-empty strings")
        result.append(_safe_relative_path(value))
    if len(set(result)) != len(result):
        raise EpubPackageError("manifest assets must not contain duplicates")
    return tuple(result)


def _safe_relative_path(value: str) -> PurePosixPath:
    """Validate one package-relative POSIX path."""
    relative = PurePosixPath(value)
    if relative.is_absolute() or not relative.parts:
        raise EpubPackageError(f"unsafe EPUB-ready path: {value!r}")
    if any(part in {"", ".", ".."} for part in relative.parts):
        raise EpubPackageError(f"unsafe EPUB-ready path: {value!r}")
    return relative


def _require_file(root: Path, relative: PurePosixPath) -> Path:
    """Resolve one safe source file beneath an EPUB-ready root."""
    candidate = (root / Path(*relative.parts)).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise EpubPackageError(
            f"EPUB-ready artifact escapes root: {relative.as_posix()}"
        ) from exc
    if not candidate.is_file():
        raise EpubPackageError(f"missing EPUB-ready artifact: {candidate}")
    return candidate


def _collect_toc_entries(payload: dict[str, Any]) -> tuple[EpubTocEntry, ...]:
    """Collect a flat TOC from semantic heading nodes in document order."""
    nodes = payload.get("nodes")
    if not isinstance(nodes, list):
        raise EpubPackageError("semantic document field 'nodes' must be a list")
    entries: list[EpubTocEntry] = []
    _collect_heading_nodes(nodes, entries)
    return tuple(entries)


def _collect_heading_nodes(
    nodes: list[Any], entries: list[EpubTocEntry]
) -> None:
    """Recursively collect heading nodes from semantic containers."""
    for node in nodes:
        if not isinstance(node, dict):
            raise EpubPackageError("semantic document nodes must be objects")
        node_type = node.get("type")
        if node_type == "heading":
            node_id = node.get("node_id")
            content = node.get("content")
            role = node.get("role")
            if not isinstance(node_id, str) or not node_id:
                raise EpubPackageError("semantic heading has invalid node_id")
            if not isinstance(role, str):
                raise EpubPackageError("semantic heading has invalid role")
            if _heading_role_is_navigable(role):
                label = _semantic_navigation_text(content).strip()
                if label:
                    entries.append(EpubTocEntry(label=label, target_id=node_id))
        children = node.get("children")
        if children is not None:
            if not isinstance(children, list):
                raise EpubPackageError(
                    "semantic container children must be a list"
                )
            _collect_heading_nodes(children, entries)


def _heading_role_is_navigable(role: str) -> bool:
    """Return whether one semantic heading role belongs in the EPUB TOC.

    Supporting labels such as subtitles are rendered in the reading flow but do not
    represent navigation hierarchy by themselves.
    """
    return role not in {"chapter_label", "subtitle", "genre_label"}


def _semantic_navigation_text(value: Any) -> str:
    """Flatten heading text for navigation while omitting footnote references."""
    if not isinstance(value, list):
        raise EpubPackageError("semantic text content must be a list")
    parts: list[str] = []
    omitted_reference = False
    for inline in value:
        if not isinstance(inline, dict):
            raise EpubPackageError("semantic inline values must be objects")
        text = inline.get("text")
        role = inline.get("role")
        if not isinstance(text, str):
            raise EpubPackageError("semantic inline text must be a string")
        if not isinstance(role, str):
            raise EpubPackageError("semantic inline role must be a string")
        if role == "footnote_ref":
            omitted_reference = bool(text.strip()) or omitted_reference
            continue
        if omitted_reference and parts and _needs_navigation_separator(parts[-1], text):
            parts.append(" ")
        parts.append(text)
        omitted_reference = False
    return "".join(parts)


def _needs_navigation_separator(previous: str, current: str) -> bool:
    """Return whether text split by an omitted noteref needs a readable space."""
    if not previous or not current:
        return False
    if previous[-1].isspace() or current[0].isspace():
        return False
    if current[0] in ",.;:!?)]}»”’":
        return False
    if previous[-1] in "([{«“‘/-":
        return False
    return True


def _derive_identifier(
    *,
    root: Path,
    title: str,
    language: str,
    author: str | None,
    content_relative: PurePosixPath,
    stylesheet_relative: PurePosixPath,
    asset_relatives: tuple[PurePosixPath, ...],
) -> str:
    """Derive a stable UUID URN from publication metadata and content bytes."""
    digest = hashlib.sha256()
    for value in (title, language, author or ""):
        digest.update(value.encode("utf-8"))
        digest.update(b"\0")
    for relative in (
        content_relative,
        stylesheet_relative,
        *sorted(asset_relatives, key=lambda item: item.as_posix()),
    ):
        digest.update(relative.as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(_require_file(root, relative).read_bytes())
        digest.update(b"\0")
    stable_uuid = uuid.uuid5(uuid.NAMESPACE_URL, f"siftforge:{digest.hexdigest()}")
    return f"urn:uuid:{stable_uuid}"


def _normalize_modified(value: str | None) -> str:
    """Return an EPUB 3 UTC modification timestamp."""
    if value is None:
        return datetime.now(UTC).replace(microsecond=0).strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        )
    if not _MODIFIED_PATTERN.fullmatch(value):
        raise EpubPackageError(
            "modified must use UTC format YYYY-MM-DDTHH:MM:SSZ"
        )
    try:
        datetime.strptime(value, "%Y-%m-%dT%H:%M:%SZ")
    except ValueError as exc:
        raise EpubPackageError(f"invalid modified timestamp: {value}") from exc
    return value


@dataclass(frozen=True, slots=True)
class _ManifestItem:
    """One OPF manifest item relative to ``EPUB/package.opf``."""

    item_id: str
    href: str
    media_type: str


def _build_manifest_items(
    *,
    content_relative: PurePosixPath,
    stylesheet_relative: PurePosixPath,
    asset_relatives: tuple[PurePosixPath, ...],
) -> tuple[_ManifestItem, ...]:
    """Build deterministic OPF manifest entries excluding the navigation item."""
    items = [
        _ManifestItem(
            item_id="content",
            href=content_relative.as_posix(),
            media_type="application/xhtml+xml",
        ),
        _ManifestItem(
            item_id="css",
            href=stylesheet_relative.as_posix(),
            media_type="text/css",
        ),
    ]
    for index, relative in enumerate(
        sorted(asset_relatives, key=lambda item: item.as_posix()),
        start=1,
    ):
        items.append(
            _ManifestItem(
                item_id=f"asset-{index:04d}",
                href=relative.as_posix(),
                media_type=_asset_media_type(relative),
            )
        )
    return tuple(items)


def _asset_media_type(relative: PurePosixPath) -> str:
    """Return an EPUB-compatible media type for one referenced asset."""
    suffix = relative.suffix.lower()
    types = {
        ".gif": "image/gif",
        ".jpeg": "image/jpeg",
        ".jpg": "image/jpeg",
        ".png": "image/png",
        ".svg": "image/svg+xml",
    }
    try:
        return types[suffix]
    except KeyError as exc:
        raise EpubPackageError(
            f"unsupported EPUB asset type: {relative.as_posix()}"
        ) from exc


def _render_container_xml() -> str:
    """Render the mandatory EPUB container document."""
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<container version="1.0" '
        'xmlns="urn:oasis:names:tc:opendocument:xmlns:container">\n'
        "  <rootfiles>\n"
        '    <rootfile full-path="EPUB/package.opf" '
        'media-type="application/oebps-package+xml" />\n'
        "  </rootfiles>\n"
        "</container>\n"
    )


def _render_package_opf(
    *,
    title: str,
    language: str,
    author: str | None,
    identifier: str,
    modified: str,
    items: tuple[_ManifestItem, ...],
) -> str:
    """Render a minimal EPUB 3 package document."""
    metadata = [
        f'    <dc:identifier id="pub-id">{_text(identifier)}</dc:identifier>',
        f"    <dc:title>{_text(title)}</dc:title>",
        f"    <dc:language>{_text(language)}</dc:language>",
    ]
    if author is not None:
        metadata.append(f"    <dc:creator>{_text(author)}</dc:creator>")
    metadata.append(
        f'    <meta property="dcterms:modified">{_text(modified)}</meta>'
    )

    manifest_lines = [
        '    <item id="nav" href="nav.xhtml" '
        'media-type="application/xhtml+xml" properties="nav" />'
    ]
    manifest_lines.extend(
        f'    <item id="{_attr(item.item_id)}" href="{_attr(item.href)}" '
        f'media-type="{_attr(item.media_type)}" />'
        for item in items
    )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<package xmlns="http://www.idpf.org/2007/opf" '
        'version="3.0" unique-identifier="pub-id">\n'
        '  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">\n'
        + "\n".join(metadata)
        + "\n  </metadata>\n"
        + "  <manifest>\n"
        + "\n".join(manifest_lines)
        + "\n  </manifest>\n"
        + "  <spine>\n"
        + '    <itemref idref="content" />\n'
        + "  </spine>\n"
        + "</package>\n"
    )


def _render_nav_xhtml(
    *,
    title: str,
    language: str,
    content_relative: PurePosixPath,
    entries: tuple[EpubTocEntry, ...],
) -> str:
    """Render the EPUB 3 navigation document from semantic headings."""
    navigation = entries or (EpubTocEntry(label=title, target_id=""),)
    items: list[str] = []
    for entry in navigation:
        href = content_relative.as_posix()
        if entry.target_id:
            href = f"{href}#{entry.target_id}"
        items.append(
            f'        <li><a href="{_attr(href)}">'
            f"{_text(entry.label)}</a></li>"
        )
    return (
        '<?xml version="1.0" encoding="utf-8"?>\n'
        '<!DOCTYPE html>\n'
        '<html xmlns="http://www.w3.org/1999/xhtml" '
        'xmlns:epub="http://www.idpf.org/2007/ops" '
        f'lang="{_attr(language)}" xml:lang="{_attr(language)}">\n'
        "  <head>\n"
        "    <meta charset=\"utf-8\" />\n"
        f"    <title>{_text(title)}</title>\n"
        "  </head>\n"
        "  <body>\n"
        '    <nav epub:type="toc" id="toc">\n'
        f"      <h1>{_text(title)}</h1>\n"
        "      <ol>\n"
        + "\n".join(items)
        + "\n      </ol>\n"
        + "    </nav>\n"
        + "  </body>\n"
        + "</html>\n"
    )


def _write_zip_text(
    archive: zipfile.ZipFile,
    member: str,
    text: str,
) -> None:
    """Write one UTF-8 text member with stable archive metadata."""
    _write_zip_bytes(archive, member, text.encode("utf-8"))


def _write_zip_bytes(
    archive: zipfile.ZipFile,
    member: str,
    data: bytes,
    *,
    compression: int = zipfile.ZIP_DEFLATED,
) -> None:
    """Write one EPUB archive member with deterministic ZIP metadata."""
    info = zipfile.ZipInfo(member, date_time=_FIXED_ZIP_TIMESTAMP)
    info.compress_type = compression
    info.create_system = 0
    info.external_attr = 0o600 << 16
    archive.writestr(info, data)


def _validate_epub_archive(path: Path) -> None:
    """Perform deterministic structural checks before publishing an EPUB."""
    try:
        with zipfile.ZipFile(path, "r") as archive:
            infos = archive.infolist()
            if not infos or infos[0].filename != "mimetype":
                raise EpubPackageError("EPUB mimetype must be the first ZIP member")
            if infos[0].compress_type != zipfile.ZIP_STORED:
                raise EpubPackageError("EPUB mimetype must be stored uncompressed")
            if archive.read("mimetype") != _EPUB_MIMETYPE:
                raise EpubPackageError("EPUB mimetype content is invalid")
            names = {info.filename for info in infos}
            required = {
                "META-INF/container.xml",
                "EPUB/package.opf",
                "EPUB/nav.xhtml",
            }
            missing = sorted(required - names)
            if missing:
                raise EpubPackageError(
                    f"EPUB archive is missing required members: {missing}"
                )
            for name in names:
                pure = PurePosixPath(name)
                if pure.is_absolute() or ".." in pure.parts:
                    raise EpubPackageError(f"unsafe EPUB member path: {name}")
            container = ElementTree.fromstring(
                archive.read("META-INF/container.xml")
            )
            rootfile = container.find(
                ".//{urn:oasis:names:tc:opendocument:xmlns:container}rootfile"
            )
            if rootfile is None or rootfile.get("full-path") != "EPUB/package.opf":
                raise EpubPackageError("container.xml does not reference package.opf")
            package = ElementTree.fromstring(archive.read("EPUB/package.opf"))
            namespace = {"opf": "http://www.idpf.org/2007/opf"}
            manifest_items = package.findall(".//opf:manifest/opf:item", namespace)
            for item in manifest_items:
                href = item.get("href")
                if href is None:
                    raise EpubPackageError("OPF manifest item has no href")
                member = f"EPUB/{href}"
                if member not in names:
                    raise EpubPackageError(
                        f"OPF manifest references missing member: {member}"
                    )
            nav = ElementTree.fromstring(archive.read("EPUB/nav.xhtml"))
            content_items = [
                item
                for item in manifest_items
                if item.get("id") == "content"
            ]
            if len(content_items) != 1:
                raise EpubPackageError("OPF must contain exactly one content item")
            content_href = content_items[0].get("href")
            if content_href is None:
                raise EpubPackageError("content manifest item has no href")
            content = ElementTree.fromstring(
                archive.read(f"EPUB/{content_href}")
            )
            content_ids = {
                element_id
                for element in content.iter()
                if (element_id := element.get("id")) is not None
            }
            xhtml = {"xhtml": "http://www.w3.org/1999/xhtml"}
            for anchor in nav.findall(".//xhtml:a", xhtml):
                href = anchor.get("href")
                if href is None or "#" not in href:
                    continue
                target_path, fragment = href.split("#", 1)
                if target_path == content_href and fragment not in content_ids:
                    raise EpubPackageError(
                        f"navigation target does not exist: {fragment}"
                    )
    except KeyError as exc:
        raise EpubPackageError(f"EPUB member is missing: {exc}") from exc


def _text(value: str) -> str:
    """Escape XML element text."""
    return html.escape(value, quote=False)


def _attr(value: str) -> str:
    """Escape XML attribute text."""
    return html.escape(value, quote=True)
