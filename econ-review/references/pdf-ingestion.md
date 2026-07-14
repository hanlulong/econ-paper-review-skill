# PDF Ingestion and Verified Transcription

Use this protocol whenever a PDF is a source, including when TeX, Word, or Markdown is also supplied. A PDF has no canonical semantic Markdown representation. The generated Markdown is a navigable transcription; the original PDF and page/object renders remain authoritative for layout, equations, tables, figures, and ambiguous glyphs.

Read [pdf-backends.md](pdf-backends.md) before installing, invoking, or adding a conversion backend. Backend selection must preserve this contract and the project's commercial-license boundary.

## Contents

- [Local command](#local-command)
- [Outputs and authority](#outputs-and-authority)
- [Source preference and reconciliation](#source-preference-and-reconciliation)
- [Tables](#tables)
- [Figures](#figures)
- [Equations and symbols](#equations-and-symbols)
- [OCR and degraded cases](#ocr-and-degraded-cases)
- [Parser isolation boundary](#parser-isolation-boundary)
- [Completion gates](#completion-gates)

## Local command

Run the dependency check once:

```bash
python3 "$SKILL_ROOT/scripts/pdf_ingestion.py" doctor
```

The command exits nonzero when a required Poppler command is absent or an
installed core Python distribution is missing or outside the version range in
`requirements-core.txt`. Optional Docling, MarkItDown, and Mathpix-adapter
dependencies are reported as `compatible`, `unavailable`, or `unsupported`
against their separate manifests; an optional mismatch does not fail the core
doctor but cannot be selected as an available backend.

For a PDF-only manuscript, create the source package before reconstruction:

```bash
python3 "$SKILL_ROOT/scripts/pdf_ingestion.py" ingest manuscript.pdf review \
  --review-id REVIEW-ID --source-id SRC-01 --ocr auto
```

Local OCR defaults to Tesseract's `eng` language data. For another installed
language or a multilingual manuscript, pass a safe plus-separated list such as
`--ocr-language eng+fra`; the exact value becomes part of the pipeline
fingerprint. This option changes prose OCR only and never promotes mathematical
or exhibit transcription.

This writes `review/evidence/pdf-ingestion/SRC-01/` atomically. Each PDF source receives a separate default directory and source-qualified block, object, and anchor IDs. Use `--role appendix` or `--role supplement` for additional sources; the default role is `manuscript`. Rerunning is idempotent only when the source hash, review/source identity, role, extraction configuration, requested proposal state, complete toolchain fingerprint, and object-detector source contract match. Thus a classifier implementation change cannot silently reuse stale candidate crops. A changed or invalid existing package requires `--force`. Legacy v0.1 and v0.2 ingestion packages remain independently verifiable under their recorded fingerprint rules. Validate a package with:

```bash
python3 "$SKILL_ROOT/scripts/pdf_ingestion.py" check review/evidence/pdf-ingestion/SRC-01
```

Here `SKILL_ROOT` is the absolute directory containing the loaded `SKILL.md`,
whether Claude Code installed it under `.claude/skills` or Codex installed it
under `.codex/skills` or `.agents/skills`. Install core Python dependencies with
`python3 -m pip install -r "$SKILL_ROOT/requirements-core.txt"`; the optional
Docling, MarkItDown, and Mathpix environments use the corresponding manifests
beside it. Both `ingest` and `check` repeat the core version check before
processing a package, and explicit optional modes fail closed when their
installed version is outside the declared contract. `auto` records an
unsupported Docling installation as
unavailable rather than running it.

The core evidence path is local. With the default `--semantic-backend auto`, Docling runs only when its command and model artifacts are locally available; otherwise ingestion records a bounded warning and continues. Use `--semantic-backend none` for a strict Poppler/pdfplumber/Tesseract-only run. Model downloads are disabled unless `--allow-model-downloads` is supplied.

The only implemented external path is the optional Mathpix premium proposal. It requires all of `--mathpix`, `--authorize-external-upload mathpix`, and `--accept-mathpix-retention`, plus `MATHPIX_APP_ID` and `MATHPIX_APP_KEY` in the process environment. The service receives the complete PDF. Do not use it for a confidential manuscript unless the user has authority to upload it and the deployment's provider agreement, retention policy, and data-processing terms have been reviewed. No credentials are written into the package.

## Outputs and authority

- `source/original.pdf`: private read-only copy with the original SHA-256.
- `manuscript.md`: paper-order reading surface with stable block markers, PDF pages, bounding boxes, methods, and character spans.
- `pages/page-NNNN.native.txt`: the preserved native text-layer alternative, including an explicit empty file when no native text exists.
- `pages/page-NNNN.ocr.txt`: the preserved local-OCR alternative when OCR was attempted. `ingestion.json` identifies which alternative drives canonical Markdown.
- `renders/page-NNNN.png`: complete page render for visual authority.
- `objects/tables/`: rendered crops plus candidate Markdown and CSV grids when a rectangular grid is recovered.
- `objects/figures/`: caption-driven crops that preserve vector and composite figures through rendering.
- `objects/equations/`: rendered crops plus raw glyph candidates; generic PDF text is never labeled verified LaTeX.
- `ingestion.json`: hashes, tool versions, the current candidate-detector source digest, per-page methods and warnings, typed blocks/objects, symbol occurrences, and quality state.
- `source-manifest.generated.json`: a valid single-source manifest that can seed or be merged into `review/evidence/source-manifest.json` after checking source-ID and anchor-ID uniqueness. A current ingestion creates one typed anchor for every canonical block and exactly one `scope` anchor over the complete authenticated Markdown extraction. The package checker re-derives every block anchor's kind, span, and hash and binds the scope anchor to the source ID, full character range, and Markdown SHA-256. Older block-only generated manifests remain package-verifiable for compatibility, but they do not provide the source-wide anchor required by a new full-review coverage contract; rerun the same ingestion with `--force` before merging such a source into a new review.
- `reconciliation/page-packets.json`: a deterministic routing manifest linking each page render and adjacent-page context to selected/native/OCR text, stable blocks, object crops, normalized backend candidates, and material disagreement signals. It contains no adjudication decision and cannot rewrite canonical Markdown.
- `proposals/docling/`: optional local Markdown, structured JSON, referenced images, and a sanitized run log. The proposal is attempted by `--semantic-backend auto` when locally available or required by `--semantic-backend docling`.
- `proposals/markitdown.md`: optional local Markdown written only when `--markitdown-proposal` is explicitly requested and the installed command satisfies `requirements-markitdown.txt`.
- `proposals/mathpix/`: optional hosted Mathpix Markdown, line-level JSON, and a deletion receipt. It is created only under the explicit external-upload gate above.

Every proposal records its engine, version, input hash, artifact hashes, processing mode, and warnings in `ingestion.json`. Proposal files are immutable comparison surfaces. They never change canonical Markdown, stable anchors, or evidence authority automatically.

The page packets define a strict decision vocabulary for a later human or agent pass. Agreement among converters is useful triage but is not visual verification. Only a decision that records direct render comparison may support an exact quotation or a change to a load-bearing equation, table cell, symbol, sign, value, or label. Preserve `bounded` wherever the render or source does not resolve the conflict.

Persist inspected scope in a separate `reconciliation-decisions.json` that
conforms to `assets/pdf-reconciliation-decisions.schema.json`. Validate it with:

```bash
python3 "$SKILL_ROOT/scripts/pdf_reconciliation.py" \
  review/evidence/pdf-ingestion/SRC-01 \
  review/evidence/pdf-ingestion/SRC-01/reconciliation-decisions.json
```

Each decision must identify its block or object, page, exact evidence hashes,
transcription and alternatives, unreadable regions, verifier/model provenance,
and a concrete render-comparison note. `model_adjudicated` remains a proposal;
`render_verified` requires the page render and, for an object, its crop hash.
The ledger verifies only its declared scope and never rewrites canonical Markdown.

Do not list the source PDF or complete page renders in the author-facing review document manifest. The local Review Desk may consume the generated Markdown and selected audit crops, but a public build must never bundle manuscript-derived assets without explicit publication authorization.

## Source preference and reconciliation

Use the richest source without weakening visual verification:

1. When TeX or structured Markdown exists, use it for semantic structure, equations, and tables, align it to PDF pages, and keep the PDF renders as visual authority.
2. For a born-digital PDF with usable Unicode, use native prose blocks but verify every load-bearing formula, symbol, table, and figure against its render.
3. For missing or damaged text layers, use local OCR for prose only. Preserve the native alternative and warnings; keep tables and equations image-backed.
4. Use Docling, MarkItDown, Mathpix, or an LLM-assisted reading to locate likely structure and transcription disagreements, not to settle them.
5. If extraction and the rendered page conflict, the visible page controls what the paper actually communicates. Resolve the conflict against the render or structured source, or mark the object bounded.

Never normalize mathematical text with NFKC. It can collapse distinctions among symbols, superscripts, compatibility glyphs, and formatting. The ingester preserves raw UTF-8 block content and records Unicode codepoints and warnings.

Poppler can emit XML 1.0-forbidden control characters in its bounding-box XHTML when a PDF font has a damaged or missing Unicode map. The ingester removes only those forbidden characters from the temporary XML parser input so that layout parsing can continue. `ingestion.json.parser_repairs` records the exact count, affected codepoints, raw XHTML hash, parser-input hash, and repair policy. A nonzero count is also disclosed in the quality warnings. This repair does not normalize, guess, or replace a mathematical symbol; the copied PDF and rendered page remain authoritative, and any affected transcription still requires visual verification.

The canonical page transcription preserves Poppler's logical block order. It
does not impose a global top-to-bottom/left-to-right sort, because that
interleaves lines from two-column papers. Geometry-sensitive table and figure
operations sort locally for their own purpose without changing reading order.

## Tables

Table detection is a candidate generator, not verification. The module attempts geometry-based grid extraction and also creates a caption-driven crop when no grid is recovered. For every table:

- inspect the complete crop or page render;
- recover multi-level headers, spanners, panels, row labels, notes, units, and continuation pages;
- compare every reported cell with the render before quoting it;
- do not infer that an extraction blank is a manuscript blank;
- omit CSV as an authoritative representation when the table is nonrectangular;
- link the verified table audit to the ingestion object and source anchor.

If detection misses a table, add a manual render crop and audit record; never conclude that the paper has no tables from the candidate inventory alone.

## Figures

Caption-driven crops are deliberately inclusive because many economics figures are vector drawings rather than embedded raster images. Inspect and, when necessary, replace the automatic region with a manual crop that contains every panel, axis, legend, note, and caption. The full page render remains available to resolve crop boundaries and nearby references.

Do not infer `no figures` from `pdfimages`: vector figures often have no extractable image object. Confirm absence from all rendered pages.

## Equations and symbols

Generic PDF extraction cannot guarantee correct mathematical semantics, especially when fonts lack Unicode maps. For each load-bearing equation:

- use TeX source when supplied and compare the compiled form with the PDF;
- otherwise inspect the saved equation crop and treat `raw_unicode` only as a search/navigation candidate;
- manually record a transcription only after checking subscripts, superscripts, accents, brackets, operators, equation numbers, line breaks, and signs;
- keep unresolved formulas `bounded`; do not quote or derive from corrupted text;
- reconcile the exact symbol inventory with the later term/variable map. For every emitted symbol candidate, retain its codepoints and block-derived occurrence anchors, then adjudicate it as a mapped term, standard unambiguous notation, prose noise, extraction artifact, or non-load-bearing notation with a paper-specific reason. Mapped terms record first-use and definition anchors, domain, units, normalization, and every material reuse; an actually undefined term records a scope-anchored checked absence rather than a fabricated definition.

Pay special attention to Latin/Greek lookalikes, `l/1`, `O/0`, `v/ν`, minus/hyphen, multiplication/letter x, primes, accents, and missing superscripts or subscripts. A machine confidence value never authorizes a quotation.

## OCR and degraded cases

`--ocr auto` invokes local Tesseract only for pages with sparse native text or control glyphs. When OCR is selected, its preserved text—not the damaged native blocks—drives canonical Markdown, while both alternatives remain hashed in the package. OCR-derived prose is low-confidence until checked against the page. OCR does not make equation, symbol, or table transcription complete.

Replacement characters and private-use glyphs also trigger the automatic OCR
comparison when Tesseract is available. They remain disclosed and require
render verification even when OCR appears cleaner.

The preflight also uses `pypdf` only as a non-executing structural inspector. Encryption fails closed. Document JavaScript, open/additional actions, annotation actions, forms, portfolios, and embedded files are recorded as warnings; no action runs and no attachment is opened. Repeated page-level and annotation-action findings are grouped by type with sorted page ranges, while document-level OpenAction remains a distinct warning.

Docling is a non-authoritative local proposal. `auto` may use cached models; `docling` fails closed when the backend cannot run. `--allow-model-downloads` authorizes downloading model artifacts, not uploading the manuscript. Formula enrichment is disabled by default because it can be slow and model-generated; `--docling-formulas` does not waive render verification.

MarkItDown is never invoked by default. Its proposal is a convenience comparison, not a fallback completion gate, verified quotation source, equation transcription, or table authority.

Mathpix is never invoked by default. The adapter uploads the complete PDF, retrieves Mathpix Markdown and line data, and requests deletion in a `finally` path. Ingestion fails if deletion cannot be confirmed. A completed package records the provider request ID; retain any request ID shown in a failed-job error for operator follow-up. Provider documentation allows retention windows and short-lived caches that a successful delete response may not erase instantly. Treat the output as a proposal and independently verify it against the render. Do not use Mathpix output to train or develop a competing conversion model without written permission and legal review.

A review agent may inspect saved page images using the user's active model subscription when that processing is within the authorized environment. This is visual adjudication, not a second canonical converter: record which pages and objects were inspected, retain the render-backed result or boundary, and never infer that a subscription grants permission to send a confidential manuscript to an unrelated API.

Use the following states honestly:

- `ready_for_review`: all pages were rendered and have native/OCR text or an explicit page record; visual object verification is still required.
- `bounded`: one or more pages or mathematical objects cannot be transcribed safely; the review may continue only within the recorded boundary.
- `failed`: the source, resource limits, extraction, rendering, package validation, or atomic commit failed.

Encrypted PDFs, malformed page counts, unsafe paths, excessive page/file limits, missing required tools, hash failures, and broken character spans fail closed. To avoid accidental disk and memory exhaustion from render expansion, ingestion defaults to at most 500 pages and 250 MB; an operator may raise those limits explicitly up to the 2,000-page and 1 GB hard caps. Embedded JavaScript, forms, attachments, and actions are never executed.

## Parser isolation boundary

A PDF is attacker-controlled input to native and model-heavy parsers. Byte,
page, file-count, response-size, and timeout limits reduce exposure; they do not
make Poppler, pypdf, pdfplumber, Pillow, Tesseract, Docling, or their transitive
libraries memory-safe or eliminate parser vulnerabilities. Keep these tools
patched and do not describe the Python preflight as a security sandbox.

Local use inherits the security boundary of the user's machine and installed
tools. A hosted service should run ingestion in an ephemeral, least-privilege
worker with no manuscript-derived network egress, strict CPU/memory/disk/process
limits, a read-only runtime, isolated temporary storage, and deletion after the
declared retention window. Put separately authorized remote proposals behind a
distinct egress-capable broker so the default parser worker remains offline.

## Completion gates

Before reconstruction or finalization:

1. `pdf_ingestion.py check` passes.
2. The declared PDF page count equals the page, text, and render inventories.
3. Every table and figure visible in the rendered manuscript is represented in the relevant audit, even if automatic detection missed it.
4. Every load-bearing equation and ambiguous symbol has render-backed verification or an explicit boundary.
5. Quotations resolve to Markdown spans whose markers map back to PDF page and bounding box.
6. The generated source-manifest fragment has been merged without duplicate IDs and the normal trust-spine validation passes. For a new full review, confirm that each in-scope PDF source contributes exactly one authenticated `scope` anchor; acceptance of an older block-only ingestion package is a compatibility decision, not evidence of source-wide coverage.

The package check recomputes hashes for the original PDF, canonical Markdown, selected/native/OCR page text, every page render, every object crop, candidate table Markdown/CSV, and every declared proposal artifact. It also decodes every declared render and crop, checks page-pixel geometry against the declared DPI, verifies crop dimensions do not exceed their source page, and validates page order, source-qualified and unique IDs, page/bounding-box references, block spans, symbol references, object-to-block links, proposal input hashes and processing declarations, reconciliation counts, quality flags, and the generated source-manifest fragment. For a remote proposal it additionally checks that explicit authorization and confirmed deletion were recorded and that credential fields were not persisted.

Passing ingestion means the extraction package is internally intact. It does not mean that automatic Markdown, table grids, formulas, or symbols are substantively correct; that requires the separate reconstruction, exhibit, technical, and verification passes.
