#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "econ-review"
CLAUDE_MANIFEST_PATH = PLUGIN_ROOT / ".claude-plugin" / "plugin.json"
CODEX_MANIFEST_PATH = PLUGIN_ROOT / ".codex-plugin" / "plugin.json"


def strict_json(path: Path) -> dict:
    def reject_duplicate_pairs(pairs: list[tuple[str, object]]) -> dict:
        result: dict = {}
        for key, value in pairs:
            if key in result:
                raise ValueError(f"duplicate JSON key: {key}")
            result[key] = value
        return result

    value = json.loads(path.read_text(encoding="utf-8"), object_pairs_hook=reject_duplicate_pairs)
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


PLUGIN_VERSION = strict_json(CLAUDE_MANIFEST_PATH)["version"]


class NativePluginTests(unittest.TestCase):
    def test_source_repository_does_not_publish_a_marketplace(self) -> None:
        self.assertFalse((ROOT / ".claude-plugin" / "marketplace.json").exists())
        release_contract = strict_json(ROOT / "scripts" / "public-release-files.json")
        self.assertNotIn(".claude-plugin/marketplace.json", release_contract["files"])

    def test_native_manifests_are_synchronized(self) -> None:
        claude = strict_json(CLAUDE_MANIFEST_PATH)
        codex = strict_json(CODEX_MANIFEST_PATH)

        for field in (
            "name",
            "version",
            "description",
            "author",
            "homepage",
            "repository",
            "license",
            "keywords",
            "skills",
        ):
            with self.subTest(field=field):
                self.assertEqual(claude[field], codex[field])

        self.assertEqual(claude["name"], "econ-review")
        self.assertEqual(claude["version"], PLUGIN_VERSION)
        self.assertRegex(claude["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertEqual(claude["license"], "PolyForm-Noncommercial-1.0.0")
        self.assertEqual(claude["homepage"], "https://openecon.ai")
        self.assertEqual(claude["repository"], "https://github.com/hanlulong/econ-paper-review-skill")
        self.assertEqual(claude["skills"], "./skills/")

        interface = codex["interface"]
        self.assertEqual(interface["displayName"], "Econ Review")
        self.assertEqual(interface["websiteURL"], "https://openecon.ai")
        self.assertTrue(all("econ-review" in prompt for prompt in interface["defaultPrompt"]))

    def test_native_plugin_is_complete_but_passive_until_setup_is_requested(self) -> None:
        for relative in (
            Path("scripts/setup_econ_review.py"),
            Path("skills/econ-review/SKILL.md"),
            Path("skills/econ-review-setup/SKILL.md"),
            Path("assets/review-desk.zip"),
        ):
            with self.subTest(payload=relative.as_posix()):
                self.assertTrue((PLUGIN_ROOT / relative).is_file())
        for manifest_path in (CLAUDE_MANIFEST_PATH, CODEX_MANIFEST_PATH):
            manifest = strict_json(manifest_path)
            with self.subTest(manifest=manifest_path.name):
                self.assertNotIn("hooks", manifest)
                self.assertNotIn("commands", manifest)
                self.assertNotIn("setup", manifest)

    def test_both_clients_resolve_the_same_root_skill(self) -> None:
        for path in (CLAUDE_MANIFEST_PATH, CODEX_MANIFEST_PATH):
            with self.subTest(manifest=path.relative_to(ROOT).as_posix()):
                manifest = strict_json(path)
                self.assertEqual(
                    (PLUGIN_ROOT / manifest["skills"]).resolve(),
                    (PLUGIN_ROOT / "skills").resolve(),
                )

        canonical = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
        entry = (PLUGIN_ROOT / "skills" / "econ-review" / "SKILL.md").read_text(
            encoding="utf-8"
        )
        frontmatter = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
        canonical_match = frontmatter.match(canonical)
        entry_match = frontmatter.match(entry)
        self.assertIsNotNone(canonical_match)
        self.assertIsNotNone(entry_match)
        assert canonical_match is not None and entry_match is not None
        self.assertEqual(canonical_match.group(1), entry_match.group(1))
        self.assertIn("../../SKILL.md", entry)

    def test_external_catalog_commands_and_migration_are_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "INSTALL.md").read_text(encoding="utf-8")

        readme_install = readme.split("## Install", 1)[1].split("## Use it", 1)[0]
        normalized_readme_install = " ".join(readme_install.split())
        normalized_install = " ".join(install.split())
        self.assertIn("Install or update Econ Review as a standalone skill", readme_install)
        self.assertIn(
            "github.com/hanlulong/econ-paper-review-skill/blob/main/INSTALL.md",
            readme_install,
        )
        self.assertIn("keep exactly one active copy for this client", normalized_readme_install)
        self.assertIn("do not change the other client", normalized_readme_install)
        self.assertIn("## Agent installation contract", install)
        self.assertRegex(install, r"Do not ask the user to copy or run\s+commands")
        self.assertIn("$HOME/.agents/skills/econ-review", install)
        self.assertIn("PYTHON scripts/install_econ_review.py --dry-run", install)
        self.assertIn("INSTALLED_SKILL/scripts/validate_skill_package.py", install)
        self.assertIn("exactly one active Econ Review copy", install)
        self.assertIn("Use the same prompt later to update Econ Review", readme_install)
        self.assertIn(
            "Run econ-review-setup now and finish its user-level setup with Review Desk.",
            readme_install,
        )
        self.assertLess(
            readme_install.index("Install or update Econ Review"),
            readme_install.index("/plugin marketplace add OpenEconAI/plugins"),
        )
        self.assertNotIn("After installing, ask once", readme_install)
        self.assertNotIn("Use econ-review-setup to finish setup on this machine", readme_install)
        self.assertLess(
            install.index("## Direct standalone installation"),
            install.index("## Optional native plugin installation"),
        )

        for command in (
            "/plugin marketplace add OpenEconAI/plugins",
            "/plugin install econ-review@openeconai",
            "codex plugin marketplace add OpenEconAI/plugins",
            "codex plugin add econ-review@openeconai",
        ):
            with self.subTest(readme_command=command):
                self.assertIn(command, readme)
                self.assertIn(command, install)

        for command in (
            "claude plugin marketplace update openeconai",
            "claude plugin update econ-review@openeconai",
            "codex plugin marketplace upgrade openeconai",
            "claude plugin uninstall econ-review@openeconai",
            "codex plugin remove econ-review@openeconai",
        ):
            with self.subTest(install_command=command):
                self.assertIn(command, install)

        migration = install.split("### Migrate from the former marketplace", 1)[1].split(
            "## Runtime, PDF, and Review Desk notes", 1
        )[0]
        self.assertIn("only the selected client's old", migration)
        self.assertIn("Do not remove the other client's installation", migration)

        for obsolete in (
            "/plugin marketplace add hanlulong/econ-paper-review-skill",
            "/plugin install econ-review@econ-paper-review",
            "claude plugin marketplace add hanlulong/econ-paper-review-skill",
            "claude plugin install econ-review@econ-paper-review",
            "codex plugin marketplace add hanlulong/econ-paper-review-skill",
            "codex plugin add econ-review@econ-paper-review",
        ):
            with self.subTest(obsolete=obsolete):
                self.assertNotIn(obsolete, readme)
                self.assertNotIn(obsolete, install)

        update_section = install.split("### Update a native plugin", 1)[1].split(
            "### Remove a native plugin", 1
        )[0]
        self.assertNotIn("plugin uninstall", update_section)
        self.assertNotIn("plugin remove", update_section)
        self.assertIn("complete review workflow", readme)
        self.assertIn("may download only the declared core Python packages", readme)
        self.assertIn("private user-owned environment", install)
        self.assertIn("Native plugins are optional", normalized_install)
        self.assertIn("/econ-review:econ-review", install)
        self.assertIn("$econ-review:econ-review", install)

    @unittest.skipUnless(shutil.which("claude"), "Claude Code CLI is not installed")
    def test_claude_strict_validation(self) -> None:
        claude = shutil.which("claude")
        assert claude is not None
        result = subprocess.run(
            [claude, "plugin", "validate", "--strict", str(PLUGIN_ROOT)],
            cwd=ROOT,
            capture_output=True,
            text=True,
            timeout=60,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_isolated_native_package_passes_package_validator(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            installed = Path(temporary) / PLUGIN_VERSION
            shutil.copytree(PLUGIN_ROOT, installed)
            self.assertFalse((installed / "review-viewer").exists())
            result = subprocess.run(
                [
                    sys.executable,
                    str(installed / "scripts" / "validate_skill_package.py"),
                    str(installed),
                ],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
