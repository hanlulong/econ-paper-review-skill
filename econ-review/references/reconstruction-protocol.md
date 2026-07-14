# Reconstruction Protocol

Reconstruct the paper in linked views before criticizing it. Build the inventory from the source manifest and stable anchors, not from memory or an unverified table of contents. During the first pass, record uncertainties without turning them into findings.

## Contents

- [Source-derived paper map](#0-source-derived-paper-map)
- [Two-pass claim inventory](#1-claim-inventory)
- [Derivation and methods maps](#2-derivation-ledger)
- [Argument and evidence map](#4-argument-and-evidence-map)
- [Internal reconciliation](#5-internal-reconciliation)
- [Reader path and understanding digest](#6-reader-path-and-terminology-map)

## 0. Source-derived paper map

Create the source manifest first. Hash each supplied source, record any normalized extraction separately, and assign stable anchors to every section, appendix component, table, figure, equation, code range, and other claim-bearing span. For Markdown or LaTeX, derive the heading/environment outline from source syntax and adjudicate every object in `coverage.json.source_inventory`; a whole-source scope anchor cannot substitute for this partition. `scripts/propose_source_inventory.py <review-dir> <source-id> <coverage-unit-id>` prints read-only candidate outline anchors and inventory rows for manual review and never edits a package. For a PDF, run and validate [pdf-ingestion.md](pdf-ingestion.md), merge its generated source-manifest fragment, and retain the typed page, block, object, symbol, and bounding-box map. Derive the coverage-unit inventory from those anchors. A reviewer assertion that the inventory is complete is not a substitute for this map, and automatic object detection is not proof that the PDF inventory is complete.

In a current full review, give every canonical PDF page, block, table, figure, and equation exactly one source-inventory state. Use `covered` only with source-bound coverage; a covered table or figure also joins its rendered-audit row. Use `duplicate`, `false_positive`, or `bounded` only with an object-specific reason. For a heading or LaTeX environment that is outside the substantive review, use an explicit `excluded` row rather than silently dropping it. Checked-absence scope anchors remain valid evidence for an absence search, but they do not count as granular inventory closure.

For each unit record its ordinal position in the paper, its role, and whether it was read, rendered, or bounded. Preserve the distinction between manuscript text, a rendered transcription, a reviewer observation, a checked absence, a computation, and an external source. This distinction controls what may later be displayed as a quotation.

## 1. Claim inventory

Group every substantive occurrence of the same economic assertion into a claim family across the abstract, introduction, model or design, results, mechanism discussion, policy discussion, exhibits, appendix, and conclusion. Build the ledger in two passes so reconstruction does not prejudge the paper:

1. **Intent pass:** restate the author's intended claim, scope, qualifiers, and intended evidence faithfully. Populate `canonical_supported_claim` with this provisional faithful restatement and keep support `inconclusive_from_text` unless the relevant evidence has already been verified. Do not narrow the claim merely because a later audit may challenge it.
2. **Support pass:** after the design, argument, exhibit, and analytical audits, replace the provisional restatement with the strongest statement the verified evidence supports. Then classify every occurrence relative to that final supported claim.

Preserve the intended claim in the occurrence records even when the final supported claim is narrower. This separation lets the review distinguish an author claim, an evidentiary result, and the reviewer's final claim boundary rather than reasoning in a circle.

| Field | Content |
|---|---|
| Claim ID | Stable ID such as `CLM-01` |
| Canonical supported claim | Strongest faithful statement supported by the verified evidence |
| Occurrences | Exact statements and locators across all claim-bearing sections |
| Scope | Population, period, margin, equilibrium, or counterfactual |
| Claim type | Descriptive, causal, structural, theoretical, mechanism, external-validity, policy, novelty |
| Evidence | Equation, proposition, table column, figure panel, estimate, calibration, or citation |
| Locator | Resolvable source location |
| Support state | Supported, partially supported, in conflict, inconclusive from text, not assessed |
| Gap | Exact difference between claim and delivered evidence, if any |
| Load-bearing qualifiers | Minimum conditions needed to prevent a materially broader reading |
| Occurrence relation | Consistent, safe compression, qualifier loss, scope expansion, strength inflation, definition drift, numerical conflict, contradiction, or inconclusive |

Trace every occurrence to the same evidentiary object. A shorter abstract or conclusion statement is acceptable when it is safe compression. Flag scope or certainty inflation only during the support pass, after verifying the underlying result and checking whether later evidence legitimately supports the stronger statement. Persist the structured ledger in `evidence/claims.json`.

## 2. Derivation ledger

Use this for formal theory, structural models, estimators, indices, welfare formulas, and any equation carrying a headline claim.

1. Record primitives, timing, information, constraints, equilibrium or solution concept, regularity conditions, and definitions without copying the paper's derivation steps.
2. State the target equation or proposition.
3. Derive the result from the recorded assumption set.
4. Compare each logical or algebraic step with the paper.
5. Classify the result:
   - `reproduced`;
   - `reproduced_with_unstated_assumption`;
   - `not_reproduced`;
   - `inconclusive_from_text`.
6. Identify which assumption is load-bearing and whether the interpretation respects it.

In a single-agent run, call this a separated assumption-first derivation, not a fresh-context independent proof. Verify sign conventions, domains, boundary conditions, equilibrium selection, approximation order, and units before alleging an error.

## 3. Methods map

Build the pipeline “for a robot” at the level needed to recover each headline exhibit:

1. Data sources or model inputs.
2. Unit of observation, sample period, population, and exclusions.
3. Variable, treatment, instrument, running variable, shock, moment, or parameter definitions.
4. Transformations, merges, interpolation, weighting, and missing-data handling.
5. Estimand or target object.
6. Variation, assignment, exclusion, functional-form restriction, equilibrium restriction, or calibration that identifies it.
7. Estimator or solution algorithm.
8. Fixed effects, controls, timing, lag/lead structure, normalization, and aggregation.
9. Uncertainty treatment or numerical error assessment.
10. Exact mapping from specification to each headline table column, figure, proposition, or counterfactual.

Do not demand disclosure for its own sake. Treat an unmapped element as material only if it prevents evaluation, interpretation, or reproduction of a claim that matters.

After the methods map, create the claim-to-burden map in [design-audit.md](design-audit.md). Activate burdens from the actual object and evidentiary bridge, including required omissions. Do not infer scope from the declared paper family alone.

In full mode, also build the structured analytical ledgers in [analytical-ledgers.md](analytical-ledgers.md). The prose methods map is not a substitute for checking subgroup assignment, measure algebra, assumption enforcement, derived-number traceability, comparison harmonization, timing/test semantics, and availability claims.

Persist source bindings while reconstructing, not after drafting the report. Each claim occurrence carries its precise anchor, exact or normalized representation, and canonical locator; the claim-family anchor list must match those occurrences. Reader rows name the claim families they summarize. Term rows bind first use and direct support, and the terminology candidate inventory records why each symbol or phrase was mapped, treated as standard, rejected as prose/extraction noise, or deemed non-load-bearing. A clean claim or terminology state also records the authenticated scope searched for contrary or missing evidence.

## 4. Argument and evidence map

In full mode, follow [argument-evidence-audit.md](argument-evidence-audit.md) and persist its structured state under `argument_audit` in `evidence/claims.json`. New reviews use claims-audit schema v0.2. Build these views from source anchors rather than a retrospective summary:

1. one complete economic link for every headline claim, including the benchmark, actors or constraints, intermediate objects, endpoint, warrant, strongest alternative channel or ordering, and contribution that survives narrowing;
2. one differential-content map for every load-bearing comparison, including treatment or protocol stages before each outcome where applicable;
3. every asserted relationship across results, claim families, populations, horizons, or model components;
4. every material object motivated, promised, preregistered, collected, derived, calibrated, simulated, modeled, or used for interpretation;
5. magnitude context for every headline quantitative object; and
6. every step from the observed population or model domain to a broader target.

Do not fill these views with audit meta-prose such as “the relevant material was checked.” Each row must name the paper object, source unit, and result of the check. A `not_applicable` state is valid only when the reconstructed paper truly contains no such object and the reason is recorded.

## 5. Internal reconciliation

Reconcile:

- definitions and notation across sections;
- units, denominators, baselines, and percentage versus percentage-point language;
- signs and timing across equations, text, tables, and figures;
- sample sizes and populations across exhibits;
- estimand and interpretation;
- partial-equilibrium versus general-equilibrium claims;
- average, local, marginal, and heterogeneous effects;
- calibrated versus estimated objects;
- statistical and economic significance;
- headline, caveat, and conclusion strength.

Also reconcile related results that the paper uses to explain or validate one another. Distinguish a true contradiction from different populations, horizons, comparisons, estimands, or theoretical domains. For experiments and surveys, reconstruct the complete arm-by-stage experience through each outcome so an intermediate prompt or task is not mistaken for neutral administration. For any focal comparison, record all other dimensions that vary before attributing the difference to one named component.

Record apparent conflicts as questions first. Promote them only after checking definitions, notes, and appendices.

## 6. Reader path and terminology map

Record where each headline object, comparison, benchmark, load-bearing qualifier, and supporting exhibit first becomes available to a first-time reader. Then inventory load-bearing terms, acronyms, constructed measures, symbols, parameters, indices, units, domains, transformations, and normalizations. Mark each as clearly defined, defined remotely, undefined, inconsistent, overloaded, or bounded. Do not flag standard notation whose local meaning is unambiguous.

## 7. Understanding digest

Produce no more than one page containing:

- the question;
- the paper's answer;
- the economic mechanism or empirical variation;
- the target object and identifying assumptions;
- the evidence chain for the headline result;
- the role of the measured or modeled intermediate objects and the strongest credible bypass channel;
- the closest reconstruction uncertainty.

Use the user's correction as evidence about author intent, but verify the corrected reading against the manuscript before changing the audit.

The digest is a reader checkpoint, not canonical evidence. Every factual statement retained in later synthesis must resolve to claim IDs, source anchors, verified computations, or verified external-source records.
