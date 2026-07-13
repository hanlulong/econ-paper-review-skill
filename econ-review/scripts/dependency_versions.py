#!/usr/bin/env python3
"""Evaluate installed Python distributions against bundled requirement files.

This module is deliberately small and offline.  It reads only local requirement
files, follows local ``-r`` includes, and uses the installed ``packaging``
library for PEP 440/508 semantics.  It never installs or imports a dependency
being checked.
"""

from __future__ import annotations

from dataclasses import dataclass
from importlib import metadata
from pathlib import Path
from typing import Iterable


class DependencyContractError(RuntimeError):
    """The bundled dependency contract cannot be evaluated safely."""


@dataclass(frozen=True)
class RequirementStatus:
    """Compatibility state for one installed Python distribution."""

    name: str
    requirement: str
    installed_version: str | None
    state: str

    @property
    def compatible(self) -> bool:
        return self.state == "compatible"


def installed_distribution_version(name: str) -> str | None:
    """Return distribution metadata without importing executable package code."""

    try:
        return metadata.version(name)
    except metadata.PackageNotFoundError:
        return None
    except Exception as exc:
        raise DependencyContractError(
            f"could not read installed-version metadata for {name}: {exc}"
        ) from exc


def _packaging_api():
    try:
        from packaging.requirements import InvalidRequirement, Requirement
        from packaging.utils import canonicalize_name
        from packaging.version import InvalidVersion, Version
    except ImportError as exc:
        raise DependencyContractError(
            "the packaging library is required to evaluate bundled Python version constraints"
        ) from exc
    return Requirement, InvalidRequirement, Version, InvalidVersion, canonicalize_name


def _requirement_lines(
    path: Path, stack: tuple[Path, ...] = (), root: Path | None = None,
) -> Iterable[tuple[Path, int, str]]:
    candidate = path.expanduser().absolute()
    if candidate.is_symlink():
        raise DependencyContractError(f"requirement manifest must not be a symbolic link: {candidate}")
    path = candidate.resolve()
    root = path.parent if root is None else root
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise DependencyContractError(f"requirement include escapes its manifest directory: {path}") from exc
    if path in stack:
        chain = " -> ".join(item.name for item in (*stack, path))
        raise DependencyContractError(f"cyclic requirement include: {chain}")
    if not path.is_file():
        raise DependencyContractError(f"requirement manifest is missing or unsafe: {path}")
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except (OSError, UnicodeError) as exc:
        raise DependencyContractError(f"could not read requirement manifest {path}: {exc}") from exc
    for number, raw in enumerate(lines, 1):
        value = raw.strip()
        if not value or value.startswith("#"):
            continue
        if value.startswith("-r ") or value.startswith("--requirement "):
            _, include = value.split(None, 1)
            include = include.strip()
            if not include or include.startswith("-"):
                raise DependencyContractError(f"invalid requirement include at {path}:{number}")
            yield from _requirement_lines(path.parent / include, (*stack, path), root)
            continue
        if value.startswith("-"):
            raise DependencyContractError(
                f"unsupported pip directive at {path}:{number}; manifests may contain only requirements and -r includes"
            )
        yield path, number, value


def load_manifest(path: Path) -> dict[str, object]:
    """Load one requirement per canonical distribution name.

    Environment markers are evaluated for the active interpreter.  Duplicate
    identical requirements from nested includes are collapsed; conflicting
    duplicates fail closed instead of relying on pip's resolver behavior.
    """

    Requirement, InvalidRequirement, _, _, canonicalize_name = _packaging_api()
    requirements: dict[str, object] = {}
    for source, number, value in _requirement_lines(path):
        try:
            requirement = Requirement(value)
        except InvalidRequirement as exc:
            raise DependencyContractError(
                f"invalid requirement at {source}:{number}: {value!r}"
            ) from exc
        if requirement.url:
            raise DependencyContractError(
                f"direct-URL requirement is outside the supported offline contract at {source}:{number}"
            )
        if requirement.marker is not None and not requirement.marker.evaluate():
            continue
        key = canonicalize_name(requirement.name)
        previous = requirements.get(key)
        if previous is not None and str(previous) != str(requirement):
            raise DependencyContractError(
                f"conflicting requirements for {requirement.name}: {previous} and {requirement}"
            )
        requirements[key] = requirement
    if not requirements:
        raise DependencyContractError(f"requirement manifest has no active requirements: {path}")
    return requirements


_INSTALLED_UNSET = object()


def check_requirement(
    requirement: object, *, installed_version: str | None | object = _INSTALLED_UNSET,
) -> RequirementStatus:
    """Evaluate one parsed ``packaging.requirements.Requirement``."""

    _, _, Version, InvalidVersion, _ = _packaging_api()
    name = str(getattr(requirement, "name", ""))
    if not name:
        raise DependencyContractError("requirement object is missing a distribution name")
    if installed_version is _INSTALLED_UNSET:
        installed = installed_distribution_version(name)
    else:
        installed = installed_version
    if installed is None:
        return RequirementStatus(name, str(requirement), None, "unavailable")
    installed = str(installed)
    try:
        parsed = Version(installed)
    except InvalidVersion:
        return RequirementStatus(name, str(requirement), installed, "unsupported")
    specifier = getattr(requirement, "specifier", None)
    compatible = specifier is not None and specifier.contains(parsed, prereleases=None)
    return RequirementStatus(
        name, str(requirement), installed, "compatible" if compatible else "unsupported"
    )


def check_manifest(path: Path) -> list[RequirementStatus]:
    return [check_requirement(requirement) for requirement in load_manifest(path).values()]


def check_manifest_requirement(
    path: Path, name: str, *, installed_version: str | None | object = _INSTALLED_UNSET,
) -> RequirementStatus:
    _, _, _, _, canonicalize_name = _packaging_api()
    requirements = load_manifest(path)
    key = canonicalize_name(name)
    if key not in requirements:
        raise DependencyContractError(f"{name} is not declared by {path}")
    return check_requirement(requirements[key], installed_version=installed_version)


def incompatibility_message(status: RequirementStatus, *, optional: bool = False) -> str:
    profile = "optional backend" if optional else "required dependency"
    if status.state == "unavailable":
        return f"{profile} {status.name} is unavailable; install {status.requirement}"
    return (
        f"{profile} {status.name} {status.installed_version or 'version-unknown'} is unsupported; "
        f"install {status.requirement}"
    )


def require_compatible(path: Path) -> list[RequirementStatus]:
    checks = check_manifest(path)
    failures = [incompatibility_message(row) for row in checks if not row.compatible]
    if failures:
        raise DependencyContractError("; ".join(failures))
    return checks
