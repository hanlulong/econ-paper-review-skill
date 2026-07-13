# Literature Frontier Protocol

## Contents

- [Structured frontier state](#structured-frontier-state)
- [1. Define the search object](#1-define-the-search-object)
- [2. Search in layers](#2-search-in-layers)
- [3. Build the closest-paper table](#3-build-the-closest-paper-table)
- [4. Verify claim support](#4-verify-claim-support)
- [5. Assess contribution](#5-assess-contribution)
- [6. Duplicate-publication check](#6-duplicate-publication-check)
- [7. Degrade honestly](#7-degrade-honestly)

Use live search for every novelty, contribution, citation-support, duplicate-publication, and venue-positioning judgment, subject to the run's confidentiality policy. Never substitute model memory.

Before any outbound query, record `external_search_policy` as `forbidden`, `deidentified`, or `exact_allowed`. Default confidential or unpublished manuscripts to `deidentified`. Exact titles, distinctive phrases, author identities, manuscript identifiers, and unpublished numerical fingerprints require `exact_allowed` permission. Log the exact outbound queries; when the policy forbids a necessary search, mark the affected judgment bounded.

## Structured frontier state

Current full reviews use `external-sources.json` schema v0.3 and record one frontier status. Schema v0.2 retains the structured frontier-only legacy contract; v0.1 is the older source-ledger contract.

- `complete`: every query family retained in scope was executed, its exact outbound query text is logged, and the closest-paper table contains at least one genuinely close verified source;
- `bounded`: search was attempted or required but permission, systems, metadata, or source access prevented a defensible frontier conclusion; or
- `not_assessed`: the frontier was deliberately outside the authorized assessment scope and no search was attempted.

Both `bounded` and `not_assessed` require a structured boundary stating the affected scope, the effect on the review, and what would complete the check. Use `bounded`, not `not_assessed`, after a partial search. A `complete` state requires at least one closest source, not an arbitrary paper quota. Use as many query families and close comparisons as the question requires.

Each executed query log records the literal string sent to the search system, execution date, system, disclosure classification, and any stable `EXT-*` records retained from the results. Under `deidentified`, do not log or send a query classified as `exact_manuscript_identity`; under `forbidden`, do not execute a query. Exact-title searching is one optional family for public or explicitly authorized manuscripts, not a completion requirement for confidential work.

Each closest-paper row joins to exactly one stable external-source ID. Its citation, question, design or object, and main-result fields each resolve to an exact proposition-support record owned by that source; its main-result support is also the row's primary support record. The overlap and incremental-difference judgments cite the manuscript anchors being compared. Mark the row `bounded` and state the boundary when a load-bearing field has only partial or conflicting support. A complete frontier audit needs at least one complete closest-paper comparison, but it does not impose an arbitrary paper quota. This makes a generic novelty concern insufficient while keeping the comparison fair and auditable.

Every v0.3 proposition-support record names the proposition kind and access scope, points to an exact code-point span in a saved UTF-8 capture, and stores the span hash. `support_state` is still a reviewer judgment; a matching span proves what was captured, not that an arbitrary paraphrase follows from it. An abstract may fully support a narrowly recorded question or main-result statement only when the proposition matches the captured statement. Metadata supports bibliographic metadata, not a substantive result. A source-level absence claim needs a complete full-text scope and a concrete completeness basis. Never encode “no prior work exists” as support from one source; the defensible statement is that no closer result was found within the completed, logged search scope.

Dates must be chronologically possible: source access and query execution cannot postdate the recorded frontier assessment, and the assessment cannot be future-dated. Update the assessment date whenever the source or query ledger is extended.

## 1. Define the search object

Extract:

- economic question and mechanism;
- outcome, treatment or shock, setting, population, and period;
- design, model class, data asset, or theorem;
- claimed contributions and every “first,” “novel,” “unexplored,” or frontier claim;
- three to six distinctive phrases for title and duplicate searches.

## 2. Search in layers

Search several query families rather than one long query:

1. Exact question and closest mechanism.
2. Same design or model applied to the same outcome.
3. Same data or institutional setting.
4. Recent surveys, handbook chapters, and methods papers that define the current standard.
5. Exact title, headline finding plus sample, and title variants for duplicate or prior-version checks only under `exact_allowed`; otherwise use deidentified economic objects and design terms.
6. Subject to the recorded outbound-search policy, the institutional provision, program component, policy instrument, model object, or named measurement object combined with the paper's outcome and mechanism. Use exact names only when the combination is permitted; otherwise deidentify the provision or other distinctive elements.
7. Current-year and recent working-paper searches, then backward and forward citation chaining from the closest verified paper when the search interface permits it.

Prioritize economics sources and stable records: journal pages, RePEc/IDEAS, NBER, CEPR, SSRN, institutional working-paper pages, Crossref, and author pages. Use Google Scholar for discovery when available, then verify on a stable primary page.

Do not mechanically impose a five-year window. Search older foundational work and recent frontier work; adjust the window to the field's publication cycle.

When the manuscript studies an active policy or institution, search both stated or survey outcomes and realized administrative, market, or behavioral outcomes. The latter may bound the paper's contribution or supply a validation opportunity, but its existence does not by itself invalidate a paper about beliefs, communication, measurement, or a distinct mechanism.

## 3. Build the closest-paper table

For each genuinely close paper, record the following in canonical `external-sources.json` and render the readable table from it:

| Field | Content |
|---|---|
| Citation | Verified authors, year, title, outlet/status |
| Stable link | DOI or primary URL |
| Access date | ISO date |
| Question | What it asks |
| Design/object | Data, variation, model, theorem, or method |
| Main result | Only what the source supports |
| Overlap | Exact overlap with the reviewed paper |
| Difference | Exact incremental value of the reviewed paper |
| Confidence | High, medium, or low based on access |

Prefer two accurately characterized papers to a long unverified list.

A completed frontier audit must contain a populated closest-paper table; otherwise use an explicit bounded or not-assessed state tied to search permission, access, or authorized scope. A generic bibliography summary or source list is not evidence that the closest comparison was found. Record query families and why the selected papers are closer than salient alternatives.

## 4. Verify claim support

For every source named in the report:

1. Verify existence and metadata.
2. Open the abstract or full text from a stable source.
3. State the precise proposition for which the source is being used.
4. Classify support as `supported`, `partial`, `conflict`, or `inconclusive`, and state the access scope.
5. Avoid inferring absence of a result from an abstract alone.

Do not cite a paper merely because it shares keywords. Do not imply priority, replication, contradiction, or retraction without direct evidence.

## 5. Assess contribution

Separate:

- question importance;
- data or measurement contribution;
- identification or methodological contribution;
- theoretical or mechanism contribution;
- quantitative or policy contribution;
- external-validity contribution.

Compare the paper to its closest alternatives along the dimension it actually claims. A new setting is not automatically a weak contribution; ask whether it changes the economic answer, mechanism, measurement, or decision relevance.

## 6. Duplicate-publication check

Search exact and near-exact titles, distinctive findings with sample/setting, working-paper series, and author variants when confidentiality permits. Distinguish legitimate earlier drafts, conference versions, companion papers, and true duplication. Treat a match as a private concern until verified.

## 7. Degrade honestly

If search, metadata, full text, or permission is unavailable, record the limitation in structured source state; do not complete the claim from memory. Set the affected judgment to `bounded` or `not_assessed` and remove unsupported named references from the report.
