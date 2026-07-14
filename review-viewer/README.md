# Review Desk

Review Desk is the local interaction layer for `econ-review`. It reads the canonical review artifacts, presents findings in the referee report's priority order with manuscript evidence and revision paths, and stores author progress separately in the browser.

## Run the installed app

The recommended econ-review setup uses `--with-review-desk`. It installs a
verified, prebuilt static bundle and prints a stable launch command. The command
uses Python 3.10+ to serve the app at `http://127.0.0.1:48127/`; installed users
do not need Node.js or npm. Only release-manifest files are served, only `GET`
and `HEAD` are accepted, and no review is bundled. If the browser does not open,
copy the printed URL. Review files remain in the browser and are not uploaded.

See [the installation guide](../docs/INSTALL.md) for macOS, Linux, native
Windows, and project-local commands.

## Develop locally

```bash
nvm use
npm ci
npm run dev
```

Open the printed local URL and choose **Open review folder**. Selecting the paper folder loads canonical review files, the manuscript, nested manifests, and referenced renders in one local action, including packages with duplicate image basenames in different subdirectories. **Choose individual files** remains available for small or flat bundles. The normal development command deliberately removes generated public review bundles and opens this local workflow. This keeps manuscripts and findings on the local machine and out of deployable assets. If an authorized bundled session is used, `?review=<slug>` preserves the selected bundle.

Maintainers create the runtime-free user artifact with `npm run build:release`
and verify it with `python3 scripts/build_review_desk_release.py --check`. The
release archive is deterministic and excludes source maps, development dependency
trees, and review data. It embeds a generated inventory and the complete license or notice
files for every third-party package in the shipped client bundle, plus the KaTeX
font license; the same per-file release manifest hashes those compliance files.

## Open another review

Choose **Open review folder** for a normal generated package, or select at least these files in individual-file mode:

- `findings.json`
- `run.json`

Add `review-manifest.json` to expose every intended Markdown document—including the referee report, editing comments, revision plan, and audit trail—in a stable order. Without a manifest, the viewer conservatively discovers the standard report and evidence paths. Add manuscript Markdown or text to enable manuscript context. Markdown reports render without embedded HTML; manuscript and ledger strings remain inert text. Inline and display TeX render locally with KaTeX.

Add `synthesis.json` to show the editorial posture, overall assessment, severity tally, and principal concerns above the working queue. Older packages without synthesis still load. Relative links among manifest-declared Markdown documents switch the in-app document reader instead of navigating away. For a PDF-only review, include the checked, source-specific generated Markdown path named by `evidence/source-manifest.json` (normally under `evidence/pdf-ingestion/<source-id>/`); the viewer uses that generated reading surface while the table and figure manifests control which render crops are exposed.

Add `finalization.json` to let the viewer verify package finality rather than merely repeat `run.json`. The viewer checks the receipt's review ID, declared contract, version-appropriate gates, complete local artifact inventory, and every declared SHA-256 hash. A missing, malformed, stale, incomplete, or hash-mismatched receipt leaves the package readable but explicitly unverified. Here, **verified** means that the selected package bytes match this unsigned integrity receipt; it does not authenticate the reviewer, author, or origin, and it does not replace the Python validator's full semantic checks. `run.json.status = "complete"` and an empty findings ledger are never presented as proof of finality on their own.

Current full packages may include source-bound claims, writing audit v0.4, and the granular source inventory inside `evidence/coverage.json`. The viewer integrity-checks these artifacts through the receipt and presents their manifest-declared readable Markdown documents. It deliberately does not duplicate the Python validator's evolving domain semantics in browser code, so new paper types and general framework additions remain displayable without paper-specific viewer logic.

Folder mode reads the generated package's canonical `evidence/tables.json`, `evidence/figures.json`, and `evidence/computations.json` manifests. It supports legacy table/figure path lists and current `rendered_assets`, preserves declared crop/full-page roles, and resolves only manifest-referenced PNG/JPEG/WebP renders. Local images must match their file signature and extension before an inert image blob is created; current table and figure assets must also match their declared SHA-256 hash. Computation artifacts are never executed or opened, while their recorded tool, method, anchors, result, tolerance, relative path, and hash remain inspectable. Legacy root-level manifests remain supported as fallbacks. The only repository fixture that may be bundled is a short synthetic theory review; real manuscripts must be opened through the local picker unless separately cleared for publication.

The loader rejects mismatched review IDs—including exhibit manifests—duplicate finding or exhibit labels, unsafe or ambiguous package paths, oversized files, hash-mismatched current figure renders, disguised image files, and malformed minimum structures. Loading a review without a manuscript clears the previous manuscript instead of retaining stale context. Files stay in the browser; this local app does not upload them or fetch external review content. Report links open only when they resolve to a declared local review document or an explicit HTTP(S) destination; other schemes and undeclared local paths remain inert.

## Interaction model

- Open on the review overview, then read declared reports beside the comment rail or enter the detailed queue in one action.
- Use each principal concern to open its first active linked comment.
- Work through substantive and editing comments by reviewer priority, technical severity, or canonical manuscript position. Reviewer priority is the default and follows the report's canonical `importance_rank`; Severity groups Critical, Major, Minor, then informational comments. Search includes evidence, locators, revision paths, and author notes.
- Step through every evidence item attached to a finding and toggle between the structured quote and exact-match manuscript context.
- Open any linked exhibit at its native size in a separate local tab; alternate saved renders remain selectable in the evidence pane.
- Switch between named bundled reviews without mixing actions. The workspace shows a compatibility-check loading state and restores the prior review if a bundle fails.
- Use `J` and `K` to move, `A` to mark ready for recheck, `C` to challenge, `P` to defer, `N` to focus the response, and `/` to search. Shortcuts work from noninteractive workspace surfaces; visible controls provide the same workflow.
- On narrow screens, use the Queue / Comment / Evidence switcher rather than scrolling through three stacked panes. The Comment pane includes the selected evidence excerpt in the requested issue → evidence → concern sequence; Evidence opens the full source context.
- Assign an author priority (P0/P1/P2), explicitly mark each comment reviewed, and record whether it stays open, is ready for recheck, is challenged, is deferred, is not relevant, or is not addressable. The last two dispositions are reviewed exclusions and require a reason for a final handoff.
- Status changes offer a short undo action. Undo appends a reversal event rather than erasing the original action. Note, priority, reviewed-state, and import events are recorded in the v0.4 event chain, visible in each comment's collapsed Action history.
- Build **My revision plan** at any time. Draft exports list every missing reviewed flag, active-task priority, and instruction or exclusion reason. A final handoff requires all comments reviewed, P0/P1/P2 on every active task, and a nonblank instruction or reason on every active or excluded item.
- Export `revision-tasks.json`, `revision-agent-brief.md`, and `revision-response.template.json` for an implementation agent. The agent may report file changes (`changed`) or a reasoned no-change answer (`response_only`), as well as partial, blocked, or untouched work; it never declares a finding resolved. The next econ-review round verifies the response and scans again for old and new issues.
- Export or import a schema-validated `review-actions.json` handoff. Every export first commits visible unblurred note drafts to the append-only action ledger, so task comments and action notes cannot diverge. Browser persistence is namespaced by both review ID and the SHA-256 of the exact BOM-free UTF-8 `findings.json` file that was loaded. When that fingerprint changes, exact-ID notes and personal priorities carry forward, active workflow states reopen, and surviving comments become unreviewed; deferred comments also become unreviewed, while explicit not-relevant or not-addressable exclusions remain schema-valid reviewed exclusions if their exact IDs still survive. The viewer warns that the current round needs fresh review and retains the complete prior-fingerprint payload, including unmatched history, under its original local key. Exact-fingerprint restores and imports retain their state unchanged. A different review ID is never applied. Imports merge only compatible append-only event chains, keep newer local work, and report stale, conflicting, and unmatched entries. v0.1–v0.3 handoffs remain importable and are exported as v0.4.
- Exported handoffs use portable manuscript labels and optional content hashes; they do not copy absolute local paths, usernames, or confidential folder names from the review package.
- Bundled-review URLs preserve the overview, exact comment or document, evidence item, queue order, and filters; browser Back and Forward restore those views. Free-text search is intentionally excluded from URLs to avoid leaking sensitive terms.
- The menu can keep actions only in the current tab or clear every saved snapshot for the active review. Switching to tab-only mode also removes its saved queue preference.

Canonical review files remain read-only. Local author actions are separate from reviewer severity and rank, with timestamps and append-only events. Notes commit on blur and are also committed immediately before any export; they remain optional while drafting but are required to make a plan ready for handoff. Only a later review can verify resolution or dismiss a challenge. Notes are capped at 10,000 characters per finding, and the viewer keeps in-memory work available with a visible warning if browser persistence is unavailable. Draft, blocked, verification-failed, and receipt-unverified packages carry a persistent package-status warning.

## Publication boundary

Review bundles contain the narrative reports, manuscript, findings, and extracted exhibits. They are confidential unless the operator has separately confirmed they are cleared for publication. Consequently, both `npm run sync-review` and `npm run build` refuse to copy review data without an explicit opt-in:

```bash
ALLOW_PUBLISH=1 npm run build
```

`ALLOW_PUBLISH=1` is an authorization acknowledgment, not a privacy control. Use it only for material that may be exposed in the generated site. For an intentionally bundled local session, run `npm run dev:bundled`; for confidential work, use `npm run dev` and the local file picker. Generated `public/reviews/` and legacy `public/sample-review/` directories are ignored by version control. `npm run clear-review-bundles` removes both source copies and any corresponding assets left in `dist/client/`.

## Verification

```bash
npm run lint
npx tsc --noEmit
npm test
npm run check:release
npm audit
```

The test command performs an explicitly authorized fixture build, runs the viewer and publication-guard tests, and removes the generated public bundles on exit. Bundle synchronization verifies the source finalization receipt, copies its complete canonical artifact inventory without path flattening, then verifies and stages the result before atomically replacing any existing generated bundle. The local viewer and generic build support Node.js 22.14 or later; `.nvmrc` pins the preferred local version (22.22.2). Runtime scripts explicitly enable Node's erasable-TypeScript support so the same commands also work before it became enabled by default in Node 22.18. On runtimes that expose `module.registerHooks`, the same build automatically includes the Cloudflare worker adapter. Older supported runtimes use a security-header-preserving local SSR adapter for previews and tests; that fallback does not replace the Cloudflare deployment adapter.
