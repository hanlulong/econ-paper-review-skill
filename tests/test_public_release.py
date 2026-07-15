#!/usr/bin/env python3

from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import tempfile
import unittest
import zipfile
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "scripts" / "build_public_release.py"
SPEC = importlib.util.spec_from_file_location("build_public_release", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class PublicReleaseTests(unittest.TestCase):
    WINDOWS_MANAGED_INSTALL = (
        r"python scripts\install_econ_review.py --global --all --with-review-desk"
    )

    def test_exact_contract_excludes_private_and_generated_material(self) -> None:
        paths = {path.as_posix() for path in MODULE.public_files(ROOT)}
        self.assertNotIn(".claude-plugin/marketplace.json", paths)
        self.assertIn("CONTRIBUTING.md", paths)
        self.assertIn(".github/PULL_REQUEST_TEMPLATE.md", paths)
        self.assertIn("docs/CONTRIBUTOR_LICENSE_AGREEMENT.md", paths)
        self.assertIn("econ-review/LICENSE", paths)
        self.assertIn("econ-review/.claude-plugin/plugin.json", paths)
        self.assertIn("econ-review/.codex-plugin/plugin.json", paths)
        self.assertIn("econ-review/SKILL.md", paths)
        self.assertIn("econ-review/skills/econ-review/SKILL.md", paths)
        self.assertIn("econ-review/skills/econ-review-setup/SKILL.md", paths)
        self.assertIn("econ-review/scripts/setup_econ_review.py", paths)
        self.assertIn("econ-review/assets/review-desk.zip", paths)
        self.assertIn("review-viewer/LICENSE", paths)
        self.assertIn("review-viewer/package.json", paths)
        self.assertIn("review-viewer/public/favicon.svg", paths)
        self.assertNotIn("review-viewer/release/review-desk.zip", paths)
        self.assertIn("review-viewer/scripts/launch_review_desk.py", paths)
        self.assertIn("docs/images/review-desk.gif", paths)
        self.assertIn("docs/images/review-desk-flow.png", paths)
        self.assertIn("docs/sample-review/demo-paper.pdf", paths)
        self.assertIn("docs/sample-review/paper-review.pdf", paths)
        self.assertIn("tests/fixtures/valid-review/report.md", paths)
        self.assertIn("scripts/public-release-files.json", paths)
        for private in ("DESIGN.md", "HANDOFF.md", "PROJECT-REVIEW.md", "research", "test_paper2"):
            self.assertFalse(any(path == private or path.startswith(private + "/") for path in paths))
        self.assertFalse(any("node_modules" in path or "/dist/" in path for path in paths))
        self.assertEqual(
            {path for path in paths if "/public/" in path},
            {"review-viewer/public/favicon.svg"},
        )
        self.assertFalse(any(path.startswith("benchmarks/reviews/") for path in paths))

    def test_native_windows_install_command_is_consistent(self) -> None:
        for relative in ("README.md", "docs/INSTALL.md", "install.sh"):
            with self.subTest(path=relative):
                content = (ROOT / relative).read_text(encoding="utf-8")
                self.assertIn(self.WINDOWS_MANAGED_INSTALL, content)
                self.assertNotIn("py -3 scripts", content)

    def test_public_install_guidance_does_not_require_private_credentials(self) -> None:
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        install = (ROOT / "docs" / "INSTALL.md").read_text(encoding="utf-8")
        for content in (readme, install):
            with self.subTest(document="README" if content is readme else "INSTALL"):
                self.assertIn("OpenEconAI/plugins", content)
                self.assertRegex(content, r"(?i)(never paste|do not expose) a token")
                self.assertNotIn("gh auth login", content)
                self.assertNotRegex(content, r"(?i)(export\s+GITHUB_TOKEN|GITHUB_TOKEN\s*=|github_pat_)")
        self.assertIn("${XDG_DATA_HOME:-$HOME/.local/share}/econ-review/", install)
        self.assertNotIn("${XDG_DATA_HOME:-~/.local/share}", install)
        self.assertIn("git pull --ff-only", install)
        self.assertIn("Do not combine a native plugin and a direct skill copy", install)

    def test_local_evaluation_handoffs_are_root_ignored(self) -> None:
        patterns = set((ROOT / ".gitignore").read_text(encoding="utf-8").splitlines())
        self.assertIn("/RUN_ISSUES.md", patterns)
        self.assertIn("/WINDOWS_OPTIMIZATION_HANDOFF.md", patterns)

    def test_unknown_nested_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(Path(tmp), {"scripts/public-release-files.json": b""})
            (root / "econ-review" / "client-notes.md").write_text("not for release", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "undeclared file"):
                MODULE.public_files(root)

    def test_generated_tool_caches_do_not_break_the_release_contract(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(Path(tmp), {"scripts/public-release-files.json": b""})
            cache = root / "review-viewer" / ".pytest_cache" / "v" / "cache"
            cache.mkdir(parents=True)
            (cache / "nodeids").write_text("[]", encoding="utf-8")
            self.assertEqual(MODULE.public_files(root), [Path("scripts/public-release-files.json")])

    def test_missing_declared_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(
                Path(tmp),
                {"scripts/public-release-files.json": b"", "econ-review/missing.md": b"value"},
            )
            (root / "econ-review" / "missing.md").unlink()
            with self.assertRaisesRegex(ValueError, "declared public file.*missing"):
                MODULE.public_files(root)

    def test_file_contract_rejects_duplicate_json_keys(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            for tree in MODULE.SCAN_ROOTS:
                (root / tree).mkdir(parents=True, exist_ok=True)
            (root / MODULE.FILE_CONTRACT).write_text(
                '{"schema_version":"1","schema_version":"1","files":["scripts/public-release-files.json"]}',
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate JSON key"):
                MODULE.public_files(root)

    def test_file_contract_rejects_nonportable_paths(self) -> None:
        for value in (
            "econ-review/e\u0301.md",
            "econ-review/name:stream.md",
            "econ-review/trailing. ",
            "econ-review/CON.md",
            "NUL/review-viewer/file.ts",
            "econ-review/COM1",
            "econ-review/lpt9.txt",
            "econ-review/CLOCK$.json",
        ):
            with self.subTest(path=value):
                with self.assertRaisesRegex(ValueError, "unsafe|non-canonical"):
                    MODULE._safe_relative(value)

    def test_archive_modes_are_host_independent(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            python = root / "tool.py"
            shell = root / "install.sh"
            markdown = root / "README.md"
            for path in (python, shell, markdown):
                path.write_text("fixture\n", encoding="utf-8")
                path.chmod(0o600)
            self.assertEqual(MODULE._release_mode(python), 0o755)
            self.assertEqual(MODULE._release_mode(shell), 0o755)
            self.assertEqual(MODULE._release_mode(markdown), 0o644)

    def test_privacy_scan_rejects_home_paths_and_secret_filenames(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(
                Path(tmp),
                {
                    "scripts/public-release-files.json": b"",
                    "econ-review/references/note.md": b"Source: /" + b"Users/researcher/private-paper/paper.md\n",
                },
            )
            with self.assertRaisesRegex(ValueError, "(?s)privacy scan failed.*home path"):
                MODULE.public_files(root)
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(
                Path(tmp),
                {
                    "scripts/public-release-files.json": b"",
                    "econ-review/references/client-notes.md": b"ordinary text\n",
                },
            )
            with self.assertRaisesRegex(ValueError, "sensitive filename"):
                MODULE.public_files(root)

    def test_privacy_scan_rejects_windows_home_path(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(
                Path(tmp),
                {
                    "scripts/public-release-files.json": b"",
                    "econ-review/references/note.md": b"Source: C:" + b"\\Users\\researcher\\paper.md\n",
                },
            )
            with self.assertRaisesRegex(ValueError, "Windows user path"):
                MODULE.public_files(root)

    def test_privacy_scan_rejects_modern_service_tokens(self) -> None:
        examples = {
            "GitHub fine-grained token": "github_pat_" + "A" * 60,
            "OpenAI API key": "sk-proj-" + "A" * 40,
            "Anthropic API key": "sk-ant-" + "A" * 40,
            "Slack token": "xoxb-" + "1234567890-" * 3,
            "Google API key": "AIza" + "A" * 35,
        }
        for label, token in examples.items():
            with self.subTest(label=label), tempfile.TemporaryDirectory() as tmp:
                root = self.make_contract_root(
                    Path(tmp),
                    {
                        "scripts/public-release-files.json": b"",
                        "econ-review/references/note.md": f"credential={token}\n".encode(),
                    },
                )
                with self.assertRaisesRegex(ValueError, label):
                    MODULE.public_files(root)

    def test_first_party_license_copies_must_match(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(
                Path(tmp),
                {
                    "LICENSE": b"same license\n",
                    "econ-review/LICENSE": b"same license\n",
                    "review-viewer/LICENSE": b"same license\n",
                    "scripts/public-release-files.json": b"",
                },
            )
            self.assertEqual(MODULE.public_files(root)[0], Path("LICENSE"))
            (root / "review-viewer" / "LICENSE").write_text("different\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "not synchronized"):
                MODULE.public_files(root)

    def test_archive_has_exact_hashed_manifest_and_is_deterministic(self) -> None:
        files = MODULE.public_files(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            first = Path(tmp) / "release-1.zip"
            second = Path(tmp) / "release-2.zip"
            metadata = MODULE.build_zip(ROOT, first, files)
            MODULE.build_zip(ROOT, second, files)
            self.assertEqual(first.read_bytes(), second.read_bytes())
            with zipfile.ZipFile(first) as archive:
                names = set(archive.namelist())
                embedded = json.loads(archive.read("econ-paper-review-skill/RELEASE-MANIFEST.json"))
                expected = {f"econ-paper-review-skill/{path.as_posix()}" for path in files}
                expected.add("econ-paper-review-skill/RELEASE-MANIFEST.json")
                self.assertEqual(names, expected)
                self.assertEqual(embedded, metadata)
                prefix = "econ-paper-review-skill/"
                root_license = archive.read(prefix + "LICENSE")
                self.assertEqual(root_license, archive.read(prefix + "econ-review/LICENSE"))
                self.assertEqual(root_license, archive.read(prefix + "review-viewer/LICENSE"))
                for required in (
                    "CONTRIBUTING.md",
                    ".github/PULL_REQUEST_TEMPLATE.md",
                    "docs/CONTRIBUTOR_LICENSE_AGREEMENT.md",
                ):
                    self.assertIn(prefix + required, names)
                for record in embedded["files"]:
                    data = archive.read(f"econ-paper-review-skill/{record['path']}")
                    self.assertEqual(len(data), record["size"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])

    def test_nested_review_desk_license_notice_is_mandatory(self) -> None:
        source = ROOT / "econ-review" / "assets" / "review-desk.zip"
        notice = MODULE.REVIEW_DESK_THIRD_PARTY_NOTICE
        with tempfile.TemporaryDirectory() as tmp:
            rewritten = Path(tmp) / "review-desk-without-notice.zip"
            with zipfile.ZipFile(source) as original:
                manifest = json.loads(original.read("bundle-manifest.json"))
                manifest["files"] = [record for record in manifest["files"] if record["path"] != notice]
                payloads = {
                    info.filename: (info, original.read(info.filename))
                    for info in original.infolist()
                    if info.filename not in {"bundle-manifest.json", notice}
                }
                manifest_info = original.getinfo("bundle-manifest.json")
            with zipfile.ZipFile(rewritten, "w") as output:
                output.writestr(manifest_info, MODULE._canonical_json(manifest))
                for _name, (info, data) in payloads.items():
                    output.writestr(info, data)
            with self.assertRaisesRegex(ValueError, "third-party notices"):
                MODULE._scan_review_desk_bundle(rewritten, (ROOT / "LICENSE").read_bytes())

    def test_builder_refuses_existing_or_symlink_output(self) -> None:
        files = MODULE.public_files(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "release.zip"
            target.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "already exists"):
                MODULE.build_zip(ROOT, target, files)
            target.unlink()
            try:
                target.symlink_to(Path(tmp) / "elsewhere.zip")
            except OSError:
                if os.name == "nt":
                    self.skipTest("symlink creation requires Windows Developer Mode or elevated privileges")
                raise
            with self.assertRaisesRegex(ValueError, "already exists"):
                MODULE.build_zip(ROOT, target, files)

    @staticmethod
    def make_contract_root(root: Path, contents: dict[str, bytes]) -> Path:
        for tree in MODULE.SCAN_ROOTS:
            (root / tree).mkdir(parents=True, exist_ok=True)
        paths = sorted(contents)
        contract = {"schema_version": "1", "files": paths}
        for relative, data in contents.items():
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(data)
        (root / MODULE.FILE_CONTRACT).write_text(json.dumps(contract), encoding="utf-8")
        return root


@unittest.skipIf(
    os.name == "nt",
    "install.sh exercises the POSIX entry point; Windows installation is covered by test_install_econ_review.py",
)
class InstallerTests(unittest.TestCase):
    def run_installer(
        self,
        installer: Path,
        *arguments: str,
        env: dict[str, str] | None = None,
        check: bool = True,
    ) -> subprocess.CompletedProcess[str]:
        merged = os.environ.copy()
        if env:
            merged.update(env)
        return subprocess.run(
            ["bash", str(installer), *arguments],
            text=True,
            capture_output=True,
            env=merged,
            check=check,
        )

    def test_local_install_uses_temp_home_and_replaces_existing_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            destination = home / ".codex" / "skills" / "econ-review"
            destination.mkdir(parents=True)
            (destination / "old.txt").write_text("old", encoding="utf-8")
            result = self.run_installer(ROOT / "install.sh", "--global", "--codex", env={"HOME": str(home)})
            self.assertIn("installation complete", result.stdout)
            self.assertTrue((destination / "SKILL.md").is_file())
            self.assertEqual((destination / "LICENSE").read_bytes(), (ROOT / "econ-review" / "LICENSE").read_bytes())
            self.assertFalse((destination / "old.txt").exists())
            self.assertFalse((destination / ".DS_Store").exists())
            self.assertFalse((destination / "scripts" / "__pycache__").exists())
            self.assertFalse(list(destination.parent.glob(".econ-review.*")))

    def test_repeat_install_skips_exact_tree_and_repairs_drift(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            destination = home / ".codex" / "skills" / "econ-review"
            arguments = ("--global", "--codex")
            environment = {"HOME": str(home)}

            self.run_installer(ROOT / "install.sh", *arguments, env=environment)
            installed_skill = destination / "SKILL.md"
            original_inode = installed_skill.stat().st_ino
            repeated = self.run_installer(
                ROOT / "install.sh", *arguments, env=environment,
            )
            self.assertIn("Already current Codex (global)", repeated.stdout)
            self.assertEqual(installed_skill.stat().st_ino, original_inode)

            original = installed_skill.read_bytes()
            installed_skill.write_bytes((b"X" if original[:1] != b"X" else b"Y") + original[1:])
            extra = destination / "unexpected.txt"
            extra.write_text("remove me", encoding="utf-8")
            installed_script = destination / "scripts" / "validate_review.py"
            source_script = ROOT / "econ-review" / "scripts" / "validate_review.py"
            installed_script.chmod(stat.S_IMODE(installed_script.stat().st_mode) & ~0o111)

            repaired = self.run_installer(
                ROOT / "install.sh", *arguments, env=environment,
            )
            self.assertIn("Installed Codex (global)", repaired.stdout)
            self.assertEqual(installed_skill.read_bytes(), (ROOT / "econ-review" / "SKILL.md").read_bytes())
            self.assertFalse(extra.exists())
            self.assertEqual(
                stat.S_IMODE(installed_script.stat().st_mode),
                stat.S_IMODE(source_script.stat().st_mode),
            )
            self.assertFalse(list(destination.parent.glob(".econ-review.*")))

    def test_dry_run_reports_no_changes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp) / "home"
            result = self.run_installer(
                ROOT / "install.sh", "--global", "--all", "--dry-run", env={"HOME": str(home)},
            )
            self.assertIn("dry run complete; no files changed", result.stdout)
            self.assertFalse((home / ".claude").exists())
            self.assertFalse((home / ".codex").exists())

    def test_codex_and_claude_global_and_project_install_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            project = root / "project"
            project.mkdir()
            global_result = self.run_installer(
                ROOT / "install.sh", "--global", "--all", env={"HOME": str(home)},
            )
            self.assertIn("Claude Code (global)", global_result.stdout)
            self.assertIn("Codex (global)", global_result.stdout)
            global_destinations = [
                home / ".claude" / "skills" / "econ-review",
                home / ".codex" / "skills" / "econ-review",
            ]
            for destination in global_destinations:
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertEqual(
                    (destination / "LICENSE").read_bytes(),
                    (ROOT / "econ-review" / "LICENSE").read_bytes(),
                )
                self.assertTrue((destination / "references" / "workflow.md").is_file())
                self.assertTrue((destination / "requirements-core.txt").is_file())
                self.assertTrue((destination / "requirements-docling.txt").is_file())
                self.assertTrue((destination / "requirements-markitdown.txt").is_file())
                self.assertTrue((destination / "requirements-mathpix.txt").is_file())
                self.assertTrue((destination / "scripts" / "dependency_versions.py").is_file())
                self.assertTrue(os.access(destination / "scripts" / "validate_review.py", os.X_OK))

            project_result = self.run_installer(
                ROOT / "install.sh", "--local", str(project), "--all", env={"HOME": str(home)},
            )
            self.assertIn("Claude Code (project)", project_result.stdout)
            self.assertIn("Codex (project)", project_result.stdout)
            project_destinations = [
                project / ".claude" / "skills" / "econ-review",
                project / ".agents" / "skills" / "econ-review",
            ]
            for destination in project_destinations:
                self.assertTrue((destination / "SKILL.md").is_file())
                self.assertEqual(
                    (destination / "LICENSE").read_bytes(),
                    (ROOT / "econ-review" / "LICENSE").read_bytes(),
                )
                self.assertTrue((destination / "scripts" / "pdf_ingestion.py").is_file())

    def test_platform_specific_config_directory_overrides(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            claude_root = root / "claude-config"
            codex_root = root / "codex-home"
            self.run_installer(
                ROOT / "install.sh", "--global", "--all",
                env={
                    "HOME": str(root / "home"),
                    "CLAUDE_CONFIG_DIR": str(claude_root),
                    "CODEX_HOME": str(codex_root),
                },
            )
            self.assertTrue((claude_root / "skills" / "econ-review" / "SKILL.md").is_file())
            self.assertTrue((codex_root / "skills" / "econ-review" / "SKILL.md").is_file())

    def test_remote_install_requires_url_and_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            installer = Path(tmp) / "install.sh"
            shutil.copy2(ROOT / "install.sh", installer)
            result = self.run_installer(installer, "--global", "--codex", env={"HOME": tmp}, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("remote installation is disabled", result.stderr)

    def test_verified_remote_archive_installs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = root / "standalone" / "install.sh"
            installer.parent.mkdir()
            shutil.copy2(ROOT / "install.sh", installer)
            archive = root / "release.zip"
            MODULE.build_zip(ROOT, archive, MODULE.public_files(ROOT))
            digest = hashlib.sha256(archive.read_bytes()).hexdigest()
            home = root / "home"
            result = self.run_installer(
                installer,
                "--global",
                "--codex",
                env={
                    "HOME": str(home),
                    "ECON_REVIEW_ARCHIVE_URL": archive.as_uri(),
                    "ECON_REVIEW_ARCHIVE_SHA256": digest,
                    "ECON_REVIEW_ALLOW_INSECURE_TEST_URL": "1",
                },
            )
            self.assertIn("installation complete", result.stdout)
            self.assertTrue((home / ".codex" / "skills" / "econ-review" / "SKILL.md").is_file())
            self.assertTrue(os.access(home / ".codex" / "skills" / "econ-review" / "scripts" / "validate_review.py", os.X_OK))

    def test_remote_archive_rejects_bad_checksum_extra_path_and_symlink(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = root / "standalone" / "install.sh"
            installer.parent.mkdir()
            shutil.copy2(ROOT / "install.sh", installer)
            archive = root / "release.zip"
            MODULE.build_zip(ROOT, archive, MODULE.public_files(ROOT))
            base_env = {
                "HOME": str(root / "home"),
                "ECON_REVIEW_ARCHIVE_URL": archive.as_uri(),
                "ECON_REVIEW_ALLOW_INSECURE_TEST_URL": "1",
            }
            bad_checksum = dict(base_env, ECON_REVIEW_ARCHIVE_SHA256="0" * 64)
            result = self.run_installer(installer, "--global", "--codex", env=bad_checksum, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("SHA-256 mismatch", result.stderr)

            with zipfile.ZipFile(archive, "a") as release:
                release.writestr("econ-paper-review-skill/undeclared.txt", "unexpected")
            extra_env = dict(base_env, ECON_REVIEW_ARCHIVE_SHA256=hashlib.sha256(archive.read_bytes()).hexdigest())
            result = self.run_installer(installer, "--global", "--codex", env=extra_env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("entries differ from manifest", result.stderr)

            archive.unlink()
            MODULE.build_zip(ROOT, archive, MODULE.public_files(ROOT))
            with zipfile.ZipFile(archive, "a") as release:
                link = zipfile.ZipInfo("econ-paper-review-skill/link")
                link.create_system = 3
                link.external_attr = (stat.S_IFLNK | 0o777) << 16
                release.writestr(link, "econ-review/SKILL.md")
            link_env = dict(base_env, ECON_REVIEW_ARCHIVE_SHA256=hashlib.sha256(archive.read_bytes()).hexdigest())
            result = self.run_installer(installer, "--global", "--codex", env=link_env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("non-regular archive entry", result.stderr)

    def test_remote_archive_rejects_traversal_ambiguous_roots_and_case_collisions(self) -> None:
        cases = (
            ("econ-paper-review-skill/../escape", "unsafe archive path"),
            ("econ-paper-review-skill/e\u0301.txt", "unsafe archive path"),
            ("econ-paper-review-skill/name:stream", "unsafe archive path"),
            ("econ-paper-review-skill/econ-review/NUL.txt", "unsafe archive path"),
            ("second-root/file.txt", "exactly one econ-paper-review-skill root"),
            ("econ-paper-review-skill/README.MD", "duplicate or case-colliding"),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = root / "standalone" / "install.sh"
            installer.parent.mkdir()
            shutil.copy2(ROOT / "install.sh", installer)
            for index, (entry_name, expected_message) in enumerate(cases):
                archive = root / f"release-{index}.zip"
                MODULE.build_zip(ROOT, archive, MODULE.public_files(ROOT))
                with zipfile.ZipFile(archive, "a") as release:
                    release.writestr(entry_name, "unexpected")
                env = {
                    "HOME": str(root / f"home-{index}"),
                    "ECON_REVIEW_ARCHIVE_URL": archive.as_uri(),
                    "ECON_REVIEW_ARCHIVE_SHA256": hashlib.sha256(archive.read_bytes()).hexdigest(),
                    "ECON_REVIEW_ALLOW_INSECURE_TEST_URL": "1",
                }
                with self.subTest(entry=entry_name):
                    result = self.run_installer(installer, "--global", "--codex", env=env, check=False)
                    self.assertNotEqual(result.returncode, 0)
                    self.assertIn(expected_message, result.stderr)

    def test_remote_archive_rejects_payload_tampering_even_with_updated_outer_checksum(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            installer = root / "standalone" / "install.sh"
            installer.parent.mkdir()
            shutil.copy2(ROOT / "install.sh", installer)
            original = root / "release.zip"
            tampered = root / "tampered.zip"
            MODULE.build_zip(ROOT, original, MODULE.public_files(ROOT))
            target = "econ-paper-review-skill/econ-review/SKILL.md"
            with zipfile.ZipFile(original) as source, zipfile.ZipFile(tampered, "w") as destination:
                for info in source.infolist():
                    data = source.read(info.filename)
                    if info.filename == target:
                        data = (b"X" if data[:1] != b"X" else b"Y") + data[1:]
                    destination.writestr(info, data)
            env = {
                "HOME": str(root / "home"),
                "ECON_REVIEW_ARCHIVE_URL": tampered.as_uri(),
                "ECON_REVIEW_ARCHIVE_SHA256": hashlib.sha256(tampered.read_bytes()).hexdigest(),
                "ECON_REVIEW_ALLOW_INSECURE_TEST_URL": "1",
            }
            result = self.run_installer(installer, "--global", "--codex", env=env, check=False)
            self.assertNotEqual(result.returncode, 0)
            self.assertIn("file hash mismatch", result.stderr)

    def test_failed_final_move_restores_previous_installation(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home = root / "home"
            destination = home / ".codex" / "skills" / "econ-review"
            destination.mkdir(parents=True)
            marker = destination / "old.txt"
            marker.write_text("preserve me", encoding="utf-8")
            fake_bin = root / "bin"
            fake_bin.mkdir()
            real_mv = shutil.which("mv")
            assert real_mv
            wrapper = fake_bin / "mv"
            wrapper.write_text(
                "#!/bin/sh\n"
                "for arg in \"$@\"; do\n"
                "  case \"$arg\" in *.econ-review.stage.*) exit 73;; esac\n"
                "done\n"
                f'exec "{real_mv}" "$@"\n',
                encoding="utf-8",
            )
            wrapper.chmod(0o755)
            result = self.run_installer(
                ROOT / "install.sh",
                "--global",
                "--codex",
                env={"HOME": str(home), "PATH": f"{fake_bin}{os.pathsep}{os.environ['PATH']}"},
                check=False,
            )
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(marker.read_text(encoding="utf-8"), "preserve me")
            self.assertFalse(list(destination.parent.glob(".econ-review.*")))


if __name__ == "__main__":
    unittest.main()
