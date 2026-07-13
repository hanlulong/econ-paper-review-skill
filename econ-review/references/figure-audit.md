# Separate Figure Audit

Use this protocol for every full review. Figures are first-class evidence and must be extracted and read separately from manuscript text and tables. Do not infer a figure's contents from OCR, a caption, source markup, or an author's discussion when a rendered PDF is available.

## 1. Audit contract

Write new or materially refreshed figure inventories against `figures.schema.json` version `0.2`. Version `0.1` remains valid for backward compatibility; do not relabel an existing v0.1 record as v0.2 unless its rows satisfy the v0.2 asset and identity contract. A figure-free v0.1 record may be relabeled after confirming that its empty inventory still describes the current render.

Map each rendered figure exactly once to the matching figure unit in `evidence/coverage.json` through `coverage_unit_id`, and identify the originating source-manifest row through `source_id`. Do not assign a figure to a nearby section unit merely because the figure appears within that section. Record `source_locator` as a structured object whose `source_id` and `pages` exactly equal the row's `source_id` and `pdf_pages`; put optional non-authoritative context in `context`. Do not encode an authoritative page only in prose. The row label, structured locator, source, and pages must describe the same visual object as the coverage unit.

Give every v0.2 row an `identity_keys` list containing the shortest discriminating cues that a viewer can actually observe, such as the numbered label, title, axis phrase, panel heading, or distinctive annotation. Include enough alternatives to identify both the full page and retained crops without forcing every figure to have a conventional number or caption. Matching explicit figure identifiers must reconcile the row label with its coverage-unit label; when either label lacks one, use a shared identity key instead. Every asset marked `matched` must use a visible cue linked to one of the row's keys.

## 2. Inventory and immutable asset capture

Identify every chart, plot, diagram, map, image, multi-panel figure, and figure-like appendix exhibit in the rendered paper. Keep tables in the table audit unless they contain graphical panels. For every figure:

- record the PDF page or pages, manuscript label, caption, and nearby claim-bearing text;
- retain at least one full-page render for every PDF page occupied by the figure so placement and surrounding context remain verifiable;
- add complete-figure or panel crops when the full page is too dense to inspect at readable resolution;
- preserve multi-panel structure and avoid crops that silently omit panels, legends, notes, or shared axes;
- distinguish manuscript defects from OCR, Markdown, extraction, or rendering artifacts by checking the original rendered page.

Record each retained render in `rendered_assets` with its portable POSIX-style review-relative path, lowercase SHA-256 digest, `full_page` or `crop` type, canonical `source_object_id`, and visible-identity record. For PDF sources, record the one-indexed PDF page and a nonempty `pdf_pages` row inventory. A PDF crop's `source_object_id` must equal the exact `figures[].id` in the authenticated ingestion manifest; matching only another crop's path, hash, or page is insufficient. Set `source_object_id` to `null` for full-page renders and non-PDF assets. For non-PDF sources, use the source's page number when one exists or `null` with an empty `pdf_pages` list when pagination is not meaningful. The file must decode completely as the image type declared by its extension; a filename or magic-byte prefix is not enough. Compute the digest after the asset is finalized. If any byte changes, compute a new digest and inspect the new asset again; never carry forward a stale hash or an inspection conclusion tied to different bytes.

For a PDF source, reuse the immutable assets authenticated by that source's PDF-ingestion manifest. A `full_page` record must exactly match one `pages[]` render path, digest, and page; a `crop` record must join one named `figures[]` object by `source_object_id` and match that object's crop path, digest, and page. Do not copy an image to a new path and self-attest that it is the same page or object. If the canonical object crop is inadequate, retain and inspect the canonical full page, correct the ingestion extraction in a new ingestion package, or record a bounded visual check. For a non-PDF source, `source_id` still binds the figure to its source, while ordinary path, digest, decoding, and visible-identity checks apply.

If the paper has no figures, record that the complete rendered manuscript was checked and set `no_figures_confirmed` with an empty figure list. Do not invent a figure requirement for a paper whose argument does not need one.

## 3. Bind every asset to visible identity

Do not infer asset identity from filename, directory order, extraction order, or expected page sequence. Open every retained asset and bind it to text or structure visible inside that image. For each asset, record:

- `basis`: the strongest available basis, such as the figure label, caption or title, panel or axis text, legend or annotation, distinctive visible text, or visual structure;
- `text`: the actual short identity cue observed in the image, not a generic statement that the asset was checked;
- `status`: `matched`, `mismatch`, or `bounded`;
- `notes`: how the visible cue establishes or fails to establish the link among asset, PDF page, audit row, and coverage unit.

Use `matched` only when the visible content agrees with the declared page and figure row. Use `mismatch` when the asset visibly belongs to another figure, page, or coverage unit; this is an adverse state that requires `visual_status: issue` and an active finding until the mapping is corrected or the asset regenerated. Use `bounded` only when the available image does not permit a conclusion. A bounded identity requires `visual_status: bounded` and a structured `assessment_boundary` stating the checked scope, basis, reason, missing input, and decisive evidence needed; it need not create an author-facing finding when the limitation belongs to the review inputs rather than the manuscript.

`visible_identity` is a reviewer/model visual attestation about the retained bytes, not OCR proof that the declared words occur in the image. OCR and object detection may propose cues, but the reviewer or model must open the retained asset and full-page render, record what is actually visible, and bind that observation to the asset hash. Hash validation proves which bytes were inspected; it does not prove the semantic truth of the visual attestation.

Every asset's `pdf_page` must appear in its row's `pdf_pages`, and every page in `pdf_pages` must have a corresponding full-page asset. A mismatched asset cannot coexist with a clean row or be hidden behind an assessment boundary. A bounded asset cannot coexist with a clean row and must carry the structured assessment boundary above. Remove a stale or irrelevant asset, correct it, or record the appropriate adverse or bounded state.

## 4. Read the visual object

Inspect each figure independently before reading the prose interpretation. Record:

- plotted economic object, population or domain, sample, treatment or comparison, and horizon;
- axes, scales, units, transformations, denominators, baselines, normalization, and sign convention;
- panels, series, colors, line types, markers, legend, reference lines, and annotations;
- uncertainty representation and whether it is pointwise, simultaneous, sampling, posterior, or another type;
- truncation, nonlinear or log axes, dual axes, smoothing, binning, missing values, and visual weighting;
- legibility in the rendered paper, including font size, contrast, clipping, overlap, raster quality, and accessibility without color alone.

Do not criticize a conventional visual choice merely because another style is possible. Create a finding only when the visual can mislead, cannot be decoded, contradicts its label, omits information necessary for the paper's inference, or creates material reader search cost.

## 5. Reconcile figure, caption, text, and analytical object

For each figure, compare the visual with its caption, notes, surrounding discussion, claim-family ledger, equations or model objects when relevant, and any table showing the same result. Check:

- numerical and directional consistency;
- consistent object, population, benchmark, horizon, unit, and uncertainty;
- whether prose describes the full path or only selected points fairly;
- whether the caption is self-contained enough to decode the figure;
- whether the figure visually supports the claimed mechanism, robustness, heterogeneity, or dynamic result;
- whether absence of a figure materially impedes evaluation of a dynamic, distributional, spatial, or nonlinear claim. Request a new figure only when it has clear decision value; do not impose graphical presentation on every result.

## 6. Verification and output

Write `evidence/figures.json` and `evidence/figures.md`. The structured inventory must cover every rendered figure and map every adverse state to a verified active finding. Record checked-clean figures as such so the audit cannot be satisfied by listing only problems.

Before delivery, verify all of the following:

- figure IDs and `coverage_unit_id` mappings are unique, complete, and point to figure-type coverage units; every `source_id` resolves in the source manifest;
- every asset path is review-relative, exists inside the review directory, opens as a readable image, and matches its recorded SHA-256 digest;
- every PDF asset exactly matches the corresponding page-render or named `source_object_id` figure-crop record in that source's authenticated ingestion manifest;
- every structured source locator repeats the row's source and page set exactly, including an empty page set when a non-PDF source has no meaningful pagination;
- every asset's visible identity, declared PDF page, render type, row label, and coverage unit agree;
- full-page renders cover all declared pages and any retained crops can be reconciled to them;
- every finding that uses `figure` evidence maps back from the matching figure-audit row; every mismatch or other adverse state maps to an active finding, while a non-author-facing bounded limitation has a structured assessment boundary and bounded coverage state.

A page number, caption, or text-only reference does not satisfy reciprocal visual verification. Re-open every retained crop and original rendered page before delivery. Remove any finding based only on extracted text, a misidentified image, or a conversion artifact.
