#!/usr/bin/env python3

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PLUGIN_ROOT = ROOT / "econ-review"
MARKETPLACE_PATH = ROOT / ".claude-plugin" / "marketplace.json"
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


class PluginMarketplaceTests(unittest.TestCase):
    @staticmethod
    def run_cli(command: list[str], *, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
        result = subprocess.run(
            command,
            cwd=ROOT,
            env=env,
            capture_output=True,
            text=True,
            timeout=120,
        )
        if result.returncode:
            raise AssertionError(result.stdout + result.stderr)
        return result

    def test_catalog_and_native_manifests_are_synchronized(self) -> None:
        marketplace = strict_json(MARKETPLACE_PATH)
        claude = strict_json(CLAUDE_MANIFEST_PATH)
        codex = strict_json(CODEX_MANIFEST_PATH)

        self.assertEqual(marketplace["name"], "econ-paper-review")
        self.assertEqual(
            marketplace["$schema"],
            "https://json.schemastore.org/claude-code-marketplace.json",
        )
        self.assertEqual(len(marketplace["plugins"]), 1)
        entry = marketplace["plugins"][0]
        self.assertIsInstance(entry, dict)

        common_fields = ("name", "description", "homepage")
        for field in common_fields:
            with self.subTest(field=field):
                self.assertEqual(entry[field], claude[field])
                self.assertEqual(claude[field], codex[field])
        for field in ("repository", "license", "keywords"):
            with self.subTest(field=field):
                self.assertEqual(claude[field], codex[field])

        self.assertNotIn("version", entry)
        self.assertEqual(claude["version"], codex["version"])
        self.assertRegex(claude["version"], r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
        self.assertEqual(claude["license"], "PolyForm-Noncommercial-1.0.0")
        self.assertEqual(claude["homepage"], "https://openecon.ai")
        self.assertEqual(entry["source"], "./econ-review")
        self.assertEqual((ROOT / entry["source"]).resolve(), PLUGIN_ROOT.resolve())

        skill_name = re.search(
            r"^name:\s*([^\s]+)\s*$",
            (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8"),
            re.MULTILINE,
        )
        self.assertIsNotNone(skill_name)
        self.assertEqual(skill_name.group(1), entry["name"])

    def test_both_clients_resolve_the_same_root_skill(self) -> None:
        for path in (CLAUDE_MANIFEST_PATH, CODEX_MANIFEST_PATH):
            with self.subTest(manifest=path.relative_to(ROOT).as_posix()):
                manifest = strict_json(path)
                self.assertEqual(manifest["skills"], "./skills/")
                self.assertEqual(
                    (PLUGIN_ROOT / manifest["skills"]).resolve(),
                    (PLUGIN_ROOT / "skills").resolve(),
                )
        canonical = (PLUGIN_ROOT / "SKILL.md").read_text(encoding="utf-8")
        entry = (PLUGIN_ROOT / "skills" / "econ-review" / "SKILL.md").read_text(encoding="utf-8")
        frontmatter = re.compile(r"\A---\n(.*?)\n---(?:\n|\Z)", re.DOTALL)
        self.assertEqual(frontmatter.match(canonical).group(1), frontmatter.match(entry).group(1))
        self.assertIn("../../SKILL.md", entry)
        interface = strict_json(CODEX_MANIFEST_PATH)["interface"]
        self.assertEqual(interface["displayName"], "Econ Review")
        self.assertEqual(interface["websiteURL"], "https://openecon.ai")
        self.assertTrue(all("econ-review" in prompt for prompt in interface["defaultPrompt"]))

    def test_install_and_update_commands_are_documented(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        required_readme = (
            "/plugin marketplace add hanlulong/econ-paper-review-skill",
            "/plugin install econ-review@econ-paper-review",
            "codex plugin marketplace add hanlulong/econ-paper-review-skill",
            "codex plugin add econ-review@econ-paper-review",
        )
        for command in required_readme:
            with self.subTest(command=command):
                self.assertIn(command, readme)
                self.assertIn(command, install)
        for command in (
            "claude plugin marketplace update econ-paper-review",
            "claude plugin update econ-review@econ-paper-review",
            "claude plugin marketplace add hanlulong/econ-paper-review-skill@econ-review--v0.1.0",
            "codex plugin marketplace upgrade econ-paper-review",
            "codex plugin marketplace add hanlulong/econ-paper-review-skill --ref econ-review--v0.1.0",
            "codex plugin remove econ-review@econ-paper-review",
        ):
            with self.subTest(command=command):
                self.assertIn(command, install)
        self.assertIn("does not prepare the managed Python runtime", readme)
        self.assertRegex(install, r"does not create the\s+managed Python environment")
        update_section = install.split("### Update a plugin install", 1)[1].split(
            "### Install a pinned release", 1
        )[0]
        removal_section = install.split("### Remove a plugin install", 1)[1].split(
            "## Recommended direct setup", 1
        )[0]
        self.assertNotIn("plugin uninstall", update_section)
        self.assertNotIn("plugin remove", update_section)
        self.assertIn("plugin uninstall", removal_section)
        self.assertIn("plugin remove", removal_section)

    @unittest.skipUnless(shutil.which("claude"), "Claude Code CLI is not installed")
    def test_claude_strict_validation_and_isolated_install(self) -> None:
        claude = shutil.which("claude")
        assert claude is not None
        for target in (ROOT, PLUGIN_ROOT):
            result = subprocess.run(
                [claude, "plugin", "validate", "--strict", str(target)],
                cwd=ROOT,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, "CLAUDE_CONFIG_DIR": temporary}
            commands = (
                [claude, "plugin", "marketplace", "add", str(ROOT)],
                [claude, "plugin", "install", "econ-review@econ-paper-review"],
                [claude, "plugin", "details", "econ-review@econ-paper-review"],
            )
            outputs: list[str] = []
            for command in commands:
                result = subprocess.run(
                    command,
                    cwd=ROOT,
                    env=env,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                outputs.append(result.stdout + result.stderr)
            self.assertIn("Skills (1)", outputs[-1])
            self.assertIn("econ-review", outputs[-1])
            installed = (
                Path(temporary)
                / "plugins"
                / "cache"
                / "econ-paper-review"
                / "econ-review"
                / strict_json(CLAUDE_MANIFEST_PATH)["version"]
            )
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "skills" / "econ-review" / "SKILL.md").is_file())
            self.assertFalse((installed / "review-viewer").exists())
            validate = subprocess.run(
                [sys.executable, str(installed / "scripts" / "validate_skill_package.py"), str(installed)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    @unittest.skipUnless(shutil.which("codex"), "Codex CLI is not installed")
    def test_codex_isolated_install_and_cached_package(self) -> None:
        codex = shutil.which("codex")
        assert codex is not None
        with tempfile.TemporaryDirectory() as temporary:
            env = {**os.environ, "CODEX_HOME": temporary}
            add_marketplace = subprocess.run(
                [codex, "plugin", "marketplace", "add", str(ROOT), "--json"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(
                add_marketplace.returncode,
                0,
                add_marketplace.stdout + add_marketplace.stderr,
            )
            install = subprocess.run(
                [codex, "plugin", "add", "econ-review@econ-paper-review", "--json"],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=60,
            )
            self.assertEqual(install.returncode, 0, install.stdout + install.stderr)
            record = json.loads(install.stdout)
            installed = Path(record["installedPath"])
            self.assertEqual(installed.name, strict_json(CODEX_MANIFEST_PATH)["version"])
            self.assertTrue((installed / "SKILL.md").is_file())
            self.assertTrue((installed / "skills" / "econ-review" / "SKILL.md").is_file())
            self.assertFalse((installed / "review-viewer").exists())

            validate = subprocess.run(
                [sys.executable, str(installed / "scripts" / "validate_skill_package.py"), str(installed)],
                cwd=ROOT,
                env=env,
                capture_output=True,
                text=True,
                timeout=120,
            )
            self.assertEqual(validate.returncode, 0, validate.stdout + validate.stderr)

    @unittest.skipUnless(
        shutil.which("claude") and shutil.which("codex"),
        "Claude Code and Codex CLIs are both required for the update smoke test",
    )
    def test_isolated_marketplace_update_reaches_both_clients(self) -> None:
        claude = shutil.which("claude")
        codex = shutil.which("codex")
        assert claude is not None and codex is not None
        with tempfile.TemporaryDirectory() as temporary:
            temporary_root = Path(temporary)
            marketplace_root = temporary_root / "marketplace"
            shutil.copytree(ROOT / ".claude-plugin", marketplace_root / ".claude-plugin")
            shutil.copytree(PLUGIN_ROOT, marketplace_root / "econ-review")
            claude_home = temporary_root / "claude-home"
            codex_home = temporary_root / "codex-home"
            claude_home.mkdir()
            codex_home.mkdir()
            claude_env = {**os.environ, "CLAUDE_CONFIG_DIR": str(claude_home)}
            codex_env = {**os.environ, "CODEX_HOME": str(codex_home)}

            self.run_cli(
                [claude, "plugin", "marketplace", "add", str(marketplace_root)],
                env=claude_env,
            )
            self.run_cli(
                [claude, "plugin", "install", "econ-review@econ-paper-review"],
                env=claude_env,
            )
            self.run_cli(
                [codex, "plugin", "marketplace", "add", str(marketplace_root), "--json"],
                env=codex_env,
            )
            self.run_cli(
                [codex, "plugin", "add", "econ-review@econ-paper-review", "--json"],
                env=codex_env,
            )

            for relative in (
                Path(".claude-plugin/marketplace.json"),
                Path("econ-review/.claude-plugin/plugin.json"),
                Path("econ-review/.codex-plugin/plugin.json"),
            ):
                path = marketplace_root / relative
                payload = strict_json(path)
                if relative.name != "marketplace.json":
                    payload["version"] = "0.1.1"
                path.write_text(
                    json.dumps(payload, indent=2, ensure_ascii=False) + "\n",
                    encoding="utf-8",
                )

            self.run_cli(
                [claude, "plugin", "marketplace", "update", "econ-paper-review"],
                env=claude_env,
            )
            self.run_cli(
                [claude, "plugin", "update", "econ-review@econ-paper-review"],
                env=claude_env,
            )
            claude_details = self.run_cli(
                [claude, "plugin", "details", "econ-review@econ-paper-review"],
                env=claude_env,
            )
            self.assertIn("econ-review 0.1.1", claude_details.stdout + claude_details.stderr)

            # A configured Git marketplace uses `marketplace upgrade` first.
            # This isolated source is local and therefore already reflects the
            # changed catalog; reinstalling exercises the same version switch.
            codex_update = self.run_cli(
                [codex, "plugin", "add", "econ-review@econ-paper-review", "--json"],
                env=codex_env,
            )
            self.assertEqual(json.loads(codex_update.stdout)["version"], "0.1.1")


if __name__ == "__main__":
    unittest.main()
