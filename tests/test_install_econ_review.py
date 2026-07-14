#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "install_econ_review.py"
SPEC = importlib.util.spec_from_file_location("install_econ_review", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class InstallerFixture:
    def __init__(self, root: Path, *, doctor_exit: int = 0) -> None:
        self.root = root
        self.skill = root / "econ-review"
        scripts = self.skill / "scripts"
        scripts.mkdir(parents=True)
        (self.skill / "SKILL.md").write_text(
            "---\nname: econ-review\ndescription: Synthetic installer fixture.\n---\n\n# Fixture\n",
            encoding="utf-8",
        )
        (self.skill / "requirements-core.txt").write_text("", encoding="utf-8")
        (scripts / "dependency_versions.py").write_text(
            "def require_compatible(path):\n    return []\n",
            encoding="utf-8",
        )
        (scripts / "pdf_ingestion.py").write_text(
            "import sys\n"
            "assert sys.argv[-1] == 'doctor'\n"
            "print('fixture doctor: complete')\n"
            f"raise SystemExit({doctor_exit})\n",
            encoding="utf-8",
        )


class CrossPlatformPathTests(unittest.TestCase):
    def test_platform_specific_runtime_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.Path, "home", return_value=Path(tmp) / "home"
        ), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                MODULE.runtime_default("global", None, "Darwin"),
                Path(tmp) / "home" / "Library" / "Application Support" / "econ-review" / "runtime",
            )
            self.assertEqual(
                MODULE.runtime_default("global", None, "Linux"),
                Path(tmp) / "home" / ".local" / "share" / "econ-review" / "runtime",
            )
            self.assertEqual(
                MODULE.runtime_default("global", None, "Windows"),
                Path(tmp) / "home" / "AppData" / "Local" / "econ-review" / "runtime",
            )

    def test_windows_runtime_executable_and_non_admin_guidance(self) -> None:
        runtime = Path("runtime-root")
        self.assertEqual(
            MODULE.runtime_python_path(runtime, "Windows"),
            runtime / "Scripts" / "python.exe",
        )
        guidance = MODULE.poppler_guidance("Windows")
        self.assertIn("non-admin", guidance)
        self.assertIn("Conda", guidance)
        self.assertNotIn("administrator access", guidance)

    def test_platform_specific_review_desk_locations(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.Path, "home", return_value=Path(tmp) / "home"
        ), mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(
                MODULE.review_desk_default("global", None, "Darwin"),
                Path(tmp) / "home" / "Library" / "Application Support" / "econ-review" / "review-desk",
            )
            self.assertEqual(
                MODULE.review_desk_default("global", None, "Linux"),
                Path(tmp) / "home" / ".local" / "share" / "econ-review" / "review-desk",
            )
            self.assertEqual(
                MODULE.review_desk_default("global", None, "Windows"),
                Path(tmp) / "home" / "AppData" / "Local" / "econ-review" / "review-desk",
            )

    def test_review_desk_bundle_paths_are_cross_platform_safe(self) -> None:
        for value in (
            "app/../escape.js",
            "app/name:stream.js",
            "app/CON.js",
            "app/trailing. ",
            "app/source.map",
            "app/node_modules/module.js",
            "app/reviews/private.json",
            "outside.js",
        ):
            with self.subTest(path=value):
                with self.assertRaises(MODULE.InstallError):
                    MODULE._safe_bundle_path(value)

    def test_local_runtime_is_shared_by_both_agent_installs(self) -> None:
        project = Path("project-root")
        self.assertEqual(
            MODULE.runtime_default("local", project, "Windows"),
            project / ".econ-review" / "runtime",
        )
        destinations = MODULE.installation_destinations("local", project, "all")
        self.assertEqual(
            [path for path, _ in destinations],
            [
                project / ".claude" / "skills" / "econ-review",
                project / ".agents" / "skills" / "econ-review",
            ],
        )

    def test_relative_configuration_environment_paths_fail_closed(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_HOME": "relative-config"}, clear=True):
            with self.assertRaisesRegex(MODULE.InstallError, "absolute path"):
                MODULE.installation_destinations("global", None, "codex")


class ManagedInstallerTests(unittest.TestCase):
    def run_installer(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            env=merged,
            check=check,
        )

    def test_dry_run_is_write_free_for_project_setup(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--local",
                str(project),
                "--all",
                "--dry-run",
            )
            self.assertIn("Would create managed Python runtime", result.stdout)
            self.assertIn("Would run the core dependency and Poppler health check", result.stdout)
            self.assertFalse((project / ".econ-review").exists())
            self.assertFalse((project / ".claude").exists())
            self.assertFalse((project / ".agents").exists())

    def test_managed_global_setup_is_idempotent_and_shared(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            runtime = root / "runtime"
            claude = root / "claude"
            codex = root / "codex"
            env = {
                "HOME": str(root / "home"),
                "CLAUDE_CONFIG_DIR": str(claude),
                "CODEX_HOME": str(codex),
            }
            arguments = (
                "--source",
                str(fixture.skill),
                "--runtime-dir",
                str(runtime),
                "--global",
                "--all",
            )
            first = self.run_installer(*arguments, env=env)
            self.assertIn("setup complete and ready", first.stdout)
            runtime_python = MODULE.runtime_python_path(runtime.absolute())
            self.assertTrue(runtime_python.is_file())
            destinations = (
                claude / "skills" / "econ-review",
                codex / "skills" / "econ-review",
            )
            for destination in destinations:
                metadata = json.loads(
                    (destination / ".econ-review-runtime.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metadata["python"], str(runtime_python))
                self.assertTrue((destination / "SKILL.md").is_file())
            marker = runtime / "preserve-on-reuse.txt"
            marker.write_text("keep", encoding="utf-8")
            second = self.run_installer(*arguments, env=env)
            self.assertIn("Reusing managed Python runtime", second.stdout)
            self.assertEqual(second.stdout.count("Already current"), 2)
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_copy_only_preserves_lightweight_behavior(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--local",
                str(project),
                "--codex",
                "--copy-only",
            )
            self.assertIn("Lightweight copy-only installation complete", result.stdout)
            destination = project / ".agents" / "skills" / "econ-review"
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertFalse((destination / ".econ-review-runtime.json").exists())
            self.assertFalse((project / ".econ-review").exists())

    def test_prebuilt_review_desk_installs_immutably_without_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            desk_root = root / "desk"
            bundle = ROOT / "review-viewer" / "release" / "review-desk.zip"
            arguments = (
                "--source",
                str(fixture.skill),
                "--local",
                str(project),
                "--codex",
                "--copy-only",
                "--with-review-desk",
                "--review-desk-dir",
                str(desk_root),
                "--review-desk-bundle",
                str(bundle),
            )
            first = self.run_installer(*arguments, env={"PATH": ""})
            self.assertIn("Installed verified Review Desk", first.stdout)
            self.assertIn("ready without Node.js or npm", first.stdout)
            versions = list((desk_root / "versions").iterdir())
            self.assertEqual(len(versions), 1)
            installed = versions[0]
            manifest = installed / "bundle-manifest.json"
            self.assertEqual(installed.name, hashlib.sha256(manifest.read_bytes()).hexdigest())
            self.assertTrue((installed / "app" / "index.html").is_file())
            self.assertTrue((installed / "app" / "THIRD_PARTY_NOTICES.txt").is_file())
            self.assertTrue((installed / "app" / "third-party-licenses" / "manifest.json").is_file())
            self.assertTrue(
                (
                    installed
                    / "app"
                    / "third-party-licenses"
                    / "katex-fonts"
                    / "KATEX-FONTS-OFL-1.1.txt"
                ).is_file()
            )
            self.assertTrue((installed / "launch_review_desk.py").is_file())
            self.assertTrue((desk_root / "launch_review_desk.py").is_file())
            self.assertTrue((desk_root / "current.json").is_file())
            self.assertFalse((installed / "node_modules").exists())
            self.assertFalse(any(path.suffix == ".map" for path in installed.rglob("*")))
            check = subprocess.run(
                [sys.executable, str(desk_root / "launch_review_desk.py"), "--check"],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("integrity check passed", check.stdout)
            second = self.run_installer(*arguments, env={"PATH": ""})
            self.assertIn("Already current Review Desk", second.stdout)
            self.assertIn("Already current Review Desk launcher", second.stdout)
            self.assertEqual([path.name for path in (desk_root / "versions").iterdir()], [installed.name])

    def test_review_desk_dry_run_is_write_free(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            desk_root = root / "desk"
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--local",
                str(project),
                "--codex",
                "--copy-only",
                "--with-review-desk",
                "--review-desk-dir",
                str(desk_root),
                "--review-desk-bundle",
                str(ROOT / "review-viewer" / "release" / "review-desk.zip"),
                "--dry-run",
            )
            self.assertIn("Would install verified Review Desk", result.stdout)
            self.assertIn("Review Desk launch command", result.stdout)
            self.assertFalse(desk_root.exists())
            self.assertFalse((project / ".agents").exists())

    def test_review_desk_bundle_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = ROOT / "review-viewer" / "release" / "review-desk.zip"
            tampered = root / "tampered.zip"
            shutil.copy2(source, tampered)
            rewritten = root / "rewritten.zip"
            with zipfile.ZipFile(tampered) as original, zipfile.ZipFile(rewritten, "w") as output:
                for info in original.infolist():
                    data = original.read(info.filename)
                    if info.filename == "app/index.html":
                        data += b"tampered"
                    output.writestr(info, data)
            with self.assertRaisesRegex(MODULE.InstallError, "does not match"):
                MODULE.verify_review_desk_bundle(rewritten)

            without_notice = root / "without-notice.zip"
            with zipfile.ZipFile(source) as original:
                manifest = json.loads(original.read(MODULE.REVIEW_DESK_MANIFEST_NAME))
                manifest["files"] = [
                    record
                    for record in manifest["files"]
                    if record["path"] != MODULE.REVIEW_DESK_THIRD_PARTY_NOTICE
                ]
                payloads = {
                    info.filename: (info, original.read(info.filename))
                    for info in original.infolist()
                    if info.filename
                    not in {MODULE.REVIEW_DESK_MANIFEST_NAME, MODULE.REVIEW_DESK_THIRD_PARTY_NOTICE}
                }
                manifest_info = original.getinfo(MODULE.REVIEW_DESK_MANIFEST_NAME)
            canonical = (
                json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
            ).encode("utf-8")
            with zipfile.ZipFile(without_notice, "w") as output:
                output.writestr(manifest_info, canonical)
                for _name, (info, data) in payloads.items():
                    output.writestr(info, data)
            with self.assertRaisesRegex(MODULE.InstallError, "third-party notices"):
                MODULE.verify_review_desk_bundle(without_notice)

    def test_review_desk_specific_paths_require_opt_in(self) -> None:
        result = self.run_installer("--review-desk-dir", "/synthetic/review-desk", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("require --with-review-desk", result.stderr)

    def test_missing_installed_runtime_descriptor_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            runtime = root / "runtime"
            arguments = (
                "--source",
                str(fixture.skill),
                "--runtime-dir",
                str(runtime),
                "--local",
                str(project),
                "--codex",
            )
            self.run_installer(*arguments)
            descriptor = (
                project
                / ".agents"
                / "skills"
                / "econ-review"
                / ".econ-review-runtime.json"
            )
            descriptor.unlink()
            repaired = self.run_installer(*arguments)
            self.assertIn("Installed Codex (project)", repaired.stdout)
            self.assertEqual(
                json.loads(descriptor.read_text(encoding="utf-8"))["python"],
                str(MODULE.runtime_python_path(runtime.absolute())),
            )

    def test_modified_installed_file_is_repaired(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            arguments = (
                "--source",
                str(fixture.skill),
                "--local",
                str(project),
                "--codex",
                "--copy-only",
            )
            self.run_installer(*arguments)
            installed = project / ".agents" / "skills" / "econ-review" / "SKILL.md"
            installed.write_text("tampered", encoding="utf-8")
            result = self.run_installer(*arguments)
            self.assertIn("Installed Codex (project)", result.stdout)
            self.assertEqual(
                installed.read_text(encoding="utf-8"),
                (fixture.skill / "SKILL.md").read_text(encoding="utf-8"),
            )

    def test_failed_runtime_refresh_restores_previous_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            runtime = root / "runtime"
            arguments = (
                "--source",
                str(fixture.skill),
                "--runtime-dir",
                str(runtime),
                "--local",
                str(project),
                "--codex",
            )
            self.run_installer(*arguments)
            marker = runtime / "preserved.txt"
            marker.write_text("previous runtime", encoding="utf-8")
            (fixture.skill / "requirements-core.txt").write_text(
                "this is not a valid requirement @@@\n",
                encoding="utf-8",
            )
            result = self.run_installer(*arguments, "--refresh-runtime", check=False)
            self.assertEqual(result.returncode, 1)
            self.assertIn("no command output was echoed", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "previous runtime")

    def test_missing_poppler_is_reported_without_system_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source", doctor_exit=1)
            project = root / "project"
            project.mkdir()
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--runtime-dir",
                str(root / "runtime"),
                "--local",
                str(project),
                "--codex",
                env={"PATH": str(root / "empty-path")},
                check=False,
            )
            self.assertEqual(result.returncode, 2)
            self.assertIn("Missing required Poppler commands", result.stdout)
            self.assertIn("non-admin setup", result.stdout)
            self.assertIn("PDF setup is incomplete", result.stdout)
            self.assertNotIn("sudo", result.stdout)

    def test_source_links_and_credential_files_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            secret = fixture.skill / ".env"
            secret.write_text("TOKEN=synthetic", encoding="utf-8")
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--copy-only",
                "--codex",
                env={"HOME": str(root / "home"), "CODEX_HOME": str(root / "codex")},
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("credential-bearing file", result.stderr)
            self.assertNotIn("TOKEN=synthetic", result.stderr)

    def test_bash_setup_flag_delegates_to_cross_platform_installer(self) -> None:
        if os.name == "nt":
            self.skipTest("Bash wrapper is not the native Windows entry point")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            result = subprocess.run(
                [
                    "bash",
                    str(ROOT / "install.sh"),
                    "--setup",
                    "--source",
                    str(fixture.skill),
                    "--local",
                    str(project),
                    "--codex",
                    "--dry-run",
                ],
                text=True,
                capture_output=True,
                check=True,
            )
            self.assertIn("Would create managed Python runtime", result.stdout)
            self.assertFalse((project / ".agents").exists())


if __name__ == "__main__":
    unittest.main()
