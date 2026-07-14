# Iterative Revision Cycle

The purpose of the cycle is to improve the paper, not to accumulate statuses. Keep four judgments separate:

1. the referee's verified finding and severity;
2. the user's priority, note, and disposition;
3. an implementation agent's claim about work performed; and
4. the next reviewer’s evidence-based decision about whether the concern is resolved.

No layer may silently overwrite the one before it.

## 1. User review in Review Desk

The user considers every active comment, writes a concrete instruction or reason in the note field, chooses a personal priority (`P0` do first, `P1` important next step, or `P2` later) for every active task, and marks the comment reviewed. The personal priority controls the user's work queue; it does not change canonical referee severity. Notes and priorities may remain incomplete while the plan is a draft. A plan is ready for agent handoff only when every comment is reviewed, every active task has a priority, and every active or excluded comment has a nonblank user note.

The available dispositions are:

- `open`: include the comment in the implementation plan;
- `ready_for_recheck`: include it, but tell the next reviewer that a change is already claimed;
- `challenged`: include the requested reconsideration and the user's note;
- `deferred`: keep it in the audit trail but outside the current implementation plan;
- `not_relevant` or `not_addressable`: record the deliberate exclusion and omit that exact finding ID from the next active report, queue, and plan.

Export `review-actions.json`, `revision-tasks.json`, `revision-agent-brief.md`, and `revision-response.template.json` from the same committed action snapshot. The task file records `all_comments_reviewed` and `handoff_ready` separately and preserves each row's reviewed state, priority, note, and disposition. Draft exports remain useful for inspection, but an implementation response is invalid until `handoff_ready` is true.

## 2. Implementation-agent handoff

Validate the machine-readable plan before use:

```sh
"$REVIEW_PYTHON" "$SKILL_ROOT/scripts/validate_revision_handoff.py" revision-tasks.json --findings findings.json --actions review-actions.json
"$REVIEW_PYTHON" "$SKILL_ROOT/scripts/validate_revision_handoff.py" revision-tasks.json --findings findings.json --actions review-actions.json --response revision-response.template.json --template
```

Give the implementation agent the paper sources, `revision-agent-brief.md`, `revision-tasks.json`, and the response template. The agent must:

- modify only manuscript or source files the user placed in scope;
- follow the user's note without weakening factual or methodological accuracy;
- never invent data, results, citations, evidence, or checks;
- preserve each finding ID exactly;
- give a direct response for every task, report every changed file and precise location, record checks and results, and state any blocker;
- use `changed` for a checked file edit, `response_only` for a reasoned no-change answer or challenge, `partial` for incomplete work, `blocked` for a precise impediment, or `not_attempted` for untouched work; and
- never mark a referee finding resolved.

The returned response uses `responded_at`, retains the plan and review identities, and lists exactly the active task IDs. A `changed` entry needs concrete changed locations and successful checks. A `response_only` entry explains the no-change answer without inventing file edits. A failed check cannot be reported as `changed`.

Validate the returned file:

```sh
"$REVIEW_PYTHON" "$SKILL_ROOT/scripts/validate_revision_handoff.py" revision-tasks.json --findings findings.json --actions review-actions.json --response revision-response.json
```

## 3. Next-round intake

Require the prior canonical review, revised manuscript or source project, `review-actions.json`, `revision-tasks.json`, and `revision-response.json` when available. Preserve the exact prior `findings.json` bytes: the viewer and validator define the source fingerprint as the SHA-256 of that BOM-free UTF-8 file, not a re-serialization of its parsed contents. Validate both handoffs before reading their substantive claims. Compare the review ID, source fingerprint, plan ID, manuscript hashes, and exact finding IDs. Report mismatches; never guess which paper, plan, or comment an entry belongs to.

Copy the immutable intake files directly under `evidence/prior-round/` and declare their safe package-relative paths in `run.json.prior_round`. Preserve the same `run.review_id` only for an intentional new round on the same manuscript lineage. Create `evidence/round-reconciliation.json` against `assets/round-reconciliation.schema.json`. It binds the prior snapshots by hash and records one reviewer-owned row for every prior plan row, followed by the current round's genuinely new finding IDs. Always include `successor_consolidations` and use `[]` when every successor has one prior owner. When one current diagnosis genuinely consolidates two or more superseded prior findings, declare it once in that array, list every contributing prior ID in revision-plan order, and explain why the consolidation is substantive rather than an accidental duplicate mapping. Do not copy user notes or implementation-agent response prose into the reviewer-authored JSON fields; the hashed snapshots preserve those statements without making them reviewer conclusions.

Treat agent responses as a map of places to inspect, not proof. For every prior active task:

1. reopen the cited old evidence and the finding's `resolved_when` condition;
2. inspect each claimed changed file and location in the revised source;
3. render or compile affected equations, tables, figures, references, and cross-references when applicable;
4. check nearby and cross-paper consistency, because a local repair can create a new contradiction elsewhere;
5. classify the prior concern as resolved, partly resolved, unchanged, or superseded; and
6. record the evidence for that decision before changing canonical status.

Only `resolved` removes a prior active finding on reviewer evidence. A partly resolved or unchanged issue remains active with updated evidence, consequence, repair, and rank. A materially different concern receives a new finding ID; do not recycle an excluded or resolved ID. Preserve user exclusions in the private reconciliation trail without returning them to the active report.

Use the outcomes narrowly:

- `resolved`: every closure check passed and no active successor remains;
- `partly_resolved`: the same finding ID remains active, with both passed and incomplete checks;
- `unchanged`: the same finding ID remains active and no closure check passed;
- `superseded`: the old diagnosis no longer survives as written, but one or more materially different current findings replace it under new IDs. A shared successor is valid only through an explicit `successor_consolidations` row whose prior-ID list exactly matches all records that cite that successor; and
- `user_excluded`: the exact `not_relevant` or `not_addressable` ID remains suppressed after an identity-and-scope check passes.

During drafting, validate the JSON and regenerate its readable projection with:

```sh
"$REVIEW_PYTHON" "$SKILL_ROOT/scripts/round_reconciliation.py" review/supporting --write
```

The finalizer repeats this step before report and PDF generation. It writes `evidence/round-reconciliation.md`, declares that document in `review-manifest.json`, and fails if either the snapshot bindings or readable projection are stale. The readable projection identifies each earlier issue by title and text, reproduces the author's exact instruction, explains in ordinary language what the implementation agent reports and where, and then presents the reviewer's independent conclusion, rationale, related current-comment titles, and checks. New comments also appear by title. Stable finding IDs, outcome and agent-status enums, and evidence tokens remain only in hidden HTML comments or canonical JSON; the PDF strips the hidden comments. The projection also omits hashes, plan IDs, event trails, and unrelated response metadata.

## 4. Fresh review, not a change-only scan

After adjudicating prior findings, reconstruct the revised paper and rerun every applicable logical, technical, methodological, claim-consistency, reader, exhibit, and editing pass. Inspect all changed exhibits separately and also run the normal full-paper coverage sweep. Search for:

- new claims or assumptions introduced by a repair;
- inconsistencies between changed and unchanged sections;
- altered equations, notation, samples, tables, figures, or citations;
- repairs that move rather than solve a problem; and
- genuinely new concerns unrelated to the prior report.

The next report should briefly distinguish resolved prior issues, remaining prior issues, user exclusions, and new issues, then present the current exhaustive comments in priority order. The generated opening links to the finding-by-finding round report rather than repeating its rationales. Do not repeat resolved or user-excluded findings as active comments.

## 5. Continue until the stop condition is met

Repeat the cycle until all non-excluded prior findings are verified resolved, no new verified finding survives the challenge pass, every active source and burden is covered or explicitly bounded, and finalization passes. “Perfect” means no remaining verified problem within the recorded review boundary; it is not a promise that an unknowable issue cannot exist outside supplied materials or available tools.
