#!/usr/bin/env python3
"""Validate and build a deterministic, source-allowlisted public release."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import stat
import sys
import tempfile
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from typing import Any


PACKAGE_NAME = "econ-paper-review-skill"
ARCHIVE_FORMAT_VERSION = 1
FILE_CONTRACT = Path("scripts/public-release-files.json")
SCAN_ROOTS = (
    Path(".claude-plugin"),
    Path(".github"),
    Path("benchmarks"),
    Path("docs"),
    Path("econ-review"),
    Path("review-viewer"),
    Path("scripts"),
    Path("tests"),
)
EXCLUDED_RELATIVE_PREFIXES = {Path("benchmarks/reviews")}
EXPLICIT_EXCLUDED_TREE_FILES = {Path("review-viewer/public/favicon.svg")}
ROOT_FILES = {
    Path(".gitattributes"),
    Path(".gitignore"),
    Path("CONTRIBUTING.md"),
    Path("LICENSE"),
    Path("README.md"),
    Path("THIRD_PARTY_NOTICES.md"),
    Path("install.sh"),
    Path("requirements-docling.txt"),
    Path("requirements-markitdown.txt"),
    Path("requirements-mathpix.txt"),
    Path("requirements.txt"),
}
FIRST_PARTY_LICENSES = (
    Path("LICENSE"),
    Path("econ-review/LICENSE"),
    Path("review-viewer/LICENSE"),
)
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
    "static-dist",
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
    ".svg",
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
REVIEW_DESK_FIRST_PARTY_LICENSE = "app/LICENSE.txt"
REVIEW_DESK_THIRD_PARTY_NOTICE = "app/THIRD_PARTY_NOTICES.txt"
REVIEW_DESK_THIRD_PARTY_MANIFEST = "app/third-party-licenses/manifest.json"
REVIEW_DESK_KATEX_FONT_LICENSE = "app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt"
REVIEW_DESK_REQUIRED_RUNTIME_PACKAGES = frozenset(
    {"katex", "react", "react-dom", "react-markdown", "rehype-katex", "remark-gfm", "remark-math"}
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
    """Return a host-independent archive mode.

    Native Windows does not preserve POSIX executable bits in a checkout.  A
    mode derived from ``stat`` therefore made Windows-built archives differ
    from macOS/Linux builds and left ``install.sh`` non-executable after a
    later POSIX extraction.  Public entry points are executable by contract;
    all other source files are data.
    """
    return 0o755 if path.name == "install.sh" or path.suffix.casefold() == ".py" else 0o644


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
            if (
                any(part in EXCLUDED_DIRECTORY_NAMES for part in relative.parts[:-1])
                and relative not in EXPLICIT_EXCLUDED_TREE_FILES
            ):
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


def _scan_review_desk_licenses(
    archive: zipfile.ZipFile,
    expected: set[str],
    first_party_license: bytes,
) -> None:
    if REVIEW_DESK_FIRST_PARTY_LICENSE not in expected:
        raise ValueError("Review Desk release is missing its first-party license")
    embedded_license = archive.read(REVIEW_DESK_FIRST_PARTY_LICENSE)
    try:
        embedded_license_text = embedded_license.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"Review Desk first-party license is not UTF-8: {exc}") from exc
    if not embedded_license_text.strip():
        raise ValueError("Review Desk first-party license must not be empty")
    if embedded_license != first_party_license:
        raise ValueError("Review Desk first-party license differs from the project license")

    required = {
        REVIEW_DESK_THIRD_PARTY_NOTICE,
        REVIEW_DESK_THIRD_PARTY_MANIFEST,
        REVIEW_DESK_KATEX_FONT_LICENSE,
    }
    if not required.issubset(expected):
        raise ValueError("Review Desk release is missing embedded third-party notices or licenses")
    manifest_bytes = archive.read(REVIEW_DESK_THIRD_PARTY_MANIFEST)
    manifest = json.loads(
        manifest_bytes,
        object_pairs_hook=_reject_duplicate_pairs,
        parse_constant=_reject_json_constant,
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) != {"generated_from", "packages", "schema_version", "supplemental_assets"}
        or manifest.get("schema_version") != "1"
        or manifest.get("generated_from") != "Vite client output module graph and package-lock.json"
        or manifest_bytes != _canonical_json(manifest)
    ):
        raise ValueError("Review Desk third-party license manifest has an invalid contract")

    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("Review Desk third-party package inventory must be a non-empty array")
    keys: list[tuple[str, str]] = []
    referenced: set[str] = set()
    notice_bytes = archive.read(REVIEW_DESK_THIRD_PARTY_NOTICE)
    try:
        notice = notice_bytes.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"Review Desk third-party notice is not UTF-8: {exc}") from exc
    if not notice or not notice.endswith("\n"):
        raise ValueError("Review Desk third-party notice must be non-empty and newline-terminated")
    for package in packages:
        if not isinstance(package, dict) or set(package) != {
            "declared_license",
            "license_files",
            "name",
            "version",
        }:
            raise ValueError("Review Desk third-party package record has an invalid contract")
        name = package.get("name")
        version = package.get("version")
        declared_license = package.get("declared_license")
        license_files = package.get("license_files")
        if not all(isinstance(value, str) and value for value in (name, version, declared_license)):
            raise ValueError("Review Desk third-party package identity must use non-empty strings")
        if (
            not isinstance(license_files, list)
            or not license_files
            or not all(isinstance(path, str) and path for path in license_files)
            or len(license_files) != len(set(license_files))
        ):
            raise ValueError(f"Review Desk third-party package has invalid license files: {name}@{version}")
        keys.append((name, version))
        if f"{name} {version}" not in notice:
            raise ValueError(f"Review Desk third-party notice omits {name}@{version}")
        for license_path in license_files:
            if (
                not license_path.startswith("app/third-party-licenses/packages/")
                or license_path not in expected
                or not archive.read(license_path)
            ):
                raise ValueError(f"Review Desk package references a missing or empty license: {license_path}")
            referenced.add(license_path)
    if keys != sorted(keys) or len(keys) != len(set(keys)):
        raise ValueError("Review Desk third-party package records must be sorted and unique")
    missing = REVIEW_DESK_REQUIRED_RUNTIME_PACKAGES - {name for name, _version in keys}
    if missing:
        raise ValueError("Review Desk third-party inventory omits: " + ", ".join(sorted(missing)))

    supplemental = manifest.get("supplemental_assets")
    if not isinstance(supplemental, list) or len(supplemental) != 1 or not isinstance(supplemental[0], dict):
        raise ValueError("Review Desk third-party inventory must contain one KaTeX font record")
    font = supplemental[0]
    if (
        set(font) != {"component", "copyright", "declared_license", "license_files", "reserved_font_names"}
        or font.get("component") != "KaTeX font assets"
        or font.get("declared_license") != "SIL Open Font License 1.1"
        or font.get("license_files") != [REVIEW_DESK_KATEX_FONT_LICENSE]
        or not isinstance(font.get("reserved_font_names"), list)
        or not font["reserved_font_names"]
        or not all(isinstance(name, str) and name for name in font["reserved_font_names"])
        or not isinstance(font.get("copyright"), str)
        or not font["copyright"]
    ):
        raise ValueError("Review Desk third-party inventory has an invalid KaTeX font record")
    if not archive.read(REVIEW_DESK_KATEX_FONT_LICENSE):
        raise ValueError("Review Desk KaTeX font license is empty")
    referenced.add(REVIEW_DESK_KATEX_FONT_LICENSE)
    if "KaTeX font assets" not in notice or "SIL Open Font License 1.1" not in notice:
        raise ValueError("Review Desk third-party notice omits the KaTeX font license")

    emitted = {
        name
        for name in expected
        if name.startswith("app/third-party-licenses/") and name != REVIEW_DESK_THIRD_PARTY_MANIFEST
    }
    if emitted != referenced:
        raise ValueError("Review Desk license files differ from its embedded third-party inventory")


def _scan_review_desk_bundle(path: Path, first_party_license: bytes) -> None:
    """Fail closed if the distributable viewer is stale, unsafe, or private."""

    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        names: set[str] = set()
        folded: set[str] = set()
        for info in infos:
            name = info.filename
            pure = PurePosixPath(name)
            if (
                info.is_dir()
                or info.flag_bits & 0x1
                or pure.is_absolute()
                or ".." in pure.parts
                or "\\" in name
                or ":" in name
                or name != pure.as_posix()
                or stat.S_IFMT(info.external_attr >> 16) not in {0, stat.S_IFREG}
            ):
                raise ValueError(f"unsafe Review Desk release entry: {name}")
            if name.casefold() in folded:
                raise ValueError(f"duplicate or case-colliding Review Desk release entry: {name}")
            folded.add(name.casefold())
            names.add(name)
        manifest_name = "bundle-manifest.json"
        if manifest_name not in names:
            raise ValueError("Review Desk release is missing bundle-manifest.json")
        manifest = json.loads(
            archive.read(manifest_name),
            object_pairs_hook=_reject_duplicate_pairs,
            parse_constant=_reject_json_constant,
        )
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"files", "package", "schema_version"}
            or manifest.get("package") != "econ-review-desk"
            or manifest.get("schema_version") != "1"
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("Review Desk release has an invalid manifest contract")
        if archive.read(manifest_name) != _canonical_json(manifest):
            raise ValueError("Review Desk release manifest is not canonical JSON")
        expected = {manifest_name}
        previous = ""
        for record in manifest["files"]:
            if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                raise ValueError("Review Desk release manifest has an invalid file record")
            name = record.get("path")
            digest = record.get("sha256")
            size = record.get("size")
            if not isinstance(name, str) or name <= previous:
                raise ValueError("Review Desk release records must be sorted and unique")
            previous = name
            pure = PurePosixPath(name)
            if (
                pure.is_absolute()
                or ".." in pure.parts
                or "\\" in name
                or ":" in name
                or name != pure.as_posix()
                or pure.suffix.casefold() == ".map"
                or "node_modules" in pure.parts
                or "reviews" in pure.parts
            ):
                raise ValueError(f"forbidden Review Desk release content: {name}")
            if name not in names:
                raise ValueError(f"Review Desk release is missing a declared file: {name}")
            data = archive.read(name)
            if (
                not isinstance(size, int)
                or isinstance(size, bool)
                or size != len(data)
                or not isinstance(digest, str)
                or digest != _sha256(data)
            ):
                raise ValueError(f"Review Desk release file does not match its manifest: {name}")
            expected.add(name)
            if SENSITIVE_FILENAME.search(pure.name):
                raise ValueError(f"Review Desk release contains a sensitive filename: {name}")
            try:
                text = data.decode("utf-8")
            except UnicodeDecodeError:
                continue
            for label, pattern in SENSITIVE_CONTENT.items():
                if pattern.search(text):
                    raise ValueError(f"Review Desk release contains possible {label}: {name}")
        if names != expected:
            raise ValueError("Review Desk release entries differ from its manifest")
        if not {
            "app/index.html",
            "launch_installed_review_desk.py",
            "launch_review_desk.py",
        }.issubset(expected):
            raise ValueError("Review Desk release is missing a required entry point")
        _scan_review_desk_licenses(archive, expected, first_party_license)


def _first_party_license_bytes(root: Path, declared: set[Path]) -> bytes | None:
    """Require all distributed first-party license copies to be byte-identical."""

    required = set(FIRST_PARTY_LICENSES)
    present = required & declared
    if not present:
        return None
    if present != required:
        missing = ", ".join(path.as_posix() for path in sorted(required - present))
        raise ValueError(f"public release contract omits first-party license copy: {missing}")
    payloads: list[bytes] = []
    for relative in FIRST_PARTY_LICENSES:
        path = root / relative
        if not path.is_file() or path.is_symlink():
            raise ValueError(f"first-party license is missing or unsafe: {relative.as_posix()}")
        data = path.read_bytes()
        try:
            text = data.decode("utf-8")
        except UnicodeError as exc:
            raise ValueError(f"first-party license is not UTF-8: {relative.as_posix()}: {exc}") from exc
        if not text.strip():
            raise ValueError(f"first-party license is empty: {relative.as_posix()}")
        payloads.append(data)
    if len(set(payloads)) != 1:
        raise ValueError("distributed first-party license copies are not synchronized")
    return payloads[0]


def public_files(root: Path) -> list[Path]:
    """Return the exact, stable, symlink-free public file contract."""
    root = root.resolve()
    _, files = load_file_contract(root)
    declared = set(files)
    first_party_license = _first_party_license_bytes(root, declared)
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
    viewer_bundle = Path("review-viewer/release/review-desk.zip")
    if viewer_bundle in declared:
        if first_party_license is None:
            raise ValueError("Review Desk release requires the project first-party license")
        _scan_review_desk_bundle(root / viewer_bundle, first_party_license)
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
    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "econ-review" / "scripts"))
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
