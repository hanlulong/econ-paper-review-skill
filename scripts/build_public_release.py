#!/usr/bin/env python3
"""Validate and build a deterministic, source-allowlisted public release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_NAME = "econ-paper-review-skill"
ARCHIVE_FORMAT_VERSION = 1
FILE_CONTRACT = Path("scripts/public-release-files.json")
SCAN_ROOTS = (
    Path(".github"),
    Path("benchmarks"),
    Path("econ-review"),
    Path("review-viewer"),
    Path("scripts"),
    Path("tests"),
)
EXCLUDED_RELATIVE_PREFIXES = {Path("benchmarks/reviews")}
ROOT_FILES = {
    Path(".gitignore"),
    Path("LICENSE"),
    Path("README.md"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("install.sh"),
    Path("requirements-docling.txt"),
    Path("requirements-markitdown.txt"),
    Path("requirements-mathpix.txt"),
    Path("requirements.txt"),
}
EXCLUDED_DIRECTORY_NAMES = {
    ".mypy_cache",
    ".next",
    ".nox",
    ".nyc_output",
    ".pytest_cache",
    ".ruff_cache",
    ".tox",
    ".venv",
    ".vite",
    ".vinext",
    ".wrangler",
    "__pycache__",
    "coverage",
    "dist",
    "node_modules",
    "outputs",
    "public",
    "venv",
    "work",
}
EXCLUDED_FILE_NAMES = {".DS_Store", ".coverage", "tsconfig.tsbuildinfo"}
TEXT_SUFFIXES = {
    "",
    ".css",
    ".html",
    ".js",
    ".json",
    ".md",
    ".mjs",
    ".py",
    ".sh",
    ".toml",
    ".ts",
    ".tsx",
    ".txt",
    ".yaml",
    ".yml",
}
SENSITIVE_FILENAME = re.compile(r"(?:^|[-_.])(client|confidential|private|secret)(?:[-_.]|$)", re.I)
SENSITIVE_CONTENT = {
    "private home path": re.compile(r"/(?:Users|home)/[A-Za-z0-9_.-]+/"),
    "Windows user path": re.compile(r"[A-Za-z]:\\Users\\[^\\\r\n]+\\"),
    "private key": re.compile(r"-----BEGIN (?:RSA |OPENSSH |EC |DSA )?PRIVATE KEY-----"),
    "AWS access key": re.compile(r"(?<![A-Z0-9])AKIA[0-9A-Z]{16}(?![A-Z0-9])"),
    "GitHub token": re.compile(r"(?<![A-Za-z0-9_])gh[pousr]_[A-Za-z0-9_]{36,255}"),
    "GitHub fine-grained token": re.compile(r"(?<![A-Za-z0-9_])github_pat_[A-Za-z0-9_]{40,255}"),
    "OpenAI API key": re.compile(r"(?<![A-Za-z0-9_-])sk-(?:proj-)?[A-Za-z0-9_-]{20,}"),
    "Anthropic API key": re.compile(r"(?<![A-Za-z0-9_-])sk-ant-[A-Za-z0-9_-]{20,}"),
    "Slack token": re.compile(r"(?<![A-Za-z0-9_-])xox[baprs]-[A-Za-z0-9-]{20,}"),
    "Google API key": re.compile(r"(?<![A-Za-z0-9_-])AIza[0-9A-Za-z_-]{35}(?![A-Za-z0-9_-])"),
}
# These tests verify path redaction using exact synthetic home prefixes. Only
# the declared match text is allowed; another home path in the same file fails.
CONTENT_SCAN_ALLOWED_MATCHES = {
    "review-viewer/tests/review-actions.test.mjs": {"private home path": {"/" + "Users/researcher/"}},
    "tests/test_validate_review_actions.py": {"private home path": {"/" + "Users/person/"}},
}
WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


def _canonical_json(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise ValueError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise ValueError(f"non-standard JSON numeric constant: {value}")


def _release_mode(path: Path) -> int:
    """Canonicalize modes so archives do not depend on checkout umasks."""
    return 0o755 if stat.S_IMODE(path.stat().st_mode) & 0o111 else 0o644


def _safe_relative(raw: str) -> Path:
    pure = PurePosixPath(raw)
    if (
        not raw
        or raw.startswith("/")
        or "\\" in raw
        or ":" in raw
        or raw != unicodedata.normalize("NFC", raw)
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
        or pure.is_absolute()
        or ".." in pure.parts
    ):
        raise ValueError(f"unsafe path in public file contract: {raw!r}")
    if raw != pure.as_posix() or any(
        part in {"", "."}
        or part != part.strip()
        or part.endswith(".")
        or part.split(".", 1)[0].casefold() in WINDOWS_RESERVED_BASENAMES
        for part in pure.parts
    ):
        raise ValueError(f"non-canonical path in public file contract: {raw!r}")
    return Path(*pure.parts)


def load_file_contract(root: Path) -> tuple[dict[str, Any], list[Path]]:
    path = root / FILE_CONTRACT
    if not path.is_file() or path.is_symlink():
        raise ValueError(f"required public file contract is missing or unsafe: {FILE_CONTRACT}")
    try:
        contract = json.loads(
            path.read_text(encoding="utf-8"),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"invalid public file contract: {exc}") from exc
    if not isinstance(contract, dict) or set(contract) != {"schema_version", "files"}:
        raise ValueError("public file contract must contain exactly schema_version and files")
    if contract.get("schema_version") != "1":
        raise ValueError("public file contract must use schema_version '1'")
    raw_files = contract.get("files")
    if not isinstance(raw_files, list) or not raw_files or not all(isinstance(item, str) for item in raw_files):
        raise ValueError("public file contract files must be a non-empty string array")
    if raw_files != sorted(raw_files) or len(raw_files) != len(set(raw_files)):
        raise ValueError("public file contract files must be sorted and unique")
    if len({unicodedata.normalize("NFC", item).casefold() for item in raw_files}) != len(raw_files):
        raise ValueError("public file contract files must not collide by case")
    files = [_safe_relative(raw) for raw in raw_files]
    scan_root_names = {path.as_posix() for path in SCAN_ROOTS}
    for relative in files:
        if len(relative.parts) == 1:
            if relative not in ROOT_FILES:
                raise ValueError(f"undeclared top-level release contract path: {relative.as_posix()}")
        elif relative.parts[0] not in scan_root_names:
            raise ValueError(f"path is outside public release roots: {relative.as_posix()}")
    if FILE_CONTRACT not in files:
        raise ValueError(f"public file contract must list itself: {FILE_CONTRACT}")
    return contract, files


def _discover_release_candidates(root: Path) -> set[Path]:
    candidates: set[Path] = set()
    for base_relative in SCAN_ROOTS:
        base = root / base_relative
        if not base.is_dir() or base.is_symlink():
            raise ValueError(f"required public tree is missing or unsafe: {base_relative}")
        for path in base.rglob("*"):
            relative = path.relative_to(root)
            if any(relative == prefix or prefix in relative.parents for prefix in EXCLUDED_RELATIVE_PREFIXES):
                continue
            if any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1]):
                continue
            if path.name in EXCLUDED_FILE_NAMES or path.suffix in {".pyc", ".pyo"}:
                continue
            if path.is_symlink():
                raise ValueError(f"public release refuses symbolic link: {relative.as_posix()}")
            if path.is_file():
                candidates.add(relative)
    return candidates


def _scan_content(root: Path, files: list[Path]) -> None:
    findings: list[str] = []
    for relative in files:
        display = relative.as_posix()
        if SENSITIVE_FILENAME.search(relative.name):
            findings.append(f"{display}: sensitive filename")
        if relative.suffix.lower() not in TEXT_SUFFIXES:
            continue
        data = (root / relative).read_bytes()
        if b"\x00" in data:
            continue
        try:
            text = data.decode("utf-8")
        except UnicodeDecodeError as exc:
            findings.append(f"{display}: text-like file is not UTF-8 ({exc})")
            continue
        allowed_matches = CONTENT_SCAN_ALLOWED_MATCHES.get(display, {})
        for label, pattern in SENSITIVE_CONTENT.items():
            matches = {match.group(0) for match in pattern.finditer(text)}
            if matches - allowed_matches.get(label, set()):
                findings.append(f"{display}: possible {label}")
    if findings:
        raise ValueError("privacy scan failed:\n  " + "\n  ".join(sorted(findings)))


def public_files(root: Path) -> list[Path]:
    """Return the exact, stable, symlink-free public file contract."""
    root = root.resolve()
    _, files = load_file_contract(root)
    declared = set(files)
    discovered = _discover_release_candidates(root)
    discovered.update(relative for relative in ROOT_FILES if (root / relative).is_file())
    unknown = sorted(discovered - declared)
    missing = sorted(declared - discovered)
    if unknown:
        joined = ", ".join(path.as_posix() for path in unknown[:12])
        suffix = " ..." if len(unknown) > 12 else ""
        raise ValueError(f"undeclared file(s) in public trees: {joined}{suffix}")
    if missing:
        joined = ", ".join(path.as_posix() for path in missing[:12])
        suffix = " ..." if len(missing) > 12 else ""
        raise ValueError(f"declared public file(s) missing: {joined}{suffix}")
    for relative in files:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"required public file is missing or unsafe: {relative.as_posix()}")
    _scan_content(root, files)
    return files


def release_metadata(root: Path, files: list[Path]) -> dict[str, Any]:
    contract_bytes = (root / FILE_CONTRACT).read_bytes()
    entries = []
    for relative in files:
        data = (root / relative).read_bytes()
        entries.append(
            {
                "mode": _release_mode(root / relative),
                "path": relative.as_posix(),
                "sha256": _sha256(data),
                "size": len(data),
            }
        )
    return {
        "archive_format_version": ARCHIVE_FORMAT_VERSION,
        "file_contract_sha256": _sha256(contract_bytes),
        "files": entries,
        "package": PACKAGE_NAME,
    }


def build_zip(root: Path, destination: Path, files: list[Path]) -> dict[str, Any]:
    """Atomically write a deterministic release ZIP and return its metadata."""
    root = root.resolve()
    destination = destination.expanduser().absolute()
    if destination.exists() or destination.is_symlink():
        raise ValueError(f"output already exists: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    metadata = release_metadata(root, files)
    fd, temporary_name = tempfile.mkstemp(prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent)
    os.close(fd)
    temporary = Path(temporary_name)
    records_by_path = {record["path"]: record for record in metadata["files"]}
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            for relative in files:
                source = root / relative
                if not source.is_file() or source.is_symlink():
                    raise ValueError(f"public file changed or became unsafe during release build: {relative.as_posix()}")
                data = source.read_bytes()
                record = records_by_path[relative.as_posix()]
                if (
                    len(data) != record["size"]
                    or _sha256(data) != record["sha256"]
                    or _release_mode(source) != record["mode"]
                ):
                    raise ValueError(f"public file changed during release build: {relative.as_posix()}")
                info = zipfile.ZipInfo(f"{PACKAGE_NAME}/{relative.as_posix()}", date_time=(1980, 1, 1, 0, 0, 0))
                info.compress_type = zipfile.ZIP_DEFLATED
                info.create_system = 3
                info.external_attr = (stat.S_IFREG | _release_mode(source)) << 16
                archive.writestr(info, data)
            manifest_info = zipfile.ZipInfo(
                f"{PACKAGE_NAME}/RELEASE-MANIFEST.json", date_time=(1980, 1, 1, 0, 0, 0)
            )
            manifest_info.compress_type = zipfile.ZIP_DEFLATED
            manifest_info.create_system = 3
            manifest_info.external_attr = (stat.S_IFREG | 0o644) << 16
            archive.writestr(manifest_info, _canonical_json(metadata))
        os.replace(temporary, destination)
    except BaseException:
        temporary.unlink(missing_ok=True)
        raise
    return metadata


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--check", action="store_true", help="Check the file contract and privacy scan")
    parser.add_argument("--output", type=Path, help="Write the verified release as a deterministic ZIP")
    args = parser.parse_args()
    if not args.check and not args.output:
        parser.error("choose --check and/or --output")
    try:
        root = args.root.expanduser().resolve()
        files = public_files(root)
        if args.output:
            destination = args.output.expanduser().absolute()
            build_zip(root, destination, files)
            digest = _sha256(destination.read_bytes())
            print(f"public release archive written: {destination} ({len(files)} files)")
            print(f"sha256: {digest}")
        else:
            print(f"public release contract and privacy scan passed: {len(files)} files")
    except (OSError, ValueError, zipfile.BadZipFile) as exc:
        parser.exit(1, f"public release check failed: {exc}\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
