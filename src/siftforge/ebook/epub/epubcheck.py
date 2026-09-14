"""External EPUBCheck standards validation for generated EPUB archives."""

from __future__ import annotations

import hashlib
import json
import subprocess
import time
from dataclasses import dataclass
from pathlib import Path


class EpubCheckExecutionError(RuntimeError):
    """Raised when EPUBCheck cannot be launched or complete normally."""


@dataclass(frozen=True, slots=True)
class EpubCheckResult:
    """Captured result of one EPUBCheck validation run."""

    epub_path: Path
    epubcheck_jar: Path
    java_command: str
    command: tuple[str, ...]
    passed: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_seconds: float
    epub_sha256: str
    epubcheck_jar_sha256: str

    def to_dict(self) -> dict[str, object]:
        """Serialize the validation result for CI or artifact persistence."""
        return {
            "tool": "epubcheck",
            "passed": self.passed,
            "exit_code": self.exit_code,
            "epub": str(self.epub_path),
            "epubcheck_jar": str(self.epubcheck_jar),
            "java_command": self.java_command,
            "command": list(self.command),
            "duration_seconds": self.duration_seconds,
            "epub_sha256": self.epub_sha256,
            "epubcheck_jar_sha256": self.epubcheck_jar_sha256,
            "stdout": self.stdout,
            "stderr": self.stderr,
        }

    def to_json(self) -> str:
        """Render the captured result as deterministic human-readable JSON."""
        return json.dumps(
            self.to_dict(),
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        ) + "\n"


class EpubCheckRunner:
    """Run the official EPUBCheck JAR as an external validation gate."""

    def __init__(
        self,
        *,
        java_command: str = "java",
        timeout_seconds: float = 120.0,
    ) -> None:
        """Configure the Java launcher and validation timeout.

        Args:
            java_command: Java executable or command available to subprocess.
            timeout_seconds: Maximum duration allowed for one EPUBCheck run.
        """
        if not java_command.strip():
            raise ValueError("java_command must not be empty")
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be greater than zero")
        self._java_command = java_command
        self._timeout_seconds = timeout_seconds

    def validate(
        self,
        epub_path: str | Path,
        epubcheck_jar: str | Path,
    ) -> EpubCheckResult:
        """Validate one EPUB archive with the supplied EPUBCheck JAR.

        EPUBCheck validation errors are represented by a normal result with
        ``passed=False``. Configuration, launch, and timeout failures raise
        ``EpubCheckExecutionError`` instead.
        """
        epub = Path(epub_path).expanduser().resolve()
        jar = Path(epubcheck_jar).expanduser().resolve()
        if not epub.is_file():
            raise EpubCheckExecutionError(f"EPUB file does not exist: {epub}")
        if not jar.is_file():
            raise EpubCheckExecutionError(
                f"EPUBCheck JAR does not exist: {jar}"
            )

        command = (
            self._java_command,
            "-jar",
            str(jar),
            str(epub),
        )
        started = time.monotonic()
        try:
            completed = subprocess.run(
                command,
                check=False,
                capture_output=True,
                text=True,
                encoding="utf-8",
                errors="replace",
                timeout=self._timeout_seconds,
            )
        except FileNotFoundError as exc:
            raise EpubCheckExecutionError(
                f"Java command was not found: {self._java_command}"
            ) from exc
        except subprocess.TimeoutExpired as exc:
            raise EpubCheckExecutionError(
                "EPUBCheck timed out after "
                f"{self._timeout_seconds:g} seconds"
            ) from exc
        except OSError as exc:
            raise EpubCheckExecutionError(
                f"failed to launch EPUBCheck: {exc}"
            ) from exc
        duration = time.monotonic() - started

        return EpubCheckResult(
            epub_path=epub,
            epubcheck_jar=jar,
            java_command=self._java_command,
            command=command,
            passed=completed.returncode == 0,
            exit_code=completed.returncode,
            stdout=completed.stdout,
            stderr=completed.stderr,
            duration_seconds=duration,
            epub_sha256=_sha256_file(epub),
            epubcheck_jar_sha256=_sha256_file(jar),
        )


def _sha256_file(path: Path) -> str:
    """Return the SHA-256 hex digest for one local file."""
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()
