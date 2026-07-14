#!/usr/bin/env python3
"""Schema checks for explicit literature-facing claim classification."""

from __future__ import annotations

import copy
import json
import unittest
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker


ROOT = Path(__file__).resolve().parents[1]
SCHEMA = json.loads(
    (ROOT / "econ-review" / "assets" / "claims.schema.json").read_text(encoding="utf-8")
)
PAYLOAD = json.loads(
    (ROOT / "tests" / "fixtures" / "valid-review" / "evidence" / "claims.json").read_text(
        encoding="utf-8"
    )
)
VALIDATOR = Draft202012Validator(SCHEMA, format_checker=FormatChecker())


def errors(payload: dict) -> list[str]:
    return [error.message for error in VALIDATOR.iter_errors(payload)]


class ClaimsLiteratureScopeTests(unittest.TestCase):
    def test_current_claim_inventory_is_explicit(self) -> None:
        self.assertEqual(errors(PAYLOAD), [])

    def test_every_claim_classifies_literature_relevance(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        payload["claim_families"][0].pop("literature_facing")
        self.assertTrue(errors(payload))

    def test_literature_exclusion_requires_a_reason(self) -> None:
        payload = copy.deepcopy(PAYLOAD)
        claim = payload["claim_families"][0]
        claim["literature_facing"] = False
        claim["literature_exclusion_basis"] = None
        self.assertTrue(errors(payload))


if __name__ == "__main__":
    unittest.main()
