#!/usr/bin/env python3
"""Symlink-resistant, contained, atomic file I/O for review packages."""

from __future__ import annotations

import hashlib
import json
import os
import stat
import tempfile
import unicodedata
from pathlib import Path
from typing import Any


_WINDOWS_RESERVED_BASENAMES = frozenset(
    {"con", "prn", "aux", "nul", "clock$"}
    | {f"com{number}" for number in range(1, 10)}
    | {f"lpt{number}" for number in range(1, 10)}
)


class StrictJsonError(ValueError):
    """Raised when JSON is syntactically accepted by Python but contract-ambiguous."""


def _reject_duplicate_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for key, item in pairs:
        if key in value:
            raise StrictJsonError(f"duplicate JSON key: {key}")
        value[key] = item
    return value


def _reject_json_constant(value: str) -> None:
    raise StrictJsonError(f"non-standard JSON numeric constant: {value}")


def strict_json_loads(value: str | bytes | bytearray) -> Any:
    """Parse standards-compliant JSON while rejecting duplicate object keys.

    Python's default decoder accepts duplicate keys with last-value-wins
    semantics and also accepts NaN/Infinity. Both behaviors make signed review
    artifacts ambiguous across implementations, so every contract-bearing
    loader uses this function instead.
    """
    return json.loads(
        value,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_json_constant,
    )


def strict_json_load(path: Path) -> Any:
    return strict_json_loads(path.read_text(encoding="utf-8"))


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def canonical_portable_path(value: str) -> str:
    """Return a browser/ZIP-portable canonical relative package path.

    Review receipts are consumed by Python and browser runtimes on different
    filesystems. Reject aliases and names whose meaning differs across those
    runtimes instead of signing a package that the viewer cannot verify.
    """
    if not isinstance(value, str) or not value:
        raise ValueError("package path must be a nonempty string")
    if value != value.strip() or value != unicodedata.normalize("NFC", value):
        raise ValueError(f"package path is not canonical Unicode text: {value!r}")
    if value.startswith("/") or "\\" in value or ":" in value:
        raise ValueError(f"package path is not portable: {value!r}")
    if any(ord(character) < 32 or ord(character) == 127 for character in value):
        raise ValueError(f"package path contains a control character: {value!r}")
    parts = value.split("/")
    if any(
        part in {"", ".", ".."}
        or part != part.strip()
        or part.endswith(".")
        or part.split(".", 1)[0].casefold() in _WINDOWS_RESERVED_BASENAMES
        for part in parts
    ):
        raise ValueError(f"package path is not a canonical relative path: {value!r}")
    return "/".join(parts)


def _contained_path(root: Path, relative: str | Path, *, create_parents: bool) -> Path:
    root = root.resolve(strict=True)
    rel = Path(relative)
    if rel.is_absolute() or not rel.parts or ".." in rel.parts:
        raise ValueError(f"path must stay inside review directory: {relative}")
    current = root
    for part in rel.parts[:-1]:
        current = current / part
        if current.exists() or current.is_symlink():
            mode = current.lstat().st_mode
            if stat.S_ISLNK(mode) or not stat.S_ISDIR(mode):
                raise ValueError(f"path component is not a real directory: {current}")
        elif create_parents:
            current.mkdir(mode=0o755)
        else:
            raise FileNotFoundError(current)
    destination = root / rel
    if destination.is_symlink():
        raise ValueError(f"refusing symbolic-link destination: {destination}")
    try:
        destination.resolve(strict=False).relative_to(root)
    except ValueError as exc:
        raise ValueError(f"path resolves outside review directory: {relative}") from exc
    return destination


def safe_read_bytes(root: Path, relative: str | Path) -> bytes:
    path = _contained_path(root, relative, create_parents=False)
    flags = os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0)
    descriptor = os.open(path, flags)
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise ValueError(f"path is not a regular file: {path}")
        with os.fdopen(descriptor, "rb", closefd=False) as handle:
            return handle.read()
    finally:
        os.close(descriptor)


def safe_read_text(root: Path, relative: str | Path) -> str:
    return safe_read_bytes(root, relative).decode("utf-8")


def safe_read_json(root: Path, relative: str | Path) -> Any:
    return strict_json_loads(safe_read_bytes(root, relative))


def atomic_write_bytes(root: Path, relative: str | Path, value: bytes) -> Path:
    destination = _contained_path(root, relative, create_parents=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{destination.name}.", dir=destination.parent)
    try:
        with os.fdopen(descriptor, "wb") as handle:
            handle.write(value)
            handle.flush()
            os.fsync(handle.fileno())
        if destination.is_symlink():
            raise ValueError(f"refusing symbolic-link destination: {destination}")
        os.replace(temporary, destination)
        directory_fd = os.open(destination.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    except Exception:
        try:
            os.unlink(temporary)
        except FileNotFoundError:
            pass
        raise
    return destination


def atomic_write_text(root: Path, relative: str | Path, value: str) -> Path:
    return atomic_write_bytes(root, relative, value.encode("utf-8"))


def atomic_write_json(root: Path, relative: str | Path, value: Any) -> Path:
    return atomic_write_text(
        root,
        relative,
        json.dumps(value, indent=2, ensure_ascii=False, allow_nan=False) + "\n",
    )
