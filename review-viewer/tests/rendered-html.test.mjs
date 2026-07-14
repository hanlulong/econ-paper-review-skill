import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

async function render() {
  const workerUrl = new URL("../dist/server/index.js", import.meta.url);
  workerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
  let { default: worker } = await import(workerUrl.href);
  if (typeof worker?.fetch !== "function") {
    const localWorkerUrl = new URL("../dist/server/local-worker.js", import.meta.url);
    localWorkerUrl.searchParams.set("test", `${process.pid}-${Date.now()}`);
    ({ default: worker } = await import(localWorkerUrl.href));
  }

  return worker.fetch(
    new Request("http://localhost/", { headers: { accept: "text/html" } }),
    { ASSETS: { fetch: async () => new Response("Not found", { status: 404 }) } },
    { waitUntil() {}, passThroughOnException() {} },
  );
}

test("server-renders the Review Desk shell without starter metadata", async () => {
  const response = await render();
  assert.equal(response.status, 200);
  assert.match(response.headers.get("content-type") ?? "", /^text\/html\b/i);

  const html = await response.text();
  assert.match(html, /<title>Review Desk<\/title>/i);
  assert.match(html, /Opening the review/);
  assert.doesNotMatch(html, /codex-preview|Your site is taking shape|react-loading-skeleton/i);
});

test("ships the evidence-first interaction model", async () => {
  const [workspace, css, packageJson, localPackage, markdownRenderer, actionStorage, evidenceContract, ledgerContract, textEvidencePresentation, locatorFormatter] = await Promise.all([
    readFile(new URL("../app/review-workspace.tsx", import.meta.url), "utf8"),
    readFile(new URL("../app/globals.css", import.meta.url), "utf8"),
    readFile(new URL("../package.json", import.meta.url), "utf8"),
    readFile(new URL("../lib/local-review-package.ts", import.meta.url), "utf8"),
    readFile(new URL("../app/markdown-content.tsx", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-action-storage.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-evidence-contract.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-ledger-contract.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-text-evidence-presentation.ts", import.meta.url), "utf8"),
    readFile(new URL("../lib/review-locator.ts", import.meta.url), "utf8"),
  ]);

  for (const label of [
    "Review overview",
    "Manuscript context",
    "Concern",
    "Suggestions",
    "Ready to close when",
    "Instruction or response",
    "Import actions",
    "Review document reader",
    "Principal concerns",
    "Undo status",
    "Action history",
  ]) assert.match(workspace, new RegExp(label));

  assert.match(workspace, /localStorage/);
  assert.match(actionStorage, /review-desk:v\$\{REVIEW_ACTION_STORAGE_VERSION\}:\$\{encodeURIComponent\(reviewId\)\}:/);
  assert.match(actionStorage, /complete prior payload remains archived/i);
  assert.match(workspace, /source_review_fingerprint: ledgerFingerprint/);
  assert.match(workspace, /sha256Hex\(findingsText\)/);
  assert.match(workspace, /Reviewed by decision/);
  assert.match(workspace, /Reopen this comment before reconsidering the decision/);
  assert.match(workspace, /openFinding\(\s*linkedFinding\.id/);
  assert.match(workspace, /parseReviewUrlState/);
  assert.match(workspace, /addEventListener\("popstate"/);
  assert.match(workspace, /Review files need attention/);
  assert.doesNotMatch(workspace, /Review ready/);
  assert.match(workspace, /No comments are recorded in this review/);
  assert.match(workspace, /Any incomplete checks are identified separately/);
  assert.doesNotMatch(workspace, /Review complete|No active comments remain/);
  assert.match(workspace, /This tab only/);
  const sessionStorageControl = workspace.slice(workspace.indexOf('aria-pressed={persistenceMode === "session"}'), workspace.indexOf('className="danger-text"'));
  assert.doesNotMatch(sessionStorageControl, /clearBrowserReviewActions|localStorage\.removeItem/);
  assert.match(sessionStorageControl, /Existing browser snapshots are unchanged/);
  assert.match(workspace, /missing-exhibit/);
  assert.match(workspace, /source-manifest\.json/);
  assert.match(workspace, /exactAnchorExcerpt\(manuscript, activeSourceAnchor, sha256Hex\)/);
  assert.match(workspace, /evidence\/computations\.json/);
  assert.match(workspace, /validateReviewComputations/);
  assert.match(workspace, /validateReviewComputationLinks/);
  assert.match(workspace, /ComputationProvenance/);
  assert.match(workspace, /sourceAnchorPageLabel\(locator\)/);
  assert.match(workspace, /<dt>Location<\/dt>/);
  for (const label of ["Calculation details", "Inputs checked", "Result", "Method", "Tolerance"]) {
    assert.match(workspace, new RegExp(label));
  }
  assert.doesNotMatch(workspace, /Artifact record/);
  assert.doesNotMatch(workspace, /<dt>SHA-256<\/dt>/);
  assert.match(workspace, /does not rerun the calculation/);
  assert.match(workspace, /Comparison passages/);
  assert.match(workspace, /conciseSourceAnchorLabel/);
  assert.match(workspace, /data-source-anchor=/);
  assert.match(workspace, /evidence\.anchor_ids/);
  assert.match(workspace, /MAX_NOTE_CHARS = 10_000/);
  assert.match(workspace, /maxLength=\{MAX_NOTE_CHARS\}/);
  assert.match(workspace, /setPersistenceWarning/);
  assert.match(workspace, /Export actions/);
  assert.match(workspace, /reconcileReviewActions/);
  assert.match(workspace, /mergeReviewActionEntries/);
  assert.match(workspace, /conflicts kept local/);
  assert.match(actionStorage, /Older legacy actions exist/);
  assert.doesNotMatch(workspace, /Ready for recheck requires a response or changed location|A challenge requires an explanation|returned to open because the evidence required/);
  assert.doesNotMatch(workspace, /setLocalState\(\(current\) => \(\{ \.\.\.current, \.\.\.result\.entries \}\)\)/);
  assert.match(workspace, /review-actions\.json/);
  assert.match(workspace, /ready_for_recheck/);
  assert.match(workspace, /challenged/);
  assert.match(workspace, /workflowDecision\(entry\.disposition\) === status/);
  assert.match(workspace, /<option value="open">Open<\/option>[\s\S]*<option value="ready_for_recheck">Ready for review<\/option>[\s\S]*<option value="deferred">Set aside<\/option>/);
  assert.doesNotMatch(workspace, />Recheck<\/button>|>Challenge<\/button>|>Defer<\/button>|>Not relevant<\/button>|>Not addressable<\/button>/);
  assert.match(workspace, /className=\{`decision-menu/);
  assert.match(workspace, /Reasoned response/);
  assert.match(workspace, /Revisit later/);
  assert.match(workspace, /severity/);
  assert.match(workspace, /validateSynthesis/);
  assert.match(workspace, /synthesis\.json/);
  assert.match(workspace, /openPrincipalConcern/);
  assert.match(workspace, /resolveReviewDocumentLink/);
  assert.match(workspace, /setReportView\(linked\.document\.id\)/);
  assert.match(workspace, /pendingDocumentAnchor/);
  assert.match(markdownRenderer, /markdownHeadingSlug/);
  assert.match(workspace, /report-document-link/);
  assert.match(workspace, /undoLastStatusChange/);
  assert.match(workspace, /The reversal was added to its action history/);
  assert.match(workspace, /decision_role/);
  assert.match(workspace, /Filter by publication relevance/);
  assert.match(workspace, /Ready for review/);
  assert.match(workspace, /Set aside/);
  assert.match(workspace, /report_channel/);
  assert.match(workspace, /Filter by comment category/);
  assert.match(workspace, /return finding\.report_channel === "writing" \? "Editing comments"/);
  assert.match(workspace, /<option value="writing">Editing comments \(\{editingCount\}\)<\/option>/);
  assert.doesNotMatch(workspace, /<option value="writing">Writing/);
  assert.match(workspace, /Filters\{activeFilters/);
  assert.match(workspace, /channelLabel/);
  assert.match(workspace, /lazy\(\(\) => import\("\.\/markdown-content"\)\)/);
  assert.match(workspace, /<Suspense fallback=/);
  assert.match(workspace, /MarkdownRenderBoundary/);
  assert.match(workspace, /Formatted view unavailable/);
  assert.match(workspace, /The original review text remains available below/);
  assert.doesNotMatch(workspace, /from "react-markdown"/);
  assert.match(markdownRenderer, /ReactMarkdown/);
  assert.match(markdownRenderer, /remarkGfm/);
  assert.match(markdownRenderer, /remarkMath/);
  assert.match(markdownRenderer, /rehypeKatex/);
  assert.match(markdownRenderer, /skipHtml/);
  assert.match(workspace, /blocked-report-image/);
  assert.doesNotMatch(workspace, /<span>Possible fix<\/span>/);
  assert.match(workspace, /report\.md/);
  assert.match(workspace, /editing-comments\.md/);
  assert.doesNotMatch(workspace, /writing-report\.md/);
  assert.match(workspace, /Optional context<\/strong><span>Include the manuscript and saved table or figure images when available/);
  assert.match(workspace, /Open a review without uploading it/);
  assert.match(workspace, /Open review folder/);
  assert.doesNotMatch(workspace, /npm run dev:bundled/);
  assert.doesNotMatch(workspace, /run\.paper_family\.replaceAll/);
  assert.match(workspace, /webkitdirectory/);
  assert.match(workspace, /Duplicate relative file paths were selected/);
  assert.match(workspace, /normalizedFilePath/);
  assert.match(workspace, /onDrop=/);
  assert.match(workspace, /mobilePane/);
  assert.match(workspace, /mobile-view-switcher/);
  assert.match(workspace, /evidenceText/);
  assert.doesNotMatch(workspace, /Fairness check|Fairness and verification|Saved locally in this browser|changed-locations/);
  assert.match(workspace, /detailMode.*overview/);
  assert.match(workspace, /Start with the first comment/);
  assert.match(workspace, /Resolve critical comments first, then major comments/);
  assert.match(workspace, /What was reviewed/);
  assert.match(workspace, /What could not be checked/);
  assert.match(workspace, /side-by-side-reader/);
  assert.match(workspace, /sortReviewFindings\(matching, queueOrder\)/);
  assert.match(workspace, />Reviewer priority<\/button>/);
  assert.match(workspace, />Severity<\/button>/);
  assert.doesNotMatch(workspace, />Importance<\/button>/);
  assert.match(workspace, /Paper order/);
  assert.match(workspace, /My revision plan/);
  assert.match(workspace, /revision-tasks\.json/);
  assert.match(workspace, /revision-agent-brief\.md/);
  assert.match(workspace, /revision-response\.template\.json/);
  assert.match(workspace, /Instructions for my editing agent/);
  assert.match(workspace, /Agent response form/);
  assert.match(workspace, /Mark as read and decided/);
  assert.match(workspace, /const marksReviewed = nextStatus !== "open"/);
  assert.match(workspace, /previousReviewed: entry\.reviewed/);
  assert.match(workspace, /Next unreviewed/);
  assert.match(workspace, /Does not apply/);
  assert.match(workspace, /Cannot address/);
  assert.match(workspace, /Filter by reviewed state/);
  assert.match(workspace, /Filter by my priority/);
  assert.match(workspace, /Do not self-declare reviewer findings resolved/);
  assert.match(workspace, /response_only/);
  assert.match(workspace, /commitRevisionNoteDrafts/);
  assert.match(workspace, /handoff_ready/);
  assert.match(workspace, /Comment #\$\{index \+ 1\}/);
  assert.doesNotMatch(workspace, /<h1 className="visually-hidden">Review Desk for \{run\.review_id\}/);
  assert.doesNotMatch(workspace, /Publication role:|Repairability:|Author disposition:/);
  assert.match(workspace, /This is not a complete review folder/);
  assert.match(workspace, /unsupported older or newer version/);
  assert.match(workspace, /Some files changed after the review was generated/);
  assert.match(workspace, /event\.key\.toLowerCase\(\) === "j"/);
  assert.match(workspace, /event\.key\.toLowerCase\(\) === "k"/);
  assert.match(workspace, /aria-keyshortcuts="J K R S N"/);
  assert.match(workspace, /\["ArrowDown", "ArrowUp", "Home", "End"\]/);
  assert.match(workspace, /event\.isComposing/);
  assert.match(workspace, /closest\("input, textarea, select, button, a/);
  const shortcutHandler = workspace.slice(workspace.indexOf("const onKey = (event: globalThis.KeyboardEvent)"), workspace.indexOf("window.addEventListener(\"keydown\", onKey)"));
  assert.ok(shortcutHandler.indexOf("if (event.key === \"Escape\"") < shortcutHandler.indexOf("if (interactive) return;"), "Escape handling must remain available in interactive controls");
  assert.match(shortcutHandler, /topMenu\.current\?\.open/);
  assert.match(shortcutHandler, /reportView !== "none"/);
  assert.ok(shortcutHandler.indexOf("if (interactive) return;") < shortcutHandler.indexOf("event.key.toLowerCase() === \"o\""), "interactive controls must suppress every global letter shortcut");
  assert.doesNotMatch(shortcutHandler, /findingControl|interactive &&/);
  assert.match(workspace, /focusAfterFilter/);
  assert.match(workspace, /nextLedger\.review_id !== nextRun\.review_id/);
  assert.match(workspace, /validateReviewLedger as validateLedger/);
  assert.match(workspace, /value\.target\.venue === null/);
  assert.match(workspace, /formatUserFacingLocator\(value\)/);
  assert.match(locatorFormatter, /value\.paragraph && `para\./);
  assert.match(locatorFormatter, /value\.lines && `lines/);
  assert.doesNotMatch(locatorFormatter, /value\.file/);
  assert.match(evidenceContract, /typeof field === "string"/);
  assert.match(ledgerContract, /raw\.fix\.resolved_when/);
  assert.match(workspace, /value\.target\.venue/);
  assert.match(workspace, /setManuscript\(nextManuscript\)/);
  assert.match(workspace, /contains invalid JSON/);
  assert.match(localPackage, /Multiple manuscript files were selected/);
  assert.match(workspace, /useMemo\(\(\) => \{/);
  assert.match(locatorFormatter, /online appendix/i);
  assert.match(workspace, /filtered\.find\(\(finding\) => finding\.id === selectedId\)/);
  assert.match(workspace, /aria-pressed=/);
  assert.match(workspace, /compact-progress/);
  assert.match(workspace, /\{index \+ 1\}\. \{readableState\(item\.type\)\}/);
  assert.match(workspace, /exhibit-preview/);
  assert.match(workspace, /render-switcher/);
  assert.match(workspace, /Open full size/);
  assert.match(workspace, /target="_blank"/);
  assert.match(workspace, /reviews\/index\.json/);
  assert.match(workspace, /Choose bundled review/);
  assert.match(workspace, /entry\.base_path/);
  assert.match(workspace, /aria-busy=\{isReviewLoading\}/);
  assert.match(workspace, /loadedReviewSlug/);
  assert.match(workspace, /response\.ok/);
  assert.match(workspace, /Filter by review dimension/);
  assert.match(workspace, /locator\(selected, activeEvidenceIndex\)/);
  assert.match(workspace, /selected\.evidence\[activeEvidenceIndex\]/);
  assert.match(workspace, /The active filters exclude every finding/);
  assert.match(workspace, /tabIndex=\{finding\.id === selected\.id \? 0 : -1\}/);
  assert.match(localPackage, /inferReviewPackageRoot/);
  assert.doesNotMatch(localPackage, /reviewMatch|folder named review/i);
  assert.match(workspace, /manifestValue !== null/);
  assert.match(workspace, /validateReviewDocumentManifest\(manifestValue\)/);
  assert.match(workspace, /MAX_SELECTED_FILE_COUNT/);
  assert.match(workspace, /localLoadSequence/);
  assert.match(workspace, /const sequence = \+\+localLoadSequence\.current/);
  assert.match(workspace, /cancelled \|\| sequence !== localLoadSequence\.current/);
  assert.match(workspace, /stagedObjectUrls/);
  assert.match(workspace, /for \(const url of stagedObjectUrls\) URL\.revokeObjectURL\(url\)/);
  assert.match(workspace, /matchReferencedImagePaths/);
  assert.match(workspace, /summary, \[contenteditable/);
  assert.match(workspace, /reportView !== "none" \|\| !filtered\.length/);
  assert.match(workspace, /openMobilePane/);
  assert.match(workspace, /ref=\{evidenceHeading\} tabIndex=\{-1\}/);
  assert.match(workspace, /EquationEvidence/);
  assert.match(workspace, /View raw equation/);
  assert.match(workspace, /View raw evidence/);
  assert.match(workspace, /equationEvidencePresentation/);
  assert.match(workspace, /EvidenceSemanticFrame/);
  assert.match(workspace, /<EvidenceSemanticFrame representation=\{evidence\?\.representation\}/);
  assert.doesNotMatch(workspace, /support_record_id|Support record/);
  assert.match(workspace, /evidence\?\.type === "equation"/);
  assert.match(workspace, /\["code", "table_cell"\]\.includes/);
  assert.doesNotMatch(workspace, /quote-mark/);
  assert.match(textEvidencePresentation, /verbatim:\s*"Verbatim source excerpt"/);
  assert.match(textEvidencePresentation, /reviewer_observation:\s*"Reviewer observation"/);
  assert.match(textEvidencePresentation, /createElement\("blockquote"/);
  assert.match(textEvidencePresentation, /role:\s*"note"/);
  assert.match(css, /prefers-reduced-motion/);
  assert.match(css, /\.report-reader/);
  assert.match(css, /\.report-document \.katex-display/);
  assert.match(css, /\.welcome-card/);
  assert.match(css, /\.mobile-hidden/);
  assert.match(css, /@media \(pointer: coarse\)/);
  assert.match(css, /:focus-visible/);
  assert.match(css, /\.workspace-grid\s*\{[^}]*grid-template-columns:\s*340px minmax\(0, 1fr\)/);
  assert.match(css, /\.app-shell\s*\{\s*height:\s*100vh/);
  assert.doesNotMatch(css, /\.evidence-sheet blockquote\s*\{/);
  assert.match(css, /\.evidence-sheet \.source-excerpt\s*\{[^}]*white-space:\s*pre-wrap/);
  assert.match(css, /\.document-pane\s*\{[^}]*display:\s*none/);
  assert.match(css, /outline:\s*3px solid #0b6b63/);
  assert.match(css, /\.topbar\s*\{[^}]*height:\s*56px/);
  assert.match(css, /\.topbar\s*\{[^}]*grid-template-columns:\s*auto minmax\(180px, 420px\) minmax\(0, 1fr\) auto/);
  assert.match(css, /\.header-review-picker select\s*\{[^}]*max-width:\s*420px/);
  assert.match(css, /\.compact-evidence-block\s*\{\s*display:\s*grid/);
  assert.match(css, /\.filter-popover/);
  assert.match(css, /\.rail-controls\s*\{[^}]*position:\s*sticky/);
  assert.match(css, /\.author-action-bar\s*\{[^}]*position:\s*static/);
  assert.match(css, /\.comment-pane\s*\{[^}]*grid-template-rows:\s*minmax\(0, 1fr\) auto/);
  assert.match(css, /\.document-pane:not\(\.mobile-hidden\)\s*\{\s*display:\s*flex/);
  assert.match(workspace, /data-testid="compact-header"/);
  assert.match(workspace, /data-testid="comment-scroll"/);
  assert.match(workspace, /data-testid="author-action-dock"/);
  assert.match(workspace, /data-testid="evidence-context"/);
  assert.match(workspace, /<nav className="finding-list" aria-label=/);
  assert.doesNotMatch(workspace, /className="finding-list" role="listbox"|role="option"|aria-controls="comment-panel evidence-panel"/);
  assert.match(workspace, /<button className="overview-link" onClick=\{openOverview\}/);
  assert.match(workspace, /aria-current=\{detailMode === "overview"/);
  assert.match(workspace, /className="skip-link" href="#review-detail">Skip to review detail/);
  assert.doesNotMatch(workspace, /href="#comment-panel"/);
  assert.ok((workspace.match(/id="review-detail"/g) || []).length >= 5, "every conditional detail view needs the stable skip-link target");
  assert.doesNotMatch(workspace, /className="verdict-band"|className="progress-strip"/);
  assert.doesNotMatch(workspace, /Canonical review says verification passed|Venue not specified|Evidence-first revision/);
  assert.match(workspace, /Open evidence context/);
  assert.match(workspace, /report-toolbar/);
  assert.doesNotMatch(workspace, /review-desk:orientation|matchMedia\("\(min-width: 761px\)"\)/);
  assert.match(workspace, /review-desk:queue-order/);
  assert.match(workspace, /event\.key === "Escape" && mobilePane === "evidence"/);
  assert.match(workspace, /topMenu\.current\.open = false/);
  assert.match(workspace, /reportBackButton\.current\?\.focus/);
  assert.doesNotMatch(workspace, /role="dialog" aria-modal="false"/);
  assert.doesNotMatch(css, /\.orientation-strip/);
  assert.match(css, /\.overview-link\s*\{[^}]*min-height:\s*52px/);
  assert.match(css, /env\(safe-area-inset-bottom\)/);
  assert.match(css, /@media print/);
  assert.match(css, /\.comment-pane\s*\{[^}]*height:\s*calc\(100% - 49px\)/);
  assert.match(css, /\.comment-title-row h2:focus-visible\s*\{[^}]*outline:\s*none[^}]*text-decoration-color:\s*var\(--teal\)/);
  assert.match(css, /\.workspace-actions button\s*\{[^}]*min-height:\s*44px/);
  assert.match(css, /\.workspace-grid\s*\{[^}]*--author-action-dock-height:\s*58px/);
  assert.match(css, /\.document-pane\s*\{[^}]*inset:\s*0 0 var\(--author-action-dock-height\) auto/);
  assert.match(css, /\.author-action-bar\s*\{[^}]*z-index:\s*13[^}]*height:\s*var\(--author-action-dock-height\)/);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.document-pane\s*\{[^}]*position:\s*static/);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.compact-review-summary\s*\{[^}]*display:\s*none/);
  assert.match(css, /@media \(max-width:\s*760px\)[\s\S]*\.comment-heading\s*\{[^}]*flex-direction:\s*column/);
  assert.match(css, /\.decision-block p[^}]*max-width:\s*68ch/);
  assert.match(css, /\.severity-pill\.severity-critical\s*\{[^}]*background:\s*var\(--critical\)/);
  assert.match(css, /\.severity-pill\.severity-major\s*\{[^}]*background:\s*var\(--coral-soft\)/);
  assert.match(css, /\.status-dot\s*\{[^}]*border:\s*2px solid #737e83/);
  assert.match(css, /\.revision-plan-pane/);
  assert.match(css, /\.personal-priority-control/);
  assert.match(css, /\.reviewed-toggle\.active/);
  assert.match(css, /\.status-not_relevant/);
  assert.match(css, /\.status-not_addressable/);
  assert.match(css, /\.filter-help\s*\{[^}]*color:\s*#5c686d/);
  assert.match(css, /\.exhibit-image-link/);
  assert.match(css, /\.comparison-source-switcher/);
  assert.match(css, /\.computation-provenance/);
  assert.match(css, /@media \(max-width: 1080px\) and \(min-width: 761px\)/);
  assert.match(css, /\.equation-render \.katex-display/);
  assert.match(css, /\.equation-render-prose/);
  assert.match(css, /\.equation-evidence\s*\{[^}]*max-width:\s*100%[^}]*overflow:\s*hidden/);
  assert.match(css, /\.evidence-note\s*\{[^}]*background:\s*#f1f2ef[^}]*border-left:\s*3px solid #7d8a8d/);
  assert.match(css, /\.compact-evidence-block \.source-excerpt/);
  assert.doesNotMatch(css, /\.quote-mark/);
  assert.match(css, /overflow-wrap:\s*anywhere/);
  assert.doesNotMatch(packageJson, /react-loading-skeleton/);
  assert.match(packageJson, /remark-math/);
  assert.match(packageJson, /rehype-katex/);
});

test("serves baseline local-only security headers", async () => {
  const response = await render();
  assert.match(response.headers.get("content-security-policy") ?? "", /frame-ancestors 'none'/);
  assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(response.headers.get("referrer-policy"), "no-referrer");
  assert.match(response.headers.get("permissions-policy") ?? "", /camera=\(\)/);
});

test("the authorized bundled fixture is synthetic and internally consistent", async () => {
  const registry = JSON.parse(await readFile(new URL("../public/reviews/index.json", import.meta.url), "utf8"));
  assert.equal(registry.default_review, "synthetic-theory-v03");
  assert.deepEqual(registry.reviews.map((review) => review.slug), ["synthetic-theory-v03"]);

  for (const entry of registry.reviews) {
    const base = new URL(`../public/reviews/${entry.slug}/`, import.meta.url);
    const [ledger, run, synthesis, sourceManifest, computations, manuscript, startHere, report, editingComments, tables, figures, finalization] = await Promise.all([
      readFile(new URL("findings.json", base), "utf8").then(JSON.parse),
      readFile(new URL("run.json", base), "utf8").then(JSON.parse),
      readFile(new URL("synthesis.json", base), "utf8").then(JSON.parse),
      readFile(new URL("evidence/source-manifest.json", base), "utf8").then(JSON.parse),
      readFile(new URL("evidence/computations.json", base), "utf8").then(JSON.parse),
      readFile(new URL("synthetic-paper.md", base), "utf8"),
      readFile(new URL("README.md", base), "utf8"),
      readFile(new URL("report.md", base), "utf8"),
      readFile(new URL("editing-comments.md", base), "utf8"),
      readFile(new URL("evidence/tables.json", base), "utf8").then(JSON.parse),
      readFile(new URL("evidence/figures.json", base), "utf8").then(JSON.parse),
      readFile(new URL("finalization.json", base), "utf8").then(JSON.parse),
    ]);
    const active = ledger.findings.filter((finding) => !["dismissed", "resolved"].includes(finding.status));
    assert.equal(ledger.review_id, run.review_id);
    assert.equal(synthesis.review_id, run.review_id);
    assert.equal(sourceManifest.review_id, run.review_id);
    assert.equal(computations.review_id, run.review_id);
    assert.equal(finalization.review_id, run.review_id);
    assert.equal(finalization.contract_version, "0.4");
    assert.ok(finalization.artifacts["evidence/source-manifest.json"]);
    assert.equal(new Set(computations.computations.map((row) => row.id)).size, computations.computations.length);
    assert.ok(sourceManifest.anchors.length > 0);
    assert.equal(active.length, run.counts.critical + run.counts.major + run.counts.minor + run.counts.info);
    assert.equal(run.schema_version, "0.4");
    assert.equal(active.length, 2);
    assert.match(manuscript, /Boundary Case in a Static Signaling Model/);
    assert.match(startHere, /Start here/i);
    assert.match(report, /Detailed Comments \(1\)/);
    assert.match(editingComments, /^# Editing comments$/m);
    assert.match(editingComments, /Detailed Editing Comments \(1\)/);
    assert.deepEqual(new Set(active.map((finding) => finding.report_channel)), new Set(["substance", "writing"]));
    assert.doesNotMatch(manuscript, /Place-Based Green|Racial Inequality in Housing/);
    for (const row of [
      ...tables.tables.map((value) => ({ paths: value.rendered_assets?.map((asset) => asset.path) || value.render_paths })),
      ...figures.figures.map((value) => ({ paths: value.rendered_assets?.map((asset) => asset.path) || value.extraction_paths })),
    ]) {
      assert.ok(row.paths.length > 0);
      for (const path of row.paths) await readFile(new URL(path, base));
    }
    const normalize = (kind, label) => label
      .replace(new RegExp(`^Appendix\\s+${kind}\\s+`, "i"), "")
      .replace(new RegExp(`^${kind}\\s+`, "i"), "")
      .split(":", 1)[0]
      .trim()
      .toLowerCase();
    const tableKeys = new Set(tables.tables.map((row) => normalize("Table", row.label)));
    const figureKeys = new Set(figures.figures.map((row) => normalize("Figure", row.label)));
    const exhibitEvidence = active.flatMap((finding) => finding.evidence).filter((item) => ["table_cell", "figure"].includes(item.type));
    for (const item of exhibitEvidence) {
      const kind = item.type === "figure" ? "Figure" : "Table";
      const keys = item.type === "figure" ? figureKeys : tableKeys;
      assert.ok(keys.has(normalize(kind, item.locator.exhibit)), `missing ${item.type} join for ${entry.slug}: ${item.locator.exhibit}`);
    }
  }

});
