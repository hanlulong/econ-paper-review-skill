#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import os
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

    def test_license_is_required_and_nonempty(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "LICENSE").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("LICENSE is missing" in error for error in errors), errors)
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "LICENSE").write_text("\n", encoding="utf-8")
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("LICENSE must not be empty" in error for error in errors), errors)

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

    def test_duplicate_yaml_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            skill = target / "SKILL.md"
            skill.write_text(
                skill.read_text(encoding="utf-8").replace(
                    "name: econ-review\n",
                    "name: shadow-review\nname: econ-review\n",
                    1,
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("duplicate key 'name'" in error for error in errors), errors)

    def test_duplicate_schema_keys_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            schema = target / "assets" / "run.schema.json"
            schema.write_text(
                schema.read_text(encoding="utf-8").replace(
                    '  "$schema":',
                    '  "$id": "https://invalid.example/shadow",\n  "$schema":',
                    1,
                ),
                encoding="utf-8",
            )
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("duplicate JSON key: $id" in error for error in errors), errors)

    def test_missing_local_markdown_target_fails(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "references" / "workflow.md").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("missing link target" in error and "workflow.md" in error for error in errors), errors)

    def test_long_reference_requires_contents_navigation(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            reference = target / "references" / "workflow.md"
            reference.write_text(
                reference.read_text(encoding="utf-8").replace("## Contents\n", "## Navigation\n", 1),
                encoding="utf-8",
            )
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("workflow.md" in error and "## Contents" in error for error in errors), errors)

    def test_missing_finalizer_generator_fails_installed_runtime_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "scripts" / "generate_sources.py").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("finalizer generator is missing" in error and "generate_sources.py" in error for error in errors), errors)

    def test_missing_dependency_evaluator_fails_installed_runtime_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "scripts" / "dependency_versions.py").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(
                any("required runtime script is missing" in error and "dependency_versions.py" in error for error in errors),
                errors,
            )

    def test_python_syntax_error_fails_installed_runtime_check(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            script = target / "scripts" / "generate_sources.py"
            script.write_text("def broken(:\n", encoding="utf-8")
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("not compilable Python" in error and "generate_sources.py" in error for error in errors), errors)

    def test_runtime_referenced_schema_must_ship(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            (target / "assets" / "coverage.schema.json").unlink()
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("runtime references missing schema" in error and "coverage.schema.json" in error for error in errors), errors)

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_package_root_is_rejected_before_resolution(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            linked = Path(temporary) / "linked-skill"
            linked.symlink_to(target, target_is_directory=True)
            errors = MODULE.validate_skill_package(linked)
            self.assertTrue(any("skill directory must not be a symbolic link" in error for error in errors), errors)

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    @unittest.skipUnless(hasattr(os, "symlink"), "symlinks unavailable")
    def test_symlinked_asset_tree_fails_before_external_schema_is_read(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            target = self.copy_skill(temporary)
            outside = Path(temporary) / "outside-assets"
            outside.mkdir()
            (outside / "host.schema.json").write_text("not JSON", encoding="utf-8")
            shutil.rmtree(target / "assets")
            (target / "assets").symlink_to(outside, target_is_directory=True)
            errors = MODULE.validate_skill_package(target)
            self.assertTrue(any("skill package contains a symbolic link: assets" in error for error in errors), errors)
            self.assertFalse(any("host.schema.json" in error for error in errors), errors)


if __name__ == "__main__":
    unittest.main()
