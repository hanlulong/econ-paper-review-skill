#!/usr/bin/env python3
"""Validate the portable econ-review skill package without Codex internals."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml
from jsonschema import Draft202012Validator, SchemaError

sys.path.insert(0, str(Path(__file__).resolve().parent))
from safe_io import strict_json_load  # noqa: E402


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
LOCAL_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_FRONTMATTER = {"name", "description"}
ALLOWED_OPENAI_TOP_LEVEL = {"interface", "dependencies", "policy"}
REQUIRED_RUNTIME = {
    "dependency_versions.py",
    "finalize_review.py",
    "propose_source_inventory.py",
    "safe_io.py",
    "trust_spine.py",
    "validate_review.py",
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
    if root.is_symlink():
        return [f"skill directory must not be a symbolic link: {root}"]
    root = root.resolve()
    if not root.is_dir():
        return [f"skill directory does not exist: {root}"]

    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current, name)
            if path.is_symlink():
                errors.append(f"skill package contains a symbolic link: {path.relative_to(root)}")
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
    if name != root.name:
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
    raise SystemExit(main())
