# Literature Frontier Protocol

Use live search for every novelty, contribution, citation-support, duplicate-publication, and venue-positioning judgment, subject to the run's confidentiality policy. Never substitute model memory.

Before any outbound query, record `external_search_policy` as `forbidden`, `deidentified`, or `exact_allowed`. Default confidential or unpublished manuscripts to `deidentified`. Exact titles, distinctive phrases, author identities, manuscript identifiers, and unpublished numerical fingerprints require `exact_allowed` permission. Log the exact outbound queries; when the policy forbids a necessary search, mark the affected judgment bounded.

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

Prioritize economics sources and stable records: journal pages, RePEc/IDEAS, NBER, CEPR, SSRN, institutional working-paper pages, Crossref, and author pages. Use Google Scholar for discovery when available, then verify on a stable primary page.

Do not mechanically impose a five-year window. Search older foundational work and recent frontier work; adjust the window to the field's publication cycle.

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

## 4. Verify claim support

For every source named in the report:

1. Verify existence and metadata.
2. Open the abstract or full text from a stable source.
3. State the precise proposition for which the source is being used.
4. Classify support as `supported`, `partially_supported`, `in_conflict`, or `inconclusive_from_source`.
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
