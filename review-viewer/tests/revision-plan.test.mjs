import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

import { generateReviewActionsPayload, reconcileReviewActions, updateReviewAction } from "../lib/review-actions.ts";
import {
  buildAgentResponseTemplate,
  buildRevisionTasks,
  commitRevisionNoteDrafts,
  deterministicJson,
  renderRevisionAgentBrief,
} from "../lib/revision-plan.ts";

const T0 = "2026-07-12T12:00:00.000Z";
const T1 = "2026-07-12T12:05:00.000Z";

function finding(id, { rank, severity = "major", ordinal, source = "SRC-01", status = "open" }) {
  return {
    id,
    title: `${id} title`,
    importance_rank: rank,
    severity,
    dimension: "logic",
    essential: true,
    status,
    support_state: "supported",
    issue: `${id} issue`,
    why_it_matters: "It matters.",
    reader_effect: "The reader cannot verify the claim.",
    paper_position: { ordinal, source_id: source, section: `Section ${ordinal}` },
    display_evidence_id: `EVD-${id}`,
    evidence: [{
      id: `EVD-${id}`,
      type: "quote",
      representation: "verbatim",
      content: `${id} quoted text`,
      source: "manuscript",
      locator: { section: String(ordinal), page: ordinal },
    }],
    counterargument: { result: "survived", author_reply: "", notes: "" },
    fix: {
      what: `Revise ${id}.`,
      how: `Explain the comparison for ${id}.`,
      effort: "medium",
      publishability: "material",
      resolved_when: `${id} is explicit and internally consistent.`,
    },
    verification: `Re-read ${id}.`,
  };
}

function action(id, patch, at = T0) {
  return updateReviewAction(undefined, id, patch, at);
}

const findings = [
  finding("ITEM-03", { rank: 3, severity: "minor", ordinal: 3 }),
  finding("ITEM-01", { rank: 1, severity: "critical", ordinal: 1 }),
  finding("ITEM-02", { rank: 2, severity: "major", ordinal: 2 }),
  finding("ITEM-04", { rank: 4, severity: "major", ordinal: 4 }),
];

test("revision tasks use personal priority, reviewer rank, and an explicit excluded appendix", () => {
  const entries = {
    "ITEM-01": action("ITEM-01", { user_priority: "P1", reviewed: true, response_note: "Preserve the baseline wording." }),
    "ITEM-02": action("ITEM-02", { user_priority: "P0", reviewed: true }),
    "ITEM-03": action("ITEM-03", { reviewed: false }),
    "ITEM-04": action("ITEM-04", {
      disposition: "not_relevant",
      reviewed: true,
      response_note: "This mechanism is outside the paper's stated scope.",
    }),
  };
  const payload = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings,
    entries,
  });

  assert.deepEqual(payload.tasks.map((task) => task.finding_id), ["ITEM-02", "ITEM-01", "ITEM-03"]);
  assert.deepEqual(payload.tasks.map((task) => task.user_priority), ["P0", "P1", null]);
  assert.deepEqual(payload.excluded.map((task) => task.finding_id), ["ITEM-04"]);
  assert.equal(payload.excluded[0].disposition, "not_relevant");
  assert.equal(payload.all_comments_reviewed, false);
  assert.equal(payload.handoff_ready, false);
  assert.equal(payload.tasks[0].reviewed, true);
  assert.equal(payload.excluded[0].reviewed, true);
  assert.match(payload.plan_id, /^[0-9a-f]{8}-[0-9a-f]{4}-5[0-9a-f]{3}-a[0-9a-f]{3}-[0-9a-f]{12}$/);
  assert.equal(payload.generated_at, T0);
  assert.equal(payload.tasks[0].source_location, "Section 2 · p. 2");
  assert.equal(payload.tasks[0].relevant_text, "ITEM-02 quoted text");
});

test("draft notes are verbatim, override saved notes, and do not get reformatted inside Markdown fences", () => {
  const saved = action("ITEM-01", { response_note: "Saved note", reviewed: true }, T0);
  const verbatim = "First line\r\n\r\n```\r\nkeep this spacing";
  const payload = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings: [findings[1]],
    entries: { "ITEM-01": saved },
    draft_notes: { "ITEM-01": verbatim },
  });
  assert.equal(payload.tasks[0].user_comment, "First line\n\n```\nkeep this spacing");
  const brief = renderRevisionAgentBrief(payload);
  assert.match(brief, /````text\nFirst line\n\n```\nkeep this spacing\n````/);
  assert.match(brief, /All comments reviewed/);
  assert.match(brief, /Missing decisions — do not implement this draft/);
});

test("agent tasks omit internal reviewer-observation storage labels", () => {
  const derived = finding("ITEM-07", { rank: 7, ordinal: 7 });
  derived.evidence[0].representation = "reviewer_observation";
  derived.evidence[0].content = "[Reviewer observation] The table and text report different samples.";
  const payload = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings: [derived],
    entries: { "ITEM-07": action("ITEM-07", { user_priority: "P0", reviewed: true, response_note: "Reconcile the sample descriptions." }) },
  });
  assert.equal(payload.tasks[0].relevant_text, "The table and text report different samples.");
  assert.doesNotMatch(renderRevisionAgentBrief(payload), /\[Reviewer observation\]/);
});

test("task JSON, plan IDs, and response templates are deterministic and schema-shaped", async () => {
  const taskSchema = JSON.parse(await readFile(new URL("../../econ-review/assets/revision-tasks.schema.json", import.meta.url), "utf8"));
  const responseSchema = JSON.parse(await readFile(new URL("../../econ-review/assets/agent-response.schema.json", import.meta.url), "utf8"));
  const entries = {
    "ITEM-01": action("ITEM-01", { user_priority: "P0", reviewed: true }, T1),
  };
  const options = {
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings: [findings[1]],
    entries,
  };
  const first = buildRevisionTasks(options);
  const second = buildRevisionTasks(options);
  assert.deepEqual(second, first);
  assert.equal(deterministicJson(first), deterministicJson(second));
  assert.deepEqual(Object.keys(first).sort(), [...taskSchema.required].sort());
  assert.deepEqual(Object.keys(first.tasks[0]).sort(), [...taskSchema.$defs.task.required].sort());

  const response = buildAgentResponseTemplate(first);
  assert.deepEqual(Object.keys(response).sort(), [...responseSchema.required].sort());
  assert.equal(response.plan_id, first.plan_id);
  assert.equal(response.responded_at, null);
  assert.deepEqual(response.entries, [{
    finding_id: "ITEM-01",
    status: "not_attempted",
    response: "",
    changed_files: [],
    changed_locations: [],
    verification: [],
    blocker: null,
  }]);
});

test("resolved and dismissed canonical findings never become implementation tasks", () => {
  const payload = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings: [
      finding("ITEM-05", { rank: 5, ordinal: 5, status: "resolved" }),
      finding("ITEM-06", { rank: 6, ordinal: 6, status: "dismissed" }),
    ],
    entries: {},
  });
  assert.deepEqual(payload.tasks, []);
  assert.deepEqual(payload.excluded, []);
  assert.equal(payload.all_comments_reviewed, true);
  assert.equal(payload.handoff_ready, true);
});

test("unblurred note drafts are committed once and shared by task and action exports", () => {
  const initial = action("ITEM-01", { user_priority: "P0", reviewed: true }, T0);
  const entries = commitRevisionNoteDrafts(
    { "ITEM-01": initial },
    { "ITEM-01": "Keep both lines.\n\nDo not broaden the claim." },
    T1,
  );
  const tasks = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    findings: [findings[1]],
    entries,
  });
  const actions = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    exported_at: T1,
    entries,
  });
  assert.equal(tasks.tasks[0].user_comment, actions.entries[0].response_note);
  assert.equal(tasks.handoff_ready, true);
  assert.equal(actions.entries[0].events.at(-1).type, "note_revised");
  assert.deepEqual(commitRevisionNoteDrafts(entries, { "ITEM-01": tasks.tasks[0].user_comment }, T1), entries);
});

test("a changed review round cannot become handoff-ready until carried comments are reviewed again", () => {
  const prior = action("ITEM-01", {
    disposition: "ready_for_recheck",
    response_note: "Keep the narrow implementation instruction.",
    user_priority: "P0",
    reviewed: true,
  }, T0);
  const source = generateReviewActionsPayload({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v1",
    exported_at: T1,
    entries: [prior],
  });
  const rolled = reconcileReviewActions(source, {
    review_id: "review-1",
    review_fingerprint: "ledger-v2",
    finding_ids: ["ITEM-01"],
  }, { rollover_at: T1 });
  const beforeReview = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v2",
    findings: [findings[1]],
    entries: rolled.entries,
  });
  assert.equal(beforeReview.tasks[0].disposition, "open");
  assert.equal(beforeReview.tasks[0].reviewed, false);
  assert.equal(beforeReview.tasks[0].user_priority, "P0");
  assert.equal(beforeReview.tasks[0].user_comment, "Keep the narrow implementation instruction.");
  assert.equal(beforeReview.all_comments_reviewed, false);
  assert.equal(beforeReview.handoff_ready, false);

  const reconsidered = updateReviewAction(rolled.entries["ITEM-01"], "ITEM-01", { reviewed: true }, T1);
  const afterReview = buildRevisionTasks({
    source_review_id: "review-1",
    source_review_fingerprint: "ledger-v2",
    findings: [findings[1]],
    entries: { "ITEM-01": reconsidered },
  });
  assert.equal(afterReview.all_comments_reviewed, true);
  assert.equal(afterReview.handoff_ready, true);
});
