#!/usr/bin/env python3
"""The Review Desk demo package must stay a faithful delivery of the fixture."""

from __future__ import annotations

import importlib.util
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "econ-review" / "scripts"
FIXTURE = ROOT / "tests" / "fixtures" / "valid-review"
DEMO = ROOT / "docs" / "sample-review" / "review"


def load_delivery_module():
    sys.path.insert(0, str(SCRIPTS))
    try:
        spec = importlib.util.spec_from_file_location("create_delivery_demo_test", SCRIPTS / "create_delivery.py")
        assert spec and spec.loader
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module
    finally:
        sys.path.remove(str(SCRIPTS))


def tree(root: Path) -> dict[str, bytes]:
    return {
        path.relative_to(root).as_posix(): path.read_bytes()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


class DemoReviewPackageTests(unittest.TestCase):
    def test_supporting_folder_is_the_canonical_fixture(self) -> None:
        self.assertEqual(tree(DEMO / "supporting"), tree(FIXTURE))
        self.assertEqual((DEMO / "paper-review.pdf").read_bytes(), (FIXTURE / "paper-review.pdf").read_bytes())

    def test_reader_files_match_the_delivery_generator(self) -> None:
        module = load_delivery_module()
        self.assertEqual((DEMO / "README.md").read_text(encoding="utf-8"), module.delivery_readme(FIXTURE))
        include_writing = (FIXTURE / "editing-comments.md").is_file()
        for source, destination in module.READER_FILES.items():
            if not (FIXTURE / source).is_file():
                continue
            expected = (FIXTURE / source).read_text(encoding="utf-8")
            if source in {"report.md", "editing-comments.md", "fix-plan.md"}:
                expected = module.reader_markdown(expected, include_writing=include_writing, include_round=False)
            self.assertEqual((DEMO / destination).read_text(encoding="utf-8"), expected, destination)
        expected_files = {"README.md", "paper-review.pdf"} | {
            destination for source, destination in module.READER_FILES.items() if (FIXTURE / source).is_file()
        }
        top_level = {path.relative_to(DEMO).as_posix() for path in DEMO.rglob("*") if path.is_file()} - {
            f"supporting/{name}" for name in tree(FIXTURE)
        }
        self.assertEqual(top_level, expected_files)

    def test_delivery_readme_lists_contents_as_prose_and_explains_review_desk(self) -> None:
        module = load_delivery_module()
        self.assertEqual(module.combined_contents("the referee report", "the revision plan"), "the referee report and the revision plan")
        self.assertEqual(
            module.combined_contents("the referee report", "the editing comments", "the revision plan"),
            "the referee report, the editing comments, and the revision plan",
        )
        readme = module.delivery_readme(FIXTURE)
        self.assertIn("## Open the review in Review Desk", readme)
        self.assertIn("http://127.0.0.1:48127/", readme)
        self.assertIn("## Next round", readme)
        self.assertIn("review-actions.json", readme)


if __name__ == "__main__":
    unittest.main()
