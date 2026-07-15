#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import hashlib
import json
import os
import shlex
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "setup_econ_review.py"
ROOT_WRAPPER = ROOT / "scripts" / "install_econ_review.py"
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
        (self.skill / "LICENSE").write_text("Synthetic license fixture.\n", encoding="utf-8")
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
                Path(tmp) / "home" / ".econ-review" / "runtime",
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

    def test_windows_review_desk_launcher_uses_managed_runtime_and_forwards_args(self) -> None:
        runtime_python = Path(r"D:\econ-review\runtime\Scripts\python.exe")
        launcher = MODULE.review_desk_cmd_bytes(runtime_python).decode("utf-8")
        self.assertIn(f'"{runtime_python}"', launcher)
        self.assertIn('-I "%~dp0launch_review_desk.py" %*', launcher)
        self.assertIn("set PYTHONUTF8=1", launcher)
        self.assertTrue(launcher.endswith("exit /b %ERRORLEVEL%\r\n"))

    def test_windows_review_desk_launcher_escapes_percent_in_runtime_path(self) -> None:
        launcher = MODULE.review_desk_cmd_bytes(
            Path(r"D:\Profiles\100%Reviewer\runtime\Scripts\python.exe")
        ).decode("utf-8")
        self.assertIn(r"100%%Reviewer", launcher)

    def test_posix_review_desk_command_is_shell_safe(self) -> None:
        arguments = [
            Path("/tmp/$HOME runtime/bin/python"),
            "-I",
            Path("/tmp/$(touch should-not-run)/launch_review_desk.py"),
        ]
        command = MODULE.format_launch_command(arguments, system="Linux")
        self.assertEqual(shlex.split(command), [str(value) for value in arguments])
        self.assertIn("'/tmp/$HOME runtime", command)
        self.assertIn("'/tmp/$(touch should-not-run)", command)

    def test_windows_review_desk_command_is_pasteable_in_powershell(self) -> None:
        launcher = Path(r"D:\Review Roots\O'Brien $Reviewer\Review Desk\review-desk.cmd")
        command = MODULE.format_launch_command([launcher], system="Windows")
        self.assertEqual(
            command,
            r"& 'D:\Review Roots\O''Brien $Reviewer\Review Desk\review-desk.cmd'",
        )

        python = Path(r"C:\Program Files\Python\python.exe")
        script = Path(r"D:\Review Roots\Reviewer Name\Review Desk\launch_review_desk.py")
        self.assertEqual(
            MODULE.format_launch_command([python, "-I", script], system="Windows"),
            r"& 'C:\Program Files\Python\python.exe' '-I' "
            r"'D:\Review Roots\Reviewer Name\Review Desk\launch_review_desk.py'",
        )

    def test_review_desk_command_rejects_multiline_paths(self) -> None:
        with self.assertRaisesRegex(MODULE.InstallError, "line breaks"):
            MODULE.format_launch_command(["/tmp/review\ncommand"], system="Linux")

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
                Path(tmp) / "home" / ".econ-review" / "review-desk",
            )

    def test_windows_store_runtime_redirection_is_resolved(self) -> None:
        requested = Path("/profiles/reviewer/AppData/Local/econ-review/runtime")
        actual_python = Path(
            "/profiles/reviewer/AppData/Local/Packages/Python/LocalCache/Local/"
            "econ-review/runtime/Scripts/python.exe"
        )
        with mock.patch.object(MODULE.os.path, "realpath", return_value=str(actual_python)):
            actual_runtime, python = MODULE.resolve_runtime_location(requested, "Windows")
        self.assertEqual(actual_runtime, actual_python.parent.parent)
        self.assertEqual(python, actual_python)

    def test_windows_store_runtime_redirection_fails_closed_on_unexpected_layout(self) -> None:
        requested = Path("/profiles/reviewer/AppData/Local/econ-review/runtime")
        with mock.patch.object(
            MODULE.os.path,
            "realpath",
            return_value="/unexpected/location/interpreter.exe",
        ):
            with self.assertRaisesRegex(MODULE.InstallError, "unexpected location"):
                MODULE.resolve_runtime_location(requested, "Windows")

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
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.Path, "home", return_value=Path(tmp) / "home"
        ):
            project = Path(tmp) / "project-root"
            runtime = MODULE.runtime_default("local", project, "Windows")
            self.assertEqual(runtime.parent.parent.parent, Path(tmp) / "home" / ".econ-review")
            self.assertEqual(runtime.name, "runtime")
            self.assertNotIn(project, runtime.parents)
            destinations = MODULE.installation_destinations("local", project, "all")
            self.assertEqual(
                [path for path, _ in destinations],
                [
                    project / ".claude" / "skills" / "econ-review",
                    project / ".agents" / "skills" / "econ-review",
                ],
            )

    def test_windows_project_scope_key_is_case_normalized(self) -> None:
        with tempfile.TemporaryDirectory() as tmp, mock.patch.object(
            MODULE.Path, "home", return_value=Path(tmp) / "home"
        ):
            upper = MODULE.support_scope_root(
                "local",
                Path(tmp) / "ReviewProject",
                "Windows",
            )
            lower = MODULE.support_scope_root(
                "local",
                Path(tmp) / "reviewproject",
                "Windows",
            )
            self.assertEqual(upper, lower)

    def test_relative_configuration_environment_paths_fail_closed(self) -> None:
        with mock.patch.dict(os.environ, {"CODEX_HOME": "relative-config"}, clear=True):
            with self.assertRaisesRegex(MODULE.InstallError, "absolute path"):
                MODULE.installation_destinations("global", None, "codex")


class ManagedInstallerTests(unittest.TestCase):
    def setUp(self) -> None:
        self._support_home_context = tempfile.TemporaryDirectory()
        self.addCleanup(self._support_home_context.cleanup)
        self.support_home = Path(self._support_home_context.name) / "home"

    def run_installer(
        self,
        *arguments: str,
        env: dict[str, str] | None = None,
        cwd: Path | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        merged["HOME"] = str(self.support_home)
        merged["XDG_DATA_HOME"] = str(self.support_home / ".local" / "share")
        if env:
            merged.update(env)
        return subprocess.run(
            [sys.executable, str(SCRIPT), *arguments],
            text=True,
            capture_output=True,
            env=merged,
            cwd=cwd,
            check=check,
        )

    @staticmethod
    def source_snapshot(root: Path) -> dict[str, tuple[str, int, str]]:
        snapshot: dict[str, tuple[str, int, str]] = {}
        for path in sorted((root, *root.rglob("*"))):
            relative = "." if path == root else path.relative_to(root).as_posix()
            if path.is_dir():
                snapshot[relative] = ("directory", stat.S_IMODE(path.stat().st_mode), "")
            else:
                snapshot[relative] = (
                    "file",
                    stat.S_IMODE(path.stat().st_mode),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
        return snapshot

    def test_managed_runtime_persists_windows_store_actual_interpreter(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            requested = root / "LocalAppData" / "econ-review" / "runtime"
            actual = root / "Packages" / "Python" / "LocalCache" / "Local" / "econ-review" / "runtime"
            actual_python = actual / "Scripts" / "python.exe"
            actual_python.parent.mkdir(parents=True)
            actual_python.write_bytes(b"synthetic executable")

            def redirected(path: object) -> str:
                if str(path).replace("\\", "/").endswith("/runtime/Scripts/python.exe"):
                    return str(actual_python)
                return str(path)

            completed = subprocess.CompletedProcess([], 0, "", "")
            with mock.patch.object(MODULE.platform, "system", return_value="Windows"), \
                    mock.patch.object(MODULE.os.path, "realpath", side_effect=redirected), \
                    mock.patch.object(MODULE.subprocess, "run", return_value=completed), \
                    mock.patch.object(MODULE, "_run_quiet", return_value=completed), \
                    mock.patch.object(MODULE, "python_major_minor", return_value=(3, 11)), \
                    mock.patch.object(MODULE, "runtime_is_reusable", return_value=True):
                python = MODULE.ensure_runtime(
                    requested,
                    fixture.skill,
                    refresh=True,
                    dry_run=False,
                )

            self.assertEqual(python, actual_python)
            self.assertTrue((actual / ".econ-review-runtime.json").is_file())

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

    def test_dry_run_never_executes_a_preexisting_target_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            runtime = root / "runtime"
            python = MODULE.runtime_python_path(runtime)
            python.parent.mkdir(parents=True)
            python.write_text("untrusted synthetic interpreter", encoding="utf-8")
            with mock.patch.object(
                MODULE,
                "_run_quiet",
                side_effect=AssertionError("dry run executed the target runtime"),
            ), mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=AssertionError("dry run spawned a child process"),
            ):
                planned = MODULE.ensure_runtime(
                    runtime,
                    fixture.skill,
                    refresh=False,
                    dry_run=True,
                )
            self.assertEqual(planned, python)

    def test_runtime_builder_preflight_runs_only_when_creation_is_needed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            runtime = root / "runtime"
            python = MODULE.runtime_python_path(runtime)
            python.parent.mkdir(parents=True)
            python.write_text("synthetic", encoding="utf-8")
            with mock.patch.object(MODULE, "runtime_is_reusable", return_value=True), \
                    mock.patch.object(MODULE, "require_runtime_builder") as preflight:
                reused = MODULE.ensure_runtime(
                    runtime,
                    fixture.skill,
                    refresh=False,
                    dry_run=False,
                    reuse_if_bound=True,
                )
            self.assertEqual(reused, python)
            preflight.assert_not_called()

            marker = runtime / "preserve-before-preflight"
            marker.write_text("keep", encoding="utf-8")
            with mock.patch.object(
                MODULE,
                "require_runtime_builder",
                side_effect=MODULE.InstallError("missing venv support"),
            ):
                with self.assertRaisesRegex(MODULE.InstallError, "missing venv"):
                    MODULE.ensure_runtime(
                        runtime,
                        fixture.skill,
                        refresh=True,
                        dry_run=False,
                    )
            self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_managed_setup_does_not_write_the_shared_pip_cache(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            runtime = root / "runtime"

            def create_fixture_runtime(
                *_args: object,
                **_kwargs: object,
            ) -> subprocess.CompletedProcess[str]:
                python = MODULE.runtime_python_path(runtime)
                python.parent.mkdir(parents=True)
                python.write_text("fixture", encoding="utf-8")
                return subprocess.CompletedProcess([], 0, "", "")

            with mock.patch.object(MODULE, "require_runtime_builder"), mock.patch.object(
                MODULE.subprocess,
                "run",
                side_effect=create_fixture_runtime,
            ), mock.patch.object(
                MODULE,
                "_run_quiet",
                return_value=subprocess.CompletedProcess([], 0, "", ""),
            ) as quiet, mock.patch.object(
                MODULE,
                "python_major_minor",
                return_value=(3, 12),
            ), mock.patch.object(MODULE, "runtime_is_reusable", return_value=True):
                MODULE.ensure_runtime(
                    runtime,
                    fixture.skill,
                    refresh=False,
                    dry_run=False,
                )

            pip_command = quiet.call_args_list[0].args[0]
            self.assertIn("--no-cache-dir", pip_command)

    def test_runtime_reuse_compares_the_managed_interpreter_version(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            runtime = root / "runtime"
            python = MODULE.runtime_python_path(runtime)
            python.parent.mkdir(parents=True)
            python.write_text("synthetic", encoding="utf-8")
            (runtime / ".econ-review-runtime.json").write_text(
                json.dumps(
                    {
                        "schema_version": "1",
                        "requirements_sha256": MODULE.requirements_digest(
                            fixture.skill / "requirements-core.txt"
                        ),
                        "python_major_minor": [3, 11],
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(MODULE, "python_major_minor", return_value=(3, 11)), \
                    mock.patch.object(MODULE, "python_satisfies_core", return_value=True):
                self.assertTrue(MODULE.runtime_is_reusable(runtime, fixture.skill))

    def test_dependency_probe_rejects_managed_python_older_than_310(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            python = root / "python"
            python.write_text("synthetic", encoding="utf-8")
            with mock.patch.object(MODULE, "python_major_minor", return_value=(3, 9)), \
                    mock.patch.object(
                        MODULE,
                        "_run_quiet",
                        side_effect=AssertionError("old interpreter should not run dependency probes"),
                    ):
                self.assertFalse(MODULE.python_satisfies_core(python, fixture.skill))

    def test_support_only_setup_keeps_read_only_plugin_cache_unchanged(self) -> None:
        if os.name == "nt":
            self.skipTest("POSIX mode enforcement is covered by native Windows path tests")
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "Plugin Cache With Spaces" / "0.2.0")
            assets = fixture.skill / "assets"
            assets.mkdir()
            shutil.copy2(ROOT / "econ-review" / "assets" / "review-desk.zip", assets)
            for path in fixture.skill.rglob("*"):
                path.chmod(0o555 if path.is_dir() else 0o444)
            fixture.skill.chmod(0o555)
            before = self.source_snapshot(fixture.skill)
            try:
                result = self.run_installer(
                    "--source",
                    str(fixture.skill),
                    "--support-only",
                    "--global",
                    "--with-review-desk",
                )
                self.assertIn("supporting setup is complete", result.stdout)
                self.assertEqual(self.source_snapshot(fixture.skill), before)
                self.assertFalse(any(path.name == "__pycache__" for path in fixture.skill.rglob("*")))
                self.assertFalse((self.support_home / ".claude" / "skills").exists())
                self.assertFalse((self.support_home / ".agents" / "skills").exists())
                with mock.patch.object(MODULE.Path, "home", return_value=self.support_home), \
                        mock.patch.dict(
                            os.environ,
                            {"XDG_DATA_HOME": str(self.support_home / ".local" / "share")},
                        ):
                    descriptor = MODULE.support_descriptor_default("global", None)
                    desk = MODULE.review_desk_default("global", None)
                value = json.loads(descriptor.read_text(encoding="utf-8"))
                self.assertTrue(Path(value["python"]).is_file())
                self.assertNotIn(fixture.skill, Path(value["runtime"]).parents)
                self.assertTrue((desk / "launch_review_desk.py").is_file())
                self.assertEqual(stat.S_IMODE(descriptor.stat().st_mode), 0o600)
                resolved = self.run_installer(
                    "--source",
                    str(fixture.skill),
                    "--runtime-path",
                )
                self.assertEqual(Path(resolved.stdout.strip()), Path(value["python"]))
            finally:
                fixture.skill.chmod(0o755)
                for path in fixture.skill.rglob("*"):
                    path.chmod(0o755 if path.is_dir() else 0o644)

    def test_project_support_state_is_external_and_scope_bound(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            self.run_installer(
                "--source",
                str(fixture.skill),
                "--support-only",
                "--local",
                str(project),
            )
            self.assertFalse((project / ".econ-review").exists())
            global_lookup = self.run_installer(
                "--source",
                str(fixture.skill),
                "--runtime-path",
                check=False,
            )
            self.assertEqual(global_lookup.returncode, 2)
            local_lookup = self.run_installer(
                "--source",
                str(fixture.skill),
                "--runtime-path",
                "--local",
                str(project),
            )
            self.assertTrue(Path(local_lookup.stdout.strip()).is_file())

    def test_support_cleanup_requires_preview_or_confirmation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            self.run_installer(
                "--source",
                str(fixture.skill),
                "--support-only",
                "--global",
            )
            with mock.patch.object(MODULE.Path, "home", return_value=self.support_home), \
                    mock.patch.dict(
                        os.environ,
                        {"XDG_DATA_HOME": str(self.support_home / ".local" / "share")},
                    ):
                descriptor = MODULE.support_descriptor_default("global", None)
                runtime = MODULE.runtime_default("global", None)
                desk = MODULE.review_desk_default("global", None)
                product_root = MODULE.support_data_root()
            desk.mkdir(parents=True)
            (desk / "desk-state").write_text("remove", encoding="utf-8")
            sibling = product_root / "keep-unrelated-user-data"
            sibling.write_text("keep", encoding="utf-8")
            direct_skill = root / "direct-skill-copy"
            direct_skill.mkdir()
            (direct_skill / "SKILL.md").write_text("keep", encoding="utf-8")
            refused = self.run_installer(
                "--source",
                str(fixture.skill),
                "--cleanup-support",
                check=False,
            )
            self.assertEqual(refused.returncode, 1)
            self.assertTrue(descriptor.exists())
            preview = self.run_installer(
                "--source",
                str(fixture.skill),
                "--cleanup-support",
                "--global",
                "--dry-run",
            )
            self.assertIn("Cleanup dry run complete; no files changed", preview.stdout)
            self.assertTrue(descriptor.exists())
            removed = self.run_installer(
                "--source",
                str(fixture.skill),
                "--cleanup-support",
                "--global",
                "--confirm-cleanup",
            )
            self.assertIn("support cleanup complete", removed.stdout)
            self.assertFalse(descriptor.exists())
            self.assertFalse(runtime.exists())
            self.assertFalse(desk.exists())
            self.assertEqual(sibling.read_text(encoding="utf-8"), "keep")
            self.assertTrue((direct_skill / "SKILL.md").is_file())

    @unittest.skipIf(os.name == "nt", "symlink creation is privilege-dependent on Windows")
    def test_support_cleanup_rejects_linked_default_target(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            outside = root / "outside-runtime"
            outside.mkdir()
            marker = outside / "keep"
            marker.write_text("safe", encoding="utf-8")
            with mock.patch.object(MODULE.Path, "home", return_value=self.support_home), \
                    mock.patch.dict(
                        os.environ,
                        {"XDG_DATA_HOME": str(self.support_home / ".local" / "share")},
                    ):
                runtime = MODULE.runtime_default("global", None)
            runtime.parent.mkdir(parents=True, exist_ok=True)
            runtime.symlink_to(outside, target_is_directory=True)
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--cleanup-support",
                "--global",
                "--dry-run",
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("refusing linked or junction managed runtime", result.stderr)
            self.assertEqual(marker.read_text(encoding="utf-8"), "safe")

    def test_local_support_cleanup_works_after_project_directory_is_removed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            self.run_installer(
                "--source",
                str(fixture.skill),
                "--support-only",
                "--local",
                str(project),
            )
            project.rmdir()
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--cleanup-support",
                "--local",
                str(project),
                "--confirm-cleanup",
            )
            self.assertIn("support cleanup complete", result.stdout)

    def test_subprocess_isolation_blocks_cwd_pip_and_venv_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            manuscript = root / "manuscript"
            manuscript.mkdir()
            markers = (root / "venv-shadow-ran", root / "pip-shadow-ran")
            for name, marker in zip(("venv.py", "pip.py"), markers):
                (manuscript / name).write_text(
                    f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n",
                    encoding="utf-8",
                )
            self.run_installer(
                "--source",
                str(fixture.skill),
                "--support-only",
                "--global",
                cwd=manuscript,
            )
            self.assertFalse(any(marker.exists() for marker in markers))

    def test_support_destinations_cannot_overlap_the_plugin(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            fixture = InstallerFixture(Path(tmp) / "source")
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--support-only",
                "--runtime-dir",
                str(fixture.skill / "runtime"),
                "--dry-run",
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("must not overlap", result.stderr)

    def test_support_only_rejects_ignored_agent_selectors(self) -> None:
        result = self.run_installer("--support-only", "--codex", "--dry-run", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("does not accept --claude or --codex", result.stderr)

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
                self.assertFalse((destination / ".econ-review-runtime.json").exists())
                metadata = json.loads(
                    (destination / ".econ-review-install.json").read_text(encoding="utf-8")
                )
                self.assertEqual(metadata["runtime_python"], str(runtime_python))
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertEqual(
                    (destination / "LICENSE").read_bytes(),
                    (fixture.skill / "LICENSE").read_bytes(),
                )
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
            self.assertEqual(
                (destination / "LICENSE").read_bytes(),
                (fixture.skill / "LICENSE").read_bytes(),
            )
            self.assertFalse((destination / ".econ-review-runtime.json").exists())
            self.assertFalse((project / ".econ-review").exists())

    def test_prebuilt_review_desk_installs_immutably_without_node(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            desk_root = root / "desk"
            bundle = ROOT / "econ-review" / "assets" / "review-desk.zip"
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
            self.assertEqual(
                (installed / "app" / "LICENSE.txt").read_bytes(),
                (ROOT / "review-viewer" / "LICENSE").read_bytes(),
            )
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

    def test_windows_review_desk_cmd_is_installed_and_idempotent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            desk_root = root / "desk"
            runtime_python = root / "runtime" / "Scripts" / "python.exe"
            bundle = ROOT / "econ-review" / "assets" / "review-desk.zip"
            MODULE.install_review_desk(
                bundle,
                desk_root,
                dry_run=False,
                runtime_python=runtime_python,
                system="Windows",
            )
            launcher = desk_root / MODULE.REVIEW_DESK_WINDOWS_LAUNCHER
            self.assertEqual(launcher.read_bytes(), MODULE.review_desk_cmd_bytes(runtime_python))
            before = launcher.stat().st_mtime_ns
            MODULE.install_review_desk(
                bundle,
                desk_root,
                dry_run=False,
                runtime_python=runtime_python,
                system="Windows",
            )
            self.assertEqual(launcher.stat().st_mtime_ns, before)

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
                str(ROOT / "econ-review" / "assets" / "review-desk.zip"),
                "--dry-run",
            )
            self.assertIn("Would install verified Review Desk", result.stdout)
            self.assertIn("Review Desk launch command", result.stdout)
            self.assertFalse(desk_root.exists())
            self.assertFalse((project / ".agents").exists())

    def test_review_desk_bundle_tampering_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            source = ROOT / "econ-review" / "assets" / "review-desk.zip"
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

    def test_review_desk_rejects_unlisted_version_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "desk"
            bundle = ROOT / "econ-review" / "assets" / "review-desk.zip"
            installed = MODULE.install_review_desk(bundle, root, dry_run=False)
            manifest_bytes, records, _digest = MODULE.verify_review_desk_bundle(bundle)
            (installed / "hashlib.py").write_text("raise RuntimeError('shadowed')\n", encoding="utf-8")

            self.assertFalse(MODULE.review_desk_is_current(installed, manifest_bytes, records))
            with self.assertRaisesRegex(MODULE.InstallError, "fails verification"):
                MODULE.install_review_desk(bundle, root, dry_run=False)

    def test_review_desk_authenticates_version_launcher_before_exec(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "desk"
            bundle = ROOT / "econ-review" / "assets" / "review-desk.zip"
            installed = MODULE.install_review_desk(bundle, root, dry_run=False)
            marker = Path(tmp) / "unverified-launcher-ran"
            (installed / "launch_review_desk.py").write_text(
                f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(root / "launch_review_desk.py"), "--check"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            self.assertNotEqual(result.returncode, 0)
            self.assertIn("pre-launch authentication", result.stderr)
            self.assertFalse(marker.exists())

    def test_review_desk_stable_launcher_blocks_local_module_shadowing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "desk"
            bundle = ROOT / "econ-review" / "assets" / "review-desk.zip"
            MODULE.install_review_desk(bundle, root, dry_run=False)
            marker = Path(tmp) / "shadow-module-ran"
            (root / "json.py").write_text(
                f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n",
                encoding="utf-8",
            )

            result = subprocess.run(
                [sys.executable, str(root / "launch_review_desk.py"), "--check"],
                text=True,
                capture_output=True,
                timeout=30,
                check=False,
            )

            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertIn("integrity check passed", result.stdout)
            self.assertFalse(marker.exists())

    def test_review_desk_specific_paths_require_opt_in(self) -> None:
        result = self.run_installer("--review-desk-dir", "/synthetic/review-desk", check=False)
        self.assertEqual(result.returncode, 1)
        self.assertIn("require --with-review-desk", result.stderr)

    def test_missing_external_runtime_descriptor_is_repaired(self) -> None:
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
            with mock.patch.object(MODULE.Path, "home", return_value=self.support_home), \
                    mock.patch.dict(
                        os.environ,
                        {"XDG_DATA_HOME": str(self.support_home / ".local" / "share")},
                    ):
                descriptor = MODULE.support_descriptor_default("local", project.resolve())
            descriptor.unlink()
            marker = runtime / "unbound-runtime-must-not-run"
            marker.write_text("replace", encoding="utf-8")
            repaired = self.run_installer(*arguments)
            self.assertIn("Prepared managed Python runtime", repaired.stdout)
            self.assertFalse(marker.exists())
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

    def test_unlisted_installed_module_is_removed_before_doctor(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            (fixture.skill / "scripts" / "pdf_ingestion.py").write_text(
                "import hashlib\n"
                "import sys\n"
                "assert sys.argv[-1] == 'doctor'\n"
                "print('fixture doctor: complete')\n",
                encoding="utf-8",
            )
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
            destination = project / ".agents" / "skills" / "econ-review"
            marker = root / "shadow-module-ran"
            shadow = destination / "scripts" / "hashlib.py"
            shadow.write_text(
                f"open({str(marker)!r}, 'w', encoding='utf-8').write('executed')\n",
                encoding="utf-8",
            )

            result = self.run_installer(*arguments, "--check")

            self.assertIn("Installed Codex (project)", result.stdout)
            self.assertFalse(shadow.exists())
            self.assertFalse(marker.exists())

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

    def test_source_license_is_required(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            (fixture.skill / "LICENSE").unlink()
            result = self.run_installer(
                "--source",
                str(fixture.skill),
                "--copy-only",
                "--codex",
                env={"HOME": str(root / "home"), "CODEX_HOME": str(root / "codex")},
                check=False,
            )
            self.assertEqual(result.returncode, 1)
            self.assertIn("missing a safe LICENSE", result.stderr)

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

    def test_root_python_wrapper_delegates_to_canonical_setup_tool(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            fixture = InstallerFixture(root / "source")
            project = root / "project"
            project.mkdir()
            arguments = (
                "--source",
                str(fixture.skill),
                "--copy-only",
                "--local",
                str(project),
                "--codex",
                "--dry-run",
            )
            environment = os.environ.copy()
            environment["PYTHONDONTWRITEBYTECODE"] = "1"
            canonical = subprocess.run(
                [sys.executable, str(SCRIPT), *arguments],
                text=True,
                capture_output=True,
                env=environment,
                check=True,
            )
            wrapper = subprocess.run(
                [sys.executable, str(ROOT_WRAPPER), *arguments],
                text=True,
                capture_output=True,
                env=environment,
                check=True,
            )
            self.assertEqual(wrapper.stdout, canonical.stdout)
            self.assertEqual(wrapper.stderr, canonical.stderr)


if __name__ == "__main__":
    unittest.main()
