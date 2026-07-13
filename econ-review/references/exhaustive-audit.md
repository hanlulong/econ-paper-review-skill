# Exhaustive Audit Protocol

Use this protocol in `full` mode. Keep the editorial synthesis selective while making the detailed-comment inventory comprehensive. Apply no length limit to the report or to an individual comment; use enough space to establish the evidence, consequence, fairness, and fix.

## 1. Set the comment policy

Record in `run.json.comment_policy`:

- `minimum_target`: the user's requested minimum; use `0` when none is requested. Do not infer a target from paper family or a universal number.
- `maximum`: `null` by default for exhaustive full reviews; use a positive limit only when the user explicitly requests one.
- `exhaustive`: set `true` only after completing source-derived coverage and any sweep triggered by the conditions below.

A minimum is a search and coverage obligation, not permission to invent issues. If fewer comments survive after two complete sweeps, ship fewer and explain the shortfall rather than padding; keep the run non-complete relative to an unmet explicit target until the user accepts the bounded result.

## 2. Build the coverage matrix

Create `review/evidence/coverage.md` with one row for every:

- title, abstract, main section, and subsection;
- table, figure, numbered equation, and proposition;
- footnote cluster containing substantive content;
- reference list and data/code availability statement;
- appendix section, table, figure, and technical derivation.

For each row record `checked_no_issue`, finding IDs, `bounded`, or `not_applicable`. Never leave a row implicit.

Mirror the readable matrix in `review/evidence/coverage.json` using `assets/coverage.schema.json`. Derive the unit inventory from the source manifest rather than asking the reviewer to attest that it is complete. Record activated inferential burdens, every checked unit, linked finding IDs, and structured second-sweep state. Generate the readable matrix from this state.

Add a dimension matrix covering:

The matrix must make the logical, technical, and methodological passes separately visible. The numbered dimensions below elaborate those views; a single generic `checked` row cannot stand in for them.

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

Adapt this inventory to the paper family. For formal theory, enumerate assumptions, definitions, lemmas, propositions, theorems, corollaries, proofs, examples, equilibrium cases, and boundary cases. For structural or quantitative work, enumerate calibration inputs, targeted and untargeted moments, algorithms, solution and convergence diagnostics, welfare formulas, counterfactuals, and validation exercises. For macro work, enumerate accounting identities, aggregate states and flows, steady-state or balanced-growth objects, transition paths, shocks and policy rules, solution approximations, impulse responses or decompositions, and welfare mappings; also activate the empirical, structural, or theory branch warranted by the claim. For mixed work, enumerate every model-to-evidence bridge. Mark irrelevant rows `not_applicable`; never substitute an empirical checklist for an applicable theory, macro, or structural branch.

## 3. Generate candidates independently

When subagents are available, choose independent roles that cover the paper's actual contribution. The following is a default menu, not a mandatory method template:

- design, methods, and inference when the paper estimates empirical objects;
- data, measurement, and reproducibility when the paper uses data or computation;
- primitives, proofs, equilibrium, and comparative statics when the paper is theoretical;
- calibration, solution, identification, and counterfactuals when the paper is structural or quantitative;
- logic, equations, numbers, and cross-exhibit consistency;
- rendered table contracts and extraction-conflict resolution;
- analytical ledgers for endogenous partitions, measure construction, assumption enforcement, derived calculations, comparison comparability, timing/tests, and exclusivity claims;
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

The second sweep searches for missed issues; it does not relax the admission standard. Record new candidates, rejected candidates with reasons, and the final coverage result.

## 8. Verify every detailed comment

Apply the full evidence and locator checks to every comment. For minor substantive comments, the author-reply analysis may be brief but must establish fairness. For objective mechanical corrections, exact source/render verification replaces adversarial rebuttal. Ensure every active ledger item appears exactly once in the appropriate detailed section, in rank order, and in the fix plan.
