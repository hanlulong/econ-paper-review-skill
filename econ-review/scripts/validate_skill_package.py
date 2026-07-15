#!/usr/bin/env python3
"""Validate the portable econ-review skill package without Codex internals."""

from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
import re
import stat
import sys
import unicodedata
import zipfile
from pathlib import Path, PurePosixPath
from urllib.parse import unquote

import yaml
from jsonschema import Draft202012Validator, SchemaError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import strict_json_load, strict_json_loads  # noqa: E402


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
LOCAL_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
STRICT_SEMVER = re.compile(
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)\."
    r"(?:0|[1-9][0-9]*)"
    r"(?:-(?:"
    r"(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*)"
    r"(?:\.(?:0|[1-9][0-9]*|[0-9]*[A-Za-z-][0-9A-Za-z-]*))*"
    r"))?"
    r"(?:\+[0-9A-Za-z-]+(?:\.[0-9A-Za-z-]+)*)?"
)
ALLOWED_FRONTMATTER = {"name", "description"}
ALLOWED_OPENAI_TOP_LEVEL = {"interface", "dependencies", "policy"}
REQUIRED_RUNTIME = {
    "cli_io.py",
    "dependency_versions.py",
    "finalize_review.py",
    "propose_source_inventory.py",
    "query_source.py",
    "review_timing.py",
    "safe_io.py",
    "setup_econ_review.py",
    "trust_spine.py",
    "validate_review.py",
}
REVIEW_DESK_BUNDLE = Path("assets/review-desk.zip")
REVIEW_DESK_REQUIRED_FILES = {
    "app/LICENSE.txt",
    "app/THIRD_PARTY_NOTICES.txt",
    "app/index.html",
    "app/third-party-licenses/katex-fonts/KATEX-FONTS-OFL-1.1.txt",
    "app/third-party-licenses/manifest.json",
    "launch_installed_review_desk.py",
    "launch_review_desk.py",
}


class UniqueKeySafeLoader(yaml.SafeLoader):
    """Safe YAML loader that rejects duplicate mapping keys."""


def _construct_unique_mapping(
    loader: UniqueKeySafeLoader, node: yaml.MappingNode, deep: bool = False,
) -> dict:
    loader.flatten_mapping(node)
    mapping: dict = {}
    for key_node, value_node in node.value:
        key = loader.construct_object(key_node, deep=deep)
        try:
            duplicate = key in mapping
        except TypeError as exc:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                "found an unhashable mapping key",
                key_node.start_mark,
            ) from exc
        if duplicate:
            raise yaml.constructor.ConstructorError(
                "while constructing a mapping",
                node.start_mark,
                f"found duplicate key {key!r}",
                key_node.start_mark,
            )
        mapping[key] = loader.construct_object(value_node, deep=deep)
    return mapping


UniqueKeySafeLoader.add_constructor(
    yaml.resolver.BaseResolver.DEFAULT_MAPPING_TAG,
    _construct_unique_mapping,
)


def _yaml_mapping(text: str, label: str, errors: list[str]) -> dict:
    loader = UniqueKeySafeLoader(text)
    try:
        value = loader.get_single_data()
    except yaml.YAMLError as exc:
        errors.append(f"{label} is not valid YAML: {exc}")
        return {}
    finally:
        loader.dispose()
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a YAML mapping")
        return {}
    return value


def _validate_json_schemas(root: Path, errors: list[str]) -> None:
    asset_root = root / "assets"
    schemas = sorted(asset_root.glob("*.schema.json")) if asset_root.is_dir() else []
    if not schemas:
        errors.append("assets must contain at least one *.schema.json contract")
        return
    identifiers: dict[str, Path] = {}
    for path in schemas:
        label = path.relative_to(root)
        try:
            schema = strict_json_load(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{label} is not strict JSON: {exc}")
            continue
        if not isinstance(schema, dict):
            errors.append(f"{label} must contain a JSON object")
            continue
        if schema.get("$schema") != "https://json-schema.org/draft/2020-12/schema":
            errors.append(f"{label} must declare JSON Schema Draft 2020-12")
        try:
            Draft202012Validator.check_schema(schema)
        except SchemaError as exc:
            errors.append(f"{label} is not a valid Draft 2020-12 schema: {exc.message}")
        identifier = schema.get("$id")
        if not isinstance(identifier, str) or not identifier.strip():
            errors.append(f"{label} requires a nonempty $id")
        elif identifier in identifiers:
            errors.append(
                f"{label} repeats $id {identifier!r} from {identifiers[identifier].relative_to(root)}"
            )
        else:
            identifiers[identifier] = path


def _inside(root: Path, candidate: Path) -> bool:
    try:
        candidate.relative_to(root)
        return True
    except ValueError:
        return False


def _is_link_or_junction(path: Path) -> bool:
    """Return true for symlinks and native Windows reparse points."""

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


def _is_versioned_plugin_cache(root: Path, skill_name: str, skill_description: str) -> bool:
    """Recognize the cache layout created by Claude Code and Codex plugins.

    Direct skill installs live in a directory named for the skill. Marketplace
    clients instead cache the plugin in a directory named for its version. The
    exception remains fail-closed: the strict, regular client manifests must
    bind that directory, version, root skill path, and SKILL.md name together.
    """

    if (
        not SKILL_NAME.fullmatch(skill_name)
        or len(skill_name) > 64
        or not STRICT_SEMVER.fullmatch(root.name)
    ):
        return False
    manifests: list[dict] = []
    for relative in (
        Path(".claude-plugin/plugin.json"),
        Path(".codex-plugin/plugin.json"),
    ):
        manifest_path = root / relative
        if not manifest_path.is_file() or _is_link_or_junction(manifest_path):
            return False
        try:
            manifest = strict_json_load(manifest_path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError):
            return False
        if not isinstance(manifest, dict):
            return False
        manifests.append(manifest)
    return all(
        manifest.get("name") == skill_name
        and manifest.get("version") == root.name
        and manifest.get("skills") == "./skills/"
        for manifest in manifests
    ) and _plugin_entry_matches(root, skill_name, skill_description)


def _plugin_entry_matches(root: Path, skill_name: str, skill_description: str) -> bool:
    entry_path = root / "skills" / skill_name / "SKILL.md"
    if not entry_path.is_file() or _is_link_or_junction(entry_path):
        return False
    try:
        text = entry_path.read_text(encoding="utf-8")
    except (OSError, UnicodeError):
        return False
    match = FRONTMATTER.match(text)
    if not match:
        return False
    errors: list[str] = []
    frontmatter = _yaml_mapping(match.group(1), "plugin skill frontmatter", errors)
    return not errors and frontmatter == {
        "name": skill_name,
        "description": skill_description,
    }


def _validate_links(root: Path, errors: list[str]) -> None:
    for document in sorted(root.rglob("*.md")):
        if document.is_symlink():
            continue
        text = document.read_text(encoding="utf-8")
        for raw in LOCAL_LINK.findall(text):
            target = raw.strip()
            if not target or target.startswith("#") or re.match(r"^[a-z][a-z0-9+.-]*:", target, re.I):
                continue
            if target.startswith("<") and ">" in target:
                target = target[1:target.index(">")]
            else:
                target = target.split(maxsplit=1)[0]
            target = unquote(target.split("#", 1)[0].split("?", 1)[0])
            if not target:
                continue
            resolved = (document.parent / target).resolve()
            if not _inside(root, resolved):
                errors.append(f"{document.relative_to(root)} has an escaping link: {raw}")
            elif not resolved.exists():
                errors.append(f"{document.relative_to(root)} has a missing link target: {raw}")


def _validate_reference_navigation(root: Path, errors: list[str]) -> None:
    reference_root = root / "references"
    if not reference_root.is_dir():
        return
    for document in sorted(reference_root.glob("*.md")):
        if document.is_symlink():
            continue
        text = document.read_text(encoding="utf-8")
        if len(text.splitlines()) > 100 and not re.search(r"^## Contents\s*$", text, re.MULTILINE):
            errors.append(
                f"{document.relative_to(root)} exceeds 100 lines and requires a compact ## Contents section"
            )


def _safe_review_desk_member(raw: object) -> PurePosixPath:
    reserved = {
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
        raise ValueError(f"unsafe Review Desk bundle path: {raw!r}")
    path = PurePosixPath(raw)
    if (
        path.is_absolute()
        or ".." in path.parts
        or raw != path.as_posix()
        or any(
            part in {"", "."}
            or part != part.strip()
            or part.endswith(".")
            or part.split(".", 1)[0].casefold() in reserved
            for part in path.parts
        )
    ):
        raise ValueError(f"unsafe Review Desk bundle path: {raw!r}")
    if path.suffix.casefold() == ".map" or "node_modules" in path.parts or "reviews" in path.parts:
        raise ValueError(f"forbidden Review Desk bundle content: {raw}")
    if path not in {
        PurePosixPath("launch_review_desk.py"),
        PurePosixPath("launch_installed_review_desk.py"),
    } and path.parts[0] != "app":
        raise ValueError(f"Review Desk bundle path is outside the app contract: {raw}")
    return path


def _validate_review_desk_bundle(root: Path, errors: list[str]) -> None:
    bundle = root / REVIEW_DESK_BUNDLE
    label = REVIEW_DESK_BUNDLE.as_posix()
    if not bundle.is_file() or _is_link_or_junction(bundle):
        errors.append(f"required plugin payload is missing or unsafe: {label}")
        return
    try:
        if bundle.stat().st_size > 20 * 1024 * 1024:
            errors.append(f"{label} exceeds the 20 MiB compressed limit")
            return
        archive = zipfile.ZipFile(bundle)
    except (OSError, zipfile.BadZipFile) as exc:
        errors.append(f"{label} is not a readable ZIP archive: {exc}")
        return
    try:
        with archive:
            infos = archive.infolist()
            if not infos or len(infos) > 500:
                errors.append(f"{label} has an invalid entry count")
                return
            if sum(info.file_size for info in infos) > 40 * 1024 * 1024:
                errors.append(f"{label} exceeds the 40 MiB uncompressed limit")
                return
            names: set[str] = set()
            folded: set[str] = set()
            info_by_name: dict[str, zipfile.ZipInfo] = {}
            for info in infos:
                if info.is_dir() or info.flag_bits & 0x1 or info.file_size > 10 * 1024 * 1024:
                    errors.append(f"{label} has an unsafe entry: {info.filename}")
                    return
                mode = info.external_attr >> 16
                if stat.S_IFMT(mode) not in {0, stat.S_IFREG}:
                    errors.append(f"{label} has a non-regular entry: {info.filename}")
                    return
                try:
                    if info.filename != "bundle-manifest.json":
                        _safe_review_desk_member(info.filename)
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")
                    return
                if info.filename.casefold() in folded:
                    errors.append(f"{label} has duplicate or case-colliding entries: {info.filename}")
                    return
                folded.add(info.filename.casefold())
                names.add(info.filename)
                info_by_name[info.filename] = info
            if "bundle-manifest.json" not in names:
                errors.append(f"{label} is missing bundle-manifest.json")
                return
            manifest_bytes = archive.read("bundle-manifest.json")
            try:
                manifest = strict_json_loads(manifest_bytes)
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{label} has invalid strict manifest JSON: {exc}")
                return
            if not isinstance(manifest, dict) or set(manifest) != {"files", "package", "schema_version"}:
                errors.append(f"{label} manifest has unexpected fields")
                return
            if manifest.get("package") != "econ-review-desk" or manifest.get("schema_version") != "1":
                errors.append(f"{label} manifest has the wrong package or schema version")
                return
            canonical = (
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            if manifest_bytes != canonical:
                errors.append(f"{label} manifest is not canonical JSON")
                return
            records = manifest.get("files")
            if not isinstance(records, list) or not records:
                errors.append(f"{label} manifest files must be a non-empty array")
                return
            expected = {"bundle-manifest.json"}
            previous = ""
            for record in records:
                if not isinstance(record, dict) or set(record) != {"path", "sha256", "size"}:
                    errors.append(f"{label} manifest contains an invalid file record")
                    return
                try:
                    path = _safe_review_desk_member(record.get("path")).as_posix()
                except ValueError as exc:
                    errors.append(f"{label}: {exc}")
                    return
                if path <= previous:
                    errors.append(f"{label} manifest paths must be sorted and unique")
                    return
                previous = path
                digest = record.get("sha256")
                size = record.get("size")
                if (
                    not isinstance(digest, str)
                    or len(digest) != 64
                    or any(character not in "0123456789abcdef" for character in digest)
                    or not isinstance(size, int)
                    or isinstance(size, bool)
                    or size < 0
                ):
                    errors.append(f"{label} manifest has invalid size or hash metadata: {path}")
                    return
                if path not in info_by_name:
                    errors.append(f"{label} is missing manifest-declared content: {path}")
                    return
                data = archive.read(path)
                if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
                    errors.append(f"{label} content does not match its manifest: {path}")
                    return
                expected.add(path)
            if names != expected:
                errors.append(f"{label} entries differ from its manifest")
                return
            if not REVIEW_DESK_REQUIRED_FILES.issubset(expected):
                errors.append(f"{label} lacks required launchers, app files, or license notices")
                return
            license_path = root / "LICENSE"
            if license_path.is_file() and archive.read("app/LICENSE.txt") != license_path.read_bytes():
                errors.append(f"{label} first-party license is not synchronized with LICENSE")
                return
            for required in REVIEW_DESK_REQUIRED_FILES - {
                "app/index.html",
                "launch_installed_review_desk.py",
                "launch_review_desk.py",
            }:
                if not archive.read(required):
                    errors.append(f"{label} contains an empty required notice or license: {required}")
                    return
            try:
                strict_json_loads(archive.read("app/third-party-licenses/manifest.json"))
            except (UnicodeError, json.JSONDecodeError, ValueError) as exc:
                errors.append(f"{label} has an invalid third-party license manifest: {exc}")
    except (OSError, KeyError, RuntimeError, zipfile.BadZipFile) as exc:
        errors.append(f"{label} could not be verified safely: {exc}")


def _validate_plugin_payload(
    root: Path,
    skill_name: object,
    skill_description: object,
    errors: list[str],
) -> None:
    manifests: list[dict] = []
    for relative in (Path(".claude-plugin/plugin.json"), Path(".codex-plugin/plugin.json")):
        path = root / relative
        if not path.is_file() or _is_link_or_junction(path):
            errors.append(f"required native plugin manifest is missing or unsafe: {relative.as_posix()}")
            continue
        try:
            value = strict_json_load(path)
        except (OSError, UnicodeError, json.JSONDecodeError, ValueError) as exc:
            errors.append(f"{relative.as_posix()} is not strict JSON: {exc}")
            continue
        if not isinstance(value, dict):
            errors.append(f"{relative.as_posix()} must contain a JSON object")
            continue
        if (
            value.get("name") != "econ-review"
            or value.get("skills") != "./skills/"
            or not isinstance(value.get("version"), str)
            or not STRICT_SEMVER.fullmatch(value["version"])
        ):
            errors.append(f"{relative.as_posix()} does not bind the econ-review skill directory")
        manifests.append(value)
    if len(manifests) == 2 and manifests[0].get("version") != manifests[1].get("version"):
        errors.append("Claude and Codex plugin manifest versions are not synchronized")

    if (
        not isinstance(skill_name, str)
        or not isinstance(skill_description, str)
        or not _plugin_entry_matches(root, skill_name, skill_description)
    ):
        errors.append("skills/econ-review/SKILL.md does not match the canonical skill frontmatter")

    setup_path = root / "skills" / "econ-review-setup" / "SKILL.md"
    if not setup_path.is_file() or _is_link_or_junction(setup_path):
        errors.append("required plugin payload is missing or unsafe: skills/econ-review-setup/SKILL.md")
    else:
        try:
            setup_text = setup_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"skills/econ-review-setup/SKILL.md is not readable UTF-8: {exc}")
        else:
            match = FRONTMATTER.match(setup_text)
            if not match:
                errors.append("skills/econ-review-setup/SKILL.md has invalid frontmatter delimiters")
            else:
                setup = _yaml_mapping(
                    match.group(1),
                    "skills/econ-review-setup/SKILL.md frontmatter",
                    errors,
                )
                if (
                    set(setup) != ALLOWED_FRONTMATTER
                    or setup.get("name") != "econ-review-setup"
                    or not isinstance(setup.get("description"), str)
                    or not setup["description"].strip()
                ):
                    errors.append("skills/econ-review-setup/SKILL.md has the wrong setup-skill contract")
    _validate_review_desk_bundle(root, errors)


def _validate_runtime(root: Path, errors: list[str]) -> None:
    scripts = root / "scripts"
    if not scripts.is_dir():
        errors.append("scripts runtime directory is missing")
        return
    for name in sorted(REQUIRED_RUNTIME):
        path = scripts / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"required runtime script is missing or unsafe: scripts/{name}")

    parsed: dict[Path, ast.AST] = {}
    texts: dict[Path, str] = {}
    for path in sorted(scripts.glob("*.py")):
        try:
            text = path.read_text(encoding="utf-8")
            texts[path] = text
            parsed[path] = ast.parse(text, filename=str(path))
            compile(text, str(path), "exec")
        except (OSError, UnicodeError, SyntaxError) as exc:
            errors.append(f"{path.relative_to(root)} is not compilable Python: {exc}")

    finalizer = scripts / "finalize_review.py"
    tree = parsed.get(finalizer)
    declared_generators: set[str] = set()
    if tree is not None:
        for node in getattr(tree, "body", []):
            if not isinstance(node, (ast.Assign, ast.AnnAssign)):
                continue
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            if not any(isinstance(target, ast.Name) and target.id == "GENERATORS" for target in targets):
                continue
            value = node.value
            if isinstance(value, (ast.Tuple, ast.List)):
                for element in value.elts:
                    if (
                        isinstance(element, ast.BinOp)
                        and isinstance(element.op, ast.Div)
                        and isinstance(element.right, ast.Constant)
                        and isinstance(element.right.value, str)
                    ):
                        declared_generators.add(element.right.value)
        if not declared_generators:
            errors.append("scripts/finalize_review.py must declare a statically inspectable GENERATORS list")
    for name in sorted(declared_generators):
        path = scripts / name
        if not path.is_file() or path.is_symlink():
            errors.append(f"finalizer generator is missing or unsafe: scripts/{name}")

    schema_names = {
        match
        for text in texts.values()
        for match in re.findall(r"[\"']([A-Za-z0-9-]+\.schema\.json)[\"']", text)
    }
    for name in sorted(schema_names):
        if not (root / "assets" / name).is_file():
            errors.append(f"runtime references missing schema: assets/{name}")


def validate_skill_package(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.expanduser().absolute()
    if _is_link_or_junction(root):
        return [f"skill directory must not be a symbolic link or junction: {root}"]
    root = root.resolve()
    if not root.is_dir():
        return [f"skill directory does not exist: {root}"]

    for current, directories, files in os.walk(root, followlinks=False):
        safe_directories: list[str] = []
        for name in directories:
            path = Path(current, name)
            if _is_link_or_junction(path):
                errors.append(
                    "skill package contains a symbolic link or junction: "
                    f"{path.relative_to(root)}"
                )
            else:
                safe_directories.append(name)
        directories[:] = safe_directories
        for name in files:
            path = Path(current, name)
            if _is_link_or_junction(path):
                errors.append(
                    "skill package contains a symbolic link or junction: "
                    f"{path.relative_to(root)}"
                )
    if errors:
        # Do not follow an already-rejected assets, references, or scripts
        # subtree during the deeper schema/link/runtime passes below.
        return errors

    license_path = root / "LICENSE"
    if not license_path.is_file() or license_path.is_symlink():
        errors.append("LICENSE is missing or unsafe")
    else:
        try:
            license_text = license_path.read_text(encoding="utf-8")
        except (OSError, UnicodeError) as exc:
            errors.append(f"LICENSE is not readable UTF-8: {exc}")
        else:
            if not license_text.strip():
                errors.append("LICENSE must not be empty")

    skill_path = root / "SKILL.md"
    if not skill_path.is_file() or skill_path.is_symlink():
        return errors + ["SKILL.md is missing or unsafe"]
    try:
        skill_text = skill_path.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        return errors + [f"SKILL.md is not UTF-8: {exc}"]
    match = FRONTMATTER.match(skill_text)
    if not match:
        return errors + ["SKILL.md has invalid YAML frontmatter delimiters"]
    frontmatter = _yaml_mapping(match.group(1), "SKILL.md frontmatter", errors)
    unexpected = sorted(set(frontmatter) - ALLOWED_FRONTMATTER)
    if unexpected:
        errors.append(f"SKILL.md frontmatter has unsupported keys: {', '.join(unexpected)}")
    name = frontmatter.get("name")
    description = frontmatter.get("description")
    if not isinstance(name, str) or not SKILL_NAME.fullmatch(name) or len(name) > 64:
        errors.append("SKILL.md name must be 1-64 lowercase letters, digits, or single hyphens")
    if name != root.name and not (
        isinstance(name, str)
        and isinstance(description, str)
        and _is_versioned_plugin_cache(root, name, description)
    ):
        errors.append(f"SKILL.md name {name!r} does not match directory name {root.name!r}")
    if not isinstance(description, str) or not description.strip() or len(description) > 1024:
        errors.append("SKILL.md description must be a nonempty string of at most 1024 characters")
    elif "<" in description or ">" in description:
        errors.append("SKILL.md description must not contain angle brackets")

    openai_path = root / "agents" / "openai.yaml"
    if not openai_path.is_file() or openai_path.is_symlink():
        errors.append("agents/openai.yaml is missing or unsafe")
    else:
        metadata = _yaml_mapping(openai_path.read_text(encoding="utf-8"), "agents/openai.yaml", errors)
        unexpected_top = sorted(set(metadata) - ALLOWED_OPENAI_TOP_LEVEL)
        if unexpected_top:
            errors.append(f"agents/openai.yaml has unsupported top-level keys: {', '.join(unexpected_top)}")
        interface = metadata.get("interface")
        if not isinstance(interface, dict):
            errors.append("agents/openai.yaml requires an interface mapping")
        else:
            display_name = interface.get("display_name")
            short_description = interface.get("short_description")
            default_prompt = interface.get("default_prompt")
            if not isinstance(display_name, str) or not display_name.strip():
                errors.append("agents/openai.yaml interface.display_name must be nonempty")
            if not isinstance(short_description, str) or not 25 <= len(short_description.strip()) <= 64:
                errors.append("agents/openai.yaml interface.short_description must be 25-64 characters")
            if not isinstance(default_prompt, str) or f"${name}" not in default_prompt:
                errors.append(f"agents/openai.yaml interface.default_prompt must mention ${name}")

    _validate_links(root, errors)
    _validate_reference_navigation(root, errors)
    _validate_json_schemas(root, errors)
    _validate_plugin_payload(root, name, description, errors)
    _validate_runtime(root, errors)
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "skill_directory",
        nargs="?",
        type=Path,
        default=Path(__file__).resolve().parents[1],
        help="directory containing SKILL.md (defaults to this installed skill)",
    )
    args = parser.parse_args(argv)
    errors = validate_skill_package(args.skill_directory)
    if errors:
        for error in errors:
            print(f"ERROR: {error}", file=sys.stderr)
        return 1
    print(f"econ-review package validation passed: {args.skill_directory.resolve()}")
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
