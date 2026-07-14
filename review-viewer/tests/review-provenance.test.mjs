import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import {
  indexReviewComputations,
  isSafeComputationArtifactPath,
  validateReviewComputationLinks,
  validateReviewComputations,
} from "../lib/review-computations-contract.ts";
import { sha256Hex } from "../lib/review-fingerprint.ts";
import { validateReviewLedger } from "../lib/review-ledger-contract.ts";
import {
  alignContextToWordBoundaries,
  conciseSourceAnchorLabel,
  exactAnchorExcerpt,
  sourceAnchorPageLabel,
  stripGeneratedAnchorComments,
} from "../lib/review-manuscript-context.ts";

const computation = {
  id: "CMP-01",
  finding_ids: ["LOGIC-01"],
  input_anchor_ids: ["ANC-01", "ANC-02"],
  tool: "deterministic algebra check",
  method: "Evaluate the equality case under both available actions.",
  result: "Both actions return the same payoff at equality.",
  artifact_path: "evidence/computation-inputs/boundary-check.json",
  artifact_sha256: "a".repeat(64),
  tolerance: "exact symbolic equality",
};

const computationEvidence = {
  id: "EVD-LOGIC-01-C",
  type: "computation",
  representation: "computed_result",
  anchor_id: null,
  computation_id: "CMP-01",
  source_record_id: null,
  source: "reviewer computation",
  locator: {},
  content: "[Computation] Both actions return the same payoff at equality.",
  scope_checked: null,
};

const linkedLedger = {
  schema_version: "0.4",
  review_id: "synthetic-valid-001",
  findings: [{ id: "LOGIC-01", evidence: [computationEvidence] }],
};

const sourceManifest = {
  review_id: "synthetic-valid-001",
  anchors: [{ id: "ANC-01" }, { id: "ANC-02" }],
};

test("validates and indexes canonical computation provenance without opening its artifact", () => {
  const checked = validateReviewComputations({
    schema_version: "0.1",
    review_id: "synthetic-valid-001",
    computations: [computation],
  });
  assert.equal(checked.computations[0].method, computation.method);
  assert.equal(indexReviewComputations(checked)["CMP-01"].artifact_path, computation.artifact_path);
  assert.equal(isSafeComputationArtifactPath(computation.artifact_path), true);
  assert.equal(isSafeComputationArtifactPath("../../private/result.json"), false);
  assert.equal(isSafeComputationArtifactPath("/private/reviewer/result.json"), false);
  assert.equal(isSafeComputationArtifactPath("https://example.test/result.json"), false);
});

test("rejects duplicate computation IDs and malformed provenance metadata", () => {
  const base = { schema_version: "0.1", review_id: "synthetic-valid-001", computations: [computation] };
  assert.throws(() => validateReviewComputations({ ...base, computations: [computation, computation] }), /duplicate computation/);
  assert.throws(() => validateReviewComputations({ ...base, computations: [{ ...computation, input_anchor_ids: ["ANC-01", "ANC-01"] }] }), /duplicate input anchors/);
  assert.throws(() => validateReviewComputations({ ...base, computations: [{ ...computation, artifact_sha256: "not-a-hash" }] }), /invalid provenance/);
  assert.throws(() => validateReviewComputations({ ...base, computations: [{ ...computation, artifact_path: "../result.json" }] }), /invalid provenance/);
});

test("accepts schema 0.2 finding-linked and audit-only computations", () => {
  const findingLinked = validateReviewComputations({
    schema_version: "0.2",
    review_id: "synthetic-valid-001",
    computations: [{
      ...computation,
      audit_links: [{ kind: "analytical_entry", id: "ANA-ALGEBRA-01" }],
    }],
  });
  assert.doesNotThrow(() => validateReviewComputationLinks(linkedLedger, findingLinked, sourceManifest));

  const auditOnly = validateReviewComputations({
    schema_version: "0.2",
    review_id: "synthetic-valid-001",
    computations: [{
      ...computation,
      finding_ids: [],
      audit_links: [{ kind: "magnitude_assessment", id: "MAG-01" }],
    }],
  });
  assert.doesNotThrow(() => validateReviewComputationLinks(
    { ...linkedLedger, findings: [{ id: "LOGIC-01", evidence: [] }] },
    auditOnly,
    sourceManifest,
  ));

  assert.throws(() => validateReviewComputations({
    schema_version: "0.2",
    review_id: "synthetic-valid-001",
    computations: [{ ...computation, finding_ids: [], audit_links: [] }],
  }), /must link a finding or audit row/);
  assert.throws(() => validateReviewComputations({
    schema_version: "0.2",
    review_id: "synthetic-valid-001",
    computations: [{
      ...computation,
      audit_links: [
        { kind: "analytical_entry", id: "ANA-ALGEBRA-01" },
        { kind: "analytical_entry", id: "ANA-ALGEBRA-01" },
      ],
    }],
  }), /duplicate audit links/);
});

test("checks computation review, finding, evidence, and input-anchor joins", () => {
  const checked = validateReviewComputations({ schema_version: "0.1", review_id: linkedLedger.review_id, computations: [computation] });
  assert.doesNotThrow(() => validateReviewComputationLinks(linkedLedger, checked, sourceManifest));
  assert.throws(() => validateReviewComputationLinks(linkedLedger, null, sourceManifest), /computations\.json is missing/);
  assert.throws(() => validateReviewComputationLinks(linkedLedger, { ...checked, review_id: "another-review" }, sourceManifest), /different review ID/);
  assert.throws(() => validateReviewComputationLinks(linkedLedger, { ...checked, computations: [{ ...computation, finding_ids: ["OTHER-01"] }] }, sourceManifest), /does not declare its link/);
  assert.throws(() => validateReviewComputationLinks(linkedLedger, { ...checked, computations: [{ ...computation, input_anchor_ids: ["ANC-99"] }] }, sourceManifest), /unknown input anchor/);
  assert.throws(() => validateReviewComputationLinks({ ...linkedLedger, findings: [{ id: "LOGIC-01", evidence: [{ ...computationEvidence, computation_id: "CMP-99" }] }] }, checked, sourceManifest), /unknown computation/);
});

test("composite comparison evidence validates and each selected anchor yields its own exact manuscript excerpt", async () => {
  const [ledgerValue, manifestValue, manuscript] = await Promise.all([
    readFile(new URL("../../tests/fixtures/valid-review/findings.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../../tests/fixtures/valid-review/evidence/source-manifest.json", import.meta.url), "utf8").then(JSON.parse),
    readFile(new URL("../../tests/fixtures/valid-review/synthetic-paper.md", import.meta.url), "utf8"),
  ]);
  ledgerValue.findings[0].evidence[0] = {
    ...ledgerValue.findings[0].evidence[0],
    representation: "composite_comparison",
    anchor_id: null,
    anchor_ids: ["ANC-01", "ANC-02"],
    content: "[Reviewer comparison] The uniqueness statement and its summary are inconsistent at equality.",
  };
  const ledger = validateReviewLedger(ledgerValue);
  assert.deepEqual(ledger.findings[0].evidence[0].anchor_ids, ["ANC-01", "ANC-02"]);

  const anchors = Object.fromEntries(manifestValue.anchors.map((anchor) => [anchor.id, anchor]));
  const first = exactAnchorExcerpt(manuscript, anchors["ANC-01"], sha256Hex);
  const second = exactAnchorExcerpt(manuscript, anchors["ANC-02"], sha256Hex);
  assert.equal(first.exact, true);
  assert.equal(second.exact, true);
  assert.notEqual(first.highlight, second.highlight);
  assert.match(first.highlight, /unique for every parameter value/);
  assert.match(second.highlight, /proposition characterize/);
  assert.doesNotMatch(`${first.before}${first.after}${second.before}${second.after}`, /<!--|-->|bbox=|method=pdf_text_layer/);

  ledgerValue.findings[0].evidence[0].anchor_ids = ["ANC-01"];
  assert.throws(() => validateReviewLedger(ledgerValue), /invalid evidence data/);
});

test("source controls abbreviate page locators and context cleanup removes sliced ingestion comments only", () => {
  assert.equal(conciseSourceAnchorLabel(0, "PDF p. 16, bbox 1,2,3,4, block SRC-01-PDF-B0247"), "Source 1 · p. 16");
  assert.equal(sourceAnchorPageLabel("PDF p. 18, bbox 1,2,3,4"), "p. 18");
  assert.equal(sourceAnchorPageLabel("Online appendix, paragraph 2"), null);
  assert.equal(conciseSourceAnchorLabel(1, "Online appendix, paragraph 2"), "Source 2");
  assert.equal(
    stripGeneratedAnchorComments("0247; page=16; bbox=1,2,3,4; method=pdf_text_layer -->\nVisible before.\n<!-- SRC-01-PDF-B0248; page=16"),
    "\nVisible before.\n",
  );
  const manuscript = "<!-- generated -->\nBefore exact HIGHLIGHT after.<!-- trailing";
  const start = manuscript.indexOf("HIGHLIGHT");
  const excerpt = exactAnchorExcerpt(manuscript, {
    id: "ANC-01",
    start_char: start,
    end_char: start + "HIGHLIGHT".length,
    content_sha256: sha256Hex("HIGHLIGHT"),
  }, sha256Hex);
  assert.equal(excerpt.highlight, "HIGHLIGHT", "comment cleanup must not alter the verified span");
  assert.doesNotMatch(`${excerpt.before}${excerpt.after}`, /<!--|-->/);
});

test("bounded manuscript context trims inward at word boundaries without changing the exact anchor", () => {
  const manuscript = "Header wholesale loan rate anchors TARGET and explains macroeconomic volatility in the model.";
  const start = manuscript.indexOf("TARGET");
  const end = start + "TARGET".length;
  const loanStart = manuscript.indexOf("loan");
  const volatilityStart = manuscript.indexOf("volatility");
  const contextBefore = start - (loanStart + 1);
  const contextAfter = volatilityStart + 4 - end;
  const [alignedStart, alignedEnd] = alignContextToWordBoundaries(
    manuscript,
    start - contextBefore,
    end + contextAfter,
  );
  assert.equal(manuscript.slice(alignedStart).startsWith("oan"), false);
  assert.equal(manuscript.slice(0, alignedEnd).endsWith("vola"), false);

  const excerpt = exactAnchorExcerpt(manuscript, {
    id: "ANC-02",
    start_char: start,
    end_char: end,
    content_sha256: sha256Hex("TARGET"),
  }, sha256Hex, contextBefore, contextAfter);
  assert.equal(excerpt.highlight, "TARGET");
  assert.equal(excerpt.before.trimStart().startsWith("oan"), false);
  assert.equal(excerpt.after.trimEnd().endsWith("vola"), false);
  assert.ok(excerpt.before.length <= contextBefore);
  assert.ok(excerpt.after.length <= contextAfter);
});
