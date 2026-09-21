"""Create a human-owned proofreading workspace from EPUB-ready artifacts."""

from __future__ import annotations

import hashlib
import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any


class EbookProofError(ValueError):
    """Raised when a proofreading workspace cannot be prepared safely."""


@dataclass(frozen=True, slots=True)
class EbookProofStatus:
    """Current edit status of one persisted proof workspace."""

    proof_dir: Path
    editable_paths: tuple[Path, ...]
    modified_paths: tuple[Path, ...]

    @property
    def modified_count(self) -> int:
        """Return the number of human-edited XHTML files."""
        return len(self.modified_paths)


@dataclass(frozen=True, slots=True)
class EbookProofRun:
    """Artifacts created for one human proofreading workspace."""

    source_dir: Path
    proof_dir: Path
    manifest_path: Path
    editable_paths: tuple[Path, ...]

    @property
    def editable_count(self) -> int:
        """Return the number of XHTML documents intended for human editing."""
        return len(self.editable_paths)


class EbookProofService:
    """Create and inspect protected human-editable EPUB proof workspaces."""

    def inspect(self, proof_root: str | Path) -> EbookProofStatus:
        """Inspect a proof workspace and report which XHTML files changed.

        Args:
            proof_root: Existing human-owned proof workspace.

        Returns:
            Current editable files and those changed from the frozen baseline.

        Raises:
            EbookProofError: If the proof manifest or tracked files are invalid.
        """
        proof = Path(proof_root).expanduser().resolve()
        payload = _load_proof_manifest(proof)
        editable_values = payload.get("editable")
        baseline = payload.get("baseline_sha256")
        if not isinstance(editable_values, list) or not editable_values:
            raise EbookProofError("proof manifest editable list is missing or empty")
        if not isinstance(baseline, dict):
            raise EbookProofError("proof manifest baseline_sha256 must be an object")

        editable_paths: list[Path] = []
        modified_paths: list[Path] = []
        for value in editable_values:
            if not isinstance(value, str) or not value.strip():
                raise EbookProofError("proof manifest editable paths must be strings")
            relative = Path(value)
            if relative.is_absolute() or ".." in relative.parts:
                raise EbookProofError(f"unsafe proof editable path: {value!r}")
            path = (proof / relative).resolve()
            try:
                path.relative_to(proof)
            except ValueError as exc:
                raise EbookProofError(
                    f"proof editable path escapes workspace: {value!r}"
                ) from exc
            if not path.is_file():
                raise EbookProofError(f"missing proof editable file: {path}")
            expected = baseline.get(value)
            if not isinstance(expected, str) or not expected:
                raise EbookProofError(
                    f"missing baseline hash for proof file: {value}"
                )
            editable_paths.append(path)
            if _sha256_file(path) != expected:
                modified_paths.append(path)

        return EbookProofStatus(
            proof_dir=proof,
            editable_paths=tuple(editable_paths),
            modified_paths=tuple(modified_paths),
        )

    def prepare(
        self,
        epub_ready_root: str | Path,
        proof_root: str | Path,
        *,
        force: bool = False,
    ) -> EbookProofRun:
        """Copy EPUB-ready artifacts into a human-owned proof workspace.

        The proof directory is never replaced unless ``force`` is explicitly
        requested. This prevents a later machine rebuild from silently erasing
        manual proofreading changes.

        Args:
            epub_ready_root: Generated EPUB-ready directory to freeze for review.
            proof_root: Destination human-owned proofreading directory.
            force: Explicitly replace an existing proof directory.

        Returns:
            Paths describing the newly prepared proof workspace.

        Raises:
            EbookProofError: If paths are unsafe or source artifacts are invalid.
        """
        source = Path(epub_ready_root).expanduser().resolve()
        proof = Path(proof_root).expanduser().resolve()
        if not source.is_dir():
            raise EbookProofError(f"EPUB-ready root is not a directory: {source}")
        _require_epub_ready_manifest(source)
        _validate_distinct_trees(source, proof)

        if proof.exists():
            if proof.is_symlink():
                raise EbookProofError(
                    f"refusing to replace symlinked proof path: {proof}"
                )
            if not force:
                raise EbookProofError(
                    "proof workspace already exists; refusing to overwrite "
                    f"human edits: {proof} (use --force only intentionally)"
                )
            if not proof.is_dir():
                raise EbookProofError(f"proof path is not a directory: {proof}")
            shutil.rmtree(proof)

        proof.parent.mkdir(parents=True, exist_ok=True)
        try:
            shutil.copytree(source, proof)
        except OSError as exc:
            raise EbookProofError(f"failed to create proof workspace: {exc}") from exc

        editable_paths = tuple(
            sorted(
                path
                for path in (proof / "text").glob("*.xhtml")
                if path.is_file()
            )
        )
        if not editable_paths:
            shutil.rmtree(proof, ignore_errors=True)
            raise EbookProofError(
                "EPUB-ready source contains no text/*.xhtml files to proofread"
            )

        manifest_path = proof / "proof-manifest.json"
        manifest_path.write_text(
            json.dumps(
                _proof_manifest_payload(
                    source=source,
                    proof=proof,
                    editable_paths=editable_paths,
                ),
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )
        return EbookProofRun(
            source_dir=source,
            proof_dir=proof,
            manifest_path=manifest_path,
            editable_paths=editable_paths,
        )


def _load_proof_manifest(root: Path) -> dict[str, Any]:
    """Load and validate one human-proof workspace manifest."""
    if not root.is_dir():
        raise EbookProofError(f"proof root is not a directory: {root}")
    path = root / "proof-manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EbookProofError(f"missing proof manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EbookProofError(f"invalid proof manifest JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise EbookProofError("proof manifest must be a JSON object")
    if payload.get("format") != "siftforge-ebook-proof-v1":
        raise EbookProofError("unsupported or missing proof manifest format")
    return payload


def _require_epub_ready_manifest(root: Path) -> dict[str, Any]:
    """Load and minimally validate the source EPUB-ready manifest."""
    path = root / "manifest.json"
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise EbookProofError(f"missing EPUB-ready manifest: {path}") from exc
    except json.JSONDecodeError as exc:
        raise EbookProofError(f"invalid EPUB-ready manifest JSON: {path}") from exc
    if not isinstance(payload, dict):
        raise EbookProofError("EPUB-ready manifest must be a JSON object")
    if payload.get("format") != "epub-ready-xhtml":
        raise EbookProofError(
            "EPUB-ready manifest has unsupported or missing format"
        )
    return payload


def _validate_distinct_trees(source: Path, proof: Path) -> None:
    """Reject overlapping source/proof trees that make copying destructive."""
    if source == proof:
        raise EbookProofError("proof directory must differ from EPUB-ready source")
    if _is_relative_to(proof, source):
        raise EbookProofError("proof directory must not be inside EPUB-ready source")
    if _is_relative_to(source, proof):
        raise EbookProofError("EPUB-ready source must not be inside proof directory")


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is beneath ``parent`` without raising."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True


def _proof_manifest_payload(
    *,
    source: Path,
    proof: Path,
    editable_paths: tuple[Path, ...],
) -> dict[str, object]:
    """Build provenance and baseline hashes for one new proof workspace."""
    return {
        "format": "siftforge-ebook-proof-v1",
        "policy": "human-owned-do-not-overwrite",
        "source_epub_ready": str(source),
        "proof_root": str(proof),
        "editable": [path.relative_to(proof).as_posix() for path in editable_paths],
        "baseline_sha256": {
            path.relative_to(proof).as_posix(): _sha256_file(path)
            for path in editable_paths
        },
        "notes": (
            "Edit text/*.xhtml as the final human proofreading layer. "
            "Preserve XHTML structure, element ids, links, and filenames."
        ),
    }


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 digest of one proof baseline file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
