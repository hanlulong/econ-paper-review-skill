# PDF Ingestion and Verified Transcription

Use this protocol whenever a PDF is a source, including when TeX, Word, or Markdown is also supplied. A PDF has no canonical semantic Markdown representation. The generated Markdown is a navigable transcription; the original PDF and page/object renders remain authoritative for layout, equations, tables, figures, and ambiguous glyphs.

Read [pdf-backends.md](pdf-backends.md) before installing, invoking, or adding a conversion backend. Backend selection must preserve this contract and the project's commercial-license boundary.

## Local command

Run the dependency check once:

```bash
python3 scripts/pdf_ingestion.py doctor
```

For a PDF-only manuscript, create the source package before reconstruction:

```bash
python3 scripts/pdf_ingestion.py ingest manuscript.pdf review \
  --review-id REVIEW-ID --source-id SRC-01 --ocr auto
```

This writes `review/evidence/pdf-ingestion/SRC-01/` atomically. Each PDF source receives a separate default directory and source-qualified block, object, and anchor IDs. Use `--role appendix` or `--role supplement` for additional sources; the default role is `manuscript`. Rerunning is idempotent only when the source hash, review/source identity, role, extraction configuration, requested proposal state, and complete toolchain fingerprint match. A changed or invalid existing package requires `--force`. Validate it independently with:

```bash
python3 scripts/pdf_ingestion.py check review/evidence/pdf-ingestion/SRC-01
```

The module never calls a network service. External OCR or equation transcription is outside this contract and requires explicit user permission plus a separately recorded privacy boundary.

## Outputs and authority

- `source/original.pdf`: private read-only copy with the original SHA-256.
- `manuscript.md`: paper-order reading surface with stable block markers, PDF pages, bounding boxes, methods, and character spans.
- `pages/page-NNNN.native.txt`: the preserved native text-layer alternative, including an explicit empty file when no native text exists.
- `pages/page-NNNN.ocr.txt`: the preserved local-OCR alternative when OCR was attempted. `ingestion.json` identifies which alternative drives canonical Markdown.
- `renders/page-NNNN.png`: complete page render for visual authority.
- `objects/tables/`: rendered crops plus candidate Markdown and CSV grids when a rectangular grid is recovered.
- `objects/figures/`: caption-driven crops that preserve vector and composite figures through rendering.
- `objects/equations/`: rendered crops plus raw glyph candidates; generic PDF text is never labeled verified LaTeX.
- `ingestion.json`: hashes, tool versions, per-page methods and warnings, typed blocks/objects, symbol occurrences, and quality state.
- `source-manifest.generated.json`: a valid single-source manifest that can seed or be merged into `review/evidence/source-manifest.json` after checking source-ID and anchor-ID uniqueness.
- `proposals/markitdown.md`: an optional, non-authoritative proposal written only when `--markitdown-proposal` is explicitly requested and a local `markitdown` command is installed. Its engine version and hash are recorded; it never changes canonical Markdown or evidence authority.

Do not list the source PDF or complete page renders in the author-facing review document manifest. The local Review Desk may consume the generated Markdown and selected audit crops, but a public build must never bundle manuscript-derived assets without explicit publication authorization.

## Source preference and reconciliation

Use the richest source without weakening visual verification:

1. When TeX or structured Markdown exists, use it for semantic structure, equations, and tables, align it to PDF pages, and keep the PDF renders as visual authority.
2. For a born-digital PDF with usable Unicode, use native prose blocks but verify every load-bearing formula, symbol, table, and figure against its render.
3. For missing or damaged text layers, use local OCR for prose only. Preserve the native alternative and warnings; keep tables and equations image-backed.
4. If extraction and the rendered page conflict, the visible page controls what the paper actually communicates. Resolve manually or mark the object bounded.

Never normalize mathematical text with NFKC. It can collapse distinctions among symbols, superscripts, compatibility glyphs, and formatting. The ingester preserves raw UTF-8 block content and records Unicode codepoints and warnings.

Poppler can emit XML 1.0-forbidden control characters in its bounding-box XHTML when a PDF font has a damaged or missing Unicode map. The ingester removes only those forbidden characters from the temporary XML parser input so that layout parsing can continue. `ingestion.json.parser_repairs` records the exact count, affected codepoints, raw XHTML hash, parser-input hash, and repair policy. A nonzero count is also disclosed in the quality warnings. This repair does not normalize, guess, or replace a mathematical symbol; the copied PDF and rendered page remain authoritative, and any affected transcription still requires visual verification.

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
- reconcile the symbol inventory with the later term/variable map, including first definition, domain, units, normalization, and every material reuse.

Pay special attention to Latin/Greek lookalikes, `l/1`, `O/0`, `v/ν`, minus/hyphen, multiplication/letter x, primes, accents, and missing superscripts or subscripts. A machine confidence value never authorizes a quotation.

## OCR and degraded cases

`--ocr auto` invokes local Tesseract only for pages with sparse native text or control glyphs. When OCR is selected, its preserved text—not the damaged native blocks—drives canonical Markdown, while both alternatives remain hashed in the package. OCR-derived prose is low-confidence until checked against the page. OCR does not make equation, symbol, or table transcription complete.

The preflight also uses `pypdf` only as a non-executing structural inspector. Encryption fails closed. Document JavaScript, open/additional actions, annotation actions, forms, portfolios, and embedded files are recorded as warnings; no action runs and no attachment is opened. Repeated page-level and annotation-action findings are grouped by type with sorted page ranges, while document-level OpenAction remains a distinct warning.

MarkItDown is never invoked by default. Its proposal is a convenience comparison, not a fallback completion gate, verified quotation source, equation transcription, or table authority. Do not enable it merely because the native extraction is weak; resolve weak extraction from the rendered PDF and the appropriate source files.

Use the following states honestly:

- `ready_for_review`: all pages were rendered and have native/OCR text or an explicit page record; visual object verification is still required.
- `bounded`: one or more pages or mathematical objects cannot be transcribed safely; the review may continue only within the recorded boundary.
- `failed`: the source, resource limits, extraction, rendering, package validation, or atomic commit failed.

Encrypted PDFs, malformed page counts, unsafe paths, excessive page/file limits, missing required tools, hash failures, and broken character spans fail closed. Embedded JavaScript, forms, attachments, and actions are never executed.

## Completion gates

Before reconstruction or finalization:

1. `pdf_ingestion.py check` passes.
2. The declared PDF page count equals the page, text, and render inventories.
3. Every table and figure visible in the rendered manuscript is represented in the relevant audit, even if automatic detection missed it.
4. Every load-bearing equation and ambiguous symbol has render-backed verification or an explicit boundary.
5. Quotations resolve to Markdown spans whose markers map back to PDF page and bounding box.
6. The generated source-manifest fragment has been merged without duplicate IDs and the normal trust-spine validation passes.

The package check recomputes hashes for the original PDF, canonical Markdown, selected/native/OCR page text, every page render, every object crop, candidate table Markdown/CSV, and any MarkItDown proposal. It also verifies page order, source-qualified and unique IDs, page/bounding-box references, block spans, symbol references, object-to-block links, quality flags, and the generated source-manifest fragment.

Passing ingestion means the extraction package is internally intact. It does not mean that automatic Markdown, table grids, formulas, or symbols are substantively correct; that requires the separate reconstruction, exhibit, technical, and verification passes.
