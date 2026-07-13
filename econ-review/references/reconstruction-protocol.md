# Reconstruction Protocol

Reconstruct the paper in linked views before criticizing it. Build the inventory from the source manifest and stable anchors, not from memory or an unverified table of contents. During the first pass, record uncertainties without turning them into findings.

## 0. Source-derived paper map

Create the source manifest first. Hash each supplied source, record any normalized extraction separately, and assign stable anchors to every section, appendix component, table, figure, equation, code range, and other claim-bearing span. For a PDF, run and validate [pdf-ingestion.md](pdf-ingestion.md), merge its generated source-manifest fragment, and retain the typed page, block, object, symbol, and bounding-box map. Derive the coverage-unit inventory from those anchors. A reviewer assertion that the inventory is complete is not a substitute for this map, and automatic object detection is not proof that the PDF inventory is complete.

For each unit record its ordinal position in the paper, its role, and whether it was read, rendered, or bounded. Preserve the distinction between manuscript text, a rendered transcription, a reviewer observation, a checked absence, a computation, and an external source. This distinction controls what may later be displayed as a quotation.

## 1. Claim inventory

Group every substantive occurrence of the same economic assertion into a claim family across the abstract, introduction, model or design, results, mechanism discussion, policy discussion, exhibits, appendix, and conclusion. Record one canonical supported claim—the strongest statement the verified evidence supports—and compare every occurrence with it.

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

Trace every occurrence to the same evidentiary object. A shorter abstract or conclusion statement is acceptable when it is safe compression. Flag scope or certainty inflation only after verifying the underlying result and checking whether later evidence legitimately supports the stronger statement. Persist the structured ledger in `evidence/claims.json`.

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

## 4. Internal reconciliation

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

Record apparent conflicts as questions first. Promote them only after checking definitions, notes, and appendices.

## 5. Reader path and terminology map

Record where each headline object, comparison, benchmark, load-bearing qualifier, and supporting exhibit first becomes available to a first-time reader. Then inventory load-bearing terms, acronyms, constructed measures, symbols, parameters, indices, units, domains, transformations, and normalizations. Mark each as clearly defined, defined remotely, undefined, inconsistent, overloaded, or bounded. Do not flag standard notation whose local meaning is unambiguous.

## 6. Understanding digest

Produce no more than one page containing:

- the question;
- the paper's answer;
- the economic mechanism or empirical variation;
- the target object and identifying assumptions;
- the evidence chain for the headline result;
- the closest reconstruction uncertainty.

Use the user's correction as evidence about author intent, but verify the corrected reading against the manuscript before changing the audit.

The digest is a reader checkpoint, not canonical evidence. Every factual statement retained in later synthesis must resolve to claim IDs, source anchors, verified computations, or verified external-source records.
