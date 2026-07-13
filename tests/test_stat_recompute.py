#!/usr/bin/env python3

from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "econ-review" / "scripts" / "stat_recompute.py"
SPEC = importlib.util.spec_from_file_location("stat_recompute", SCRIPT)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class StatRecomputeTests(unittest.TestCase):
    def test_core_recomputations(self) -> None:
        output = MODULE.run({"checks": [
            {"id": "t", "type": "t_from_beta_se", "beta": 0.5, "se": 0.2, "reported": 2.5},
            {"id": "f", "type": "f_from_t", "t": 2.5, "reported": 6.25},
            {"id": "share", "type": "share_from_count", "count": 1, "total": 4, "reported": 25},
            {"id": "n", "type": "n_drift", "expected": 100, "observed": 98, "reported": -2},
        ]})
        self.assertEqual(output["counts"], {"match": 4, "mismatch": 0, "recomputed": 0})

    def test_mismatch_and_invalid_denominator(self) -> None:
        output = MODULE.run({"checks": [
            {"id": "t", "type": "t_from_beta_se", "beta": 0.5, "se": 0.2, "reported": 2.4},
        ]})
        self.assertEqual(output["results"][0]["status"], "mismatch")
        with self.assertRaisesRegex(ValueError, "total must be positive"):
            MODULE.run({"checks": [{"type": "share_from_count", "count": 1, "total": 0}]})

    def test_grim_check(self) -> None:
        consistent = MODULE.run({"checks": [
            {"id": "grim", "type": "grim_mean", "mean": "2.00", "n": 10, "decimals": 2},
        ]})
        self.assertEqual(consistent["results"][0]["status"], "match")
        self.assertIn("compatible with an integer-valued sample mean", consistent["results"][0]["interpretation"])
        inconsistent = MODULE.run({"checks": [
            {"id": "grim", "type": "grim_mean", "mean": "2.05", "n": 10, "decimals": 2},
        ]})
        self.assertEqual(inconsistent["results"][0]["status"], "mismatch")
        self.assertIn("not compatible", inconsistent["results"][0]["interpretation"])
        with self.assertRaisesRegex(ValueError, "omit reported"):
            MODULE.run({"checks": [
                {"id": "grim", "type": "grim_mean", "mean": "2.00", "n": 10, "reported": 0},
            ]})


if __name__ == "__main__":
    unittest.main()
