# Review Actions Handoff

`review-actions.json` is an author-response sidecar, not a mutation of the verified findings ledger. It lets work recorded in the local viewer survive regeneration and inform a later review round.

The portable handoff records manuscript basenames or other non-sensitive labels plus a content hash when one was actually computed. It must not copy absolute paths, usernames, client names, or confidential directory structure from `run.json`. Full local provenance remains in the private review package.

New exports use action schema v0.4. `source_review_fingerprint` is the lowercase SHA-256 of the exact BOM-free UTF-8 `findings.json` bytes loaded by Review Desk; preserve that file unchanged with the handoff. Each entry retains its current disposition, note, personal priority, and reviewed state for convenient reading and an append-only `events` chain for disposition changes, note revisions, priority changes, reviewed-state changes, imports, and reversals. Current state must equal replayed event state. Events have UUIDs, timestamps, origins, and a linear parent chain: the first parent is null and every later event names its immediate predecessor. Changing a note, priority, reviewed state, or disposition appends an event rather than erasing history. Older imports are normalized without pretending they contained fields or history that did not exist.

`user_priority` is the author's planning choice (`P0`, `P1`, `P2`, or unassigned while drafting). It never rewrites the referee's canonical severity or `importance_rank`. `reviewed` records that the user has considered the comment; it does not claim that the paper has resolved it. The viewer may build a deterministic personal revision plan at any time. It remains a draft until every comment is reviewed, every active task has a P0/P1/P2 priority, and every active or excluded comment has a user instruction or reason. The ready plan groups included work P0 through P2 and preserves each finding ID, reviewed state, disposition, and response note.

## Dispositions

- `open`: no response has been recorded.
- `ready_for_recheck`: the author asks the next review to inspect the comment again. A note is optional; the next review independently checks the manuscript and linked evidence.
- `challenged`: the author asks the next review to reconsider the diagnosis. A note is useful but optional; the state is not verified counterevidence by itself.
- `deferred`: the author is intentionally not addressing the comment in the current round.
- `not_relevant`: the user has considered the comment and decided it does not apply to the revision. Record the choice and omit that exact finding ID from the next-round active list and personal revision plan.
- `not_addressable`: the user has considered the comment and decided the revision cannot address it. Record the choice and omit that exact finding ID from the next-round active list and personal revision plan.

Never translate `ready_for_recheck` into canonical `resolved` without reopening the cited manuscript location and rerunning every affected consistency or evidence mapping. A challenge is a request to reconsider, not an automatic dismissal. A deferral remains open for reviewer purposes. `not_relevant` and `not_addressable` are explicit user exclusions, not referee verification: preserve them in the handoff trail while suppressing them from the next active presentation. If later evidence creates a materially different concern, give it a new finding ID rather than silently reviving the excluded one.

## Next-round intake

When the user supplies a handoff:

1. Run `python3 "$SKILL_ROOT/scripts/validate_review_actions.py" <review-actions.json>`, which validates the schema, unique IDs, history order, and timestamps.
2. Compare `source_review_id`, source manuscript hashes when available, and the source fingerprint with the prior review package. Report mismatches; do not silently discard the file.
3. Reconcile entries only by exact stable `finding_id`. A review round belongs to the same lineage only when it reviews a revision of the same manuscript and intentionally retains `run.review_id`; unrelated papers or fresh review exercises must use a new review ID. Retain a finding ID only when the underlying issue is the same, even if its wording or rank changes. Assign a new ID when the diagnosis materially changes. List unmatched prior entries and new current findings separately.
4. For `ready_for_recheck`, inspect any note, the manuscript, exhibits, appendix, and affected claim family. Set the canonical finding to `resolved` only after the repair and its `resolved_when` condition pass.
5. For `challenged`, rerun the counterargument and verification pass using the supplied response as an author-side claim. The result may remain open, become weakened, or be dismissed; record the evidence.
6. Keep `deferred` findings active unless the paper has independently changed enough to resolve them.
7. For `not_relevant` and `not_addressable`, retain the imported entry in the evidence trail but exclude that exact finding ID from the next-round active report, editing comments, viewer queue, and generated revision plan. Do not use the exclusion to suppress a materially new issue under a recycled ID.
8. Preserve the handoff in the new review evidence trail and summarize imported, excluded, unmatched, and newly created findings in `evidence/verification.md`.

For v0.4, also validate event UUID uniqueness, the immediate-predecessor parent chain, chronological order, replayed disposition, note, personal priority, reviewed state, and maximum sizes. Never trust client-supplied current fields when they disagree with the event chain. An excluded disposition must have `reviewed: true`.

The viewer may merge an older local workspace by exact finding ID, but it must warn about different fingerprints, different review IDs, malformed entries, stale imports, conflicting histories, and entries with no current match. It must never overwrite newer local work with an older import. Import never changes canonical `findings.json`.
