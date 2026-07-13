import assert from "node:assert/strict";
import test from "node:test";

import {
  NO_FINALIZATION_RECEIPT,
  expectedFinalizationGates,
  validateFinalizationReceipt,
  verifyReviewFinalization,
} from "../lib/review-finalization.ts";
import { sha256ReviewBytes } from "../lib/local-review-package.ts";

const encoder = new TextEncoder();

async function packageFixture(options = {}) {
  const artifactBytes = new Map([
    ["findings.json", encoder.encode('{"review_id":"review-1"}\n')],
    ["run.json", encoder.encode('{"review_id":"review-1"}\n')],
  ]);
  const artifacts = Object.fromEntries(await Promise.all(Array.from(artifactBytes, async ([path, bytes]) => [
    path,
    await sha256ReviewBytes(bytes),
  ])));
  const receipt = {
    schema_version: "0.3",
    review_id: "review-1",
    contract_version: "0.4",
    artifacts,
    gates: expectedFinalizationGates({ receiptVersion: "0.3", reviewMode: "full", hasPdfSource: false }),
    ...options.receipt,
  };
  return { artifactBytes, receipt, ...options.context };
}

test("verifies receipt identity, current full-review gates, exact inventory, and every artifact hash", async () => {
  const fixture = await packageFixture();
  assert.deepEqual(await verifyReviewFinalization({
    receipt: fixture.receipt,
    reviewId: "review-1",
    reviewContractVersion: "0.4",
    reviewMode: "full",
    hasPdfSource: false,
    artifactBytes: fixture.artifactBytes,
  }), {
    status: "verified",
    receipt_present: true,
    receipt_version: "0.3",
    detail: "Finalization receipt 0.3 and 2 artifact hashes verified for integrity in this viewer. This unsigned receipt does not establish authorship or origin.",
  });
});

test("keeps a package explicitly unverified when no receipt is present", async () => {
  const fixture = await packageFixture();
  assert.deepEqual(await verifyReviewFinalization({
    receipt: null,
    reviewId: "review-1",
    reviewContractVersion: "0.4",
    reviewMode: "full",
    hasPdfSource: false,
    artifactBytes: fixture.artifactBytes,
  }), NO_FINALIZATION_RECEIPT);
});

test("rejects malformed receipts, wrong identity or contract, and unsafe artifact paths", async () => {
  const fixture = await packageFixture();
  assert.throws(() => validateFinalizationReceipt({ ...fixture.receipt, extra: true }), /unsupported structure/);
  assert.throws(() => validateFinalizationReceipt({
    ...fixture.receipt,
    artifacts: { "../findings.json": "a".repeat(64) },
  }), /Unsafe relative path/);
  assert.throws(() => validateFinalizationReceipt({
    ...fixture.receipt,
    artifacts: { "evidence/A.txt": "a".repeat(64), "evidence/a.txt": "b".repeat(64) },
  }), /case-ambiguous/);
  assert.throws(() => validateFinalizationReceipt({
    ...fixture.receipt,
    artifacts: { "evidence/e\u0301.txt": "a".repeat(64) },
  }), /Unsafe relative path/);
  assert.throws(() => validateFinalizationReceipt({
    ...fixture.receipt,
    artifacts: { "evidence/NUL.txt": "a".repeat(64) },
  }), /Unsafe relative path/);
  assert.doesNotThrow(() => validateFinalizationReceipt({
    ...fixture.receipt,
    artifacts: { "evidence/finalization.json": "a".repeat(64) },
  }));
  const prototypeNamedArtifact = validateFinalizationReceipt(JSON.parse(JSON.stringify({
    ...fixture.receipt,
    artifacts: JSON.parse(`{"__proto__":"${"a".repeat(64)}"}`),
  })));
  assert.deepEqual(Object.keys(prototypeNamedArtifact.artifacts), ["__proto__"]);
  for (const context of [
    { reviewId: "other", reviewContractVersion: "0.4" },
    { reviewId: "review-1", reviewContractVersion: "0.3" },
  ]) {
    const result = await verifyReviewFinalization({
      receipt: fixture.receipt,
      reviewId: context.reviewId,
      reviewContractVersion: context.reviewContractVersion,
      reviewMode: "full",
      hasPdfSource: false,
      artifactBytes: fixture.artifactBytes,
    });
    assert.equal(result.status, "unverified");
    assert.equal(result.receipt_present, true);
  }
});

test("detects gate drift, missing or undeclared files, and modified bytes", async () => {
  const fixture = await packageFixture();
  const cases = [
    {
      receipt: { ...fixture.receipt, gates: fixture.receipt.gates.filter((gate) => gate !== "burden_coverage_v02") },
      bytes: fixture.artifactBytes,
      pattern: /gates do not match/,
    },
    {
      receipt: fixture.receipt,
      bytes: new Map([["findings.json", fixture.artifactBytes.get("findings.json")]]),
      pattern: /missing run\.json/,
    },
    {
      receipt: fixture.receipt,
      bytes: new Map([...fixture.artifactBytes, ["notes.txt", encoder.encode("undeclared")]]),
      pattern: /undeclared notes\.txt/,
    },
    {
      receipt: fixture.receipt,
      bytes: new Map([...fixture.artifactBytes, ["evidence/finalization.json", encoder.encode("undeclared")]]),
      pattern: /undeclared evidence\/finalization\.json/,
    },
    {
      receipt: fixture.receipt,
      bytes: new Map([...fixture.artifactBytes, ["evidence/review-actions.json", encoder.encode("undeclared")]]),
      pattern: /undeclared evidence\/review-actions\.json/,
    },
    {
      receipt: fixture.receipt,
      bytes: new Map([...fixture.artifactBytes, ["run.json", encoder.encode("changed")]]),
      pattern: /does not match its declared SHA-256 hash/,
    },
  ];
  for (const item of cases) {
    const result = await verifyReviewFinalization({
      receipt: item.receipt,
      reviewId: "review-1",
      reviewContractVersion: "0.4",
      reviewMode: "full",
      hasPdfSource: false,
      artifactBytes: item.bytes,
    });
    assert.equal(result.status, "unverified");
    assert.match(result.detail, item.pattern);
  }
});

test("verifies versioned quick/full and PDF gate contracts without accepting extra claims", () => {
  assert.deepEqual(expectedFinalizationGates({ receiptVersion: "0.1", reviewMode: "full", hasPdfSource: false }), [
    "source_integrity", "structured_verification", "report_generation", "fix_plan_generation", "contract_validation",
  ]);
  assert.deepEqual(expectedFinalizationGates({ receiptVersion: "0.2", reviewMode: "full", hasPdfSource: true }), [
    "source_integrity", "source_ingestion", "structured_verification", "structured_audit_v02", "report_generation", "fix_plan_generation", "contract_validation",
  ]);
  assert.deepEqual(expectedFinalizationGates({ receiptVersion: "0.3", reviewMode: "quick", hasPdfSource: false }), [
    "source_integrity", "structured_verification", "report_generation", "fix_plan_generation", "contract_validation",
  ]);
  assert.throws(() => expectedFinalizationGates({ receiptVersion: "0.3", reviewMode: "other", hasPdfSource: false }), /full or quick/);
});
