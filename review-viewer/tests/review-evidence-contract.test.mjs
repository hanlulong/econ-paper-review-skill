import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  isValidReviewEvidence,
  isReviewEvidenceType,
  REVIEW_EVIDENCE_TYPES,
} from "../lib/review-evidence-contract.ts";
import {
  reviewEvidenceText,
  validateReviewLedger,
} from "../lib/review-ledger-contract.ts";

test("viewer evidence kinds stay synchronized with the canonical findings schema", async () => {
  const schema = JSON.parse(await readFile(
    new URL("../../econ-review/assets/findings.schema.json", import.meta.url),
    "utf8",
  ));
  const canonicalTypes = schema.$defs.evidence.properties.type.enum;

  assert.deepEqual([...REVIEW_EVIDENCE_TYPES].sort(), [...canonicalTypes].sort());
  assert.equal(new Set(REVIEW_EVIDENCE_TYPES).size, REVIEW_EVIDENCE_TYPES.length);
  for (const evidenceType of canonicalTypes) assert.equal(isReviewEvidenceType(evidenceType), true);
  assert.equal(isReviewEvidenceType("computation"), true);
  assert.equal(isReviewEvidenceType("unknown_future_type"), false);
  assert.equal(isReviewEvidenceType(null), false);
});

test("accepts a canonical v0.4 computation evidence record", () => {
  const computationEvidence = {
    id: "EVD-CAL-01-A",
    type: "computation",
    representation: "computed_result",
    anchor_id: null,
    computation_id: "CMP-01",
    source_record_id: null,
    source: "reviewer recomputation",
    locator: {
      section: "Calibration",
      page: 18,
      paragraph: null,
      lines: null,
      exhibit: null,
      equation: null,
      file: "evidence/computation-inputs/result.json",
    },
    content: "[Computation] The recomputed value differs from the manuscript value.",
    scope_checked: null,
  };

  assert.equal(isValidReviewEvidence(computationEvidence, "0.4"), true);
  assert.equal(isValidReviewEvidence({ ...computationEvidence, type: "unsupported" }, "0.4"), false);
  assert.equal(isValidReviewEvidence({ ...computationEvidence, representation: undefined }, "0.4"), false);
});

test("loads and renders computation evidence through the viewer ledger contract", async () => {
  const ledger = JSON.parse(await readFile(
    new URL("../../tests/fixtures/valid-review/findings.json", import.meta.url),
    "utf8",
  ));
  const original = ledger.findings[0].evidence[0];
  ledger.findings[0].evidence[0] = {
    ...original,
    type: "computation",
    representation: "computed_result",
    anchor_id: null,
    computation_id: "CMP-01",
    source: "reviewer recomputation",
    content: "[Computation] The recomputed value differs from the manuscript value.",
  };

  const loaded = validateReviewLedger(ledger);
  const evidence = loaded.findings[0].evidence[0];
  assert.equal(evidence.type, "computation");
  assert.equal(reviewEvidenceText(evidence), "[Computation] The recomputed value differs from the manuscript value.");
});

test("keeps the precise checked scope visible when absence evidence also has narrative content", () => {
  const evidence = {
    type: "absence_scope",
    representation: "checked_absence",
    source: "complete manuscript boundary",
    locator: {},
    content: "[Checked absence] No formula was found in the reported result sections.",
    scope_checked: "Sections 4.1-4.3, every figure note, and the full appendix",
  };
  assert.equal(
    reviewEvidenceText(evidence),
    "[Checked absence] No formula was found in the reported result sections.\n\nScope checked: Sections 4.1-4.3, every figure note, and the full appendix",
  );
  assert.equal(reviewEvidenceText({ ...evidence, content: null }), "Scope checked: Sections 4.1-4.3, every figure note, and the full appendix");
});
