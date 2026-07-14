#!/usr/bin/env python3
"""Start the current immutable Review Desk version from its stable launcher."""

from __future__ import annotations

import sys


# Python normally prepends a script's directory to sys.path.  The stable
# installation directory is data, not an import root, so remove it before any
# shadowable standard-library import.  ``-I`` already omits that directory.
if __name__ == "__main__" and not sys.flags.isolated and sys.path:
    _SCRIPT_PATH_ENTRY = sys.path[0]
    sys.path[:] = [
        entry
        for index, entry in enumerate(sys.path)
        if index != 0 and entry not in {"", _SCRIPT_PATH_ENTRY}
    ]

import hashlib
import json
import os
import re
import stat
import unicodedata
from pathlib import Path, PurePosixPath


MANIFEST_NAME = "bundle-manifest.json"
LAUNCHERS = {"launch_installed_review_desk.py", "launch_review_desk.py"}


def _is_link_or_junction(path: Path) -> bool:
    if path.is_symlink():
        return True
    is_junction = getattr(path, "is_junction", None)
    if is_junction and is_junction():
        return True
    try:
        attributes = getattr(path.lstat(), "st_file_attributes", 0)
    except OSError:
        return False
    return bool(attributes & getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0))


def _strict_json_object(data: bytes, label: str) -> dict[str, object]:
    def reject_duplicates(pairs: list[tuple[str, object]]) -> dict[str, object]:
        value: dict[str, object] = {}
        for key, item in pairs:
            if key in value:
                raise ValueError(f"duplicate JSON key: {key}")
            value[key] = item
        return value

    def reject_constant(value: str) -> None:
        raise ValueError(f"non-standard JSON numeric constant: {value}")

    try:
        value = json.loads(
            data.decode("utf-8"),
            object_pairs_hook=reject_duplicates,
            parse_constant=reject_constant,
        )
    except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
        raise ValueError(f"{label} is invalid: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"{label} must be an object")
    return value


def _safe_manifest_path(raw: object) -> PurePosixPath:
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or ":" in raw
        or raw.startswith("/")
        or raw != unicodedata.normalize("NFC", raw)
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        raise ValueError(f"unsafe Review Desk manifest path: {raw!r}")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or any(part in {"", "."} or part != part.strip() or part.endswith(".") for part in path.parts)
        or raw != path.as_posix()
        or (raw not in LAUNCHERS and path.parts[0] != "app")
    ):
        raise ValueError(f"unsafe Review Desk manifest path: {raw!r}")
    return path


def _verify_exact_membership(root: Path, expected_files: set[str]) -> None:
    expected_directories = {""}
    for raw in expected_files:
        parts = PurePosixPath(raw).parts
        for length in range(1, len(parts)):
            expected_directories.add(PurePosixPath(*parts[:length]).as_posix())

    actual_files: set[str] = set()
    actual_directories: set[str] = set()

    def raise_walk_error(error: OSError) -> None:
        raise error

    for current, directories, names in os.walk(
        root,
        followlinks=False,
        onerror=raise_walk_error,
    ):
        current_path = Path(current)
        if _is_link_or_junction(current_path):
            raise ValueError("the selected Review Desk version contains a link or junction")
        relative_directory = current_path.relative_to(root).as_posix()
        actual_directories.add("" if relative_directory == "." else relative_directory)
        for name in directories:
            candidate = current_path / name
            if _is_link_or_junction(candidate) or not candidate.is_dir():
                raise ValueError("the selected Review Desk version contains an unsafe directory")
        for name in names:
            candidate = current_path / name
            if _is_link_or_junction(candidate) or not candidate.is_file():
                raise ValueError("the selected Review Desk version contains a non-regular file")
            actual_files.add(candidate.relative_to(root).as_posix())

    if actual_files != expected_files or actual_directories != expected_directories:
        raise ValueError("the selected Review Desk version differs from its exact manifest membership")


def _verified_launcher(version: Path, digest: str) -> Path:
    manifest_path = version / MANIFEST_NAME
    if _is_link_or_junction(manifest_path) or not manifest_path.is_file():
        raise ValueError("the selected Review Desk manifest is missing or unsafe")
    manifest_bytes = manifest_path.read_bytes()
    if hashlib.sha256(manifest_bytes).hexdigest() != digest:
        raise ValueError("the selected Review Desk manifest does not match its immutable digest")
    value = _strict_json_object(manifest_bytes, "Review Desk manifest")
    if set(value) != {"files", "package", "schema_version"}:
        raise ValueError("Review Desk manifest has unexpected fields")
    if value.get("package") != "econ-review-desk" or value.get("schema_version") != "1":
        raise ValueError("Review Desk manifest has the wrong package or schema version")
    records = value.get("files")
    if not isinstance(records, list) or not records or len(records) > 500:
        raise ValueError("Review Desk manifest files must be a non-empty bounded array")

    expected_files = {MANIFEST_NAME}
    checked: list[tuple[PurePosixPath, int, str]] = []
    previous = ""
    folded: set[str] = set()
    for record in records:
        if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
            raise ValueError("Review Desk manifest contains an invalid file record")
        path = _safe_manifest_path(record.get("path"))
        name = path.as_posix()
        if name <= previous or name.casefold() in folded:
            raise ValueError("Review Desk manifest file records must be sorted and portable-unique")
        previous = name
        folded.add(name.casefold())
        size = record.get("size")
        file_digest = record.get("sha256")
        if not isinstance(size, int) or isinstance(size, bool) or size < 0:
            raise ValueError(f"invalid Review Desk file size: {name}")
        if not isinstance(file_digest, str) or not re.fullmatch(r"[0-9a-f]{64}", file_digest):
            raise ValueError(f"invalid Review Desk file hash: {name}")
        expected_files.add(name)
        checked.append((path, size, file_digest))

    if not LAUNCHERS.issubset(expected_files) or "app/index.html" not in expected_files:
        raise ValueError("Review Desk manifest lacks its launchers or application entry point")
    _verify_exact_membership(version, expected_files)
    for path, size, file_digest in checked:
        candidate = version.joinpath(*path.parts)
        data = candidate.read_bytes()
        if len(data) != size or hashlib.sha256(data).hexdigest() != file_digest:
            raise ValueError(f"Review Desk file failed pre-launch authentication: {path}")
    return version / "launch_review_desk.py"


def main() -> int:
    root = Path(__file__).absolute().parent
    pointer = root / "current.json"
    if _is_link_or_junction(pointer) or not pointer.is_file():
        raise ValueError("Review Desk current-version pointer is missing or unsafe; rerun the installer")
    value = _strict_json_object(pointer.read_bytes(), "Review Desk current-version pointer")
    if set(value) != {"digest", "schema_version"}:
        raise ValueError("Review Desk current-version pointer is malformed; rerun the installer")
    digest = value.get("digest")
    if value.get("schema_version") != "1" or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Review Desk current-version pointer is invalid; rerun the installer")
    versions = root / "versions"
    version = versions / digest
    if (
        _is_link_or_junction(versions)
        or not versions.is_dir()
        or _is_link_or_junction(version)
        or not version.is_dir()
    ):
        raise ValueError("the selected Review Desk version is missing or unsafe; rerun the installer")
    launcher = _verified_launcher(version, digest)
    os.execv(sys.executable, [sys.executable, "-I", str(launcher), *sys.argv[1:]])
    return 1


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"Review Desk could not start: {exc}", file=sys.stderr)
        raise SystemExit(1)
