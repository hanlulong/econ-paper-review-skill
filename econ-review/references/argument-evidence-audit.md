# Argument and Evidence Audit

Use this protocol in every full review after the claim inventory and methods map are stable. Its purpose is to test whether the paper's economic argument is worth believing and whether the evidence actually answers that argument. It applies to empirical, descriptive, experimental, theoretical, structural, quantitative, macro, and mixed papers. Adapt the objects; do not substitute a preferred paper type or demand a formal model by default.

Save the structured result under `argument_audit` in `evidence/claims.json`. New reviews use claims-audit schema v0.2. Keep the readable explanation in `evidence/reader-claim-audit.md` and the compact reconstruction in `evidence/reconstruction.md`. Bind every claim family to the precise canonical manuscript anchor(s) where that claim is made; a whole-source scope anchor is not a claim anchor. Every populated argument row identifies its claim family and carries `evidence_refs` that resolve back to at least one of those claim anchors, directly or through verified finding evidence, plus any computation or external-source record needed for the check. Coverage labels and free-text summaries are not evidence by themselves; an unrelated valid anchor cannot certify a row.

Treat the audit artifacts as linked views, not separate sources of truth. Claim families own claim wording and scope; this audit owns relationships among economic objects; the analytical ledgers own algebra, implementation, timing, and formal restrictions; the reader audit owns presentation and search cost; coverage owns only whether the relevant source units and dimensions were checked. Reference the canonical row instead of restating it in a second ledger. If one root cause appears in several views, link those rows to one finding unless the author must make genuinely different repairs.

## Contents

- [Economic argument map](#1-map-the-economic-argument-not-only-the-headline-sentence)
- [Comparison and intervention content](#2-inventory-the-complete-comparison-or-intervention-experience)
- [Cross-result and evidence-object reconciliation](#3-reconcile-related-results-across-claim-families)
- [Diagnostic force](#5-classify-what-each-evidence-object-can-establish)
- [Magnitude and transport](#6-make-headline-magnitudes-interpretable-and-feasible)
- [Contribution rescue, admission, and verification](#8-preserve-contribution-rescue-options-without-manufacturing-defects)

## 1. Map the economic argument, not only the headline sentence

For every headline claim, reconstruct the shortest complete chain:

`economic question -> starting object or intervention -> actors, incentives, constraints, or information -> intermediate object(s) -> decision, equilibrium, measurement, welfare, or policy endpoint`.

Record:

- the economic question and benchmark;
- the starting object: variation, intervention, policy, primitive, restriction, model input, descriptive measure, or comparison;
- the role of every measured or modeled object: target, mechanism, prerequisite, proxy, consequence, validation object, or background fact;
- the warrant connecting each link, including timing and maintained conditions;
- the scale, domain, or institutional benchmark needed to interpret the endpoint;
- the strongest plausible bypass channel, reverse ordering, counterexample, or alternative mechanism compatible with the evidence;
- a paper-specific alternative assessment even when no credible alternative survives, rather than empty arrays used as a completion signal;
- evidence in the paper that distinguishes the stated chain from that alternative;
- the strongest contribution that survives if the narrowest unsupported link is removed.

An internally valid estimate, theorem, or simulation may still leave the paper's economic contribution unsupported if the measured object is only a proxy, consequence, or unnecessary intermediate for the claimed endpoint. Conversely, do not demand a mechanism the paper does not claim. If the contribution is explicitly descriptive, predictive, measurement-based, or about communication itself, assess that contribution on its own terms.

The first repair is a clear verbal economic warrant and faithful claim boundary. Recommend a formal model only when it would resolve a live ambiguity, discipline comparative statics, or distinguish alternatives better than a conceptual argument. Other valid repairs include an institutional calibration, existing-data diagnostic, alternative framing, validation exercise, or narrower contribution.

## 2. Inventory the complete comparison or intervention experience

Define a treatment, shock, model comparison, robustness comparison, or counterfactual as the full set of differences between the focal and benchmark conditions—not the label attached to one component.

For each load-bearing comparison, record:

- focal and benchmark conditions;
- the intended varying component;
- every other difference in content, magnitude, specificity, salience, timing, information, task burden, implementation, sample support, or measurement;
- for human-subject or field interventions, every screen, message, prompt, question, required response, attention or comprehension check, feedback item, routing event, delay, and platform feature from assignment through each outcome;
- whether each differential element occurs before or after the target outcome;
- which outcomes and estimands are exposed to each element;
- whether the evidence supports a component effect, a bundled-package effect, or only a compound comparison.

Questions or interactions shown only to one arm before an outcome are part of that outcome's intervention. They can change attention, interpretation, demand, salience, or mental models even when described as survey administration. Do not call this priming automatically: retain a concern only when the differential element plausibly affects the measured object or invalidates the paper's component-level attribution. A differential element after the outcome cannot contaminate that earlier outcome.

The same logic applies outside experiments. If a model counterfactual changes several primitives, a robustness comparison also changes the sample, or a theoretical case changes both assumptions and equilibrium selection, do not attribute the entire difference to one named component.

## 3. Reconcile related results across claim families

Within-family wording consistency is not enough. Build an edge for every important inference that uses one result to explain, validate, mediate, benchmark, or motivate another.

For each edge, reconcile:

- comparison or counterfactual;
- population, support, sample, and selection;
- outcome or theoretical object;
- horizon, timing, and information set;
- estimand, unit, normalization, and uncertainty;
- the asserted economic relationship and causal or logical ordering.

Classify the edge as coherent, an explained difference between distinct objects, an unexplained tension, a contradiction, or bounded. Different signs or significance levels are not automatically inconsistent. A null intermediate and non-null downstream result are a concern only when the paper says the downstream result operates through that intermediate for a comparable population and horizon. Ask for reconciliation or claim narrowing before requesting new analysis.

## 4. Account for promised, measured, and modeled objects

Create an evidence-object inventory from the abstract, introduction, theory or conceptual framework, registrations, methods, instruments, data dictionary, model, results, and appendix. Include every object that is:

- used to motivate the contribution;
- designated as a headline, secondary, mechanism, heterogeneity, diagnostic, validation, welfare, or robustness object;
- preregistered, collected, elicited, derived, calibrated, simulated, or promised in the text;
- necessary to interpret another reported result.

Mark each object `accounted_for`, `partially_accounted`, `unexplained_omission`, or `bounded`. An object is accounted for when it is reported or its non-use is transparently and credibly explained. Collection alone does not require publication of every variable, and an exploratory instrument item need not become a headline result. Retain a finding only when the omission creates selective emphasis, breaks a promised argument, prevents interpretation of a material result, or conflicts with a registration or stated analysis plan.

Also flag decorative evidence: a reported descriptive or auxiliary object should not be presented as mechanism evidence unless its relationship to the design and argument is established. The minimum repair may be integration, relabeling, relocation, or an explicit statement that it is descriptive.

## 5. Classify what each evidence object can establish

For every load-bearing result or diagnostic, state in `relevance_to_argument` and `accounting`:

- whether it is the direct identifying or proving object, an implication or falsification check, a sensitivity exercise, targeted in-sample fit, untargeted or out-of-sample validation, a numerical or implementation diagnostic, or an external benchmark;
- the exact assumption, link, or alternative it bears on;
- which assumptions it shares with the headline result; and
- what an adverse, clean, or inconclusive outcome changes in the supported claim.

Keep these evidentiary categories distinct:

- Failure to reject a placebo, balance, pre-trend, specification, or restriction test is not positive proof of the maintained assumption. Assess whether the diagnostic has power and targets the live alternative.
- Matching a targeted moment or in-sample object is implementation or fit evidence, not independent validation. Untargeted or out-of-sample evidence is stronger only for the object it actually tests.
- Numerical convergence establishes that an algorithm met its stated rule. It does not by itself establish global optimality, equilibrium uniqueness, approximation accuracy, or economic correctness.
- Predictive performance does not establish causality or mechanism; a correct theorem does not establish that its domain describes the application; stability across specifications that share the same failure mode is not independent triangulation.
- Several checks provide stronger triangulation only to the extent that their identifying failures, data errors, model restrictions, or measurement problems are meaningfully distinct.

Record a clean but limited diagnostic as a safeguard, not a criticism. Create a finding only when the manuscript attributes more evidentiary force to the object than it can carry, omits a diagnostic needed to distinguish a live alternative, or leaves the result uninterpretable.

Before requesting an analysis, apply a branching test: state how a favorable, adverse, and inconclusive result would change the claim or review assessment. If no plausible outcome would change either, remove the request or label it optional strengthening. Do not ask the author to perform a ritual test merely to document that it was run.

## 6. Make headline magnitudes interpretable and feasible

For every headline quantitative estimate, calibration, simulation, forecast, welfare number, or comparative static, record:

- the exact focal comparison and comparison-specific baseline or denominator;
- unit, transformation, horizon, and absolute versus relative scale;
- support, floor, ceiling, boundary, parameter domain, or accounting constraint;
- arm, cell, cluster, state, case, or simulation support;
- uncertainty, numerical error, or sensitivity relevant to the interpretation;
- an economically meaningful benchmark;
- any extensive- versus intensive-margin distinction;
- a computation record if feasibility or an adverse numerical claim is checked.

A pooled mean is not a control mean, and an average over treated and benchmark observations may not support a proportional-effect interpretation. Do not call an estimate implausible merely because it is large or based on a small cell. Flag missing comparison context, thin support, probability or accounting infeasibility, or an interpretation that outruns the available precision. Verify arithmetic through the computation ledger rather than hand calculation.

## 7. Match sample and model scope to the target claim

For every claim that travels from an observed sample, calibrated domain, local estimand, model class, or institutional setting to a broader target, record:

- source population or domain;
- target population, domain, setting, or policy margin;
- overlap and support;
- assumptions or evidence supporting transport;
- weighting, standardization, validation, comparative statics, or external evidence if used;
- the strongest supported scope.

Do not mandate reweighting for nonprobability samples. Weighting or standardization is informative only with a declared target, adequate overlap, defensible effect modifiers, and a credible adjustment model. Otherwise narrow the population claim and describe the sample. Apply the same fairness rule to theoretical domains and structural counterfactuals: a transparent local result is not defective because it is not universal.

## 8. Preserve contribution-rescue options without manufacturing defects

Record the strongest supported framing after the audit. Optional validation opportunities—such as comparing forecasts with outcomes that have since realized, adding a policy benchmark, or testing a discriminating implication—belong in the revision path only when feasible and decision-relevant. Label them optional unless the current central claim cannot stand without them.

Do not turn every attractive extension into a finding. A human referee's preferred framing, control, robustness estimator, or additional outcome is evidence about possible reader concerns, not proof that the paper is wrong.

## 9. Admission and verification

Create a finding only when the structured audit shows a paper-specific adverse state and the concern survives the fairness check. Every adverse row must map to an active finding; every checked-clean, not-applicable, or bounded row needs a source-specific reason. Coverage dimensions and finding links must agree with `claims.json`.

For a bounded row or a bounded or not-applicable comparison, result-relationship, magnitude, or transport collection, record a structured boundary: the scope actually checked, canonical evidence references to that source scope or absence record, the status basis, the paper-specific reason, any missing input, and the evidence that would resolve the boundary. A bounded row propagates to its collection and coverage state; a bounded headline link propagates to the central-argument assessment. `Not applicable` means the triggering object is absent or outside the paper's claims; it is not shorthand for an unfinished check. An empty bounded collection and every bounded row must identify both the unavailable input and decisive evidence needed.

Before finalization, verify:

- every headline claim appears in an economic-argument link;
- every load-bearing comparison has a complete differential-content map or a justified not-applicable state;
- every asserted cross-result relationship is reconciled;
- every material promised or measured object is accounted for;
- every load-bearing diagnostic states what it can establish, which assumptions it shares with the headline result, and what result would change the assessment;
- every headline quantitative object has magnitude context or a justified not-applicable state;
- every broad population or domain claim has transport support or is narrowed;
- adverse states resolve to exact source anchors, checked absences, computations, or verified external evidence.
