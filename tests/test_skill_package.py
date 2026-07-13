#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import shutil
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "validate_skill_package.py"
SPEC = importlib.util.spec_from_file_location("validate_skill_package", SCRIPT)
MODULE = importlib.util.module_from_spec(SPEC)
assert SPEC and SPEC.loader
SPEC.loader.exec_module(MODULE)


class SkillPackageValidationTests(unittest.TestCase):
    def copy_skill(self, temporary: str) -> Path:
        target = Path(temporary) / "econ-review"
        shutil.copytree(ROOT / "econ-review", target)
        return target

    def test_current_skill_package_passes(self) -> None:
        self.assertEqual(MODULE.validate_skill_package(ROOT / "econ-review"), [])

    def test_frontmatter_rejects_unsupported_keys(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            skill = target / "SKILL.md"
            skill.write_text(skill.read_text(encoding="utf-8").replace("name: econ-review\n", "name: econ-review\nversion: 1\n", 1), encoding="utf-8")
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("unsupported keys" in error for error in errors), errors)

    def test_openai_prompt_must_name_the_skill(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            metadata = target / "agents" / "openai.yaml"
            metadata.write_text(metadata.read_text(encoding="utf-8").replace("$econ-review", "$another-skill"), encoding="utf-8")
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("default_prompt" in error for error in errors), errors)

    def test_missing_local_markdown_target_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "references" / "workflow.md").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("missing link target" in error and "workflow.md" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
