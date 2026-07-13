# Exhaustive Audit Protocol

Use this protocol in `full` mode. Keep the editorial synthesis selective while making the detailed-comment inventory comprehensive. Apply no length limit to the report or to an individual comment; use enough space to establish the evidence, consequence, fairness, and fix.

## Contents

- [Comment policy](#1-set-the-comment-policy)
- [Coverage matrix and canonical ownership](#2-build-the-coverage-matrix)
- [Independent candidate generation](#3-generate-candidates-independently)
- [Admission, refutation, and deduplication](#4-admit-real-minor-issues)
- [Ranking and second sweep](#6-rank-all-survivors)
- [Detailed-comment verification](#8-verify-every-detailed-comment)

## 1. Set the comment policy

Record in `run.json.comment_policy`:

- `minimum_target`: the user's requested minimum; use `0` when none is requested. Do not infer a target from paper family or a universal number.
- `maximum`: `null`. A current full review has no comment cap. If the user requests a fixed-size deliverable, use `quick` mode or clarify the conflict rather than silently calling a truncated inventory exhaustive.
- `exhaustive`: set `true` only after completing source-derived coverage and any sweep triggered by the conditions below.

A minimum is a search and coverage obligation, not permission to invent issues. If fewer comments survive after the required sweeps, ship fewer and record a source-specific shortfall rather than padding. That documented shortfall is valid completion evidence when source coverage and every activated burden are otherwise complete.

## 2. Build the coverage matrix

Build source-derived review units in `review/evidence/coverage.json` for every material object represented by the authenticated source inventory, including, when present:

- title, abstract, main section, and subsection;
- table, figure, numbered equation, and proposition;
- footnote cluster containing substantive content;
- reference list and data/code availability statement;
- appendix section, table, figure, and technical derivation.

For each unit record `checked_no_issue`, finding IDs, `bounded`, or `not_applicable`, plus its source and anchor IDs. Every internal source—manuscript, appendix, supplement, supplied code, and supplied data dictionary—must also appear in the assessment boundary, needs a complete-source `scope` anchor, and has every anchor assigned to a review unit. Equation, table, figure, and code-range anchors also require a matching typed unit; hiding them inside one generic whole-paper row is not coverage. External literature records remain in the separate external-source ledger. This is an anchored completeness guarantee: it does not prove that a defective source manifest discovered every semantic heading or object, so reconcile the manifest inventory against the complete rendered source before declaring it complete.

Mirror the readable matrix in `review/evidence/coverage.json` using `assets/coverage.schema.json`. Derive the unit inventory from the source manifest rather than asking the reviewer to attest that it is complete. Record activated inferential burdens, every checked unit, linked finding IDs, and structured second-sweep state. Generate the readable matrix from this state.

Add one burden-audit row for every row in `run.json.activated_burdens`; the sets must match exactly. That audit, not a paper-family label or a legacy dimension list, is the scope authority. The three separate logical, technical, and methodological views must remain explicit.

When the source inventory contains code or a data dictionary, or when `capabilities.replication_code` is `not_permitted`, `static_only`, or `executed`, activate at least one reproducibility or computational-validity burden and cover every unit derived from those supplied materials in its burden audit. A `not_permitted` review remains bounded rather than inapplicable. `static_only` and `executed` also require typed code units for each inspected code source. Use `not_supplied` only when the source inventory contains no supplied code.

The dimension matrix always records the genuinely general reader/process checks: contribution and literature, reader clarity, claim consistency, terms and variables, review tone, writing and typography, and language mechanics. Add every dimension required by an activated structured claim, analytical, figure, table, replication, or governance audit. The following list is candidate vocabulary, not a universal checklist:

1. contribution and literature positioning;
2. claim-family consistency, qualifier persistence, and claim-evidence calibration;
3. data provenance, linkage, sample, and missingness;
4. measurement and constructed variables;
5. identification, model assumptions, and estimand;
6. estimation, computation, and inference;
7. equations, logic, internal consistency, and units;
8. results, magnitudes, rendered table integrity, and rendered figures;
9. robustness, heterogeneity, mechanisms, and policy claims;
10. reproducibility, documentation, and data/code availability;
11. reader comprehension, terminology and variable definitions, narrative logic, and whether the argument is convincing;
12. title, abstract, structure, writing, tone, typography, notation, and appendix navigation;
13. partitions/regimes, measure algebra, assumption implementation, derived-number traceability, comparison harmonization, timing/test semantics, and availability/exclusivity claims.
14. economic argument chain, object roles, institutional or model benchmark, alternative channels, and contribution after claim narrowing;
15. complete focal-versus-benchmark content, including intervention or protocol stages before each outcome and any co-varying feature that limits component attribution;
16. cross-result coherence across comparisons, populations or domains, horizons, estimands, and logical or temporal order;
17. accounting for objects promised, motivated, preregistered, collected, modeled, or required to interpret another result;
18. comparison-specific magnitude context, feasible support, cell or case support, uncertainty, and economically meaningful benchmarks;
19. transport from the observed sample or model domain to the target population, setting, model class, or policy margin.
20. evidentiary role and diagnostic force: what each load-bearing check can establish, shared failure modes, and which possible results would change the claim or assessment.
21. conditionally activated research integrity, participant protection, registration, sensitive/restricted-data governance, reuse rights, funding, and conflict disclosures.
22. conditionally activated code and replication traceability, safe execution boundary, environment/data availability, stochastic or numerical stability, exhibit reproduction, and failure classification.

Route this vocabulary from source-derived objects and claim-evidence bridges. For example, a proof activates formal objects; an archive activates provenance, selection, chronology, and corroboration; a predictor activates target, information-set, validation, and deployment burdens; a synthesis activates search, inclusion, harmonization, dependence, and selection. Descriptive family/design/branch tags may help readers find those lenses, but they never activate or suppress them. Do not add every candidate row merely to mark it inapplicable. When an explicitly considered object-specific row is `not_applicable`, give a source-specific reason; `N/A` is a positive scope decision, not a failed check or a shortcut.

### Keep one canonical owner for each fact

Coverage breadth must not multiply diagnoses. Use the source manifest for locations, claim families for claim wording and scope, the argument audit for relationships among economic objects, analytical ledgers for formal and computational implementation, and the reader/writing audits for presentation. Other artifacts point to those canonical records rather than paraphrasing them into parallel facts.

The same source defect may appear in several audit views because it has several consequences. Link those views to one root-cause finding when one revision resolves them. Keep separate findings only when the author must make different factual corrections, analyses, or claim choices. Checked-clean and bounded rows document review coverage; they are not author-facing comments. Resolve disagreements among audit views before candidate admission rather than carrying inconsistent versions into synthesis.

## 3. Generate candidates independently

When subagents are available, choose independent roles that cover the paper's actual contribution. The following is a default menu, not a mandatory method template:

- design, methods, and inference when the paper estimates empirical objects;
- data, measurement, and reproducibility when the paper uses data or computation;
- code-to-exhibit mapping and bounded execution when replication materials are supplied and permission allows;
- research integrity, participant protection, registration, and data governance only when source facts activate those burdens;
- prediction, validation, and decision use when the paper reports forecasts or machine-learning objects;
- source selection, chronology, coding, and corroboration when the evidence is institutional, historical, archival, or qualitative;
- search, inclusion, harmonization, dependence, and selection when the paper synthesizes a literature or set of estimates;
- primitives, proofs, equilibrium, and comparative statics when the paper is theoretical;
- calibration, solution, identification, and counterfactuals when the paper is structural or quantitative;
- logic, equations, numbers, and cross-exhibit consistency;
- rendered table contracts and extraction-conflict resolution;
- analytical ledgers for endogenous partitions, measure construction, assumption enforcement, derived calculations, comparison comparability, timing/tests, and exclusivity claims;
- economic-argument and evidence-object audit, including the strongest bypass channel and contribution that survives narrowing;
- intervention-flow or comparison-payload audit when focal and benchmark conditions contain multiple stages or components;
- cross-result coherence, magnitude support, and population/domain transport;
- contribution, writing, and presentation;
- cold-reader claim consistency, terminology, convincingness, and author-facing tone;
- section-by-section completeness reader.

Activate only applicable roles and add paper-specific roles as needed. Give each role the raw manuscript and reconstruction, not the existing candidate list. Ask for exact evidence, consequence, fix, strongest author reply, and survival judgment. Merge only after independent passes finish.

When subagents are unavailable, run the same roles sequentially and keep separate candidate lists until merge.

## 4. Admit real minor issues

Include a minor comment when all are true:

- the evidence and locator are exact;
- the issue is objectively misleading, inconsistent, undefined, incomplete, hard to reproduce, or needlessly difficult for a reader;
- the fix is specific and proportionate;
- resolving it improves correctness, clarity, transparency, or submission readiness;
- the comment does not merely impose taste.

Examples include inconsistent terminology, undefined variables, incorrect cross-references, ambiguous units, incomplete notes, missing uncertainty labels, unsupported abstract language, unreferenced appendix exhibits, and concrete prose that changes interpretation.

Do not include generic requests such as “discuss more literature,” “engage more with the literature,” “add robustness,” “improve writing,” or “provide more intuition” without a precise location, a verified comparator or evidentiary gap where relevant, and a paper-specific purpose.

## 5. Refute and deduplicate

For critical and major candidates, use an independent refuter when possible. For every minor candidate, at least check the surrounding paragraph, notes, relevant appendix, and definitions before keeping it.

Merge candidates when one fix resolves all repeated instances. Keep separate comments when different locations require different corrections or when aggregation would hide distinct consequences. List all relevant locations inside the retained finding. Aggregation controls the number of distinct comments; it must not erase evidence or shorten the explanation.

Delete:

- issues already addressed in the paper;
- duplicates;
- misunderstandings of the design or field convention;
- speculative objections without discriminating evidence;
- stylistic preferences with no reader or publication payoff;
- demands disproportionate to the issue.
- inherent data limitations that are disclosed and properly bound every material claim.

For every retained data-related candidate, record whether the source is avoidable handling, an inherent limit paired with claim overreach, or unclear. Use the lowest repair that resolves the issue: exact claim edit, disclosure, existing-data diagnostic, targeted sensitivity, and only then new data. Never penalize the paper merely because ideal data do not exist. Objective source-verified copyedits use `fairness_check: not_applicable`; do not invent an author rebuttal.

## 6. Rank all survivors

Assign unique consecutive ranks `1..N` for every surviving distinct issue:

1. critical essential findings;
2. major essential findings;
3. other major findings;
4. minor correctness and interpretation findings;
5. minor reproducibility, exposition, notation, citation, and presentation findings;
6. informational items only when they require action.

Within a tier, rank by expected effect on validity and publishability, then by the payoff-to-effort ratio. Use manuscript order only as a tie-breaker.

## 7. Run the second sweep

Run a cold second sweep when:

- the user requests exhaustiveness;
- a full-length paper yields fewer than the requested minimum;
- any coverage row remains unreviewed;
- one audit dimension yields no candidates despite substantive content;
- candidate overlap suggests one agent dominated the inventory.
- source-derived coverage or an activated burden remains thin relative to the manuscript objects it contains.
- a headline economic link, load-bearing comparison, related-result edge, promised evidence object, headline magnitude, or broad transport claim lacks a source-specific audit row.

The second sweep searches for missed issues; it does not relax the admission standard. Record new candidates, rejected candidates with reasons, and the final coverage result.

## 8. Verify every detailed comment

Apply the full evidence and locator checks to every comment. For minor substantive comments, the author-reply analysis may be brief but must establish fairness. For objective mechanical corrections, exact source/render verification replaces adversarial rebuttal. Ensure every active ledger item appears exactly once in the appropriate detailed section, in rank order, and in the fix plan.
