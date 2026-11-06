#!/usr/bin/env python3
"""Tests for the synced-folder and git work-tree location notice."""

from __future__ import annotations

import importlib.util
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "review_location.py"
SPEC = importlib.util.spec_from_file_location("review_location", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ReviewLocationTests(unittest.TestCase):
    def test_overleaf_and_cloud_folders_are_reported(self) -> None:
        overleaf = MODULE.location_notices(Path("/srv/econ/Dropbox/Apps/Overleaf/Broadband paper"))
        self.assertEqual(len(overleaf), 1)
        self.assertIn("Apps/Overleaf", overleaf[0])
        cloud = {
            "/srv/econ/Library/CloudStorage/Dropbox/papers/broadband": "Dropbox",
            "/srv/econ/Library/Mobile Documents/com~apple~CloudDocs/paper": "iCloud Drive",
            "/srv/econ/Library/CloudStorage/OneDrive-University/paper": "OneDrive",
            "/srv/econ/Library/CloudStorage/GoogleDrive-econ@example.org/My Drive/paper": "Google Drive",
        }
        for folder, service in cloud.items():
            notices = MODULE.location_notices(Path(folder))
            self.assertEqual(len(notices), 1, folder)
            self.assertIn(service, notices[0])

    def test_plain_and_git_folders(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            plain = Path(tmp) / "papers" / "broadband"
            plain.mkdir(parents=True)
            self.assertEqual(MODULE.location_notices(plain), [])
            (Path(tmp) / "papers" / ".git").mkdir()
            notices = MODULE.location_notices(plain)
            self.assertEqual(len(notices), 1)
            self.assertIn(".gitignore", notices[0])
            result = subprocess.run(
                [sys.executable, str(SCRIPT), str(plain)], text=True, capture_output=True, check=True,
            )
            self.assertIn("NOTICE:", result.stdout)
            self.assertIn("Ask the user", result.stdout)

    def test_symlinked_folder_is_checked_at_its_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "Library" / "CloudStorage" / "Dropbox" / "Apps" / "Overleaf" / "paper"
            target.mkdir(parents=True)
            link = Path(tmp) / "papers" / "jmp"
            link.parent.mkdir()
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError):
                self.skipTest("symlinks are unavailable")
            notices = MODULE.location_notices(link)
            self.assertEqual(len(notices), 1)
            self.assertIn("Apps/Overleaf", notices[0])
            (target.parent / ".git").mkdir()
            self.assertTrue(any(".gitignore" in notice for notice in MODULE.location_notices(link)))


if __name__ == "__main__":
    unittest.main()
