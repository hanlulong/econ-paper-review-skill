# Cross-family review benchmark

This benchmark tests whether `econ-review` routes checks from claims and evidentiary objects rather than from a single paper label. It is a framework regression suite, not a claim that the skill outperforms another product.

The six synthetic cases cover empirical causal, descriptive/measurement, structural/quantitative, macro/dynamic, formal theory, and mixed theory-empirical work. Each case contains:

- a short original manuscript with seeded, independently checkable issues;
- expected active and not-applicable burdens;
- required issue concepts stated as alternative text patterns, not prescribed reviewer prose;
- clean traps that should not become findings;
- a case-specific rubric in `cases.json`.

The clean traps matter as much as recall. For example, the descriptive case must not be criticized for lacking causal identification when it makes no causal claim, and the individually randomized experiment must not receive a ritual cluster-robustness comment without a dependence trigger.

## Run an evaluation

Create a full review package for a case under `benchmarks/reviews/<case-id>/`, then run:

```bash
python3 benchmarks/evaluate.py
```

The evaluator checks burden routing, required issue-concept recall, forbidden false positives, and the package validator. It reports each dimension separately and never collapses them into an unsupported quality or superiority score. Missing review packages are reported as `not_run`, not failures.

The benchmark manuscripts and rubrics are public-safe synthetic fixtures. Real manuscripts, competitor reports, and private evaluation labels do not belong here.
