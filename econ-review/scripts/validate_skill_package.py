#!/usr/bin/env python3
"""Validate the portable econ-review skill package without Codex internals."""

from __future__ import annotations

import argparse
import os
import re
import sys
from pathlib import Path
from urllib.parse import unquote

import yaml


FRONTMATTER = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
LOCAL_LINK = re.compile(r"\[[^\]]*\]\(([^)]+)\)")
SKILL_NAME = re.compile(r"^[a-z0-9]+(?:-[a-z0-9]+)*$")
ALLOWED_FRONTMATTER = {"name", "description"}
ALLOWED_OPENAI_TOP_LEVEL = {"interface", "dependencies", "policy"}


def _yaml_mapping(text: str, label: str, errors: list[str]) -> dict:
    try:
        value = yaml.safe_load(text)
    except yaml.YAMLError as exc:
        errors.append(f"{label} is not valid YAML: {exc}")
        return {}
    if not isinstance(value, dict):
        errors.append(f"{label} must contain a YAML mapping")
        return {}
    return value


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


def validate_skill_package(root: Path) -> list[str]:
    errors: list[str] = []
    root = root.expanduser().resolve()
    if not root.is_dir():
        return [f"skill directory does not exist: {root}"]

    for current, directories, files in os.walk(root, followlinks=False):
        for name in [*directories, *files]:
            path = Path(current, name)
            if path.is_symlink():
                errors.append(f"skill package contains a symbolic link: {path.relative_to(root)}")

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
