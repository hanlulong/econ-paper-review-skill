# Review Actions Handoff

`review-actions.json` is an author-response sidecar, not a mutation of the verified findings ledger. It lets work recorded in the local viewer survive regeneration and inform a later review round.

The portable handoff records manuscript basenames or other non-sensitive labels plus a content hash when one was actually computed. It must not copy absolute paths, usernames, client names, or confidential directory structure from `run.json`. Full local provenance remains in the private review package.

New exports use action schema v0.3. Each entry retains its current disposition and note for convenient reading and an append-only `events` chain for disposition changes, note revisions, imports, and reversals. Current state must equal replayed event state. Events have UUIDs, timestamps, origins, and a linear parent chain: the first parent is null and every later event names its immediate predecessor. Changing a note or undoing a choice appends an event rather than erasing history. v0.1/v0.2 imports remain supported and are normalized without pretending they contained event history.

## Dispositions

- `open`: no response has been recorded.
- `ready_for_recheck`: the author asks the next review to inspect the comment again. A note is optional; the next review independently checks the manuscript and linked evidence.
- `challenged`: the author asks the next review to reconsider the diagnosis. A note is useful but optional; the state is not verified counterevidence by itself.
- `deferred`: the author is intentionally not addressing the comment in the current round.

Never translate `ready_for_recheck` into canonical `resolved` without reopening the cited manuscript location and rerunning every affected consistency or evidence mapping. A challenge is a request to reconsider, not an automatic dismissal. A deferral remains open for reviewer purposes.

## Next-round intake

When the user supplies a handoff:

1. Run `python3 "$SKILL_ROOT/scripts/validate_review_actions.py" <review-actions.json>`, which validates the schema, unique IDs, history order, and timestamps.
2. Compare `source_review_id`, source manuscript hashes when available, and the source fingerprint with the prior review package. Report mismatches; do not silently discard the file.
3. Reconcile entries only by exact stable `finding_id`. A review round belongs to the same lineage only when it reviews a revision of the same manuscript and intentionally retains `run.review_id`; unrelated papers or fresh review exercises must use a new review ID. Retain a finding ID only when the underlying issue is the same, even if its wording or rank changes. Assign a new ID when the diagnosis materially changes. List unmatched prior entries and new current findings separately.
4. For `ready_for_recheck`, inspect any note, the manuscript, exhibits, appendix, and affected claim family. Set the canonical finding to `resolved` only after the repair and its `resolved_when` condition pass.
5. For `challenged`, rerun the counterargument and verification pass using the supplied response as an author-side claim. The result may remain open, become weakened, or be dismissed; record the evidence.
6. Keep `deferred` findings active unless the paper has independently changed enough to resolve them.
7. Preserve the handoff in the new review evidence trail and summarize imported, unmatched, and newly created findings in `evidence/verification.md`.

For v0.3, also validate event UUID uniqueness, the immediate-predecessor parent chain, chronological order, replayed current state, and maximum sizes. Never trust a client-supplied current disposition when it disagrees with the event chain.

The viewer may merge an older local workspace by exact finding ID, but it must warn about different fingerprints, different review IDs, malformed entries, stale imports, conflicting histories, and entries with no current match. It must never overwrite newer local work with an older import. Import never changes canonical `findings.json`.
