#!/usr/bin/env python3
"""Prepare econ-review from its self-contained skill or plugin package.

Direct-source mode installs the skill for both agents, creates or reuses one
managed Python environment, and runs the PDF-ingestion doctor. Plugin mode can
prepare only the shared runtime and Review Desk without creating duplicate
skill copies. ``--copy-only`` preserves the original lightweight behavior.
"""

from __future__ import annotations

import argparse
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
import unicodedata
import uuid
import zipfile
from pathlib import Path, PurePosixPath
from typing import Iterable, Sequence


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
    project_key = hashlib.sha256(project_identity.encode("utf-8")).hexdigest()[:24]
    return root / "projects" / project_key


def runtime_default(scope: str, project: Path | None, system: str | None = None) -> Path:
    return support_scope_root(scope, project, system) / "runtime"


def review_desk_default(scope: str, project: Path | None, system: str | None = None) -> Path:
    return support_scope_root(scope, project, system) / "review-desk"


def support_descriptor_default(
    scope: str,
    project: Path | None,
    system: str | None = None,
) -> Path:
    """Return mutable setup state outside a versioned plugin or skill tree."""

    return support_scope_root(scope, project, system) / SUPPORT_DESCRIPTOR_NAME


def _paths_overlap(first: Path, second: Path) -> bool:
    """Compare both lexical and resolved forms so links cannot hide overlap."""

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
        (support_descriptor_default(scope, project), "runtime descriptor"),
        (runtime_default(scope, project), "managed runtime"),
        (review_desk_default(scope, project), "Review Desk"),
    )
    for path, label in targets:
        require_safe_support_path(path, mutable_root, label)
        reject_source_overlap(path, source, label)
        if _is_link_or_junction(path):
            raise InstallError(f"refusing linked or junction {label} during cleanup: {path}")
        if not path.exists():
            print(f"Would keep absent {label}: {path}" if dry_run else f"Already absent {label}: {path}")
            continue
        if label == "runtime descriptor" and not path.is_file():
            raise InstallError(f"refusing non-file runtime descriptor during cleanup: {path}")
        if label != "runtime descriptor" and not path.is_dir():
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
    """Record a verified runtime outside the immutable plugin package."""

    actual_runtime, actual_python = resolve_runtime_location(runtime)
    value = {
        "python": str(actual_python.absolute()),
        "requirements_sha256": requirements_digest(source / "requirements-core.txt"),
        "runtime": str(actual_runtime.absolute()),
        "schema_version": "1",
    }
    if dry_run:
        print(f"Would record managed runtime for plugin use: {descriptor}")
        return
    if python.absolute() != actual_python.absolute():
        raise InstallError("managed Python path changed before its descriptor was written")
    if not runtime_is_reusable(runtime, source):
        raise InstallError("refusing to record a managed runtime that failed verification")
    _atomic_private_json(descriptor, value)
    print(f"Recorded managed runtime for plugin use: {descriptor}")


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
    if dry_run:
        state = (
            "already current"
            if destination_is_current(destination, source_manifest, runtime_python)
            else "install"
        )
        print(f"Would {state} {label}: {destination}")
        return
    if destination.exists() and _is_link_or_junction(destination):
        raise InstallError(f"refusing linked or junction skill destination: {destination}")
    if destination_is_current(destination, source_manifest, runtime_python):
        print(f"Already current {label}: {destination}")
        return
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = Path(tempfile.mkdtemp(prefix=".econ-review-stage-", dir=destination.parent))
    backup = destination.with_name(f".{destination.name}.backup-{uuid.uuid4().hex}")
    had_previous = destination.exists()
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
            destination.rename(backup)
        stage.rename(destination)
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        if destination.exists() and not had_previous:
            shutil.rmtree(destination, ignore_errors=True)
        if had_previous and backup.exists() and not destination.exists():
            backup.rename(destination)
        raise
    else:
        if backup.exists():
            shutil.rmtree(backup)
    print(f"Installed {label}: {destination}")


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
        claude_root = environment_path("CLAUDE_CONFIG_DIR", home / ".claude")
        codex_root = environment_path("CODEX_HOME", home / ".codex")
        choices = {
            "claude": (claude_root / "skills" / "econ-review", "Claude Code (global)"),
            "codex": (codex_root / "skills" / "econ-review", "Codex (global)"),
        }
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
        help="install for both agents (default)",
    )
    agent.add_argument(
        "--claude",
        dest="agent",
        action="store_const",
        const="claude",
        help="install for Claude Code only",
    )
    agent.add_argument("--codex", dest="agent", action="store_const", const="codex", help="install for Codex only")
    root.set_defaults(agent="all")
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


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if sys.version_info < MINIMUM_PYTHON:
        raise InstallError("Python 3.10 or newer is required")
    source = (args.source or SKILL_ROOT).expanduser().absolute()
    if not args.with_review_desk and (args.review_desk_dir or args.review_desk_bundle):
        raise InstallError("--review-desk-dir and --review-desk-bundle require --with-review-desk")
    if args.support_only and args.copy_only:
        raise InstallError("--support-only cannot be combined with --copy-only")
    if args.support_only and args.agent != "all":
        raise InstallError("--support-only does not accept --claude or --codex")
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
    scope = "local" if args.local is not None else "global"
    project = None
    if scope == "local":
        project = Path(args.local).expanduser().resolve()
        if not project.is_dir() and not args.cleanup_support:
            raise InstallError(f"local project directory does not exist: {project}")
    mutable_root = support_data_root()
    support_descriptor = support_descriptor_default(scope, project)
    require_safe_support_path(support_descriptor, mutable_root, "runtime descriptor")
    reject_source_overlap(support_descriptor, source, "runtime descriptor")
    if args.cleanup_support:
        cleanup_support_state(
            scope,
            project,
            source,
            dry_run=not args.confirm_cleanup,
        )
        return 0
    if args.runtime_path:
        python = recorded_runtime_python(support_descriptor, source)
        if python is None:
            return 2
        print(python)
        return 0
    source_manifest = file_manifest(source, files)
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
            else runtime_default(scope, project)
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
    review_desk_path: Path | None = None
    if args.with_review_desk:
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
        bundle = (args.review_desk_bundle or source / REVIEW_DESK_BUNDLE).expanduser().absolute()
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
        print("Restart or reload Codex and Claude Code sessions so they discover the installed skill.")
    return 0 if healthy else 2


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    try:
        raise SystemExit(main())
    except (InstallError, OSError, subprocess.SubprocessError) as exc:
        print(f"econ-review setup failed: {exc}", file=sys.stderr)
        raise SystemExit(1)
