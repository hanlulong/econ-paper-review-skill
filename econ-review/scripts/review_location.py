#!/usr/bin/env python3
"""Warn when a review package would be written into a synced or version-controlled folder.

The review package (confidential comments, page renders, and evidence ledgers)
normally goes in ``review/`` beside the manuscript. When that folder is an
Overleaf project synced through Dropbox, another cloud-synced folder, or a git
work tree, the package would sync to coauthors or be committed. This helper only
reports such locations; it never moves or writes anything.
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


def git_work_tree(path: Path) -> Path | None:
    for candidate in (path, *path.parents):
        if (candidate / ".git").exists():
            return candidate
    return None


def location_notices(directory: Path) -> list[str]:
    """Return one plain-language notice per sharing risk found for *directory*."""

    path = directory.expanduser().absolute()
    parts = _parts(path)
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
    if synced and not notices:
        notices.append(
            f"This folder is synced by {synced}. A review/ folder here would be uploaded and shared with anyone "
            "who can see the folder."
        )
    repository = git_work_tree(path)
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
