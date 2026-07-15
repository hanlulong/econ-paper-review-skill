#!/usr/bin/env python3
"""Prepare econ-review from its self-contained skill or plugin package.

Direct-source mode installs the skill for both agents, creates or reuses one
managed Python environment, and runs the PDF-ingestion doctor. Plugin mode can
prepare only the shared runtime and Review Desk without creating duplicate
skill copies. ``--copy-only`` preserves the original lightweight behavior.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import errno
import hashlib
import json
import ntpath
import os
import platform
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import time
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, Iterable, Iterator, Sequence


sys.dont_write_bytecode = True


MINIMUM_PYTHON = (3, 10)
SKILL_ROOT = Path(__file__).resolve().parents[1]
IGNORED_DIRECTORY_NAMES = {
    "__pycache__",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
}
IGNORED_FILE_NAMES = {".DS_Store"}
IGNORED_SUFFIXES = {".pyc", ".pyo"}
GENERATED_FILES = {".econ-review-install.json", ".econ-review-runtime.json"}
REQUIRED_POPPLER_COMMANDS = ("pdfinfo", "pdftotext", "pdftoppm")
REVIEW_DESK_BUNDLE = Path("assets/review-desk.zip")
SUPPORT_DESCRIPTOR_NAME = "runtime.json"
REVIEW_DESK_MANIFEST_NAME = "bundle-manifest.json"
REVIEW_DESK_WINDOWS_LAUNCHER = "review-desk.cmd"
REVIEW_DESK_FIRST_PARTY_LICENSE = "app/LICENSE.txt"
REVIEW_DESK_THIRD_PARTY_NOTICE = "app/THIRD_PARTY_NOTICES.txt"
REVIEW_DESK_THIRD_PARTY_MANIFEST = "app/third-party-licenses/manifest.json"
REVIEW_DESK_KATEX_FONT_LICENSE = "app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt"
SETUP_LOCK_TIMEOUT_SECONDS = 30.0
SETUP_LOCK_POLL_SECONDS = 0.1
REVIEW_DESK_REQUIRED_RUNTIME_PACKAGES = frozenset(
    {"katex", "react", "react-dom", "react-markdown", "rehype-katex", "remark-gfm", "remark-math"}
)


class InstallError(RuntimeError):
    """A safe, user-facing installation failure."""


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


def _ignored(path: Path) -> bool:
    return (
        any(part in IGNORED_DIRECTORY_NAMES for part in path.parts)
        or path.name in IGNORED_FILE_NAMES
        or path.name in GENERATED_FILES
        or path.suffix.casefold() in IGNORED_SUFFIXES
    )


def _source_files(root: Path) -> list[Path]:
    files: list[Path] = []
    portable_names: set[str] = set()
    for current, directories, names in os.walk(root, followlinks=False):
        current_path = Path(current)
        kept_directories: list[str] = []
        for name in directories:
            candidate = current_path / name
            relative = candidate.relative_to(root)
            if _ignored(relative):
                continue
            if _is_link_or_junction(candidate):
                raise InstallError(f"skill source contains a link or junction: {relative.as_posix()}")
            kept_directories.append(name)
        directories[:] = kept_directories
        for name in names:
            candidate = current_path / name
            relative = candidate.relative_to(root)
            if _ignored(relative):
                continue
            if _is_link_or_junction(candidate) or not candidate.is_file():
                raise InstallError(f"skill source contains a non-regular file: {relative.as_posix()}")
            folded_name = name.casefold()
            if (
                folded_name == ".env"
                or (folded_name.startswith(".env.") and folded_name != ".env.example")
                or candidate.suffix.casefold() in {".key", ".pem", ".p12"}
            ):
                raise InstallError(f"skill source contains a credential-bearing file: {relative.as_posix()}")
            portable = relative.as_posix().casefold()
            if portable in portable_names:
                raise InstallError(f"skill source contains case-colliding paths: {relative.as_posix()}")
            portable_names.add(portable)
            files.append(relative)
    return sorted(files, key=lambda path: path.as_posix())


def _tree_has_exact_membership(root: Path, expected_files: set[str]) -> bool:
    """Return whether *root* contains exactly the declared regular files.

    The comparison includes directories so an undeclared empty directory, link,
    junction, reparse point, or non-regular file cannot survive an idempotent
    installation check and later participate in Python module shadowing.
    """

    expected_directories = {""}
    for raw in expected_files:
        path = PurePosixPath(raw)
        if (
            not raw
            or path.is_absolute()
            or ".." in path.parts
            or raw != path.as_posix()
        ):
            return False
        for length in range(1, len(path.parts)):
            expected_directories.add(PurePosixPath(*path.parts[:length]).as_posix())

    actual_files: set[str] = set()
    actual_directories: set[str] = set()

    def raise_walk_error(error: OSError) -> None:
        raise error

    try:
        for current, directories, names in os.walk(
            root,
            followlinks=False,
            onerror=raise_walk_error,
        ):
            current_path = Path(current)
            if _is_link_or_junction(current_path):
                return False
            relative_directory = current_path.relative_to(root).as_posix()
            actual_directories.add("" if relative_directory == "." else relative_directory)
            for name in directories:
                candidate = current_path / name
                if _is_link_or_junction(candidate) or not candidate.is_dir():
                    return False
            for name in names:
                candidate = current_path / name
                if _is_link_or_junction(candidate) or not candidate.is_file():
                    return False
                actual_files.add(candidate.relative_to(root).as_posix())
    except (OSError, ValueError):
        return False

    return actual_files == expected_files and actual_directories == expected_directories


def validate_source(root: Path) -> list[Path]:
    if not root.is_dir() or _is_link_or_junction(root):
        raise InstallError(f"trusted local skill source is missing or unsafe: {root}")
    skill = root / "SKILL.md"
    if not skill.is_file() or _is_link_or_junction(skill):
        raise InstallError("skill source is missing a safe SKILL.md")
    try:
        text = skill.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InstallError(f"could not read SKILL.md as UTF-8: {exc}") from exc
    if "\nname: econ-review\n" not in f"\n{text}":
        raise InstallError("SKILL.md has the wrong skill name")
    license_path = root / "LICENSE"
    if not license_path.is_file() or _is_link_or_junction(license_path):
        raise InstallError("skill source is missing a safe LICENSE")
    try:
        license_text = license_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise InstallError(f"could not read LICENSE as UTF-8: {exc}") from exc
    if not license_text.strip():
        raise InstallError("skill source LICENSE must not be empty")
    return _source_files(root)


def file_manifest(root: Path, files: Iterable[Path]) -> dict[str, str]:
    return {
        relative.as_posix(): hashlib.sha256((root / relative).read_bytes()).hexdigest()
        for relative in files
    }


def manifest_digest(manifest: dict[str, str]) -> str:
    data = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(data).hexdigest()


def _write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
        encoding="utf-8",
    )


def _atomic_private_json(path: Path, value: object) -> None:
    """Replace a user-owned descriptor without following an existing link."""

    if path.exists() and (_is_link_or_junction(path) or not path.is_file()):
        raise InstallError(f"refusing unsafe runtime descriptor: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        descriptor = os.open(temporary, flags, 0o600)
        try:
            data = (
                json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + "\n"
            ).encode("utf-8")
            with os.fdopen(descriptor, "wb") as stream:
                descriptor = -1
                stream.write(data)
        finally:
            if descriptor >= 0:
                os.close(descriptor)
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def destination_is_current(
    destination: Path,
    source_manifest: dict[str, str],
    runtime_python: Path | None,
) -> bool:
    if not destination.is_dir() or _is_link_or_junction(destination):
        return False
    expected_files = set(source_manifest) | {".econ-review-install.json"}
    if not _tree_has_exact_membership(destination, expected_files):
        return False
    state_path = destination / ".econ-review-install.json"
    if _is_link_or_junction(state_path):
        return False
    try:
        state = json.loads(state_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    expected_runtime = str(runtime_python) if runtime_python else None
    if state != {
        "schema_version": "1",
        "source_manifest": source_manifest,
        "source_tree_sha256": manifest_digest(source_manifest),
        "runtime_python": expected_runtime,
    }:
        return False
    for relative, digest in source_manifest.items():
        candidate = destination / Path(*relative.split("/"))
        if not candidate.is_file() or _is_link_or_junction(candidate):
            return False
        if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
            return False
    return True


def managed_destination_is_intact(destination: Path) -> bool:
    """Return whether an older direct install is complete and unmodified."""

    if not destination.is_dir() or _is_link_or_junction(destination):
        return False
    state_path = destination / ".econ-review-install.json"
    if not state_path.is_file() or _is_link_or_junction(state_path):
        return False
    try:
        state = _strict_json_object(state_path.read_bytes(), "installed skill state")
        source_manifest = state.get("source_manifest")
        if (
            set(state)
            != {
                "runtime_python",
                "schema_version",
                "source_manifest",
                "source_tree_sha256",
            }
            or state.get("schema_version") != "1"
            or not isinstance(source_manifest, dict)
            or not source_manifest
            or not all(
                isinstance(relative, str)
                and relative
                and isinstance(digest, str)
                and len(digest) == 64
                for relative, digest in source_manifest.items()
            )
            or state.get("source_tree_sha256") != manifest_digest(source_manifest)
            or not _tree_has_exact_membership(
                destination,
                set(source_manifest) | {".econ-review-install.json"},
            )
        ):
            return False
        for relative, digest in source_manifest.items():
            candidate = destination / Path(*relative.split("/"))
            if hashlib.sha256(candidate.read_bytes()).hexdigest() != digest:
                return False
    except (InstallError, OSError, UnicodeError, ValueError):
        return False
    return True


def destination_matches_source(
    destination: Path,
    source_manifest: dict[str, str],
) -> bool:
    """Return whether an unmarked legacy copy exactly matches this source."""

    if (
        not destination.is_dir()
        or _is_link_or_junction(destination)
        or not _tree_has_exact_membership(destination, set(source_manifest))
    ):
        return False
    try:
        return all(
            hashlib.sha256(
                (destination / Path(*relative.split("/"))).read_bytes()
            ).hexdigest()
            == digest
            for relative, digest in source_manifest.items()
        )
    except OSError:
        return False


def _path_present(path: Path) -> bool:
    """Check for a path without following a broken link or junction."""

    try:
        path.lstat()
    except OSError:
        return False
    return True


def _backup_destination(source: Path) -> Path:
    basename = "".join(
        character if character.isalnum() or character in "._-" else "_"
        for character in source.name
    ).strip("_") or "skill"
    source_digest = hashlib.sha256(str(source).encode("utf-8")).hexdigest()[:12]
    label = f"{basename}-{source_digest}"
    run = f"{time.strftime('%Y%m%dT%H%M%SZ', time.gmtime())}-{uuid.uuid4().hex[:12]}"
    return Path.home() / ".openeconai" / "backups" / "econ-review" / run / label


def _same_volume_backup_destination(source: Path) -> Path:
    """Return an inactive backup path beside, but never inside, a skills directory."""

    if source.parent.name.casefold() != "skills":
        raise InstallError(
            f"cannot derive a safe same-volume backup root for prior installation: {source}"
        )
    client_root = source.parent.parent
    if _is_link_or_junction(client_root) or not client_root.is_dir():
        raise InstallError(f"refusing unsafe client root for same-volume backup: {client_root}")
    backup_root = client_root / ".openeconai-inactive" / "econ-review"
    for candidate in (backup_root.parent, backup_root):
        if _path_present(candidate) and (
            _is_link_or_junction(candidate) or not candidate.is_dir()
        ):
            raise InstallError(f"refusing unsafe same-volume backup ancestor: {candidate}")
    central = _backup_destination(source)
    return backup_root / central.parent.name / central.name


def preserve_inactive_copy(source: Path) -> Path:
    """Move one active path to a collision-proof, non-discovery backup."""

    destination = _backup_destination(source)
    try:
        require_safe_skill_destination(destination, "backup")
    except InstallError:
        destination = _same_volume_backup_destination(source)
        destination.parent.mkdir(parents=True, exist_ok=False)
        source.rename(destination)
        return destination
    destination.parent.mkdir(parents=True, exist_ok=False)
    try:
        source.rename(destination)
    except OSError as exc:
        if exc.errno != errno.EXDEV:
            raise
        destination.parent.rmdir()
        destination = _same_volume_backup_destination(source)
        destination.parent.mkdir(parents=True, exist_ok=False)
        source.rename(destination)
    return destination


def environment_path(name: str, fallback: Path) -> Path:
    raw = os.environ.get(name)
    if raw is None:
        return fallback
    candidate = Path(raw).expanduser()
    if not candidate.is_absolute():
        raise InstallError(f"{name} must be an absolute path when set")
    return candidate


def support_data_root(system: str | None = None) -> Path:
    """Return the user-owned product-data root outside plugin and project trees."""

    system = system or platform.system()
    home = Path.home()
    if system == "Windows":
        # Microsoft Store Python virtualizes parts of LocalAppData.  A user-home
        # root is stable for CreateFile and CreateProcess and needs no elevation.
        return home / ".econ-review"
    elif system == "Darwin":
        base = home / "Library" / "Application Support"
    else:
        base = environment_path("XDG_DATA_HOME", home / ".local" / "share")
    return base / "econ-review"


def support_scope_root(
    scope: str,
    project: Path | None,
    system: str | None = None,
) -> Path:
    root = support_data_root(system)
    if scope == "global":
        return root
    assert project is not None
    project_identity = str(project.resolve())
    if (system or platform.system()) == "Windows":
        project_identity = ntpath.normcase(project_identity)
    # A 64-bit key keeps project scopes effectively collision-free while leaving
    # enough room for the versioned Review Desk on classic Windows MAX_PATH.
    project_key = hashlib.sha256(project_identity.encode("utf-8")).hexdigest()[:16]
    return root / "projects" / project_key


def runtime_default(
    scope: str,
    project: Path | None,
    system: str | None = None,
    version_key: str | None = None,
) -> Path:
    root = support_scope_root(scope, project, system)
    return root / "runtime" if version_key is None else root / "runtimes" / version_key


def review_desk_default(
    scope: str,
    project: Path | None,
    system: str | None = None,
) -> Path:
    return support_scope_root(scope, project, system) / "review-desk"


def support_descriptor_default(
    scope: str,
    project: Path | None,
    system: str | None = None,
    version_key: str | None = None,
) -> Path:
    """Return mutable setup state outside a versioned plugin or skill tree."""

    root = support_scope_root(scope, project, system)
    if version_key is None:
        return root / SUPPORT_DESCRIPTOR_NAME
    return root / "runtime-descriptors" / f"{version_key}.json"


def support_lock_path(
    scope: str,
    project: Path | None,
    system: str | None = None,
) -> Path:
    """Return one stable lock file for a shared mutable support scope."""

    root = support_data_root(system)
    scope_name = (
        "global"
        if scope == "global"
        else f"project-{support_scope_root(scope, project, system).name}"
    )
    return root / ".locks" / f"{scope_name}.lock"


def _paths_overlap(first: Path, second: Path) -> bool:
    """Compare both lexical and resolved forms so links cannot hide overlap."""

    try:
        if os.path.samefile(first, second):
            return True
    except OSError:
        pass
    pairs = (
        (first.expanduser().absolute(), second.expanduser().absolute()),
        (first.expanduser().resolve(strict=False), second.expanduser().resolve(strict=False)),
    )
    return any(
        left == right or left in right.parents or right in left.parents
        for left, right in pairs
    )


def reject_source_overlap(path: Path, source: Path, label: str) -> None:
    if _paths_overlap(path, source):
        raise InstallError(f"{label} must not overlap the installed plugin or skill package: {path}")


def require_safe_skill_destination(destination: Path, label: str) -> None:
    """Reject linked, junction, or non-directory ancestors before skill writes."""

    target_parent = destination.expanduser().absolute().parent
    home = Path.home().expanduser().absolute()
    try:
        boundary = Path(os.path.commonpath((str(home), str(target_parent))))
    except ValueError:
        boundary = Path(target_parent.anchor)
    candidate = boundary
    try:
        relative = target_parent.relative_to(boundary)
    except ValueError as exc:
        raise InstallError(f"cannot establish a safe boundary for {label}: {destination}") from exc
    for part in relative.parts:
        candidate = candidate / part
        if _path_present(candidate) and (
            _is_link_or_junction(candidate) or not candidate.is_dir()
        ):
            raise InstallError(f"refusing unsafe {label} ancestor: {candidate}")


def require_safe_support_path(path: Path, scope_root: Path, label: str) -> None:
    """Reject link-controlled components inside the user-owned support tree."""

    target = path.expanduser().absolute()
    boundary = scope_root.expanduser().absolute()
    try:
        relative = target.relative_to(boundary)
    except ValueError as exc:
        raise InstallError(f"{label} is outside its user-owned support root: {target}") from exc
    candidate = boundary
    components = [candidate]
    for part in relative.parts[:-1]:
        candidate = candidate / part
        components.append(candidate)
    for ancestor in components:
        if _is_link_or_junction(ancestor):
            raise InstallError(f"refusing link-controlled {label} ancestor: {ancestor}")
        if ancestor.exists() and not ancestor.is_dir():
            raise InstallError(f"refusing non-directory {label} ancestor: {ancestor}")


def _open_support_lock(path: Path) -> BinaryIO:
    """Open a private regular lock file without following a final symlink."""

    if path.exists() and (_is_link_or_junction(path) or not path.is_file()):
        raise InstallError(f"refusing unsafe setup lock: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    if _is_link_or_junction(path.parent) or not path.parent.is_dir():
        raise InstallError(f"refusing unsafe setup lock directory: {path.parent}")
    flags = os.O_RDWR
    flags |= getattr(os, "O_BINARY", 0)
    flags |= getattr(os, "O_CLOEXEC", 0)
    flags |= getattr(os, "O_NOFOLLOW", 0)
    try:
        descriptor = os.open(path, flags | os.O_CREAT | os.O_EXCL, 0o600)
        created = True
    except FileExistsError:
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise InstallError(f"could not open the setup lock safely: {path}") from exc
        created = False
    except OSError as exc:
        raise InstallError(f"could not open the setup lock safely: {path}") from exc
    try:
        opened = os.fstat(descriptor)
        if not stat.S_ISREG(opened.st_mode):
            raise InstallError(f"setup lock is not a regular file: {path}")
        if opened.st_nlink != 1:
            raise InstallError(f"refusing hard-linked setup lock: {path}")
        current = path.lstat()
        if _is_link_or_junction(path) or (
            (opened.st_dev, opened.st_ino) != (current.st_dev, current.st_ino)
        ):
            raise InstallError(f"setup lock changed while it was opened: {path}")
        if created:
            try:
                os.fchmod(descriptor, 0o600)
            except (AttributeError, OSError):
                # Windows applies access control through the containing
                # user-owned directory; fchmod can be unavailable there.
                pass
        if opened.st_size == 0:
            if os.fstat(descriptor).st_nlink != 1:
                raise InstallError(f"refusing hard-linked setup lock: {path}")
            os.write(descriptor, b"\0")
        os.lseek(descriptor, 0, os.SEEK_SET)
        return os.fdopen(descriptor, "r+b", buffering=0)
    except BaseException:
        os.close(descriptor)
        raise


def _lock_is_busy(exc: OSError) -> bool:
    return (
        isinstance(exc, BlockingIOError)
        or exc.errno
        in {
            errno.EACCES,
            errno.EAGAIN,
            getattr(errno, "EDEADLK", -1),
        }
        or getattr(exc, "winerror", None) in {33, 36}
    )


def _try_lock_support_file(handle: BinaryIO, system: str) -> bool:
    handle.seek(0)
    if system == "Windows":
        import msvcrt

        try:
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError as exc:
            if _lock_is_busy(exc):
                return False
            raise
        return True

    import fcntl

    try:
        fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError as exc:
        if _lock_is_busy(exc):
            return False
        raise
    return True


def _unlock_support_file(handle: BinaryIO, system: str) -> None:
    handle.seek(0)
    if system == "Windows":
        import msvcrt

        msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        return

    import fcntl

    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


@contextmanager
def support_setup_lock(
    scope: str,
    project: Path | None,
    *,
    timeout: float = SETUP_LOCK_TIMEOUT_SECONDS,
    poll_interval: float = SETUP_LOCK_POLL_SECONDS,
    system: str | None = None,
) -> Iterator[Path]:
    """Serialize mutation of one runtime/descriptor/Review Desk scope."""

    if timeout < 0 or poll_interval <= 0:
        raise ValueError("setup lock timeout must be non-negative and poll interval positive")
    system = system or platform.system()
    root = support_data_root(system)
    path = support_lock_path(scope, project, system)
    require_safe_support_path(path, root, "setup lock")
    handle = _open_support_lock(path)
    acquired = False
    deadline = time.monotonic() + timeout
    try:
        while not acquired:
            acquired = _try_lock_support_file(handle, system)
            if acquired:
                break
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                raise InstallError(
                    "another econ-review setup, refresh, or cleanup is using this "
                    f"support scope; retry after it finishes: {path}"
                )
            time.sleep(min(poll_interval, remaining))
        yield path
    finally:
        try:
            if acquired:
                _unlock_support_file(handle, system)
        finally:
            handle.close()


def cleanup_support_state(
    scope: str,
    project: Path | None,
    source: Path,
    *,
    dry_run: bool,
) -> None:
    """Remove only exact default support targets after an explicit confirmation."""

    mutable_root = support_data_root()
    scoped_root = support_scope_root(scope, project)
    targets = (
        (support_descriptor_default(scope, project), "runtime descriptor", "file"),
        (runtime_default(scope, project), "managed runtime", "directory"),
        (review_desk_default(scope, project), "Review Desk", "directory"),
        (scoped_root / "runtime-descriptors", "versioned runtime descriptors", "directory"),
        (scoped_root / "runtimes", "versioned managed runtimes", "directory"),
    )
    for path, label, expected_kind in targets:
        require_safe_support_path(path, mutable_root, label)
        reject_source_overlap(path, source, label)
        if _is_link_or_junction(path):
            raise InstallError(f"refusing linked or junction {label} during cleanup: {path}")
        if not path.exists():
            print(f"Would keep absent {label}: {path}" if dry_run else f"Already absent {label}: {path}")
            continue
        if expected_kind == "file" and not path.is_file():
            raise InstallError(f"refusing non-file {label} during cleanup: {path}")
        if expected_kind == "directory" and not path.is_dir():
            raise InstallError(f"refusing non-directory {label} during cleanup: {path}")
        if dry_run:
            print(f"Would remove {label}: {path}")
        elif path.is_dir():
            shutil.rmtree(path)
            print(f"Removed {label}: {path}")
        else:
            path.unlink()
            print(f"Removed {label}: {path}")
    if dry_run:
        print("Cleanup dry run complete; no files changed.")
        return
    for directory in (
        scoped_root,
        scoped_root.parent if scope == "local" else None,
    ):
        if directory is not None and directory.is_dir() and not any(directory.iterdir()):
            directory.rmdir()
    print("econ-review support cleanup complete; plugin and direct skill copies were unchanged.")


def runtime_python_path(runtime: Path, system: str | None = None) -> Path:
    return runtime / ("Scripts/python.exe" if (system or platform.system()) == "Windows" else "bin/python")


def resolve_runtime_location(
    runtime: Path,
    system: str | None = None,
) -> tuple[Path, Path]:
    """Return the actual runtime root and interpreter after OS redirection.

    Python's Windows venv builder resolves Store-package file-system redirects
    for child-process execution.  Repeating that resolution here ensures pip,
    health checks, and installed agent descriptors all use the executable that
    Windows will actually launch.
    """

    system = system or platform.system()
    expected_python = runtime_python_path(runtime, system)
    if system != "Windows":
        return runtime, expected_python
    actual_python = Path(os.path.realpath(expected_python))
    if os.path.normcase(str(actual_python)) == os.path.normcase(str(expected_python)):
        return runtime, expected_python
    if (
        actual_python.name.casefold() != "python.exe"
        or actual_python.parent.name.casefold() != "scripts"
    ):
        raise InstallError(
            "Windows redirected the managed Python interpreter to an unexpected location: "
            f"{actual_python}"
        )
    actual_runtime = actual_python.parent.parent
    if actual_runtime.name.casefold() != runtime.name.casefold():
        raise InstallError(
            "Windows redirected the managed runtime outside its expected directory name: "
            f"{actual_runtime}"
        )
    return actual_runtime, actual_python


def requirements_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _run_quiet(
    command: Sequence[str],
    *,
    env: dict[str, str] | None = None,
    cwd: Path | None = None,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        list(command),
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        encoding="utf-8",
        errors="replace",
        env=env,
        cwd=cwd,
        check=False,
    )


def python_major_minor(python: Path) -> tuple[int, int] | None:
    result = _run_quiet(
        [
            str(python),
            "-B",
            "-I",
            "-c",
            "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')",
        ],
        cwd=python.parent,
    )
    if result.returncode:
        return None
    try:
        major, minor = (int(part) for part in result.stdout.strip().split("."))
    except (TypeError, ValueError):
        return None
    return major, minor


def python_satisfies_core(python: Path, source: Path) -> bool:
    if not python.is_file():
        return False
    version = python_major_minor(python)
    if version is None or version < MINIMUM_PYTHON:
        return False
    probe = _run_quiet(
        [str(python), "-B", "-I", "-m", "pip", "check"],
        cwd=python.parent,
    )
    if probe.returncode:
        return False
    checker = (
        "import sys; from pathlib import Path; "
        "sys.path.insert(0, sys.argv[1]); "
        "from dependency_versions import require_compatible; "
        "require_compatible(Path(sys.argv[2]))"
    )
    probe_environment = os.environ.copy()
    probe_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    probe = _run_quiet(
        [
            str(python),
            "-B",
            "-I",
            "-c",
            checker,
            str(source / "scripts"),
            str(source / "requirements-core.txt"),
        ],
        env=probe_environment,
        cwd=source,
    )
    return probe.returncode == 0


def require_runtime_builder() -> None:
    """Require the standard-library pieces needed to bootstrap pip in a venv."""

    try:
        import ensurepip  # noqa: F401
        import venv  # noqa: F401
    except ImportError as exc:
        raise InstallError(
            "this Python cannot create a managed environment; use Python 3.10+ "
            "with venv and ensurepip support (often provided by python3-venv on Linux)"
        ) from exc


def runtime_is_reusable(runtime: Path, source: Path) -> bool:
    try:
        actual_runtime, python = resolve_runtime_location(runtime)
    except InstallError:
        return False
    marker = actual_runtime / ".econ-review-runtime.json"
    requirements = source / "requirements-core.txt"
    if (
        not python.is_file()
        or _is_link_or_junction(runtime)
        or not marker.is_file()
        or _is_link_or_junction(marker)
    ):
        return False
    try:
        state = json.loads(marker.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    runtime_version = python_major_minor(python)
    if runtime_version is None or state != {
        "schema_version": "1",
        "requirements_sha256": requirements_digest(requirements),
        "python_major_minor": list(runtime_version),
    }:
        return False
    return python_satisfies_core(python, source)


def record_support_runtime(
    descriptor: Path,
    runtime: Path,
    python: Path,
    source: Path,
    *,
    dry_run: bool,
) -> None:
    """Record a verified runtime outside the installed skill package."""

    actual_runtime, actual_python = resolve_runtime_location(runtime)
    value = {
        "python": str(actual_python.absolute()),
        "requirements_sha256": requirements_digest(source / "requirements-core.txt"),
        "runtime": str(actual_runtime.absolute()),
        "schema_version": "1",
    }
    if dry_run:
        print(f"Would record managed runtime for Econ Review: {descriptor}")
        return
    if python.absolute() != actual_python.absolute():
        raise InstallError("managed Python path changed before its descriptor was written")
    if not runtime_is_reusable(runtime, source):
        raise InstallError("refusing to record a managed runtime that failed verification")
    _atomic_private_json(descriptor, value)
    print(f"Recorded managed runtime for Econ Review: {descriptor}")


def recorded_runtime_python(descriptor: Path, source: Path) -> Path | None:
    """Resolve the external runtime descriptor, failing closed if it is unsafe."""

    if not descriptor.exists():
        return None
    if _is_link_or_junction(descriptor) or not descriptor.is_file():
        raise InstallError(f"runtime descriptor is not a safe regular file: {descriptor}")
    value = _strict_json_object(descriptor.read_bytes(), "runtime descriptor")
    if set(value) != {"python", "requirements_sha256", "runtime", "schema_version"}:
        raise InstallError("runtime descriptor has unexpected fields")
    if value.get("schema_version") != "1":
        raise InstallError("runtime descriptor has an unsupported schema version")
    if value.get("requirements_sha256") != requirements_digest(source / "requirements-core.txt"):
        return None
    raw_runtime = value.get("runtime")
    raw_python = value.get("python")
    if not isinstance(raw_runtime, str) or not isinstance(raw_python, str):
        raise InstallError("runtime descriptor paths must be strings")
    runtime = Path(raw_runtime)
    python = Path(raw_python)
    if not runtime.is_absolute() or not python.is_absolute():
        raise InstallError("runtime descriptor paths must be absolute")
    if not runtime_is_reusable(runtime, source):
        return None
    actual_runtime, actual_python = resolve_runtime_location(runtime)
    if (
        os.path.normcase(str(actual_runtime.absolute()))
        != os.path.normcase(str(runtime.absolute()))
        or os.path.normcase(str(actual_python.absolute()))
        != os.path.normcase(str(python.absolute()))
    ):
        raise InstallError("runtime descriptor does not match the verified runtime location")
    return actual_python


def ensure_runtime(
    runtime: Path,
    source: Path,
    *,
    refresh: bool,
    dry_run: bool,
    reuse_if_bound: bool = False,
) -> Path:
    _actual_runtime, python = resolve_runtime_location(runtime)
    if dry_run:
        action = "Would verify and reuse or replace" if runtime.exists() else "Would create"
        print(f"{action} managed Python runtime: {runtime}")
        print(f"Would install core requirements from: {source / 'requirements-core.txt'}")
        return python
    if not refresh and reuse_if_bound and runtime_is_reusable(runtime, source):
        actual_runtime, python = resolve_runtime_location(runtime)
        print(f"Reusing managed Python runtime: {actual_runtime}")
        return python
    require_runtime_builder()
    if runtime.exists() and _is_link_or_junction(runtime):
        raise InstallError(f"refusing linked or junction runtime destination: {runtime}")
    runtime.parent.mkdir(parents=True, exist_ok=True)
    backup = runtime.with_name(f".{runtime.name}.backup-{uuid.uuid4().hex}")
    had_previous = runtime.exists()
    if had_previous:
        runtime.rename(backup)
    created_runtime = runtime
    try:
        try:
            subprocess.run(
                [sys.executable, "-B", "-I", "-m", "venv", str(runtime)],
                cwd=runtime.parent,
                check=True,
            )
        except subprocess.CalledProcessError as exc:
            raise InstallError(
                "Python could not create the private managed environment; use a Python 3.10+ "
                "installation with working venv and pip bootstrapping support"
            ) from exc
        created_runtime, python = resolve_runtime_location(runtime)
        if created_runtime != runtime:
            print(
                "Windows redirected the managed runtime; using and recording its actual location: "
                f"{created_runtime}"
            )
        if not python.is_file():
            raise InstallError(f"managed Python interpreter was not created: {python}")
        pip_env = os.environ.copy()
        pip_env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
        pip_env["PIP_NO_INPUT"] = "1"
        print(
            "Installing the declared core Python packages into the private managed runtime; "
            "this step may use the configured package index."
        )
        installed = _run_quiet(
            [
                str(python),
                "-B",
                "-I",
                "-m",
                "pip",
                "install",
                "--no-input",
                "--disable-pip-version-check",
                "--no-cache-dir",
                "-r",
                str(source / "requirements-core.txt"),
            ],
            env=pip_env,
            cwd=created_runtime,
        )
        if installed.returncode:
            raise InstallError(
                "core Python dependency installation failed; no command output was echoed to avoid "
                "leaking credentials from package-index configuration"
            )
        runtime_version = python_major_minor(python)
        if runtime_version is None or runtime_version < MINIMUM_PYTHON:
            raise InstallError("the managed Python runtime has an unsupported interpreter version")
        _write_json(
            created_runtime / ".econ-review-runtime.json",
            {
                "schema_version": "1",
                "requirements_sha256": requirements_digest(source / "requirements-core.txt"),
                "python_major_minor": list(runtime_version),
            },
        )
        if not runtime_is_reusable(runtime, source):
            raise InstallError("the managed Python runtime failed its dependency health check")
    except BaseException:
        shutil.rmtree(created_runtime, ignore_errors=True)
        if created_runtime != runtime:
            shutil.rmtree(runtime, ignore_errors=True)
        if had_previous and backup.exists():
            backup.rename(runtime)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)
    print(f"Prepared managed Python runtime: {created_runtime}")
    return python


def install_one(
    source: Path,
    files: list[Path],
    source_manifest: dict[str, str],
    destination: Path,
    label: str,
    runtime_python: Path | None,
    *,
    dry_run: bool,
) -> None:
    require_safe_skill_destination(destination, label)
    if dry_run:
        state = (
            "already current"
            if destination_is_current(destination, source_manifest, runtime_python)
            else "install"
        )
        print(f"Would {state} {label}: {destination}")
        return
    if destination_is_current(destination, source_manifest, runtime_python):
        print(f"Already current {label}: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".econ-review-stage-", dir=destination.parent))
    rollback = destination.with_name(f".{destination.name}.backup-{uuid.uuid4().hex}")
    had_previous = _path_present(destination)
    preserve_previous = had_previous and not managed_destination_is_intact(destination)
    try:
        for relative in files:
            target = stage / relative
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(source / relative, target)
        _write_json(
            stage / ".econ-review-install.json",
            {
                "schema_version": "1",
                "source_manifest": source_manifest,
                "source_tree_sha256": manifest_digest(source_manifest),
                "runtime_python": str(runtime_python) if runtime_python else None,
            },
        )
        validate_source(stage)
        if had_previous:
            destination.rename(rollback)
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if destination.exists() and not had_previous:
            shutil.rmtree(destination, ignore_errors=True)
        if had_previous and _path_present(rollback) and not _path_present(destination):
            rollback.rename(destination)
        raise
    else:
        if _path_present(rollback):
            if preserve_previous:
                try:
                    preserved = preserve_inactive_copy(rollback)
                except BaseException:
                    shutil.rmtree(destination, ignore_errors=True)
                    rollback.rename(destination)
                    raise InstallError(
                        f"could not preserve the prior {label}; the update was rolled back"
                    )
                print(f"Preserved modified prior copy: {preserved}")
            else:
                shutil.rmtree(rollback)
    print(f"Installed {label}: {destination}")


def legacy_codex_destinations() -> list[Path]:
    """Return historical Codex direct-skill paths, without the current path."""

    home = Path.home()
    candidates = [home / ".codex" / "skills" / "econ-review"]
    raw_codex_home = os.environ.get("CODEX_HOME")
    if raw_codex_home:
        codex_home = environment_path("CODEX_HOME", home / ".codex")
        candidates.append(codex_home / "skills" / "econ-review")
    current = home / ".agents" / "skills" / "econ-review"
    unique: list[Path] = []
    for candidate in candidates:
        if candidate == current or candidate in unique:
            continue
        unique.append(candidate)
    return unique


def migrate_legacy_codex_copies(
    source_manifest: dict[str, str],
    runtime_python: Path | None,
    *,
    dry_run: bool,
) -> None:
    """Deactivate only historical Codex copies after the current install exists."""

    current = Path.home() / ".agents" / "skills" / "econ-review"
    home_boundary = Path.home().expanduser().absolute()
    configured_root = environment_path("CODEX_HOME", home_boundary / ".codex")
    if not dry_run and not destination_is_current(
        current,
        source_manifest,
        runtime_python,
    ):
        raise InstallError("refusing legacy migration before the current Codex skill is verified")
    for legacy in legacy_codex_destinations():
        if not _path_present(legacy):
            continue
        if _paths_overlap(current, legacy):
            print(f"Skipped aliased legacy Codex path that resolves to the current skill: {legacy}")
            continue
        legacy_absolute = legacy.expanduser().absolute()
        configured_absolute = configured_root.expanduser().absolute()
        boundary = (
            home_boundary
            if legacy_absolute == home_boundary or home_boundary in legacy_absolute.parents
            else configured_absolute
        )
        ancestor = legacy_absolute.parent
        while True:
            if _path_present(ancestor) and _is_link_or_junction(ancestor):
                raise InstallError(
                    f"refusing legacy migration through a linked or junction ancestor: {ancestor}"
                )
            if ancestor == boundary:
                break
            if boundary not in ancestor.parents:
                raise InstallError(
                    f"legacy Codex path escapes its configured migration boundary: {legacy}"
                )
            ancestor = ancestor.parent
        generated = managed_destination_is_intact(legacy) or destination_matches_source(
            legacy,
            source_manifest,
        )
        if dry_run:
            action = "remove generated" if generated else "preserve modified"
            print(f"Would {action} legacy Codex copy: {legacy}")
            continue
        if generated:
            shutil.rmtree(legacy)
            print(f"Removed generated legacy Codex copy: {legacy}")
        else:
            try:
                preserved = preserve_inactive_copy(legacy)
            except BaseException as exc:
                raise InstallError(
                    f"could not preserve legacy Codex copy {legacy}: {exc}"
                ) from exc
            print(f"Preserved modified legacy Codex copy: {preserved}")
    if not dry_run and not destination_is_current(
        current,
        source_manifest,
        runtime_python,
    ):
        raise InstallError("the current Codex skill failed verification after legacy migration")


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
        raise InstallError(f"invalid {label}: {exc}") from exc
    if not isinstance(value, dict):
        raise InstallError(f"invalid {label}: expected a JSON object")
    return value


def _safe_bundle_path(raw: object) -> PurePosixPath:
    windows_reserved = {
        "con", "prn", "aux", "nul", "clock$",
        *(f"com{number}" for number in range(1, 10)),
        *(f"lpt{number}" for number in range(1, 10)),
    }
    if (
        not isinstance(raw, str)
        or not raw
        or "\\" in raw
        or ":" in raw
        or raw.startswith("/")
        or raw != unicodedata.normalize("NFC", raw)
        or any(ord(character) < 32 or ord(character) == 127 for character in raw)
    ):
        raise InstallError(f"unsafe Review Desk bundle path: {raw!r}")
    path = PurePosixPath(raw)
    if path.is_absolute() or ".." in path.parts or any(
        part in {"", "."}
        or part != part.strip()
        or part.endswith(".")
        or part.split(".", 1)[0].casefold() in windows_reserved
        for part in path.parts
    ):
        raise InstallError(f"unsafe Review Desk bundle path: {raw!r}")
    if raw != path.as_posix():
        raise InstallError(f"non-canonical Review Desk bundle path: {raw!r}")
    if path.suffix.casefold() == ".map" or "node_modules" in path.parts or "reviews" in path.parts:
        raise InstallError(f"forbidden Review Desk release content: {raw}")
    if path not in {
        PurePosixPath("launch_review_desk.py"),
        PurePosixPath("launch_installed_review_desk.py"),
    } and path.parts[0] != "app":
        raise InstallError(f"Review Desk release file is outside the app contract: {raw}")
    return path


def _verify_review_desk_licenses(archive: zipfile.ZipFile, expected: set[str]) -> None:
    if REVIEW_DESK_FIRST_PARTY_LICENSE not in expected:
        raise InstallError("Review Desk bundle lacks its first-party license")
    try:
        first_party_license = archive.read(REVIEW_DESK_FIRST_PARTY_LICENSE).decode("utf-8")
    except UnicodeError as exc:
        raise InstallError(f"Review Desk first-party license is not UTF-8: {exc}") from exc
    if not first_party_license.strip():
        raise InstallError("Review Desk first-party license must not be empty")

    required = {
        REVIEW_DESK_THIRD_PARTY_NOTICE,
        REVIEW_DESK_THIRD_PARTY_MANIFEST,
        REVIEW_DESK_KATEX_FONT_LICENSE,
    }
    if not required.issubset(expected):
        raise InstallError("Review Desk bundle lacks embedded third-party notices or licenses")
    manifest_bytes = archive.read(REVIEW_DESK_THIRD_PARTY_MANIFEST)
    manifest = _strict_json_object(manifest_bytes, "Review Desk third-party license manifest")
    if (
        set(manifest) != {"generated_from", "packages", "schema_version", "supplemental_assets"}
        or manifest.get("schema_version") != "1"
        or manifest.get("generated_from") != "Vite client output module graph and package-lock.json"
    ):
        raise InstallError("Review Desk third-party license manifest has the wrong contract")
    canonical = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if manifest_bytes != canonical:
        raise InstallError("Review Desk third-party license manifest is not canonical JSON")

    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise InstallError("Review Desk third-party package inventory must be a non-empty array")
    keys: list[tuple[str, str]] = []
    referenced: set[str] = set()
    try:
        notice = archive.read(REVIEW_DESK_THIRD_PARTY_NOTICE).decode("utf-8")
    except UnicodeError as exc:
        raise InstallError(f"Review Desk third-party notice is not UTF-8: {exc}") from exc
    if not notice or not notice.endswith("\n"):
        raise InstallError("Review Desk third-party notice must be non-empty and newline-terminated")
    for package in packages:
        if not isinstance(package, dict) or set(package) != {
            "declared_license", "license_files", "name", "version",
        }:
            raise InstallError("Review Desk third-party package record is invalid")
        name = package.get("name")
        version = package.get("version")
        declared_license = package.get("declared_license")
        license_files = package.get("license_files")
        if not all(isinstance(value, str) and value for value in (name, version, declared_license)):
            raise InstallError("Review Desk third-party package identity must use non-empty strings")
        if (
            not isinstance(license_files, list)
            or not license_files
            or not all(isinstance(path, str) and path for path in license_files)
            or len(license_files) != len(set(license_files))
        ):
            raise InstallError(f"Review Desk third-party package has invalid license files: {name}@{version}")
        keys.append((name, version))
        if f"{name} {version}" not in notice:
            raise InstallError(f"Review Desk third-party notice omits {name}@{version}")
        for license_path in license_files:
            if (
                not license_path.startswith("app/third-party-licenses/packages/")
                or license_path not in expected
                or not archive.read(license_path)
            ):
                raise InstallError(f"Review Desk package references a missing or empty license: {license_path}")
            referenced.add(license_path)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise InstallError("Review Desk third-party package records must be sorted and unique")
    missing = REVIEW_DESK_REQUIRED_RUNTIME_PACKAGES - {name for name, _version in keys}
    if missing:
        raise InstallError("Review Desk third-party inventory omits: " + ", ".join(sorted(missing)))

    supplemental = manifest.get("supplemental_assets")
    if not isinstance(supplemental, list) or len(supplemental) != 1 or not isinstance(supplemental[0], dict):
        raise InstallError("Review Desk third-party inventory must contain one KaTeX font record")
    font = supplemental[0]
    if (
        set(font) != {"component", "copyright", "declared_license", "license_files", "reserved_font_names"}
        or font.get("component") != "KaTeX font assets"
        or font.get("declared_license") != "SIL Open Font License 1.1"
        or font.get("license_files") != [REVIEW_DESK_KATEX_FONT_LICENSE]
        or not isinstance(font.get("reserved_font_names"), list)
        or not font["reserved_font_names"]
        or not isinstance(font.get("copyright"), str)
        or not font["copyright"]
    ):
        raise InstallError("Review Desk third-party inventory has an invalid KaTeX font record")
    if not archive.read(REVIEW_DESK_KATEX_FONT_LICENSE):
        raise InstallError("Review Desk KaTeX font license is empty")
    referenced.add(REVIEW_DESK_KATEX_FONT_LICENSE)
    emitted = {
        name
        for name in expected
        if name.startswith("app/third-party-licenses/") and name != REVIEW_DESK_THIRD_PARTY_MANIFEST
    }
    if emitted != referenced:
        raise InstallError("Review Desk license files differ from its embedded third-party inventory")


def verify_review_desk_bundle(bundle: Path) -> tuple[bytes, list[dict[str, object]], str]:
    if not bundle.is_file() or _is_link_or_junction(bundle):
        raise InstallError(f"trusted Review Desk bundle is missing or unsafe: {bundle}")
    if bundle.stat().st_size > 20 * 1024 * 1024:
        raise InstallError("Review Desk bundle exceeds the 20 MiB safety limit")
    try:
        archive = zipfile.ZipFile(bundle)
    except (OSError, zipfile.BadZipFile) as exc:
        raise InstallError(f"Review Desk bundle is not a readable ZIP file: {exc}") from exc
    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > 500:
            raise InstallError("Review Desk bundle has an invalid entry count")
        if sum(info.file_size for info in infos) > 40 * 1024 * 1024:
            raise InstallError("Review Desk bundle exceeds the 40 MiB uncompressed safety limit")
        names: set[str] = set()
        folded: set[str] = set()
        for info in infos:
            if info.is_dir() or info.flag_bits & 0x1 or info.file_size > 10 * 1024 * 1024:
                raise InstallError(f"unsafe Review Desk bundle entry: {info.filename}")
            mode = info.external_attr >> 16
            if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                raise InstallError(f"non-regular Review Desk bundle entry: {info.filename}")
            if info.filename == REVIEW_DESK_MANIFEST_NAME:
                path = PurePosixPath(info.filename)
            else:
                path = _safe_bundle_path(info.filename)
            normalized = path.as_posix()
            if normalized.casefold() in folded:
                raise InstallError(f"duplicate or case-colliding Review Desk bundle entry: {normalized}")
            folded.add(normalized.casefold())
            names.add(normalized)
        if REVIEW_DESK_MANIFEST_NAME not in names:
            raise InstallError("Review Desk bundle is missing bundle-manifest.json")
        manifest_bytes = archive.read(REVIEW_DESK_MANIFEST_NAME)
        manifest = _strict_json_object(manifest_bytes, "Review Desk bundle manifest")
        if set(manifest) != {"files", "package", "schema_version"}:
            raise InstallError("Review Desk bundle manifest has unexpected fields")
        if manifest.get("schema_version") != "1" or manifest.get("package") != "econ-review-desk":
            raise InstallError("Review Desk bundle manifest has the wrong package or schema version")
        records = manifest.get("files")
        if not isinstance(records, list) or not records:
            raise InstallError("Review Desk bundle manifest files must be a non-empty array")
        expected = {REVIEW_DESK_MANIFEST_NAME}
        previous = ""
        checked: list[dict[str, object]] = []
        for record in records:
            if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                raise InstallError("Review Desk bundle manifest contains an invalid file record")
            path = _safe_bundle_path(record.get("path"))
            name = path.as_posix()
            if name <= previous:
                raise InstallError("Review Desk bundle manifest file records must be sorted and unique")
            previous = name
            digest = record.get("sha256")
            size = record.get("size")
            if not isinstance(digest, str) or len(digest) != 64 or any(c not in "0123456789abcdef" for c in digest):
                raise InstallError(f"invalid Review Desk file hash: {name}")
            if not isinstance(size, int) or isinstance(size, bool) or size < 0:
                raise InstallError(f"invalid Review Desk file size: {name}")
            if name not in names:
                raise InstallError(f"Review Desk bundle is missing a manifest-declared file: {name}")
            data = archive.read(name)
            if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                raise InstallError(f"Review Desk bundle content does not match its manifest: {name}")
            expected.add(name)
            checked.append(record)
        if names != expected:
            raise InstallError("Review Desk bundle entries differ from its manifest")
        if not {
            "launch_review_desk.py",
            "launch_installed_review_desk.py",
            "app/index.html",
        }.issubset(expected):
            raise InstallError("Review Desk bundle lacks its launcher or application entry point")
        _verify_review_desk_licenses(archive, expected)
    digest = hashlib.sha256(manifest_bytes).hexdigest()
    return manifest_bytes, checked, digest


def review_desk_is_current(
    destination: Path,
    manifest_bytes: bytes,
    records: list[dict[str, object]],
) -> bool:
    if not destination.is_dir() or _is_link_or_junction(destination):
        return False
    expected_files = {REVIEW_DESK_MANIFEST_NAME} | {
        str(record["path"])
        for record in records
    }
    if not _tree_has_exact_membership(destination, expected_files):
        return False
    manifest = destination / REVIEW_DESK_MANIFEST_NAME
    if not manifest.is_file() or _is_link_or_junction(manifest) or manifest.read_bytes() != manifest_bytes:
        return False
    for record in records:
        relative = Path(*PurePosixPath(str(record["path"])).parts)
        candidate = destination / relative
        if not candidate.is_file() or _is_link_or_junction(candidate):
            return False
        data = candidate.read_bytes()
        if len(data) != record["size"] or hashlib.sha256(data).hexdigest() != record["sha256"]:
            return False
    return True


def review_desk_dispatcher_is_current(root: Path, version: Path, digest: str) -> bool:
    launcher = root / "launch_review_desk.py"
    source = version / "launch_installed_review_desk.py"
    pointer = root / "current.json"
    if any(_is_link_or_junction(path) for path in (launcher, pointer)):
        return False
    if not launcher.is_file() or not source.is_file() or launcher.read_bytes() != source.read_bytes():
        return False
    try:
        value = json.loads(pointer.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError):
        return False
    return value == {"digest": digest, "schema_version": "1"}


def review_desk_cmd_bytes(runtime_python: Path) -> bytes:
    """Build a click-friendly Windows launcher bound to the managed runtime."""

    raw_python = str(runtime_python)
    if any(character in raw_python for character in ('"', "\r", "\n")):
        raise InstallError("managed runtime path cannot be represented safely in review-desk.cmd")
    # Percent signs expand even inside cmd.exe quotes; doubling preserves a
    # literal percent in an unusual but valid user-owned path.
    quoted_python = '"' + raw_python.replace("%", "%%") + '"'
    text = (
        "@echo off\r\n"
        "setlocal DisableDelayedExpansion\r\n"
        "chcp 65001 >nul\r\n"
        "set PYTHONUTF8=1\r\n"
        f"{quoted_python} -I \"%~dp0launch_review_desk.py\" %*\r\n"
        "exit /b %ERRORLEVEL%\r\n"
    )
    return text.encode("utf-8")


def format_launch_command(
    arguments: Sequence[str | Path],
    *,
    system: str | None = None,
) -> str:
    """Return a pasteable launch command for the documented platform shell.

    macOS and Linux instructions use a POSIX shell.  Native Windows
    instructions use PowerShell, where a quoted executable path must be
    invoked with the call operator.  Keeping the two quoting rules separate
    prevents shell expansion in unusual but valid user-owned paths.
    """

    values = [str(argument) for argument in arguments]
    if any("\r" in value or "\n" in value for value in values):
        raise InstallError("Review Desk launch-command paths cannot contain line breaks")
    if (system or platform.system()) == "Windows":
        quoted = ["'" + value.replace("'", "''") + "'" for value in values]
        return "& " + " ".join(quoted)
    return shlex.join(values)


def install_review_desk_cmd(
    root: Path,
    runtime_python: Path,
    *,
    dry_run: bool,
) -> Path:
    """Install or refresh the Windows dispatcher without touching app bytes."""

    destination = root / REVIEW_DESK_WINDOWS_LAUNCHER
    expected = review_desk_cmd_bytes(runtime_python)
    if destination.exists() and (
        _is_link_or_junction(destination) or not destination.is_file()
    ):
        raise InstallError(f"refusing unsafe Review Desk Windows launcher: {destination}")
    current = destination.is_file() and destination.read_bytes() == expected
    if dry_run:
        print(
            f"Would {'keep current' if current else 'install'} Review Desk Windows launcher: "
            f"{destination}"
        )
    elif current:
        print(f"Already current Review Desk Windows launcher: {destination}")
    else:
        temporary = root / f".review-desk-{uuid.uuid4().hex}.cmd"
        try:
            temporary.write_bytes(expected)
            temporary.replace(destination)
        finally:
            temporary.unlink(missing_ok=True)
        print(f"Installed Review Desk Windows launcher: {destination}")
    return destination


def install_review_desk(
    bundle: Path,
    root: Path,
    *,
    dry_run: bool,
    runtime_python: Path | None = None,
    system: str | None = None,
) -> Path:
    manifest_bytes, records, digest = verify_review_desk_bundle(bundle)
    if root.exists() and _is_link_or_junction(root):
        raise InstallError(f"refusing linked or junction Review Desk root: {root}")
    if (root / "versions").exists() and _is_link_or_junction(root / "versions"):
        raise InstallError(f"refusing linked or junction Review Desk versions directory: {root / 'versions'}")
    destination = root / "versions" / digest
    launcher = root / "launch_review_desk.py"
    if destination.exists():
        if not review_desk_is_current(destination, manifest_bytes, records):
            raise InstallError(f"immutable Review Desk version is present but fails verification: {destination}")
        print(f"{'Would keep current' if dry_run else 'Already current'} Review Desk: {destination}")
    elif dry_run:
        print(f"Would install verified Review Desk: {destination}")
    else:
        versions = root / "versions"
        versions.mkdir(parents=True, exist_ok=True)
        stage = Path(tempfile.mkdtemp(prefix=".review-desk-stage-", dir=versions))
        try:
            with zipfile.ZipFile(bundle) as archive:
                (stage / REVIEW_DESK_MANIFEST_NAME).write_bytes(manifest_bytes)
                for record in records:
                    pure = PurePosixPath(str(record["path"]))
                    target = stage.joinpath(*pure.parts)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    with target.open("xb") as stream:
                        stream.write(archive.read(pure.as_posix()))
                    target.chmod(0o755 if pure.name == "launch_review_desk.py" else 0o644)
            if not review_desk_is_current(stage, manifest_bytes, records):
                raise InstallError("staged Review Desk failed verification")
            stage.rename(destination)
        except BaseException:
            shutil.rmtree(stage, ignore_errors=True)
            raise
        print(f"Installed verified Review Desk: {destination}")
    dispatcher_current = review_desk_dispatcher_is_current(root, destination, digest)
    if dry_run and not dispatcher_current:
        print(f"Would install Review Desk launcher: {launcher}")
    elif not dry_run and not dispatcher_current:
        dispatcher_source = destination / "launch_installed_review_desk.py"
        if launcher.is_symlink() or _is_link_or_junction(launcher):
            raise InstallError(f"refusing linked or junction Review Desk launcher: {launcher}")
        pointer = root / "current.json"
        if pointer.is_symlink() or _is_link_or_junction(pointer):
            raise InstallError(f"refusing linked or junction Review Desk pointer: {pointer}")
        launcher_temporary = root / f".launch-review-desk-{uuid.uuid4().hex}.tmp"
        pointer_temporary = root / f".current-{uuid.uuid4().hex}.tmp"
        try:
            shutil.copy2(dispatcher_source, launcher_temporary)
            launcher_temporary.chmod(0o755)
            _write_json(pointer_temporary, {"digest": digest, "schema_version": "1"})
            launcher_temporary.replace(launcher)
            pointer_temporary.replace(pointer)
        finally:
            launcher_temporary.unlink(missing_ok=True)
            pointer_temporary.unlink(missing_ok=True)
        print(f"Installed Review Desk launcher: {launcher}")
    elif not dry_run:
        print(f"Already current Review Desk launcher: {launcher}")
    launcher_python = runtime_python or Path(sys.executable)
    if (system or platform.system()) == "Windows" and runtime_python is not None:
        windows_launcher = install_review_desk_cmd(
            root,
            runtime_python,
            dry_run=dry_run,
        )
        launch_command = format_launch_command([windows_launcher], system="Windows")
    else:
        launch_command = format_launch_command(
            [launcher_python, "-I", launcher],
            system=system,
        )
    print(f"Review Desk launch command: {launch_command}")
    print("Review Desk URL: http://127.0.0.1:48127/")
    return destination


def installation_destinations(
    scope: str,
    project: Path | None,
    agent: str,
) -> list[tuple[Path, str]]:
    if scope == "local":
        assert project is not None
        choices = {
            "claude": (project / ".claude" / "skills" / "econ-review", "Claude Code (project)"),
            "codex": (project / ".agents" / "skills" / "econ-review", "Codex (project)"),
        }
    else:
        home = Path.home()
        choices = {}
        if agent in {"all", "claude"}:
            claude_root = environment_path("CLAUDE_CONFIG_DIR", home / ".claude")
            choices["claude"] = (
                claude_root / "skills" / "econ-review",
                "Claude Code (global)",
            )
        if agent in {"all", "codex"}:
            choices["codex"] = (
                home / ".agents" / "skills" / "econ-review",
                "Codex (global)",
            )
    keys = ("claude", "codex") if agent == "all" else (agent,)
    return [choices[key] for key in keys]


def poppler_guidance(system: str | None = None) -> str:
    system = system or platform.system()
    if system == "Windows":
        return (
            "Poppler is not installed or not on PATH. For a non-admin setup, install it in a "
            "user-owned Conda/micromamba environment (`conda install -c conda-forge poppler`) "
            "or unpack a trusted Windows build in a user folder and add its bin directory to PATH."
        )
    if system == "Darwin":
        return (
            "Poppler is not installed or not on PATH. For a non-admin setup, use a user-managed Homebrew installation "
            "(`brew install poppler`) or a user-owned Conda/micromamba environment "
            "(`conda install -c conda-forge poppler`)."
        )
    return (
        "Poppler is not installed or not on PATH. Without administrator access, install it in a "
        "user-owned Conda/micromamba environment (`conda install -c conda-forge poppler`)."
    )


def run_doctor(python: Path, skill: Path) -> bool:
    doctor_environment = os.environ.copy()
    doctor_environment["PYTHONDONTWRITEBYTECODE"] = "1"
    result = _run_quiet(
        [
            str(python),
            "-B",
            "-I",
            str(skill / "scripts" / "pdf_ingestion.py"),
            "doctor",
        ],
        env=doctor_environment,
        cwd=skill,
    )
    if result.stdout.strip():
        print(result.stdout.rstrip())
    if result.stderr.strip():
        print("PDF doctor returned an error; details were suppressed to avoid echoing local configuration.")
    if result.returncode:
        missing = [name for name in REQUIRED_POPPLER_COMMANDS if shutil.which(name) is None]
        if missing:
            print(f"Missing required Poppler commands: {', '.join(missing)}")
            print(poppler_guidance())
        else:
            print("PDF readiness check failed even though Poppler commands are visible; rerun the doctor directly.")
        return False
    print("PDF and core dependency health check passed.")
    return True


def parser() -> argparse.ArgumentParser:
    root = argparse.ArgumentParser(
        description="Prepare econ-review from a trusted self-contained package.",
    )
    scope = root.add_mutually_exclusive_group()
    scope.add_argument(
        "--global",
        dest="global_install",
        action="store_true",
        help="install in user agent homes (default)",
    )
    scope.add_argument(
        "--local",
        nargs="?",
        const=".",
        metavar="DIRECTORY",
        help="install for one project (default directory: current directory)",
    )
    agent = root.add_mutually_exclusive_group()
    agent.add_argument(
        "--all",
        dest="agent",
        action="store_const",
        const="all",
        help="install for both agents explicitly",
    )
    agent.add_argument(
        "--claude",
        dest="agent",
        action="store_const",
        const="claude",
        help="install for Claude Code only",
    )
    agent.add_argument("--codex", dest="agent", action="store_const", const="codex", help="install for Codex only")
    root.set_defaults(agent=None)
    root.add_argument("--source", type=Path, help="trusted local econ-review skill directory")
    root.add_argument("--runtime-dir", type=Path, help="managed runtime location")
    root.add_argument("--refresh-runtime", action="store_true", help="rebuild the managed runtime")
    root.add_argument("--copy-only", action="store_true", help="copy the skill without changing Python")
    root.add_argument(
        "--support-only",
        action="store_true",
        help="prepare the runtime and optional Review Desk without copying the skill",
    )
    root.add_argument(
        "--runtime-path",
        action="store_true",
        help="print the verified managed Python path without changing files",
    )
    root.add_argument(
        "--cleanup-support",
        action="store_true",
        help="preview or explicitly remove the default runtime, descriptor, and Review Desk",
    )
    root.add_argument(
        "--confirm-cleanup",
        action="store_true",
        help="confirm destructive support cleanup (requires --cleanup-support)",
    )
    root.add_argument("--check", action="store_true", help="run the doctor even with --copy-only")
    root.add_argument(
        "--with-review-desk",
        "--with-viewer",
        dest="with_review_desk",
        action="store_true",
        help="install the prebuilt local Review Desk (no Node.js required)",
    )
    root.add_argument("--review-desk-dir", type=Path, help="Review Desk installation root")
    root.add_argument("--review-desk-bundle", type=Path, help=argparse.SUPPRESS)
    root.add_argument("--dry-run", action="store_true", help="show changes without writing files")
    return root


def _perform_setup(
    args: argparse.Namespace,
    source: Path,
    files: list[Path],
    scope: str,
    project: Path | None,
    mutable_root: Path,
    support_descriptor: Path,
) -> int:
    """Apply or preview setup after validation and lock selection."""

    source_manifest = file_manifest(source, files)
    core_version = requirements_digest(source / "requirements-core.txt")
    destinations = (
        []
        if args.support_only
        else installation_destinations(scope, project, args.agent)
    )
    for destination, label in destinations:
        reject_source_overlap(destination, source, f"{label} destination")
    runtime_python: Path | None = None
    runtime: Path | None = None
    if not args.copy_only:
        default_runtime = args.runtime_dir is None
        runtime = (
            args.runtime_dir.expanduser().absolute()
            if args.runtime_dir
            else runtime_default(scope, project, version_key=core_version)
        )
        reject_source_overlap(runtime, source, "managed runtime")
        if default_runtime:
            require_safe_support_path(runtime, mutable_root, "managed runtime")
        reuse_if_bound = False
        if not args.dry_run and not args.refresh_runtime:
            bound_python = recorded_runtime_python(support_descriptor, source)
            if bound_python is not None:
                _actual_runtime, expected_python = resolve_runtime_location(runtime)
                reuse_if_bound = os.path.normcase(str(bound_python.absolute())) == os.path.normcase(
                    str(expected_python.absolute())
                )
        runtime_python = ensure_runtime(
            runtime,
            source,
            refresh=args.refresh_runtime,
            dry_run=args.dry_run,
            reuse_if_bound=reuse_if_bound,
        )
        record_support_runtime(
            support_descriptor,
            runtime,
            runtime_python,
            source,
            dry_run=args.dry_run,
        )
    for destination, label in destinations:
        install_one(
            source,
            files,
            source_manifest,
            destination,
            label,
            runtime_python,
            dry_run=args.dry_run,
        )
    if scope == "global" and not args.support_only and args.agent in {"all", "codex"}:
        migrate_legacy_codex_copies(
            source_manifest,
            runtime_python,
            dry_run=args.dry_run,
        )
    review_desk_path: Path | None = None
    if args.with_review_desk:
        bundle = (args.review_desk_bundle or source / REVIEW_DESK_BUNDLE).expanduser().absolute()
        default_desk_root = review_desk_default(scope, project)
        configured_desk_root = os.environ.get("ECON_REVIEW_DESK_HOME")
        desk_root = (
            args.review_desk_dir.expanduser().absolute()
            if args.review_desk_dir
            else environment_path("ECON_REVIEW_DESK_HOME", default_desk_root)
        )
        reject_source_overlap(desk_root, source, "Review Desk destination")
        if args.review_desk_dir is None and configured_desk_root is None:
            require_safe_support_path(desk_root, mutable_root, "Review Desk destination")
        review_desk_path = install_review_desk(
            bundle,
            desk_root,
            dry_run=args.dry_run,
            runtime_python=runtime_python,
        )
    if args.dry_run:
        if not args.copy_only or args.check:
            print("Would run the core dependency and Poppler health check.")
        print("Dry run complete; no files changed.")
        return 0
    healthy = True
    if not args.copy_only or args.check:
        doctor_python = runtime_python or Path(sys.executable)
        doctor_source = source if args.support_only else destinations[0][0]
        healthy = run_doctor(doctor_python, doctor_source)
    if args.copy_only:
        print("Lightweight copy-only installation complete; Python and system dependencies were unchanged.")
    elif healthy:
        if args.support_only:
            print("econ-review supporting setup is complete and ready for the installed plugin.")
        else:
            print("econ-review setup complete and ready.")
    else:
        print(
            "econ-review support was prepared, but PDF setup is incomplete; "
            "follow the Poppler guidance and rerun this command."
        )
    if review_desk_path is not None:
        print("Review Desk is installed and ready without Node.js or npm.")
    if not args.support_only:
        clients = {
            "claude": "Claude Code",
            "codex": "Codex",
            "all": "Claude Code and Codex",
        }
        print(
            f"Restart or reload {clients[args.agent]} so it discovers the installed skill."
        )
    return 0 if healthy else 2


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallError("Python 3.10 or newer is required")
    source = (args.source or SKILL_ROOT).expanduser().absolute()
    if not args.with_review_desk and (args.review_desk_dir or args.review_desk_bundle):
        raise InstallError("--review-desk-dir and --review-desk-bundle require --with-review-desk")
    if args.support_only and args.copy_only:
        raise InstallError("--support-only cannot be combined with --copy-only")
    selected_agent = args.agent
    if args.support_only and selected_agent is not None:
        raise InstallError("--support-only does not accept --claude or --codex")
    if args.cleanup_support and selected_agent is not None:
        raise InstallError("--cleanup-support does not accept --claude, --codex, or --all")
    if args.runtime_path and selected_agent is not None:
        raise InstallError("--runtime-path does not accept --claude, --codex, or --all")
    if args.support_only or args.cleanup_support or args.runtime_path:
        args.agent = "all"
    elif selected_agent is None:
        raise InstallError("choose exactly one of --claude, --codex, or --all")
    if args.confirm_cleanup and not args.cleanup_support:
        raise InstallError("--confirm-cleanup requires --cleanup-support")
    if args.cleanup_support and args.dry_run and args.confirm_cleanup:
        raise InstallError("choose either --dry-run or --confirm-cleanup for support cleanup")
    if args.cleanup_support and any(
        (
            args.support_only,
            args.copy_only,
            args.refresh_runtime,
            args.check,
            args.with_review_desk,
            args.runtime_path,
            args.runtime_dir is not None,
            args.review_desk_dir is not None,
            args.review_desk_bundle is not None,
            args.agent != "all",
        )
    ):
        raise InstallError("--cleanup-support cannot be combined with setup or installation options")
    if args.cleanup_support and not (args.dry_run or args.confirm_cleanup):
        raise InstallError("support cleanup requires --dry-run or --confirm-cleanup")
    if args.runtime_path and any(
        (
            args.support_only,
            args.copy_only,
            args.refresh_runtime,
            args.check,
            args.with_review_desk,
            args.runtime_dir is not None,
            args.review_desk_dir is not None,
            args.review_desk_bundle is not None,
            args.dry_run,
            args.cleanup_support,
            args.confirm_cleanup,
        )
    ):
        raise InstallError("--runtime-path cannot be combined with setup or installation options")
    files = validate_source(source)
    core_version = requirements_digest(source / "requirements-core.txt")
    scope = "local" if args.local is not None else "global"
    project = None
    if scope == "local":
        project = Path(args.local).expanduser().resolve()
        if not project.is_dir() and not args.cleanup_support:
            raise InstallError(f"local project directory does not exist: {project}")
    mutable_root = support_data_root()
    support_descriptor = support_descriptor_default(
        scope,
        project,
        version_key=core_version,
    )
    require_safe_support_path(support_descriptor, mutable_root, "runtime descriptor")
    reject_source_overlap(support_descriptor, source, "runtime descriptor")
    if args.cleanup_support:
        if args.confirm_cleanup:
            with support_setup_lock(scope, project):
                cleanup_support_state(
                    scope,
                    project,
                    source,
                    dry_run=False,
                )
        else:
            cleanup_support_state(
                scope,
                project,
                source,
                dry_run=True,
            )
        return 0
    if args.runtime_path:
        python = recorded_runtime_python(support_descriptor, source)
        if python is None:
            legacy_descriptor = support_descriptor_default(scope, project)
            if legacy_descriptor != support_descriptor:
                python = recorded_runtime_python(legacy_descriptor, source)
        if python is None:
            return 2
        print(python)
        return 0
    if args.dry_run or (args.copy_only and not args.with_review_desk):
        return _perform_setup(
            args,
            source,
            files,
            scope,
            project,
            mutable_root,
            support_descriptor,
        )
    with support_setup_lock(scope, project):
        return _perform_setup(
            args,
            source,
            files,
            scope,
            project,
            mutable_root,
            support_descriptor,
        )


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    try:
        raise SystemExit(main())
    except (InstallError, OSError, subprocess.SubprocessError) as exc:
        print(f"econ-review setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
