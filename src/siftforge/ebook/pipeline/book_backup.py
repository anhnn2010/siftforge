"""Create a compact, Git-friendly backup of one human-proofed ebook."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from .proof import EbookProofError, EbookProofService


class EbookBookBackupError(ValueError):
    """Raised when a book backup cannot be created safely."""


@dataclass(frozen=True, slots=True)
class EbookBookBackupRun:
    """Artifacts synchronized into one Git-friendly book backup directory."""

    output_dir: Path
    proof_dir: Path
    manifest_path: Path
    metadata_path: Path | None
    review_resolutions_path: Path | None
    build_info_path: Path | None
    editable_count: int
    modified_count: int


class EbookBookBackupService:
    """Synchronize durable book artifacts without copying extraction caches."""

    def backup(
        self,
        runs_root: str | Path,
        proof_root: str | Path,
        output_root: str | Path,
    ) -> EbookBookBackupRun:
        """Back up human-owned ebook artifacts into a Git-friendly directory.

        The destination may already be a Git working tree. Only SiftForge-managed
        backup paths are replaced; unrelated files and ``.git`` are preserved.

        Args:
            runs_root: Canonical page-run directory for the book.
            proof_root: Human-owned proof workspace created by ``prepare-proof``.
            output_root: Destination directory to commit with Git.

        Returns:
            Paths and counts describing the synchronized backup.

        Raises:
            EbookBookBackupError: If source or destination paths are unsafe.
        """
        runs = Path(runs_root).expanduser().resolve()
        proof = Path(proof_root).expanduser().resolve()
        output = Path(output_root).expanduser().resolve()

        if not runs.is_dir():
            raise EbookBookBackupError(f"page-runs root is not a directory: {runs}")
        if not proof.is_dir():
            raise EbookBookBackupError(f"proof root is not a directory: {proof}")
        _validate_disjoint_backup_trees(runs=runs, proof=proof, output=output)

        try:
            proof_status = EbookProofService().inspect(proof)
        except EbookProofError as exc:
            raise EbookBookBackupError(str(exc)) from exc

        if output.exists():
            if output.is_symlink():
                raise EbookBookBackupError(
                    f"refusing to use symlinked backup directory: {output}"
                )
            if not output.is_dir():
                raise EbookBookBackupError(
                    f"backup output is not a directory: {output}"
                )
        else:
            output.mkdir(parents=True)

        destination_proof = output / "proof"
        _replace_tree(source=proof, destination=destination_proof)

        metadata_path = _sync_optional_file(
            source=runs / "metadata.json",
            destination=output / "metadata.json",
        )
        review_resolutions_path = _sync_optional_file(
            source=runs / "review" / "resolutions.json",
            destination=output / "review" / "resolutions.json",
        )
        build_info_path = _sync_build_info(
            source=proof.parent / "build-manifest.json",
            destination=output / "build-info.json",
        )

        modified_paths = tuple(
            path.relative_to(proof).as_posix()
            for path in proof_status.modified_paths
        )
        manifest_path = output / "backup-manifest.json"
        _require_safe_managed_file(manifest_path)
        manifest_payload = {
            "format": "siftforge-book-backup-v1",
            "policy": "git-friendly-human-work",
            "artifacts": {
                "proof": "proof",
                "metadata": "metadata.json" if metadata_path is not None else None,
                "review_resolutions": (
                    "review/resolutions.json"
                    if review_resolutions_path is not None
                    else None
                ),
                "build_info": (
                    "build-info.json" if build_info_path is not None else None
                ),
            },
            "proof": {
                "editable_xhtml": len(proof_status.editable_paths),
                "modified_xhtml": list(modified_paths),
            },
            "notes": (
                "Commit this directory with Git. proof/ is the human-owned master; "
                "machine extraction caches are intentionally excluded."
            ),
        }
        manifest_path.write_text(
            json.dumps(manifest_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

        return EbookBookBackupRun(
            output_dir=output,
            proof_dir=destination_proof,
            manifest_path=manifest_path,
            metadata_path=metadata_path,
            review_resolutions_path=review_resolutions_path,
            build_info_path=build_info_path,
            editable_count=len(proof_status.editable_paths),
            modified_count=proof_status.modified_count,
        )


def _replace_tree(*, source: Path, destination: Path) -> None:
    """Replace one managed destination tree while preserving its parent."""
    if destination.exists() or destination.is_symlink():
        if destination.is_symlink():
            raise EbookBookBackupError(
                f"refusing to replace symlinked managed path: {destination}"
            )
        if not destination.is_dir():
            raise EbookBookBackupError(
                f"managed proof backup path is not a directory: {destination}"
            )
        shutil.rmtree(destination)
    try:
        shutil.copytree(source, destination)
    except OSError as exc:
        raise EbookBookBackupError(f"failed to copy proof workspace: {exc}") from exc


def _sync_optional_file(*, source: Path, destination: Path) -> Path | None:
    """Mirror an optional managed file and remove stale backup copies."""
    if not source.is_file():
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise EbookBookBackupError(
                    f"refusing to replace unsafe managed file path: {destination}"
                )
            destination.unlink()
        _remove_empty_parent(destination.parent)
        return None

    if destination.is_symlink():
        raise EbookBookBackupError(
            f"refusing to replace symlinked managed file: {destination}"
        )
    if destination.exists() and not destination.is_file():
        raise EbookBookBackupError(
            f"managed backup file path is not a regular file: {destination}"
        )
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        shutil.copy2(source, destination)
    except OSError as exc:
        raise EbookBookBackupError(
            f"failed to copy backup artifact {source}: {exc}"
        ) from exc
    return destination


def _sync_build_info(*, source: Path, destination: Path) -> Path | None:
    """Write a portable subset of the provider-free build manifest."""
    if not source.is_file():
        if destination.exists() or destination.is_symlink():
            if destination.is_symlink() or not destination.is_file():
                raise EbookBookBackupError(
                    f"refusing to replace unsafe build-info path: {destination}"
                )
            destination.unlink()
        return None

    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise EbookBookBackupError(f"invalid build manifest JSON: {source}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("format") != "siftforge-ebook-build"
    ):
        raise EbookBookBackupError(
            f"unsupported or missing build manifest format: {source}"
        )

    stages = payload.get("stages")
    stage_map = stages if isinstance(stages, dict) else {}
    compact: dict[str, Any] = {
        "format": "siftforge-book-build-info-v1",
        "excluded_pages": payload.get("excluded_pages", []),
        "metadata": payload.get("metadata"),
        "package": stage_map.get("package"),
        "epubcheck": stage_map.get("epubcheck"),
    }
    _require_safe_managed_file(destination)
    destination.write_text(
        json.dumps(compact, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return destination



def _require_safe_managed_file(path: Path) -> None:
    """Reject symlinks or non-file objects at one managed output path."""
    if path.is_symlink():
        raise EbookBookBackupError(
            f"refusing to replace symlinked managed file: {path}"
        )
    if path.exists() and not path.is_file():
        raise EbookBookBackupError(
            f"managed backup path is not a regular file: {path}"
        )

def _remove_empty_parent(path: Path) -> None:
    """Remove an empty managed subdirectory without touching user content."""
    try:
        path.rmdir()
    except OSError:
        pass


def _validate_disjoint_backup_trees(
    *,
    runs: Path,
    proof: Path,
    output: Path,
) -> None:
    """Reject source/destination overlap that could recursively destroy data."""
    for source, label in ((runs, "page-runs"), (proof, "proof")):
        if output == source or _is_relative_to(output, source):
            raise EbookBookBackupError(
                f"backup output must not be inside {label} source: {source}"
            )
        if _is_relative_to(source, output):
            raise EbookBookBackupError(
                f"{label} source must not be inside backup output: {output}"
            )


def _is_relative_to(path: Path, parent: Path) -> bool:
    """Return whether ``path`` is below ``parent`` without raising."""
    try:
        path.relative_to(parent)
    except ValueError:
        return False
    return True
