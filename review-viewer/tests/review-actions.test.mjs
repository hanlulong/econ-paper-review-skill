import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

// The repository test command enables Node's TypeScript stripping. Import the
// real module graph so relative dependencies (for example strict-json.ts) are
// exercised exactly as they are in the application.
const actions = await import("../lib/review-actions.ts");
const actionSchema = JSON.parse(await readFile(new URL("../../econ-review/assets/review-actions.schema.json", import.meta.url), "utf8"));
const T0 = "2026-07-12T12:00:00.000Z";
const T1 = "2026-07-12T12:05:00.000Z";
const T2 = "2026-07-12T12:10:00.000Z";
const SHA = "a".repeat(64);

function entry(findingId = "IDENT-01", disposition = "ready_for_recheck") {
  return {
    finding_id: findingId,
    disposition,
    response_note: "Re-estimated on the full randomized sample.",
    changed_locations: ["Section 4", "Table 3"],
    updated_at: T1,
    status_history: [
      { disposition: "open", at: T0 },
      { disposition, at: T1 },
    ],
  };
}

function payload(overrides = {}) {
  return {
    schema_version: "0.1",
    kind: "econ-review-actions",
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    source_manuscripts: [{ path: "paper.md", sha256: SHA }],
    exported_at: T2,
    entries: [entry()],
    ...overrides,
  };
}

test("generated payload round-trips without losing entry timestamps or history", () => {
  const first = entry("WRITING-02", "challenged");
  const second = entry("IDENT-01", "ready_for_recheck");
  const generated = actions.generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    source_manuscripts: [{ path: "paper.md", sha256: SHA }],
    exported_at: T2,
    entries: { "WRITING-02": first, "IDENT-01": second },
  });
  assert.deepEqual(generated.entries.map((value) => value.finding_id), ["IDENT-01", "WRITING-02"]);
  assert.equal(generated.entries[1].updated_at, T1);
  assert.deepEqual(generated.entries[1].status_history, first.status_history);
  assert.deepEqual(actions.parseReviewActions(JSON.stringify(generated)), generated);
  assert.deepEqual(Object.keys(generated).sort(), [...actionSchema.required].sort());
  assert.deepEqual(Object.keys(generated.entries[0]).sort(), [...actionSchema.$defs.entry.required, "events"].sort());
  assert.ok(actionSchema.properties.schema_version.enum.includes(generated.schema_version));
  assert.equal(generated.schema_version, "0.3");
  assert.equal(generated.kind, actionSchema.properties.kind.const);
  assert.ok(actionSchema.$defs.entry.properties.disposition.enum.includes(generated.entries[0].disposition));
});

test("portable source provenance omits local directories and disambiguates duplicate basenames", () => {
  const sources = actions.privacySafeSourceManuscripts([
    { path: "/Users/researcher/Secret Project/paper.md", sha256: SHA },
    { path: "C:\\Clients\\Confidential\\paper.md", sha256: null },
    { path: "/private/appendix.pdf", sha256: null },
  ]);
  assert.deepEqual(sources, [
    { path: "source-1-paper.md", sha256: SHA },
    { path: "source-2-paper.md", sha256: null },
    { path: "appendix.pdf", sha256: null },
  ]);
  const rendered = JSON.stringify(sources);
  assert.doesNotMatch(rendered, /Users|Secret Project|Clients|Confidential|private/);
});

test("portable source provenance normalizes unsafe local filename details", () => {
  assert.deepEqual(actions.privacySafeSourceManuscripts([
    { path: "/private/draft:e\u0301conomie.md.", sha256: SHA },
    { path: "/private/..", sha256: null },
    { path: "/private/NUL.txt", sha256: null },
  ]), [
    { path: "draft-économie.md", sha256: SHA },
    { path: "manuscript-2", sha256: null },
    { path: "manuscript-3", sha256: null },
  ]);
});

test("legacy addressed and parked statuses migrate to external dispositions", () => {
  const migrated = actions.migrateLegacyWorkspace({
    schema_version: 1,
    review_id: "review-1",
    review_fingerprint: "ledger-v1",
    exported_at: T1,
    findings: {
      "IDENT-01": { status: "addressed", note: "Implemented." },
      "WRITING-02": { status: "parked", note: "Will explain why." },
      "TABLE-03": { status: "open", note: "" },
    },
  }, T2);
  assert.equal(migrated["IDENT-01"].disposition, "ready_for_recheck");
  assert.equal(migrated["WRITING-02"].disposition, "deferred");
  assert.equal(migrated["TABLE-03"].disposition, "open");
  assert.equal(migrated["IDENT-01"].response_note, "Implemented.");
  assert.equal(migrated["IDENT-01"].updated_at, T1, "legacy exported_at should be preserved");
  assert.deepEqual(migrated["WRITING-02"].status_history, [{ disposition: "deferred", at: T1 }]);
});

test("legacy addressed state without an explanation migrates conservatively to open", () => {
  const migrated = actions.migrateLegacyWorkspace({
    "IDENT-01": { status: "addressed", note: "" },
  }, T1);
  assert.equal(migrated["IDENT-01"].disposition, "open");
  assert.deepEqual(migrated["IDENT-01"].status_history, [{ disposition: "open", at: T1 }]);
});

test("strict parsing rejects unsupported fields and internally inconsistent entries", () => {
  assert.throws(
    () => actions.parseReviewActions({ ...payload(), extra: true }),
    /unsupported fields: extra/,
  );
  assert.throws(
    () => actions.parseReviewActions(payload({ entries: [entry(), entry()] })),
    /unique finding IDs/,
  );
  assert.throws(
    () => actions.parseReviewActions(payload({ exported_at: "yesterday" })),
    /RFC 3339/,
  );
  assert.throws(
    () => actions.parseReviewActions(payload({ exported_at: "2026-02-30T12:00:00Z" })),
    /RFC 3339/,
  );
  assert.throws(
    () => actions.parseReviewActions(payload({
      source_manuscripts: [
        { path: "paper.md", sha256: SHA },
        { path: "paper.md", sha256: null },
      ],
    })),
    /unique paths/,
  );
  const afterExport = entry();
  afterExport.updated_at = "2026-07-12T12:15:00.000Z";
  assert.throws(
    () => actions.parseReviewActions(payload({ exported_at: T2, entries: [afterExport] })),
    /cannot be later than exported_at/,
  );
  const wrongHistory = entry();
  wrongHistory.disposition = "challenged";
  assert.throws(
    () => actions.parseReviewActions(payload({ entries: [wrongHistory] })),
    /must match the final status_history entry/,
  );
  const duplicateLocation = entry();
  duplicateLocation.changed_locations = ["Table 3", "Table 3"];
  assert.throws(
    () => actions.parseReviewActions(payload({ entries: [duplicateLocation] })),
    /must not contain duplicates/,
  );
  assert.throws(() => actions.parseReviewActions("{"), /invalid JSON/);
  assert.throws(
    () => actions.parseReviewActions(payload({ source_review_id: " review-1" })),
    /source_review_id must be trimmed/,
  );
  assert.throws(
    () => actions.parseReviewActions(payload({ source_manuscripts: [{ path: "paper.md ", sha256: SHA }] })),
    /source_manuscripts\[0\]\.path must be trimmed/,
  );
  for (const path of ["../paper.md", "C:/paper.md", "paper.md.", "e\u0301conomie.md", "bad\u0000name.md", "NUL.txt", "evidence/COM1.json"]) {
    assert.throws(
      () => actions.parseReviewActions(payload({ source_manuscripts: [{ path, sha256: SHA }] })),
      /canonical portable relative path/,
    );
  }
  assert.throws(
    () => actions.parseReviewActions(payload({ source_manuscripts: [
      { path: "Paper.md", sha256: SHA }, { path: "paper.md", sha256: SHA },
    ] })),
    /case-unambiguous/,
  );
  const untrimmedLocation = entry();
  untrimmedLocation.changed_locations = [" Section 4"];
  assert.throws(
    () => actions.parseReviewActions(payload({ entries: [untrimmedLocation] })),
    /changed_locations\[0\] must be trimmed/,
  );
  assert.throws(() => actions.generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    exported_at: T2,
    entries: { "WRONG-99": entry("IDENT-01") },
  }), /map key WRONG-99 does not match/);
});

test("reconciliation applies only exact overlapping finding IDs", () => {
  const source = payload({
    entries: [entry("IDENT-01"), entry("WRITING-02", "challenged"), entry("OLD-99", "deferred")],
  });
  const result = actions.reconcileReviewActions(source, {
    review_id: "review-1",
    review_fingerprint: "ledger-v1",
    finding_ids: ["IDENT-01", "WRITING-02", "NEW-03"],
  });
  assert.deepEqual(result.matched_finding_ids, ["IDENT-01", "WRITING-02"]);
  assert.deepEqual(result.unmatched_entry_ids, ["OLD-99"]);
  assert.deepEqual(result.untouched_finding_ids, ["NEW-03"]);
  assert.deepEqual(Object.keys(result.entries), ["IDENT-01", "WRITING-02"]);
  assert.deepEqual(result.warnings.map((warning) => warning.code), ["unmatched_entries"]);

  assert.throws(() => actions.reconcileReviewActions(payload(), {
    review_id: "review-1",
    review_fingerprint: "ledger-v1",
    finding_ids: ["Ident-01"],
  }), /exact canonical finding ID/);
});

test("status history is append-only and note-only changes preserve it", () => {
  const opened = actions.updateReviewAction(undefined, "IDENT-01", {}, T0);
  const ready = actions.updateReviewAction(opened, "IDENT-01", {
    disposition: "ready_for_recheck",
    changed_locations: ["Appendix Table A4"],
  }, T1);
  const noted = actions.updateReviewAction(ready, "IDENT-01", {
    response_note: "Added the requested specification.",
    changed_locations: ["Appendix Table A4"],
  }, T2);
  assert.deepEqual(ready.status_history, [
    { disposition: "open", at: T0 },
    { disposition: "ready_for_recheck", at: T1 },
  ]);
  assert.deepEqual(noted.status_history, ready.status_history);
  assert.equal(noted.updated_at, T2);
  assert.equal(noted.response_note, "Added the requested specification.");
  assert.deepEqual(noted.changed_locations, ["Appendix Table A4"]);
  assert.deepEqual(noted.events.map((event) => event.type), ["disposition_changed", "disposition_changed", "note_revised"]);
  assert.equal(noted.events[2].parent_event_id, noted.events[1].event_id);
  assert.throws(
    () => actions.updateReviewAction(noted, "IDENT-01", { disposition: "open" }, T0),
    /cannot move backwards/,
  );
});

test("independently initialized findings receive globally unique action events", () => {
  const first = actions.updateReviewAction(undefined, "IDENT-01", { disposition: "ready_for_recheck" }, T1);
  const second = actions.updateReviewAction(undefined, "WRITING-02", { disposition: "challenged" }, T1);
  const generated = actions.generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    exported_at: T2,
    entries: [first, second],
  });
  assert.equal(new Set(generated.entries.flatMap((item) => item.events.map((event) => event.event_id))).size, 4);
});

test("undoing a status appends a reversal instead of rewriting action history", () => {
  const opened = actions.updateReviewAction(undefined, "IDENT-01", {}, T0);
  const deferred = actions.updateReviewAction(opened, "IDENT-01", { disposition: "deferred" }, T1);
  const restored = actions.updateReviewAction(deferred, "IDENT-01", { disposition: "open" }, T2, { type: "reversed" });
  assert.equal(restored.disposition, "open");
  assert.deepEqual(restored.status_history, [
    { disposition: "open", at: T0 },
    { disposition: "deferred", at: T1 },
    { disposition: "open", at: T2 },
  ]);
  assert.equal(restored.events.at(-1).type, "reversed");
});

test("recheck and challenge dispositions accept an optional author note", () => {
  const opened = actions.updateReviewAction(undefined, "IDENT-01", {}, T0);
  const ready = actions.updateReviewAction(opened, "IDENT-01", { disposition: "ready_for_recheck" }, T1);
  assert.equal(ready.disposition, "ready_for_recheck");
  assert.equal(ready.response_note, "");
  const challenged = actions.updateReviewAction(opened, "IDENT-01", { disposition: "challenged" }, T1);
  assert.equal(challenged.disposition, "challenged");
  assert.equal(challenged.response_note, "");
});

test("legacy v0.1 imports retain their original disposition evidence rule", () => {
  const legacyReady = entry("IDENT-01", "ready_for_recheck");
  legacyReady.response_note = "";
  legacyReady.changed_locations = [];
  assert.throws(
    () => actions.parseReviewActions(payload({ schema_version: "0.1", entries: [legacyReady] })),
    /under action schema v0\.1/,
  );
});

test("a changed fingerprint warns but preserves exact-ID next-round reconciliation", () => {
  const result = actions.reconcileReviewActions(payload(), {
    review_id: "review-1",
    review_fingerprint: "ledger-v2",
    finding_ids: ["IDENT-01", "NEW-03"],
  });
  assert.equal(result.review_id_matches, true);
  assert.equal(result.fingerprint_matches, false);
  assert.deepEqual(result.matched_finding_ids, ["IDENT-01"]);
  assert.deepEqual(result.untouched_finding_ids, ["NEW-03"]);
  assert.deepEqual(result.warnings.map((warning) => warning.code), ["fingerprint_mismatch"]);
});

test("a changed review ID is warned and never applies coincidentally matching IDs", () => {
  const result = actions.reconcileReviewActions(payload(), {
    review_id: "different-review",
    review_fingerprint: "ledger-v1",
    finding_ids: ["IDENT-01", "NEW-03"],
  });
  assert.equal(result.review_id_matches, false);
  assert.equal(result.fingerprint_matches, true);
  assert.deepEqual(result.entries, {});
  assert.deepEqual(result.matched_finding_ids, []);
  assert.deepEqual(result.unmatched_entry_ids, ["IDENT-01"]);
  assert.deepEqual(result.untouched_finding_ids, ["IDENT-01", "NEW-03"]);
  assert.deepEqual(result.warnings.map((warning) => warning.code), ["review_id_mismatch", "unmatched_entries"]);
});

test("action merge applies new IDs and newer imports that extend current history", () => {
  const current = actions.generateReviewActionsPayload({ source_review_id: "review-1", source_review_fingerprint: "ledger-v1", exported_at: T2, entries: [entry("IDENT-01", "ready_for_recheck")] }).entries[0];
  const newer = actions.updateReviewAction(current, "IDENT-01", { disposition: "challenged", response_note: "The appendix already reports this comparison." }, T2);
  const added = actions.generateReviewActionsPayload({ source_review_id: "review-1", source_review_fingerprint: "ledger-v1", exported_at: T2, entries: [entry("NEW-03", "deferred")] }).entries[0];
  const result = actions.mergeReviewActionEntries(
    { "IDENT-01": current },
    { "IDENT-01": newer, "NEW-03": added },
  );
  assert.deepEqual(result.applied_finding_ids, ["IDENT-01", "NEW-03"]);
  assert.deepEqual(result.stale_finding_ids, []);
  assert.deepEqual(result.conflict_finding_ids, []);
  assert.deepEqual(result.entries["IDENT-01"], newer);
  assert.deepEqual(result.entries["IDENT-01"].status_history, newer.status_history);
  assert.deepEqual(result.entries["NEW-03"], added);
});

test("action merge accepts identical imports and ignores older prefix-history imports", () => {
  const old = actions.updateReviewAction(undefined, "IDENT-01", { response_note: "Earlier note" }, T0);
  const current = actions.updateReviewAction(old, "IDENT-01", { disposition: "ready_for_recheck", response_note: "Re-estimated on the full randomized sample." }, T1);
  const identical = actions.mergeReviewActionEntries({ "IDENT-01": current }, { "IDENT-01": current });
  assert.deepEqual(identical.applied_finding_ids, ["IDENT-01"]);
  assert.deepEqual(identical.conflict_finding_ids, []);
  assert.deepEqual(identical.entries["IDENT-01"], current);

  const stale = actions.mergeReviewActionEntries({ "IDENT-01": current }, { "IDENT-01": old });
  assert.deepEqual(stale.applied_finding_ids, []);
  assert.deepEqual(stale.stale_finding_ids, ["IDENT-01"]);
  assert.deepEqual(stale.conflict_finding_ids, []);
  assert.deepEqual(stale.entries["IDENT-01"], current, "newer current work must not be overwritten");
});

test("equal-timestamp divergent action content is a conflict", () => {
  const current = actions.generateReviewActionsPayload({ source_review_id: "review-1", source_review_fingerprint: "ledger-v1", exported_at: T2, entries: [entry("IDENT-01", "ready_for_recheck")] }).entries[0];
  const divergent = actions.updateReviewAction(current, "IDENT-01", { response_note: "A different response at the same instant." }, T1);
  const result = actions.mergeReviewActionEntries({ "IDENT-01": current }, { "IDENT-01": divergent });
  assert.deepEqual(result.applied_finding_ids, []);
  assert.deepEqual(result.stale_finding_ids, []);
  assert.deepEqual(result.conflict_finding_ids, ["IDENT-01"]);
  assert.deepEqual(result.entries["IDENT-01"], current);
  assert.deepEqual(result.warnings, [{
    code: "equal_timestamp_divergence",
    finding_id: "IDENT-01",
    message: "IDENT-01 has different action content at the same updated_at timestamp; current work was kept.",
  }]);
});

test("non-prefix histories conflict instead of truncating or forking history", () => {
  const current = actions.generateReviewActionsPayload({ source_review_id: "review-1", source_review_fingerprint: "ledger-v1", exported_at: T2, entries: [entry("IDENT-01", "ready_for_recheck")] }).entries[0];
  const forkBase = actions.updateReviewAction(undefined, "IDENT-01", { response_note: "Separate starting point" }, T0);
  const newerFork = actions.updateReviewAction(forkBase, "IDENT-01", { disposition: "challenged", response_note: "Forked response" }, T2);
  const newerConflict = actions.mergeReviewActionEntries(
    { "IDENT-01": current },
    { "IDENT-01": newerFork },
  );
  assert.deepEqual(newerConflict.conflict_finding_ids, ["IDENT-01"]);
  assert.equal(newerConflict.warnings[0].code, "non_prefix_history");
  assert.deepEqual(newerConflict.entries["IDENT-01"], current);

  const olderFork = actions.updateReviewAction(undefined, "IDENT-01", { disposition: "challenged", response_note: "Older fork" }, T0);
  const olderConflict = actions.mergeReviewActionEntries(
    { "IDENT-01": current },
    { "IDENT-01": olderFork },
  );
  assert.deepEqual(olderConflict.stale_finding_ids, []);
  assert.deepEqual(olderConflict.conflict_finding_ids, ["IDENT-01"]);
  assert.equal(olderConflict.warnings[0].code, "non_prefix_history");
  assert.deepEqual(olderConflict.entries["IDENT-01"], current);
});
