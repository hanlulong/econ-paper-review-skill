#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "pdf_reconciliation.py"
SPEC = importlib.util.spec_from_file_location("pdf_reconciliation", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class ProposalIndexPathTests(unittest.TestCase):
    @staticmethod
    def proposal(path: str) -> list[dict]:
        return [{
            "id": "PROP-01",
            "artifacts": [{"path": path}],
        }]

    def test_reads_only_canonical_normalized_index_inside_declared_package(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            relative = Path("evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json")
            path = root / relative
            path.parent.mkdir(parents=True)
            path.write_text(
                json.dumps({"pages": [{"page": 1, "elements": []}]}),
                encoding="utf-8",
            )
            index = MODULE.load_proposal_page_index(
                root,
                "evidence/pdf-ingestion/SRC-01",
                self.proposal(relative.as_posix()),
            )
            self.assertEqual(index["PROP-01"][1]["elements"], [])

    def test_rejects_traversal_alias_reserved_and_symlink_indexes(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            root = base / "root"
            root.mkdir()
            outside = base / "normalized.json"
            outside.write_text('{"pages":[{"page":99}]}', encoding="utf-8")
            unsafe_paths = (
                "../normalized.json",
                "evidence/pdf-ingestion/SRC-01/./normalized.json",
                "evidence/pdf-ingestion/SRC-01/NUL/normalized.json",
            )
            for unsafe in unsafe_paths:
                with self.subTest(path=unsafe):
                    self.assertEqual(
                        MODULE.load_proposal_page_index(
                            root,
                            "evidence/pdf-ingestion/SRC-01",
                            self.proposal(unsafe),
                        ),
                        {},
                    )

            inside = root / "evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json"
            inside.parent.mkdir(parents=True)
            inside.symlink_to(outside)
            self.assertEqual(
                MODULE.load_proposal_page_index(
                    root,
                    "evidence/pdf-ingestion/SRC-01",
                    self.proposal(
                        "evidence/pdf-ingestion/SRC-01/proposals/tool/normalized.json"
                    ),
                ),
                {},
            )


if __name__ == "__main__":
    unittest.main()
