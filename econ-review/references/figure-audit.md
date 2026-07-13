# Separate Figure Audit

Use this protocol for every full review. Figures are first-class evidence and must be extracted and read separately from manuscript text and tables. Do not infer a figure's contents from OCR, a caption, source markup, or an author's discussion when a rendered PDF is available.

## 1. Inventory and extraction

Identify every chart, plot, diagram, map, image, multi-panel figure, and figure-like appendix exhibit in the rendered paper. Keep tables in the table audit unless they contain graphical panels. For every figure:

- record the PDF page, manuscript label, caption, and nearby claim-bearing text;
- render or crop the complete figure at a resolution where labels, legends, markers, and uncertainty are readable;
- preserve multi-panel structure and create panel crops when the full figure is too dense;
- record the extraction path and method;
- distinguish genuine manuscript defects from OCR, Markdown, or conversion artifacts by checking the rendered page.

If the paper has no figures, record that the rendered manuscript was checked and no figures were present. Do not invent a figure requirement for a paper whose argument does not need one.

## 2. Read the visual object

Inspect each figure independently before reading the prose interpretation. Record:

- plotted economic object, population/domain, sample, treatment/comparison, and horizon;
- axes, scales, units, transformations, denominators, baselines, normalization, and sign convention;
- panels, series, colors, line types, markers, legend, reference lines, and annotations;
- uncertainty representation and whether pointwise, simultaneous, sampling, posterior, or other;
- truncation, nonlinear/log axes, dual axes, smoothing, binning, missing values, and visual weighting;
- legibility in the rendered paper, including font size, contrast, clipping, overlap, raster quality, and accessibility without color alone.

Do not criticize a conventional visual choice merely because another style is possible. Create a finding only when the visual can mislead, cannot be decoded, contradicts its label, omits information necessary for the paper's inference, or creates material reader search cost.

## 3. Reconcile figure, caption, text, and data object

For each figure, compare the visual with its caption, notes, surrounding discussion, claim-family ledger, and any table showing the same result. Check:

- numerical and directional consistency;
- consistent object, population, benchmark, horizon, unit, and uncertainty;
- whether prose describes the full path or only selected points fairly;
- whether the caption is self-contained enough to decode the figure;
- whether the figure visually supports the claimed mechanism, robustness, heterogeneity, or dynamic result;
- whether absence of a figure materially impedes evaluation of a dynamic, distributional, spatial, or nonlinear claim. Request a new figure only when it has clear decision value; do not impose graphical presentation on every result.

## 4. Verification and output

Write `evidence/figures.json` and `evidence/figures.md`. The structured inventory must cover every rendered figure and map every adverse state to a verified active finding. Record checked-clean figures as such so the audit cannot be satisfied by listing only problems. Keep crops under `evidence/figures/` when they are needed to verify the review.

Every finding that uses `figure` evidence must map back from the matching figure-audit row. A page number, caption, or text-only reference does not satisfy reciprocal visual verification.

Before delivery, re-open every retained crop and the original rendered page. A finding based only on extracted text or a conversion artifact must be removed.
