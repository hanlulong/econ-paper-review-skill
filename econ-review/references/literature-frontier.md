# Literature and Contribution Verification

## Contents

- [Operating state](#operating-state)
- [1. Inventory the claims](#1-inventory-the-claims)
- [2. Search through complementary routes](#2-search-through-complementary-routes)
- [3. Screen candidates and resolve versions](#3-screen-candidates-and-resolve-versions)
- [4. Verify sources and author attributions](#4-verify-sources-and-author-attributions)
  - [Capture exact support safely](#capture-exact-support-safely)
- [5. Compare contributions fairly](#5-compare-contributions-fairly)
- [6. Decide whether a missing paper matters](#6-decide-whether-a-missing-paper-matters)
- [7. Stop only at documented closure](#7-stop-only-at-documented-closure)
- [8. Write constructive findings](#8-write-constructive-findings)

In a full review, literature and contribution verification is a core stage whenever a confidentiality-safe search is authorized. It covers the manuscript's material novelty, contribution, priority, attribution, and load-bearing citation claims. If permission, search systems, or source access prevents that work, mark the affected claim `bounded`; do not replace live evidence with model memory. A quick review may narrow the claim set to the central contribution, but it must state that boundary.

Before any outbound query, record `search_confidentiality` as `forbidden`, `deidentified`, or `exact_allowed`. Default confidential or unpublished manuscripts to `deidentified`. Exact titles, distinctive phrases, author identities, manuscript identifiers, and unpublished numerical fingerprints require `exact_allowed` permission. Log the literal outbound query, date, system, disclosure class, and retained result IDs. Under `forbidden`, execute no query. When deidentification makes a necessary search uninformative, bound the judgment rather than disclose the manuscript.

## Operating state

Current full reviews record the frontier in `external-sources.json` schema v0.4 as:

- `complete`: every material claim is mapped to adequate search routes; every plausibly close result has been screened; work versions and chronology are resolved as far as the evidence permits; load-bearing comparisons and attributions are source-verified; and the stopping rule below is satisfied;
- `bounded`: search was attempted or required, but permission, systems, metadata, chronology, or source access prevents a defensible conclusion; or
- `not_assessed`: literature verification was outside the authorized scope and no search was attempted.

Both `bounded` and `not_assessed` require a structured boundary naming the affected claims, the consequence for the review, and what would complete the check. Use `bounded`, not `not_assessed`, after a partial search. There is no required paper count: one verified antecedent may defeat an absolute priority claim, while a broad contribution may require many screened candidates. A source list without claim coverage, screening decisions, and search closure is not a complete frontier.

The v0.4 join is compact but explicit:

- `claim_assessments` links each literature-facing statement to `internal_claim_ids`, exact `manuscript_anchor_ids`, query families, sources under assessment when applicable, an assessment, its reason, a fair restatement, and finding links;
- `query_families` and `claim_search_coverage` record discovery routes and reciprocal claim coverage;
- `candidate_screening` records every retained plausible result, including exclusion and version-duplicate decisions, plus any exact insertion anchor and positioning change;
- `work_families` resolves intellectual works across versions and preserves the earliest public date;
- `literature_comparisons` permits several claim-specific, dimension-specific comparisons to the same source; and
- `search_closure` records screened and unresolved candidates, citation chaining, current-frontier coverage, the final expansion rounds, and the stopping basis.

Each external source has one stable `EXT-*` ID. Exact proposition-support records attach substantive statements to a saved UTF-8 support span, access scope, and span hash. A matching span proves what was captured, not that an arbitrary interpretation follows from it. Dates must be chronologically possible, and the assessment date must be updated when the query or source ledger changes.

Every internal claim family explicitly records `literature_facing`. Mark it true for every material contribution, novelty, priority, attribution, coverage, citation-support, contradiction, or replication statement, whether or not it is a headline claim. A false value requires a short exclusion basis. A complete or bounded frontier must map every true claim, and each literature assessment must cite an exact anchor belonging to every internal claim it maps.

## 1. Inventory the claims

Anchor every material literature-facing statement before searching, including:

- priority or superlative claims such as “first,” “novel,” “only,” “unexplored,” or “most comprehensive”;
- statements of the gap, closest literature, and incremental contribution;
- claims that another author establishes, assumes, measures, omits, contradicts, or leaves unresolved;
- claims about accepted methods, standard findings, replication, contradiction, or the state of evidence; and
- citations carrying a premise, mechanism, calibration, identification choice, or interpretation needed by the paper's own argument.

For each claim, record its manuscript anchor, exact scope and qualifiers, claim type, contribution dimensions, search routes, candidate sources, verdict, fair restatement, and any resulting finding. Do not collapse several distinct “first” or attribution claims into one generic novelty judgment.

Use a common comparison spine that works across designs:

- economic question and object;
- mechanism, model restriction, or causal/descriptive channel;
- evidence object: data, variation, experiment, theorem, model, measurement, calibration, or prediction task;
- main result, sign, magnitude, welfare or equilibrium implication, and uncertainty where relevant;
- population, market, institution, geography, and period;
- decision, policy, or scientific relevance.

Add only claim-specific dimensions activated by the paper: estimand and identifying variation for causal work; measurement target and validation for descriptive work; assumptions, equilibrium concept, proposition, and proof domain for theory; moments, identification, fit, counterfactual, and solution method for structural work; dynamics, aggregation, policy rule, and transition path for macro work; target, loss function, split, benchmark, calibration, and transportability for prediction or machine learning; and all applicable dimensions for mixed papers. These are comparison prompts, not fixed checklists.

## 2. Search through complementary routes

Build a claim-to-search matrix and use several routes that fail differently:

1. The manuscript's bibliography and the papers it presents as closest.
2. Concept, question, mechanism, result, and economic-object searches using synonyms and field vocabulary.
3. Design, model, estimand, data, institutional setting, or policy-instrument searches activated by the claim.
4. Surveys, handbook chapters, review articles, and recent field overviews as maps to terminology and foundational work, not as substitutes for primary sources.
5. Backward references and forward citations from the closest verified candidates.
6. Recent journal and working-paper searches appropriate to the field's publication lag.
7. Author, title, phrase, and version searches for chronology or duplicate checks only when the outbound policy permits them.

After the claim inventory is stable, batch overlapping claims into shared query families and run independent metadata, repository, citation-chain, and primary-source retrieval routes concurrently when access permits. Reuse a verified work-family record across claims, but keep claim-specific screening, overlap, and disposition rows. Parallel retrieval reduces waiting time; it does not replace the two zero-yield expansion rounds or permit a discovery index to stand in for the primary source.

Search older foundations and the current frontier; do not impose a mechanical date window, journal list, or database quota. For active policies or institutions, distinguish stated or survey outcomes from realized administrative, market, or behavioral outcomes. The latter may change positioning or suggest validation, but does not automatically invalidate a paper about beliefs, communication, measurement, or another mechanism.

For broad contribution, novelty, priority, coverage, contradiction, or replication claims, complete coverage includes the manuscript bibliography, a concept or economic-object route, a mechanism/model/design/evidence route, and a current-frontier route through recent working papers, publications, books, or field syntheses as appropriate. For a named attribution or citation-support claim, complete coverage includes the manuscript bibliography and an author/version route. These are claim-level search burdens, not empirical or theoretical design checklists.

No particular database or API is mandatory. Route searches according to access and field coverage, then verify substantive claims in the primary paper:

- [EconLit](https://www.aeaweb.org/econlit/) for economics-indexed discovery and subject classification;
- [IDEAS/RePEc search](https://ideas.repec.org/search.html) and the [RePEc Author Service](https://authors.repec.org/about) for economics working papers, publication records, and author disambiguation;
- [OpenAlex Works](https://developers.openalex.org/api-reference/works/list-works) for broad concept, citation, related-work, and status discovery;
- [Crossref REST API](https://www.crossref.org/documentation/retrieve-metadata/rest-api/) for DOI metadata, bibliographic matching, relations, and update records; and
- [Semantic Scholar APIs](https://api.semanticscholar.org/api-docs/) as an optional discovery and citation-chaining route, subject to its current access terms and licence.

Journal pages, DOI landing pages, established working-paper repositories, and author-hosted manuscripts may be the best primary records. Search indexes and metadata services are discovery aids; they do not by themselves support a substantive characterization.

## 3. Screen candidates and resolve versions

Keep a candidate ledger for every plausibly close result, including candidates later excluded. Record:

- source ID, discovery query or route, and claims screened;
- relation: `closest`, `material_adjacent`, `method_or_data_precedent`, `context`, `not_close`, or `unresolved`;
- exact overlap and surviving difference on the activated comparison dimensions;
- manuscript citation status and any characterization problem;
- temporal relation to a reasonable manuscript cutoff;
- work-family ID, screening decision, and concrete inclusion or exclusion reason; and
- next action: compare directly, add or correct a citation, distinguish the contribution, resolve access/version, or take no action.

Screen at the source-claim level. The same paper may be credited fairly for one proposition and mischaracterized for another, so separate rows when citation status, materiality, disposition, or repair differs. A material row must compare the source with every affected claim and cover every activated comparison dimension, including dimensions on which the reviewed paper remains distinct.

Do not hide excluded candidates or prefer papers that make the manuscript look stronger. An exclusion such as “different setting” is insufficient when the setting is not material to the contribution; state why the difference prevents the source from changing the claim.

Group working paper, preprint, conference, accepted, published, corrected, and retracted records that represent the same work. Distinguish a version from a companion paper and from genuinely distinct work. Record the earliest verifiable public date, the version containing the relevant proposition, the preferred current citation, and unresolved chronology. Priority turns on the earliest documented public version that contains the overlapping contribution, not automatically the journal publication year. Use correction or retraction notices when they alter source status. A legitimate earlier draft or companion paper is not duplicate publication.

For each genuinely close work, retain verified citation, stable link, access date, question, evidence/design object, main result, overlap, incremental difference, temporal relation, and confidence. Prefer accurate characterization to a long decorative list.

Write `source_contribution`, `overlap`, and `surviving_difference` as complete standalone sentences. The first must tell the reader what the prior work studies, how it learns about the object, and the result relevant to the comparison; the second states the exact shared dimensions; the third identifies an economically or scientifically meaningful difference without assuming that any different sample, setting, or method is automatically a contribution. Avoid audit shorthand and fragments that only become grammatical when attached to a stock clause.

## 4. Verify sources and author attributions

Use the strongest lawful source available:

1. Full primary paper plus any correction, retraction, appendix, or version needed for the proposition.
2. An official journal or established working-paper version when full text is lawfully accessible.
3. Abstract or executive summary for a narrow proposition it actually states.
4. Authoritative metadata records for authors, title, dates, DOI, version relations, and publication status only.
5. Surveys or secondary accounts for synthesis, with the underlying primary paper checked when a claim is disputed or load-bearing.

For every source named in an author-facing finding:

1. Verify authors, title, date/version, outlet or status, and stable identifier.
2. State the exact proposition for which the source is used.
3. Record access scope and classify support as `supported`, `partial`, `conflict`, or `inconclusive`.
4. Check the proposition's subject, action, object, direction, magnitude, conditions, population, period, and certainty against the manuscript's wording.
5. Separate “the source does not establish this” from “the manuscript characterizes the source unfairly.”

Bind ordered authors, title, identifiers, source type, venue, publication and first-public dates, metadata provenance, and record status to an exact hashed metadata support span. The span is a canonical JSON projection of those fields, deep-compared with the structured ledger; one projection may support every field. Work-family membership is a derived relation and requires support from every member record. Generate names in comparisons from the bound source metadata, not free-form citation prose.

Metadata cannot support a substantive result. An abstract can support only a proposition that it states at the same scope; do not infer that a full paper omits a result from its abstract. A critical or major novelty, contradiction, replication, or mischaracterization finding requires the relevant full text and defensible chronology. If access is insufficient, bound the claim.

Capture only the metadata and shortest exact support span needed for auditability, with its provenance and hash. Respect copyright, licences, repository terms, robots rules, and access controls; do not bypass a paywall or redistribute a full copyrighted work merely to preserve evidence.

### Capture exact support safely

Use `scripts/capture_external_source.py` to build a source record instead of calculating snapshot offsets by hand. Give it a JSON spec containing the review policy, the source fields, and one or more exact captures. For example:

```json
{
  "review_id": "review-001",
  "search_confidentiality": "deidentified",
  "source": {
    "id": "EXT-01",
    "title": "A Prior Result",
    "stable_id": "doi:10.1234/example",
    "url": "https://doi.org/10.1234/example",
    "accessed_at": "2026-07-14",
    "snapshot_kind": "source_capture",
    "snapshot_path": "evidence/external/EXT-01.txt"
  },
  "captures": [{
    "support_record": {
      "id": "EXT-01-SUP-01",
      "proposition": "The source reports the stated result.",
      "proposition_kind": "reported_main_result",
      "support_state": "supported",
      "access_scope": "full_text",
      "locator": "Result section, first paragraph"
    },
    "excerpt": "The shortest exact source passage needed for support."
  }]
}
```

Run the command without write flags first. The helper requires `spec.review_id` to match the target review identity in `run.json` and/or `findings.json`; if both files exist, their identities must also agree. It then stages LF-only UTF-8 bytes, re-reads the staged file, derives character spans and hashes from those bytes, validates the source definition plus trust-spine support joins, prints the v0.4 fragment, and changes no package file:

```text
REVIEW_PYTHON scripts/capture_external_source.py REVIEW_DIR capture-spec.json
```

For deliberate fragment construction before a review directory exists, use `--standalone`. This exception is explicit, dry-run only, and cannot be combined with `--write`; once a target review exists, its identity is still enforced.

After inspecting the fragment, add `--write` to atomically create the snapshot. Add `--fragment-path evidence/external/EXT-01.source.json` to retain the validated fragment as a sidecar. Existing destinations are refused unless `--replace-existing` is also explicit. The helper does not silently merge `external-sources.json`; merge the emitted source deliberately, complete work-family/frontier links, and run full package validation.

To bind structured bibliography fields, add the complete `bibliographic_metadata` object to `source` but omit `field_support_record_ids`, then add `metadata_projection` with a `support_record_id` and locator. The helper writes one sorted, compact canonical JSON projection, maps every required metadata field to it, and validates the deep field values immediately. Do not use a metadata projection for substantive results.

## 5. Compare contributions fairly

Assess each manuscript claim separately. Possible verdicts are:

- supported within the documented scope;
- supported if narrowed;
- literature positioning is incomplete but the contribution survives;
- materially overstated;
- contradicted by a verified antecedent; or
- bounded by search, access, or chronology.

Compare the paper to the closest alternatives on the dimensions it actually claims. A new setting is not automatically weak: ask whether it changes the economic answer, mechanism, measurement, external validity, equilibrium, or decision relevance. Likewise, shared data, method, or setting alone does not establish that two papers make the same contribution.

Audit credit generously but exactly. Preserve the prior paper's qualifiers and distinguish what it establishes, suggests, assumes, measures, or leaves open. Also state the reviewed paper's genuine surviving difference. Never turn overlap on one dimension into a global “not novel” verdict.

Keep the canonical comparison at the source-claim level because one work may bear differently on several manuscript claims. In the author-facing report, synthesize those rows by intellectual work or resolved work family. Name one preferred version, describe the work once, combine only distinct overlap and difference sentences, and then assess each manuscript claim once. A source appearing in several claim rows or several versions must not appear repeatedly as if it were several papers.

One verified antecedent can falsify an absolute “first” claim. No finite search can prove universal priority. The strongest defensible positive conclusion is: “No closer antecedent was found within the documented search scope as of [date].”

## 6. Decide whether a missing paper matters

A not-cited work becomes an author-facing concern only when all of the following hold:

- it is distinct from a version already cited;
- it predates a reasonable manuscript literature cutoff, or the manuscript has otherwise undertaken to cover that period;
- verified overlap bears on a central novelty, contribution, credit, method, or interpretation claim; and
- adding or discussing it would materially change the claim, comparison, or reader's understanding.

Classify a post-cutoff source as a frontier update, not an author omission. Treat genuinely contemporaneous independent work neutrally as parallel work unless evidence supports a priority statement. Material adjacent work may merit a suggested citation; context-only work is optional. Do not manufacture a “missing literature” comment from keyword similarity, prestige, or a desire to lengthen the bibliography.

When citation is warranted, name the precise proposition it supports, the manuscript claim it changes, and the best insertion point. Adding a citation without narrowing or distinguishing an overstated claim is not a sufficient fix.

## 7. Stop only at documented closure

Search may stop without a fixed paper count only when all of these conditions hold:

1. Every material claim in the inventory has completed or explicitly bounded search coverage.
2. Complementary concept/object and design/model/evidence routes have been run, with backward and forward chaining from salient candidates when available.
3. Every plausibly close result retained from those routes is screened and every exclusion has a concrete reason.
4. Work families, public dates, and material chronology are resolved or explicitly bounded.
5. Current-frontier coverage is complete through claim-appropriate working-paper, publication, book, or synthesis routes, and two successive reasonable expansion rounds—new synonyms, citation chains, surveys, authors, or repositories as appropriate—use distinct logged searches and produce no new `closest` or `material_adjacent` work.
6. No unresolved candidate could reasonably change a novelty, attribution, or missing-citation verdict.

Record the route coverage, expansion rounds, unresolved items, stopping basis, and assessment date. A paper count, time limit, or one empty query is not closure. If a condition cannot be met, preserve completed work and set the affected claims and frontier state to `bounded`.

## 8. Write constructive findings

Report a literature concern only after the relevant manuscript claim, external proposition, chronology, and overlap have been verified. In the standard detailed-comment structure:

- **Issue** names the claim-specific problem and consequence without a generic instruction to “engage more literature.”
- **Relevant text** quotes the manuscript claim; add a compact source-supported comparison when needed, clearly labeled as external evidence rather than manuscript text.
- **Concern** explains the exact overlap, why it affects novelty, credit, or interpretation, and what contribution remains.
- **Suggestions** gives the minimum proportionate repair: narrow a sentence, correct an attribution, add and place a comparison, explain a difference, or resolve an uncertain version. Separate required corrections from optional context.
- **Status** appears last.

Use fair temporal language, avoid allegations of intent, and state what evidence would change the assessment. If search found no material problem, preserve the checked-clean claim coverage in canonical evidence; do not invent a comment to display the work.

When one or more verified public comparators materially change the contribution assessment, add `## Closest literature and key differences` after `## Is the argument convincing?` and before the detailed comments. Start with the bottom-line contribution judgment. Then discuss each distinct intellectual work once: explain its question, evidence or model, relevant result, exact overlap, and the difference that may leave room for the reviewed paper. Close by stating whether each material manuscript claim is supported, convincing only after narrowing, incompletely positioned, overstated, contradicted, or bounded; give the strongest fair restatement and the minimum concrete revision from the claim and screening ledgers.

Write `fair_restatement` as the actual sentence the author could substitute for the disputed claim, not as an instruction such as “narrow this claim.” Put the editing instruction in `recommended_change`. Keep author-facing rationales free of source IDs, ledger codes, and workflow terminology.

Write this section as ordinary referee prose, not as an audit log or annotated bibliography. Avoid repeated stock clauses such as “the overlap is specific” or “the reviewed paper remains distinct because.” Do not repeat one work for each claim, and do not repeat the full comparison inventory in a detailed comment. Do not replace named work with “deidentified checks found prior work”: deidentification governs outbound queries, not disclosure of verified public results to the author. Keep background, context-only, partial, conflicting, or inconclusive comparisons out of affirmative prose.
