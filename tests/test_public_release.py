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
    def test_exact_contract_excludes_private_and_generated_material(self) -> None:
        paths = {path.as_posix() for path in MODULE.public_files(ROOT)}
        self.assertIn("econ-review/SKILL.md", paths)
        self.assertIn("review-viewer/package.json", paths)
        self.assertIn("tests/fixtures/valid-review/report.md", paths)
        self.assertIn("scripts/public-release-files.json", paths)
        for private in ("DESIGN.md", "HANDOFF.md", "PROJECT-REVIEW.md", "research", "test_paper2"):
            self.assertFalse(any(path == private or path.startswith(private + "/") for path in paths))
        self.assertFalse(any("node_modules" in path or "/dist/" in path or "/public/" in path for path in paths))
        self.assertFalse(any(path.startswith("benchmarks/reviews/") for path in paths))

    def test_unknown_nested_file_fails_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = self.make_contract_root(Path(tmp), {"scripts/public-release-files.json": b""})
            (root / "econ-review" / "client-notes.md").write_text("not for release", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "undeclared file"):
                MODULE.public_files(root)

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
                for record in embedded["files"]:
                    data = archive.read(f"econ-paper-review-skill/{record['path']}")
                    self.assertEqual(len(data), record["size"])
                    self.assertEqual(hashlib.sha256(data).hexdigest(), record["sha256"])

    def test_builder_refuses_existing_or_symlink_output(self) -> None:
        files = MODULE.public_files(ROOT)
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "release.zip"
            target.write_bytes(b"keep")
            with self.assertRaisesRegex(ValueError, "already exists"):
                MODULE.build_zip(ROOT, target, files)
            target.unlink()
            target.symlink_to(Path(tmp) / "elsewhere.zip")
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
            self.assertFalse((destination / "old.txt").exists())
            self.assertFalse(list(destination.parent.glob(".econ-review.*")))

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
