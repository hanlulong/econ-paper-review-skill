#!/usr/bin/env python3
"""Warn when a review package would be written into a synced or version-controlled folder.

The review package (confidential comments, page renders, and evidence ledgers)
normally goes in ``review/`` beside the manuscript. When that folder is an
Overleaf project synced through Dropbox, another cloud-synced folder (including
Box and any macOS File Provider folder under ``~/Library/CloudStorage``), or a
git work tree, the package would sync to coauthors or be committed. This helper
only reports such locations; it never moves or writes anything.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.dont_write_bytecode = True


def _parts(path: Path) -> list[str]:
    return [part.casefold() for part in path.parts]


def _contains_sequence(parts: list[str], sequence: tuple[str, ...]) -> bool:
    width = len(sequence)
    return any(tuple(parts[index:index + width]) == sequence for index in range(len(parts) - width + 1))


def _file_provider_service(parts: tuple[str, ...]) -> str | None:
    """Name the macOS File Provider folder after ``Library/CloudStorage``.

    Every File Provider sync client (Box, pCloud, and others) mounts below
    ``~/Library/CloudStorage/<Provider>[-account]``.
    """

    for index in range(len(parts) - 2):
        if parts[index].casefold() == "library" and parts[index + 1].casefold() == "cloudstorage":
            provider = parts[index + 2]
            return provider.split("-", 1)[0] or provider
    return None


def _first_part_under(path: Path, homes: tuple[Path, ...]) -> str | None:
    for home in homes:
        try:
            relative = path.relative_to(home)
        except ValueError:
            continue
        if relative.parts:
            return relative.parts[0]
    return None


def git_work_tree(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def location_notices(directory: Path, *, home: Path | None = None) -> list[str]:
    """Return one plain-language notice per sharing risk found for *directory*."""

    path = directory.expanduser().absolute()
    try:
        resolved = path.resolve()
    except (OSError, RuntimeError):
        resolved = path
    # A symlinked folder can point into a synced location; check both forms.
    parts = _parts(path) + ["/"] + _parts(resolved)
    notices: list[str] = []
    if _contains_sequence(parts, ("apps", "overleaf")):
        notices.append(
            "This folder is inside Apps/Overleaf, so it is an Overleaf project synced through Dropbox. "
            "A review/ folder here would sync into the Overleaf project that coauthors can see, and its page "
            "renders count toward Overleaf's per-project file limit."
        )
    synced = None
    if any(part.startswith("dropbox") for part in parts):
        synced = "Dropbox"
    elif _contains_sequence(parts, ("library", "mobile documents")) or "icloud drive" in parts:
        synced = "iCloud Drive"
    elif any(part.startswith("onedrive") for part in parts):
        synced = "OneDrive"
    elif any(part.startswith("googledrive") or part == "google drive" for part in parts):
        synced = "Google Drive"
    if synced is None:
        synced = _file_provider_service(path.parts) or _file_provider_service(resolved.parts)
    if synced is None:
        # Box Drive's default folder is ~/Box on macOS and Windows.
        homes: tuple[Path, ...] = ()
        try:
            home_path = (home or Path.home()).expanduser().absolute()
            homes = (home_path, home_path.resolve())
        except (OSError, RuntimeError):
            pass
        for candidate in (path, resolved):
            first = _first_part_under(candidate, homes)
            if first is not None and first.casefold() == "box":
                synced = "Box"
                break
    if synced and not notices:
        notices.append(
            f"This folder is synced by {synced}. A review/ folder here would be uploaded and shared with anyone "
            "who can see the folder."
        )
    repository = git_work_tree(path) or (git_work_tree(resolved) if resolved != path else None)
    if repository is not None:
        notices.append(
            f"This folder is inside the git work tree {repository}. Add review/ to .gitignore, or write the "
            "review elsewhere, so the confidential review is not committed."
        )
    return notices


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("directory", type=Path, help="Folder where review/ would be created (normally the manuscript's folder)")
    args = parser.parse_args()
    notices = location_notices(args.directory)
    if not notices:
        print(f"No synced or version-controlled location detected for {args.directory}.")
        return 0
    for notice in notices:
        print(f"NOTICE: {notice}")
    print(
        "Ask the user whether to write the review package here or in another folder before creating review/."
    )
    return 0


if __name__ == "__main__":
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
