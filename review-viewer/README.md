# Review Desk

Review Desk is the local interaction layer for `econ-review`. It reads the canonical review artifacts, presents findings in importance order with manuscript evidence and revision paths, and stores author progress separately in the browser.

## Run locally

```bash
nvm use
npm install
npm run dev
```

Open the printed local URL and choose **Open review folder**. Selecting the paper folder loads canonical review files, the manuscript, nested manifests, and referenced renders in one local action, including packages with duplicate image basenames in different subdirectories. **Choose individual files** remains available for small or flat bundles. The normal development command deliberately removes generated public review bundles and opens this local workflow. This keeps manuscripts and findings on the local machine and out of deployable assets. If an authorized bundled session is used, `?review=<slug>` preserves the selected bundle.

## Open another review

Choose **Open review folder** for a normal generated package, or select at least these files in individual-file mode:

- `findings.json`
- `run.json`

Add `review-manifest.json` to expose every intended Markdown document—including the referee report, writing report, revision plan, and audit trail—in a stable order. Without a manifest, the viewer conservatively discovers the standard report and evidence paths. Add manuscript Markdown or text to enable manuscript context. Markdown reports render without embedded HTML; manuscript and ledger strings remain inert text. Inline and display TeX render locally with KaTeX.

Add `synthesis.json` to show the editorial posture, overall assessment, severity tally, and principal concerns above the working queue. Older packages without synthesis still load. Relative links among manifest-declared Markdown documents switch the in-app document reader instead of navigating away. For a PDF-only review, include the checked, source-specific generated Markdown path named by `evidence/source-manifest.json` (normally under `evidence/pdf-ingestion/<source-id>/`); the viewer uses that generated reading surface while the table and figure manifests control which render crops are exposed.

Folder mode reads the generated package's canonical `evidence/tables.json` and `evidence/figures.json` manifests, then resolves their referenced PNG/JPEG/WebP renders by normalized relative path. Legacy root-level `tables.json` and `figures.json` remain supported as fallbacks. The only repository fixture that may be bundled is a short synthetic theory review; real manuscripts must be opened through the local picker unless separately cleared for publication.

The loader rejects mismatched review IDs, duplicate finding IDs, oversized files, and malformed minimum structures. Loading a review without a manuscript clears the previous manuscript instead of retaining stale context. Files stay in the browser; this local app does not upload them or fetch external review content.

## Interaction model

- Open on the review overview, then read declared reports beside the comment rail or enter the detailed queue in one action.
- Use each principal concern to open its first active linked comment.
- Work through substance and writing comments by importance or canonical manuscript position. Older packages fall back to a stable natural locator order. Search includes evidence, locators, revision paths, and optional notes.
- Step through every evidence item attached to a finding and toggle between the structured quote and exact-match manuscript context.
- Open any linked exhibit at its native size in a separate local tab; alternate saved renders remain selectable in the evidence pane.
- Switch between named bundled reviews without mixing actions. The workspace shows a compatibility-check loading state and restores the prior review if a bundle fails.
- Use `J` and `K` to move, `A` to mark ready for recheck, `C` to challenge, `P` to defer, `N` to focus the response, and `/` to search. Shortcuts work from noninteractive workspace surfaces; visible controls provide the same workflow.
- On narrow screens, use the Queue / Comment / Evidence switcher rather than scrolling through three stacked panes. The Comment pane includes the selected evidence excerpt in the requested issue → evidence → concern sequence; Evidence opens the full source context.
- Mark a finding for recheck, challenge, or deferral in one click; add an optional note when useful.
- Status changes offer a short undo action. Undo appends a reversal event rather than erasing the original action. Note revisions and imports are also recorded in the v0.3 event chain.
- Export or import a schema-validated `review-actions.json` handoff. Browser persistence is namespaced by both review ID and a SHA-256 ledger fingerprint: a changed ledger reconciles exact stable finding IDs with warnings while retaining the complete prior-fingerprint payload, including unmatched history, under its original local key. A different review ID is never applied. Imports merge only compatible append-only event chains, keep newer local work, and report stale, conflicting, and unmatched entries. v0.1/v0.2 handoffs remain importable.
- Exported handoffs use portable manuscript labels and optional content hashes; they do not copy absolute local paths, usernames, or confidential folder names from the review package.
- Bundled-review URLs preserve the overview, exact comment or document, evidence item, queue order, and filters; browser Back and Forward restore those views. Free-text search is intentionally excluded from URLs to avoid leaking sensitive terms.
- The menu can keep actions only in the current tab or clear every saved snapshot for the active review. Switching to tab-only mode also removes its saved queue preference.

Canonical review files remain read-only. Local actions use the external states `open`, `ready_for_recheck`, `challenged`, and `deferred`, with timestamps and append-only events. Notes are optional and committed as revisions on blur rather than on every keystroke. Only a later review can verify resolution or dismiss a challenge. Notes are capped at 10,000 characters per finding, and the viewer keeps in-memory work available with a visible warning if browser persistence is unavailable. Draft, blocked, verification-failed, and otherwise unverified packages carry a persistent non-final warning.

## Publication boundary

Review bundles contain the narrative reports, manuscript, findings, and extracted exhibits. They are confidential unless the operator has separately confirmed they are cleared for publication. Consequently, both `npm run sync-review` and `npm run build` refuse to copy review data without an explicit opt-in:

```bash
ALLOW_PUBLISH=1 npm run build
```

`ALLOW_PUBLISH=1` is an authorization acknowledgment, not a privacy control. Use it only for material that may be exposed in the generated site. For an intentionally bundled local session, run `npm run dev:bundled`; for confidential work, use `npm run dev` and the local file picker. Generated `public/reviews/` and legacy `public/sample-review/` directories are ignored by version control. `npm run clear-review-bundles` removes both source copies and any corresponding assets left in `dist/client/`.

## Verification

```bash
npm run lint
npm test
npm audit
```

The test command performs an explicitly authorized fixture build, runs the viewer and publication-guard tests, and removes the generated public bundles on exit. Bundle synchronization validates and stages the complete package—including every manifest-referenced exhibit render—before atomically replacing any existing generated bundle. The app requires Node.js 22.18 or later; `.nvmrc` pins the tested local version (22.22.2).
