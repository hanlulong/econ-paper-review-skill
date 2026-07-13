import assert from "node:assert/strict";
import test from "node:test";

import { reviewLedgerFingerprint, sha256Hex } from "../lib/review-fingerprint.ts";
import { comparePaperPosition, parseReviewUrlState, writeReviewUrlState } from "../lib/review-view-state.ts";
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

test("review URL state round-trips navigation and filters without erasing unrelated parameters", () => {
  const url = writeReviewUrlState(new URL("https://example.test/?review=demo&keep=yes"), {
    view: "comment", finding: "ITEM-02", document: null, evidence: 2, order: "paper",
    severity: "major", role: "all", status: "open", channel: "substance", dimension: "clarity",
  });
  assert.equal(url.searchParams.get("review"), "demo");
  assert.equal(url.searchParams.get("keep"), "yes");
  assert.equal(url.searchParams.get("rv"), "1");
  assert.deepEqual(parseReviewUrlState(url.search), {
    view: "comment", finding: "ITEM-02", document: null, evidence: 2, order: "paper",
    severity: "major", role: "all", status: "open", channel: "substance", dimension: "clarity",
  });
});

test("accepts the object-based v0.4 burden metadata from the bundled fixture", async () => {
  const run = JSON.parse(await readFile(new URL("../../tests/fixtures/valid-review/run.json", import.meta.url), "utf8"));
  const burdens = validateActivatedBurdens(run.activated_burdens);
  assert.equal(burdens.length, run.activated_burdens.length);
  assert.ok(burdens.some((burden) => burden.status === "active" && burden.triggers.length));
  assert.ok(burdens.some((burden) => burden.status === "not_applicable" && burden.nonactivation_reason));
  assert.throws(() => validateActivatedBurdens([{ ...burdens[0], triggers: [], nonactivation_reason: null }]), /need a trigger/);
});
