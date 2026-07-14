#!/usr/bin/env python3
"""Cross-platform tests for Unicode-safe command-line output."""

from __future__ import annotations

import io
import subprocess
import sys
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "econ-review" / "scripts"
sys.path.insert(0, str(SCRIPTS))
import cli_io  # noqa: E402


class CliIoTests(unittest.TestCase):
    def test_every_python_cli_configures_utf8_before_running(self) -> None:
        cli_paths = sorted(SCRIPTS.glob("*.py")) + sorted((ROOT / "scripts").glob("*.py"))
        checked = 0
        for path in cli_paths:
            text = path.read_text(encoding="utf-8")
            if "__main__" not in text:
                continue
            checked += 1
            with self.subTest(path=path.relative_to(ROOT).as_posix()):
                self.assertIn("configure_utf8_stdio()", text)
        self.assertGreaterEqual(checked, 20)

    def test_reconfigures_legacy_console_streams_to_utf8(self) -> None:
        stdout_bytes = io.BytesIO()
        stderr_bytes = io.BytesIO()
        stdout = io.TextIOWrapper(stdout_bytes, encoding="cp1252", errors="strict")
        stderr = io.TextIOWrapper(stderr_bytes, encoding="cp1252", errors="strict")
        with mock.patch.object(cli_io.sys, "stdout", stdout), mock.patch.object(
            cli_io.sys, "stderr", stderr
        ):
            cli_io.configure_utf8_stdio()
            stdout.write("Greek tau: τ; ligature: ﬀ")
            stderr.write("Unicode minus: −")
            stdout.flush()
            stderr.flush()
        self.assertEqual(stdout.encoding.casefold(), "utf-8")
        self.assertEqual(stderr.encoding.casefold(), "utf-8")
        self.assertEqual(stdout_bytes.getvalue().decode("utf-8"), "Greek tau: τ; ligature: ﬀ")
        self.assertEqual(stderr_bytes.getvalue().decode("utf-8"), "Unicode minus: −")

    def test_inventory_cli_overrides_cp1252_stdout(self) -> None:
        script = SCRIPTS / "propose_source_inventory.py"
        completed = subprocess.run(
            [sys.executable, str(script), "--help"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env={"PYTHONIOENCODING": "cp1252:strict"},
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr.decode("utf-8", "replace"))
        completed.stdout.decode("utf-8")
        completed.stderr.decode("utf-8")


if __name__ == "__main__":
    unittest.main()
