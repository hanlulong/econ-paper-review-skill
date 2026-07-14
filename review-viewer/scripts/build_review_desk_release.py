#!/usr/bin/env python3
"""Create the deterministic, runtime-free Review Desk release bundle."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import stat
import tempfile
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
STATIC_ROOT = ROOT / "static-dist"
LAUNCHER = ROOT / "scripts" / "launch_review_desk.py"
INSTALLED_LAUNCHER = ROOT / "scripts" / "launch_installed_review_desk.py"
OUTPUT = ROOT / "release" / "review-desk.zip"
FIXED_TIME = (2020, 1, 1, 0, 0, 0)
FIRST_PARTY_LICENSE_SOURCE = ROOT / "LICENSE"
FIRST_PARTY_LICENSE = "app/LICENSE.txt"
THIRD_PARTY_NOTICE = "app/THIRD_PARTY_NOTICES.txt"
THIRD_PARTY_MANIFEST = "app/third-party-licenses/manifest.json"
KATEX_FONT_LICENSE = "app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt"
REQUIRED_RUNTIME_PACKAGES = frozenset(
    {
        "katex",
        "react",
        "react-dom",
        "react-markdown",
        "rehype-katex",
        "remark-gfm",
        "remark-math",
    }
)
EXPECTED_KATEX_RESERVED_NAMES = (
    "KaTeX_AMS",
    "KaTeX_Caligraphic",
    "KaTeX_Fraktur",
    "KaTeX_Main",
    "KaTeX_Math",
    "KaTeX_SansSerif",
    "KaTeX_Script",
    "KaTeX_Size1",
    "KaTeX_Size2",
    "KaTeX_Size3",
    "KaTeX_Size4",
    "KaTeX_Typewriter",
)


def source_files() -> list[tuple[str, Path]]:
    if not STATIC_ROOT.is_dir() or STATIC_ROOT.is_symlink():
        raise ValueError("static-dist is missing; run the static Vite build first")
    if not FIRST_PARTY_LICENSE_SOURCE.is_file() or FIRST_PARTY_LICENSE_SOURCE.is_symlink():
        raise ValueError("Review Desk first-party LICENSE is missing or unsafe")
    try:
        license_text = FIRST_PARTY_LICENSE_SOURCE.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise ValueError(f"Review Desk first-party LICENSE is not readable UTF-8: {exc}") from exc
    if not license_text.strip():
        raise ValueError("Review Desk first-party LICENSE must not be empty")
    for launcher in (LAUNCHER, INSTALLED_LAUNCHER):
        if not launcher.is_file() or launcher.is_symlink():
            raise ValueError(f"a Review Desk launcher is missing or unsafe: {launcher.name}")
    files: list[tuple[str, Path]] = [
        (FIRST_PARTY_LICENSE, FIRST_PARTY_LICENSE_SOURCE),
        ("launch_installed_review_desk.py", INSTALLED_LAUNCHER),
        ("launch_review_desk.py", LAUNCHER),
    ]
    folded: set[str] = {name.casefold() for name, _ in files}
    for current, directories, names in os.walk(STATIC_ROOT, followlinks=False):
        current_path = Path(current)
        kept: list[str] = []
        for name in directories:
            candidate = current_path / name
            if candidate.is_symlink():
                raise ValueError(f"static release contains a symbolic link: {candidate.relative_to(STATIC_ROOT)}")
            kept.append(name)
        directories[:] = kept
        for name in names:
            candidate = current_path / name
            relative = candidate.relative_to(STATIC_ROOT)
            if candidate.is_symlink() or not candidate.is_file():
                raise ValueError(f"static release contains a non-regular file: {relative}")
            if candidate.suffix.casefold() == ".map" or "reviews" in relative.parts or "node_modules" in relative.parts:
                raise ValueError(f"forbidden static release content: {relative.as_posix()}")
            archive_name = f"app/{relative.as_posix()}"
            if archive_name.casefold() in folded:
                raise ValueError(f"static release contains case-colliding paths: {archive_name}")
            folded.add(archive_name.casefold())
            files.append((archive_name, candidate))
    return sorted(files, key=lambda item: item[0])


def canonical_manifest(files: list[tuple[str, Path]]) -> bytes:
    records = [
        {
            "path": name,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            "size": path.stat().st_size,
        }
        for name, path in files
    ]
    value = {"files": records, "package": "econ-review-desk", "schema_version": "1"}
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def zip_info(name: str, *, executable: bool = False) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name, FIXED_TIME)
    info.compress_type = zipfile.ZIP_DEFLATED
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | (0o755 if executable else 0o644)) << 16
    return info


def build_bytes() -> bytes:
    files = source_files()
    manifest = canonical_manifest(files)
    with tempfile.SpooledTemporaryFile(max_size=32 * 1024 * 1024) as stream:
        with zipfile.ZipFile(stream, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=9) as archive:
            archive.writestr(zip_info("bundle-manifest.json"), manifest, compresslevel=9)
            for name, path in files:
                archive.writestr(
                    zip_info(name, executable=name in {"launch_review_desk.py", "launch_installed_review_desk.py"}),
                    path.read_bytes(),
                    compresslevel=9,
                )
        stream.seek(0)
        return stream.read()


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
        raise ValueError(f"{label} must be a JSON object")
    return value


def verify_embedded_licenses(
    archive: zipfile.ZipFile,
    expected: set[str],
) -> None:
    """Validate the complete, generated runtime-license inventory."""

    if FIRST_PARTY_LICENSE not in expected:
        raise ValueError("release bundle is missing its first-party license")
    embedded_license = archive.read(FIRST_PARTY_LICENSE)
    try:
        embedded_license_text = embedded_license.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"first-party license is not UTF-8: {exc}") from exc
    if not embedded_license_text.strip():
        raise ValueError("first-party license must not be empty")
    try:
        source_license = FIRST_PARTY_LICENSE_SOURCE.read_bytes()
    except OSError as exc:
        raise ValueError(f"could not read the Review Desk first-party LICENSE: {exc}") from exc
    if embedded_license != source_license:
        raise ValueError("release bundle first-party license is stale")

    required = {THIRD_PARTY_NOTICE, THIRD_PARTY_MANIFEST, KATEX_FONT_LICENSE}
    if not required.issubset(expected):
        raise ValueError("release bundle is missing embedded third-party notices or licenses")

    manifest_bytes = archive.read(THIRD_PARTY_MANIFEST)
    manifest = _strict_json_object(manifest_bytes, "third-party license manifest")
    if (
        set(manifest) != {"generated_from", "packages", "schema_version", "supplemental_assets"}
        or manifest.get("schema_version") != "1"
        or manifest.get("generated_from") != "Vite client output module graph and package-lock.json"
    ):
        raise ValueError("third-party license manifest has the wrong contract")
    canonical = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")
    if manifest_bytes != canonical:
        raise ValueError("third-party license manifest is not canonical JSON")

    packages = manifest.get("packages")
    if not isinstance(packages, list) or not packages:
        raise ValueError("third-party license manifest packages must be a non-empty array")
    package_keys: list[tuple[str, str]] = []
    referenced: set[str] = set()
    notice = archive.read(THIRD_PARTY_NOTICE)
    if not notice or not notice.endswith(b"\n"):
        raise ValueError("third-party notice must be non-empty UTF-8 text ending in a newline")
    try:
        notice_text = notice.decode("utf-8")
    except UnicodeError as exc:
        raise ValueError(f"third-party notice is not UTF-8: {exc}") from exc

    for package in packages:
        if not isinstance(package, dict) or set(package) != {
            "declared_license",
            "license_files",
            "name",
            "version",
        }:
            raise ValueError("third-party license manifest has an invalid package record")
        name = package.get("name")
        version = package.get("version")
        declared_license = package.get("declared_license")
        license_files = package.get("license_files")
        if not all(isinstance(value, str) and value for value in (name, version, declared_license)):
            raise ValueError("third-party package identity and license fields must be non-empty strings")
        if (
            not isinstance(license_files, list)
            or not license_files
            or not all(isinstance(path, str) and path for path in license_files)
            or len(license_files) != len(set(license_files))
        ):
            raise ValueError(f"third-party package has invalid license files: {name}@{version}")
        package_keys.append((name, version))
        if f"{name} {version}" not in notice_text:
            raise ValueError(f"third-party notice omits a bundled package: {name}@{version}")
        for path in license_files:
            if not path.startswith("app/third-party-licenses/packages/") or path not in expected:
                raise ValueError(f"third-party package references a missing or unsafe license file: {path}")
            if not archive.read(path):
                raise ValueError(f"third-party package license file is empty: {path}")
            referenced.add(path)
    if package_keys != sorted(package_keys) or len(package_keys) != len(set(package_keys)):
        raise ValueError("third-party package records must be sorted and unique")
    missing_packages = REQUIRED_RUNTIME_PACKAGES - {name for name, _version in package_keys}
    if missing_packages:
        raise ValueError(
            "third-party license manifest omits required runtime packages: "
            + ", ".join(sorted(missing_packages))
        )

    supplemental = manifest.get("supplemental_assets")
    if not isinstance(supplemental, list) or len(supplemental) != 1:
        raise ValueError("third-party license manifest must contain the KaTeX font asset record")
    font = supplemental[0]
    reserved_names = font.get("reserved_font_names") if isinstance(font, dict) else None
    if (
        not isinstance(font, dict)
        or set(font)
        != {"component", "copyright", "declared_license", "license_files", "reserved_font_names"}
        or font.get("component") != "KaTeX font assets"
        or font.get("declared_license") != "SIL Open Font License 1.1"
        or font.get("license_files") != [KATEX_FONT_LICENSE]
        or not isinstance(reserved_names, list)
        or tuple(reserved_names) != EXPECTED_KATEX_RESERVED_NAMES
        or not isinstance(font.get("copyright"), str)
        or not font["copyright"]
    ):
        raise ValueError("third-party license manifest has an invalid KaTeX font asset record")
    if not archive.read(KATEX_FONT_LICENSE):
        raise ValueError("KaTeX font license file is empty")
    referenced.add(KATEX_FONT_LICENSE)
    if "KaTeX font assets" not in notice_text or "SIL Open Font License 1.1" not in notice_text:
        raise ValueError("third-party notice omits the KaTeX font license")

    emitted = {
        name
        for name in expected
        if name.startswith("app/third-party-licenses/") and name != THIRD_PARTY_MANIFEST
    }
    if emitted != referenced:
        raise ValueError("third-party license files differ from the embedded license manifest")


def verify_bundle_bytes(data: bytes) -> None:
    try:
        archive = zipfile.ZipFile(io.BytesIO(data))
    except zipfile.BadZipFile as exc:
        raise ValueError(f"release bundle is not a readable ZIP: {exc}") from exc
    with archive:
        names = archive.namelist()
        if len(names) != len(set(names)) or "bundle-manifest.json" not in names:
            raise ValueError("release bundle has duplicate entries or no manifest")
        manifest_bytes = archive.read("bundle-manifest.json")
        manifest = _strict_json_object(manifest_bytes, "release bundle manifest")
        if (
            not isinstance(manifest, dict)
            or set(manifest) != {"files", "package", "schema_version"}
            or manifest.get("package") != "econ-review-desk"
            or manifest.get("schema_version") != "1"
            or not isinstance(manifest.get("files"), list)
        ):
            raise ValueError("release bundle manifest has the wrong contract")
        canonical = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")
        if manifest_bytes != canonical:
            raise ValueError("release bundle manifest is not canonical JSON")
        expected = {"bundle-manifest.json"}
        previous = ""
        for record in manifest["files"]:
            if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                raise ValueError("release bundle manifest has an invalid file record")
            name = record.get("path")
            if not isinstance(name, str) or name <= previous:
                raise ValueError("release bundle records are not sorted and unique")
            previous = name
            path = Path(*name.split("/"))
            if (
                not name
                or "\\" in name
                or ":" in name
                or name.startswith("/")
                or ".." in path.parts
                or path.suffix.casefold() == ".map"
                or "node_modules" in path.parts
                or "reviews" in path.parts
                or name not in names
            ):
                raise ValueError(f"release bundle contains an unsafe or forbidden path: {name}")
            payload = archive.read(name)
            if (
                not isinstance(record.get("size"), int)
                or isinstance(record.get("size"), bool)
                or record["size"] != len(payload)
                or not isinstance(record.get("sha256"), str)
                or record["sha256"] != hashlib.sha256(payload).hexdigest()
            ):
                raise ValueError(f"release bundle content does not match its manifest: {name}")
            expected.add(name)
        if set(names) != expected:
            raise ValueError("release bundle entries differ from its manifest")
        if not {
            "app/index.html",
            "launch_installed_review_desk.py",
            "launch_review_desk.py",
        }.issubset(expected):
            raise ValueError("release bundle is missing an entry point")
        verify_embedded_licenses(archive, expected)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true", help="verify that the checked-in bundle is current")
    args = parser.parse_args()
    if args.check:
        if not OUTPUT.is_file():
            raise SystemExit("Review Desk release bundle is missing")
        existing = OUTPUT.read_bytes()
        verify_bundle_bytes(existing)
        if STATIC_ROOT.is_dir():
            data = build_bytes()
            if existing != data:
                raise SystemExit("Review Desk release bundle is missing or stale")
            print(f"Review Desk release bundle is current: {hashlib.sha256(data).hexdigest()}")
        else:
            print(
                "Review Desk release bundle integrity passed; source freshness requires "
                "`npm run check:release`."
            )
        return 0
    data = build_bytes()
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    temporary = OUTPUT.with_name(f".{OUTPUT.name}.tmp")
    temporary.write_bytes(data)
    temporary.replace(OUTPUT)
    verify_bundle_bytes(data)
    print(f"Built {OUTPUT} ({len(data)} bytes; sha256={hashlib.sha256(data).hexdigest()})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
