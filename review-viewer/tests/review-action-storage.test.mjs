import assert from "node:assert/strict";
import test from "node:test";

import {
  clearBrowserReviewActions,
  persistBrowserReviewActions,
  restoreBrowserReviewActions,
  reviewActionStorageKey,
} from "../lib/review-action-storage.ts";
import { generateReviewActionsPayload, updateReviewAction } from "../lib/review-actions.ts";

class MemoryStorage {
  values = new Map();
  get length() { return this.values.size; }
  key(index) { return Array.from(this.values.keys())[index] ?? null; }
  getItem(key) { return this.values.get(key) ?? null; }
  setItem(key, value) { this.values.set(key, value); }
  removeItem(key) { this.values.delete(key); }
}

function action(findingId, note, at) {
  return updateReviewAction(undefined, findingId, { response_note: note }, at);
}

test("changed-ledger restore preserves the complete prior-fingerprint payload", () => {
  const storage = new MemoryStorage();
  const carried = updateReviewAction(
    action("KEEP-01", "Implemented in Section 2.", "2026-07-12T11:00:00Z"),
    "KEEP-01",
    { disposition: "ready_for_recheck", user_priority: "P0", reviewed: true },
    "2026-07-12T11:15:00Z",
  );
  const prior = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "old-ledger",
    exported_at: "2026-07-12T12:00:00Z",
    entries: [
      carried,
      action("OLD-02", "This prior finding no longer has a current ID.", "2026-07-12T11:30:00Z"),
    ],
  });
  persistBrowserReviewActions(storage, prior);
  const archivedBefore = storage.getItem(reviewActionStorageKey("review-1", "old-ledger"));

  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-1",
    review_fingerprint: "new-ledger",
    finding_ids: ["KEEP-01", "NEW-03"],
  });
  assert.deepEqual(Object.keys(restored.entries), ["KEEP-01"]);
  assert.equal(restored.entries["KEEP-01"].disposition, "open");
  assert.equal(restored.entries["KEEP-01"].reviewed, false);
  assert.equal(restored.entries["KEEP-01"].user_priority, "P0");
  assert.equal(restored.entries["KEEP-01"].response_note, "Implemented in Section 2.");
  assert.deepEqual(restored.rereview_required_finding_ids, ["KEEP-01"]);
  assert.match(restored.warning, /complete prior payload remains archived/i);
  assert.match(restored.warning, /1 action entry does not match/i);
  assert.match(restored.warning, /current comments must be reviewed again/i);
  assert.equal(storage.getItem(reviewActionStorageKey("review-1", "old-ledger")), archivedBefore, "automatic rollover must not rewrite the archived prior round");

  const current = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "new-ledger",
    exported_at: restored.entries["KEEP-01"].updated_at,
    entries: restored.entries,
  });
  persistBrowserReviewActions(storage, current);

  const archivedText = storage.getItem(reviewActionStorageKey("review-1", "old-ledger"));
  assert.ok(archivedText);
  assert.match(archivedText, /OLD-02/);
  assert.ok(storage.getItem(reviewActionStorageKey("review-1", "new-ledger")));
});

test("clears current and legacy snapshots for only the requested review", () => {
  const storage = new MemoryStorage();
  storage.setItem("review-desk:v4:review-1:a", "{}");
  storage.setItem("review-desk:v3:review-1:a", "{}");
  storage.setItem("review-desk:v2:review-1", "{}");
  storage.setItem(`review-desk:v1:review-1:${"a".repeat(64)}`, "{}");
  storage.setItem("review-desk:v3:review-2:a", "{}");
  assert.equal(clearBrowserReviewActions(storage, "review-1"), 4);
  assert.equal(storage.length, 1);
  assert.ok(storage.getItem("review-desk:v3:review-2:a"));
});

test("v3 fingerprint snapshots migrate by exact finding ID into v4 storage", () => {
  const storage = new MemoryStorage();
  const prior = generateReviewActionsPayload({
    source_review_id: "review-3",
    source_review_fingerprint: "prior-ledger",
    exported_at: "2026-07-12T12:00:00Z",
    entries: [action("ITEM-01", "Keep this note.", "2026-07-12T11:00:00Z")],
  });
  const v3Payload = {
    ...prior,
    schema_version: "0.3",
    entries: prior.entries.map((entry) => ({
      finding_id: entry.finding_id,
      disposition: entry.disposition,
      response_note: entry.response_note,
      changed_locations: entry.changed_locations,
      updated_at: entry.updated_at,
      status_history: entry.status_history,
      events: entry.events,
    })),
  };
  storage.setItem("review-desk:v3:review-3:prior-ledger", JSON.stringify(v3Payload));
  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-3",
    review_fingerprint: "current-ledger",
    finding_ids: ["ITEM-01"],
  });
  assert.equal(restored.entries["ITEM-01"].response_note, "Keep this note.");
  assert.equal(restored.entries["ITEM-01"].user_priority, null);
  assert.equal(restored.entries["ITEM-01"].reviewed, false);
  assert.deepEqual(restored.rereview_required_finding_ids, ["ITEM-01"]);
  assert.match(restored.warning, /prior ledger snapshot/i);
  assert.ok(storage.getItem("review-desk:v3:review-3:prior-ledger"), "migration must not delete archived v3 data");
});

test("storage keys isolate review IDs that contain delimiter characters", () => {
  const storage = new MemoryStorage();
  storage.setItem(reviewActionStorageKey("review", "ledger-a"), "{}");
  storage.setItem(reviewActionStorageKey("review:variant", "ledger-b"), "{}");
  assert.match(reviewActionStorageKey("review:variant", "ledger-b"), /review%3Avariant/);
  assert.equal(clearBrowserReviewActions(storage, "review"), 1);
  assert.ok(storage.getItem(reviewActionStorageKey("review:variant", "ledger-b")));
});

test("an exact current-fingerprint payload wins while older snapshots remain visible", () => {
  const storage = new MemoryStorage();
  persistBrowserReviewActions(storage, generateReviewActionsPayload({
    source_review_id: "review-2",
    source_review_fingerprint: "prior",
    exported_at: "2026-07-12T10:00:00Z",
    entries: [action("ITEM-01", "Prior note", "2026-07-12T09:00:00Z")],
  }));
  const currentAction = updateReviewAction(
    action("ITEM-01", "Current note", "2026-07-12T11:00:00Z"),
    "ITEM-01",
    { disposition: "ready_for_recheck", user_priority: "P1", reviewed: true },
    "2026-07-12T11:30:00Z",
  );
  persistBrowserReviewActions(storage, generateReviewActionsPayload({
    source_review_id: "review-2",
    source_review_fingerprint: "current",
    exported_at: "2026-07-12T12:00:00Z",
    entries: [currentAction],
  }));

  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-2",
    review_fingerprint: "current",
    finding_ids: ["ITEM-01"],
  });
  assert.equal(restored.entries["ITEM-01"].response_note, "Current note");
  assert.equal(restored.entries["ITEM-01"].disposition, "ready_for_recheck");
  assert.equal(restored.entries["ITEM-01"].reviewed, true);
  assert.equal(restored.entries["ITEM-01"].user_priority, "P1");
  assert.deepEqual(restored.rereview_required_finding_ids, []);
  assert.match(restored.warning, /prior ledger action snapshot remains archived/i);
});

test("review-ID-only legacy storage is conservatively rolled into a new round", () => {
  const storage = new MemoryStorage();
  const legacy = updateReviewAction(undefined, "ITEM-01", {
    disposition: "ready_for_recheck",
    response_note: "Keep the response.",
    user_priority: "P2",
    reviewed: true,
  }, "2026-07-12T11:00:00Z");
  storage.setItem("review-desk:v2:review-legacy", JSON.stringify({ "ITEM-01": legacy }));

  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-legacy",
    review_fingerprint: "current-ledger",
    finding_ids: ["ITEM-01"],
  });
  assert.equal(restored.entries["ITEM-01"].disposition, "open");
  assert.equal(restored.entries["ITEM-01"].reviewed, false);
  assert.equal(restored.entries["ITEM-01"].user_priority, "P2");
  assert.equal(restored.entries["ITEM-01"].response_note, "Keep the response.");
  assert.deepEqual(restored.rereview_required_finding_ids, ["ITEM-01"]);
  assert.ok(storage.getItem("review-desk:v2:review-legacy"), "legacy source data remains archived");
});
