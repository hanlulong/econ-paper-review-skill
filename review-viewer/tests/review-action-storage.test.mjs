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
  const prior = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "old-ledger",
    exported_at: "2026-07-12T12:00:00Z",
    entries: [
      action("KEEP-01", "Implemented in Section 2.", "2026-07-12T11:00:00Z"),
      action("OLD-02", "This prior finding no longer has a current ID.", "2026-07-12T11:30:00Z"),
    ],
  });
  persistBrowserReviewActions(storage, prior);

  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-1",
    review_fingerprint: "new-ledger",
    finding_ids: ["KEEP-01", "NEW-03"],
  });
  assert.deepEqual(Object.keys(restored.entries), ["KEEP-01"]);
  assert.match(restored.warning, /complete prior payload remains archived/i);
  assert.match(restored.warning, /1 action entry does not match/i);

  const current = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "new-ledger",
    exported_at: "2026-07-12T13:00:00Z",
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
  storage.setItem("review-desk:v3:review-1:a", "{}");
  storage.setItem("review-desk:v2:review-1", "{}");
  storage.setItem(`review-desk:v1:review-1:${"a".repeat(64)}`, "{}");
  storage.setItem("review-desk:v3:review-2:a", "{}");
  assert.equal(clearBrowserReviewActions(storage, "review-1"), 3);
  assert.equal(storage.length, 1);
  assert.ok(storage.getItem("review-desk:v3:review-2:a"));
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
  persistBrowserReviewActions(storage, generateReviewActionsPayload({
    source_review_id: "review-2",
    source_review_fingerprint: "current",
    exported_at: "2026-07-12T12:00:00Z",
    entries: [action("ITEM-01", "Current note", "2026-07-12T11:00:00Z")],
  }));

  const restored = restoreBrowserReviewActions(storage, {
    review_id: "review-2",
    review_fingerprint: "current",
    finding_ids: ["ITEM-01"],
  });
  assert.equal(restored.entries["ITEM-01"].response_note, "Current note");
  assert.match(restored.warning, /prior ledger action snapshot remains archived/i);
});
