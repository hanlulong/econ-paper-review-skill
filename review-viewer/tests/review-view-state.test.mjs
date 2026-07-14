import assert from "node:assert/strict";
import test from "node:test";

import { reviewLedgerFingerprint, sha256Hex } from "../lib/review-fingerprint.ts";
import {
  comparePaperPosition,
  parseReviewUrlState,
  sortReviewFindings,
  writeReviewUrlState,
} from "../lib/review-view-state.ts";
import { validateActivatedBurdens } from "../lib/review-runtime-contracts.ts";
import { readFile } from "node:fs/promises";

test("uses a canonical SHA-256 digest for review fingerprints", () => {
  assert.equal(sha256Hex("abc"), "ba7816bf8f01cfea414140de5dae2223b00361a396177a9cb410ff61f20015ad");
  assert.match(reviewLedgerFingerprint([{ id: "ITEM-01" }]), /^[a-f0-9]{64}$/);
  assert.equal(reviewLedgerFingerprint([{ id: "ITEM-01" }]), reviewLedgerFingerprint([{ id: "ITEM-01" }]));
});

test("paper ordering prefers canonical positions and safely falls back to locators", () => {
  const base = (id, rank, section, order) => ({
    id, importance_rank: rank, paper_position: order === undefined ? undefined : { ordinal: order, source_id: "SRC-01", anchor_id: `ANC-${order}`, section },
    evidence: [{ locator: { section } }],
  });
  const values = [base("ITEM-03", 1, "10", 30), base("ITEM-01", 3, "2", 10), base("ITEM-02", 2, "1", 20)];
  assert.deepEqual(values.sort(comparePaperPosition).map((item) => item.id), ["ITEM-01", "ITEM-02", "ITEM-03"]);
  const legacy = [base("OLD-10", 1, "Section 10"), base("OLD-02", 2, "Section 2")];
  assert.deepEqual(legacy.sort(comparePaperPosition).map((item) => item.id), ["OLD-02", "OLD-10"]);
});

test("priority ordering groups severity before source location and preserves original ties", () => {
  const finding = (id, severity, ordinal, importanceRank) => ({
    id,
    severity,
    importance_rank: importanceRank,
    paper_position: { ordinal, source_id: "SRC-01", anchor_id: `ANC-${ordinal}` },
    evidence: [{ locator: { section: String(ordinal) } }],
  });
  const input = [
    finding("MINOR-EARLY", "minor", 1, 1),
    finding("MAJOR-LATE", "major", 20, 2),
    finding("CRITICAL-LATE", "critical", 50, 3),
    finding("MAJOR-TIE-Z", "major", 5, 99),
    finding("MAJOR-TIE-A", "major", 5, 1),
    finding("INFO-EARLY", "info", 0, 4),
    finding("MAJOR-EARLY", "major", 2, 5),
  ];

  assert.deepEqual(sortReviewFindings(input, "priority").map((item) => item.id), [
    "CRITICAL-LATE",
    "MAJOR-EARLY",
    "MAJOR-TIE-Z",
    "MAJOR-TIE-A",
    "MAJOR-LATE",
    "MINOR-EARLY",
    "INFO-EARLY",
  ]);
  assert.deepEqual(input.map((item) => item.id), [
    "MINOR-EARLY", "MAJOR-LATE", "CRITICAL-LATE", "MAJOR-TIE-Z",
    "MAJOR-TIE-A", "INFO-EARLY", "MAJOR-EARLY",
  ], "priority sorting must not mutate the canonical ledger order");
});

test("default reviewer order is severity-first even when stored ranks are stale", () => {
  const finding = (id, severity, ordinal, importanceRank, sourceId = "SRC-01", decisionRole = "revision_value") => ({
    id,
    severity,
    decision_role: decisionRole,
    importance_rank: importanceRank,
    paper_position: { ordinal, source_id: sourceId, anchor_id: `${sourceId}-${ordinal}` },
    evidence: [{ locator: { file: sourceId, section: String(ordinal) } }],
  });
  const input = [
    finding("SECOND-SOURCE", "critical", 1, 1, "SRC-02"),
    finding("FIRST-SOURCE-LATE", "minor", 20, 3),
    finding("FIRST-SOURCE-EARLY", "major", 2, 2),
  ];
  assert.deepEqual(sortReviewFindings(input, "importance").map((item) => item.id), [
    "SECOND-SOURCE", "FIRST-SOURCE-EARLY", "FIRST-SOURCE-LATE",
  ]);
  assert.deepEqual(sortReviewFindings(input, "paper").map((item) => item.id), [
    "FIRST-SOURCE-EARLY", "FIRST-SOURCE-LATE", "SECOND-SOURCE",
  ]);
});

test("default reviewer order uses publication relevance within a severity tier", () => {
  const finding = (id, decisionRole, importanceRank) => ({
    id,
    severity: "major",
    decision_role: decisionRole,
    importance_rank: importanceRank,
    evidence: [{ locator: { section: "1" } }],
  });
  const input = [
    finding("POLISH-FIRST-RANK", "polish", 1),
    finding("DISPOSITIVE-STALE-RANK", "potentially_dispositive", 99),
    finding("REVISION-MIDDLE", "revision_value", 2),
  ];
  assert.deepEqual(sortReviewFindings(input, "importance").map((item) => item.id), [
    "DISPOSITIVE-STALE-RANK", "REVISION-MIDDLE", "POLISH-FIRST-RANK",
  ]);
});

test("canonical reviewer rank is the URL default while alternate orders remain selectable", () => {
  assert.equal(parseReviewUrlState("").order, "importance");
  assert.equal(parseReviewUrlState("?order=importance").order, "importance");
  assert.equal(parseReviewUrlState("?order=paper").order, "paper");
  assert.equal(parseReviewUrlState("?order=unknown").order, "importance");
  const priorityUrl = writeReviewUrlState(new URL("https://example.test/"), {
    view: "overview", finding: null, document: null, evidence: 0, order: "importance",
    severity: "all", role: "all", status: "all", channel: "all", dimension: "all",
    reviewed: "all", my_priority: "all",
  });
  assert.equal(priorityUrl.searchParams.has("order"), false);
});

test("review URL state round-trips navigation and filters without erasing unrelated parameters", () => {
  const url = writeReviewUrlState(new URL("https://example.test/?review=demo&keep=yes"), {
    view: "comment", finding: "ITEM-02", document: null, evidence: 2, order: "paper",
    severity: "major", role: "all", status: "open", channel: "substance", dimension: "clarity",
    reviewed: "unreviewed", my_priority: "P0",
  });
  assert.equal(url.searchParams.get("review"), "demo");
  assert.equal(url.searchParams.get("keep"), "yes");
  assert.equal(url.searchParams.get("rv"), "1");
  assert.deepEqual(parseReviewUrlState(url.search), {
    view: "comment", finding: "ITEM-02", document: null, evidence: 2, order: "paper",
    severity: "major", role: "all", status: "open", channel: "substance", dimension: "clarity",
    reviewed: "unreviewed", my_priority: "P0",
  });
});

test("revision-plan navigation round-trips without a stale finding selection", () => {
  const url = writeReviewUrlState(new URL("https://example.test/?finding=ITEM-01"), {
    view: "plan", finding: null, document: null, evidence: 0, order: "priority",
    severity: "all", role: "all", status: "all", channel: "all", dimension: "all",
    reviewed: "all", my_priority: "all",
  });
  assert.equal(url.searchParams.has("finding"), false);
  assert.equal(parseReviewUrlState(url.search).view, "plan");
});

test("accepts the object-based v0.4 burden metadata from the bundled fixture", async () => {
  const run = JSON.parse(await readFile(new URL("../../tests/fixtures/valid-review/run.json", import.meta.url), "utf8"));
  const burdens = validateActivatedBurdens(run.activated_burdens);
  assert.equal(burdens.length, run.activated_burdens.length);
  assert.equal(burdens[0].parent_id, run.activated_burdens[0].parent_id);
  assert.ok(burdens.some((burden) => burden.status === "active" && burden.triggers.length));
  assert.ok(burdens.some((burden) => burden.status === "not_applicable" && burden.nonactivation_reason));
  assert.throws(() => validateActivatedBurdens([{ ...burdens[0], triggers: [], nonactivation_reason: null }]), /need a trigger/);
});

test("accepts exactly the burden parents declared by the canonical run schema", async () => {
  const schema = JSON.parse(await readFile(new URL("../../econ-review/assets/run.schema.json", import.meta.url), "utf8"));
  const parentIds = schema.$defs.burden.properties.parent_id.enum.filter((value) => value !== null);
  assert.ok(parentIds.length > 0);

  for (const [index, parentId] of parentIds.entries()) {
    const [burden] = validateActivatedBurdens([{
      id: `schema_parent_${index}`,
      parent_id: parentId,
      object_type: "claim",
      status: "active",
      activation_basis: "observed",
      triggers: [{ kind: "claim", ref: "CLM-01", rationale: "Schema parity check." }],
      nonactivation_reason: null,
    }]);
    assert.equal(burden.parent_id, parentId);
  }

  assert.throws(() => validateActivatedBurdens([{
    id: "unsupported_parent",
    parent_id: "measurement",
    object_type: "measurement",
    status: "active",
    activation_basis: "observed",
    triggers: [{ kind: "claim", ref: "CLM-01", rationale: "Negative parity check." }],
    nonactivation_reason: null,
  }]), /parent_id is unsupported/);
});

test("accepts every burden object type declared by the canonical run schema", async () => {
  const schema = JSON.parse(await readFile(new URL("../../econ-review/assets/run.schema.json", import.meta.url), "utf8"));
  const objectTypes = schema.$defs.burden.properties.object_type.enum;
  assert.ok(Array.isArray(objectTypes) && objectTypes.length > 0);

  for (const [index, objectType] of objectTypes.entries()) {
    const [burden] = validateActivatedBurdens([{
      id: `schema_object_${index}`,
      object_type: objectType,
      status: "active",
      activation_basis: "observed",
      triggers: [{ kind: "claim", ref: "CLM-01", rationale: "Schema parity check." }],
      nonactivation_reason: null,
    }]);
    assert.equal(burden.object_type, objectType);
  }

  assert.throws(() => validateActivatedBurdens([{
    id: "unsupported_object",
    object_type: "unsupported",
    status: "active",
    activation_basis: "observed",
    triggers: [{ kind: "claim", ref: "CLM-01", rationale: "Negative parity check." }],
    nonactivation_reason: null,
  }]), /object_type is unsupported/);
});
