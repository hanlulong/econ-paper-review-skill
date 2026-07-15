# Third-Party Components and PDF Backend Policy

This file records the present dependency boundary. It is not a substitute for
legal advice. Recheck package versions and license terms before any public or
commercial release.

Policy links and terms below were last rechecked on 2026-07-14. A date-stamped
check is evidence of review, not a guarantee that provider terms remain
unchanged.

## Used by the local core

| Component | License | Current use | Distribution boundary |
|---|---|---|---|
| `jsonschema` | MIT | Review-contract validation | Python dependency; not vendored |
| `defusedxml` | Python Software Foundation license | Defensive parsing of Poppler-generated XHTML | Python dependency; not vendored |
| `pdfplumber` / `pdfminer.six` | MIT | PDF geometry and table candidates | Python dependencies; not vendored |
| `pypdfium2` / PDFium | Apache-2.0 or BSD-3-Clause for `pypdfium2`; BSD-style and additional dependency licenses for the distributed PDFium build | Cross-platform rendering dependency installed transitively by `pdfplumber`; not selected as the canonical ingestion backend | Python wheel dependency; not vendored |
| `pypdf` | BSD-3-Clause | PDF structural and safety inspection | Python dependency; not vendored |
| `reportlab` | BSD-3-Clause | Maintained PDF-report fallback when no supported TeX renderer is available | Python dependency; not vendored |
| Bitstream Vera fonts (distributed by `reportlab`) | Bitstream Vera font license | Fixed fonts for the ReportLab fallback | Loaded from the separately installed ReportLab package; glyph subsets may be embedded in generated reports |
| Pillow | HPND | Image inspection and deterministic crops | Python dependency; not vendored |
| PyYAML | MIT | Agent-skill package validation | Python dependency; not vendored |
| `packaging` | Apache-2.0 or BSD-2-Clause | Offline PEP 440/508 checks against bundled requirement manifests | Python dependency; not vendored |
| Tesseract | Apache-2.0 | Optional local prose OCR | External executable; not bundled |
| Poppler utilities | GPL | Page metadata, text geometry, and rendering | External executables; not bundled |
| [LuaLaTeX / TeX Live](https://www.tug.org/texlive/copying.html) | Package-specific free-software licenses | Preferred professional PDF report rendering when already installed | External executable and support tree; not bundled or installed by this project |
| [Tectonic](https://github.com/tectonic-typesetting/tectonic/blob/master/LICENSE) | MIT; derived TeX components use additional open-source licenses | Preferred professional PDF report rendering when explicitly installed | External executable and support bundle; not bundled or installed by this project |

Invoking a separately installed executable is not permission to redistribute
its binary. If an online or desktop distribution later bundles Poppler or
Tesseract, perform a new packaging and license review first.

The `pypdfium2` wheels include a PDFium binary and build-specific license
materials. Preserve and re-audit those notices if a future release vendors or
redistributes the managed Python runtime. The current installer obtains the
wheel through the declared Python dependency graph and does not copy it into
the source repository or plugin archive.

ReportLab 4.5.1 is pinned so fallback PDF bytes and line wrapping remain
reproducible. Its packaged Bitstream Vera fonts provide a fixed cross-platform
font source. The Vera license permits redistribution and embedding subject to
its notice and naming conditions; preserve the license file distributed with
ReportLab (`reportlab/fonts/bitstream-vera-license.txt`) when packaging the
runtime, and reassess notice placement before distributing a desktop or hosted
report generator.

The LaTeX report template expects standard TeX packages and fonts, including
the standard `article` class, Libertinus, TeX Gyre fallbacks, `microtype`,
`hyperref`, and the table and framing packages declared by the template. They
remain part of the user's
separately installed TeX distribution and are not copied into this repository.
TeX Live permits redistribution subject to the license terms of its individual
components, often including source-availability conditions; Tectonic is
MIT-licensed, while the TeX components from which it is derived retain their
own licenses. Re-audit the exact executable, support bundle, packages, and fonts
before bundling any TeX runtime. Pandoc is not used, bundled, or required.

## Used only by the optional hosted adapter

| Component | License | Current use | Distribution boundary |
|---|---|---|---|
| `requests` | Apache-2.0 | Server-side calls to an explicitly authorized Mathpix job | Optional Python dependency; not vendored |

## Review Desk dependency boundary

The Review Desk's direct JavaScript dependencies are declared in
`review-viewer/package.json`, and `package-lock.json` records the exact resolved
tree. Development dependencies are downloaded by npm and are not checked into
the source tree as `node_modules/`. The checked-in
`econ-review/assets/review-desk.zip`, however, is a distributable compiled
artifact and does contain third-party client code, CSS, and font files.

Every static release build derives its shipped-package inventory from Vite's
exact client output module graph, verifies each package and version against
`package-lock.json`, and fails if a shipped package lacks a complete license or
notice text. The bundle includes `app/THIRD_PARTY_NOTICES.txt`, a canonical
`app/third-party-licenses/manifest.json`, and the referenced upstream license
and notice files. KaTeX's emitted fonts carry their separate SIL Open Font
License 1.1 copyright and Reserved Font Name notice. These files are covered by
the bundle's own per-file hash manifest and are enforced by the bundle builder,
installer release tests, and public-release scanner. Vite, Vinext, Cloudflare,
and other development tools are not listed in that runtime inventory unless
their modules actually enter the static client artifact.

The full development lockfile includes packages that do not enter the static
artifact and therefore can have a broader license mix than the embedded
runtime inventory. A hosted deployment or a different build target must be
audited from its own exact deployed artifact rather than reusing the static
bundle's inventory.

Before a commercial deployment, generate an SBOM from the exact lockfile and
deployed artifact, preserve all required notices, and obtain a legal review of
the resulting distribution and hosting model. The deterministic embedded
inventory improves traceability but is not legal advice or a substitute for
that review. `npm audit` checks known security advisories; it is not a license
or attribution audit.

## Evaluated conversion backends

- [Docling](https://github.com/docling-project/docling) is an optional local
  semantic-structure proposal backend. Its repository code is
  [MIT-licensed](https://github.com/docling-project/docling/blob/main/LICENSE),
  while runtime model artifacts and their exact revisions remain a separate
  distribution audit (the current `docling-ibm-models` source repository is
  also MIT-licensed, but that fact alone does not inventory every artifact a
  future runtime may fetch). The
  lightweight install does not include Docling. `requirements-docling.txt`
  pins the evaluated code version; model downloads remain a separate explicit
  action. Re-audit code, transitive dependencies, model licenses, and model
  revisions before distribution or a hosted release.
- [Microsoft MarkItDown](https://github.com/microsoft/markitdown) is
  [MIT-licensed](https://github.com/microsoft/markitdown/blob/main/LICENSE) and may be evaluated as an optional
  local semantic proposal backend. Its PDF conversion is not a substitute for
  page/bounding-box provenance or render verification, so it must not become
  the sole authority for equations, tables, figures, or symbols. Its own
  security guidance says conversion runs with the privileges of the current
  process; untrusted inputs therefore belong in the same isolated worker
  boundary as the other native/model-heavy parsers. The optional
  `requirements-markitdown.txt` manifest pins the evaluated adapter version;
  its transitive PDF parser dependencies remain non-vendored and must be
  re-audited when that pin changes.
- [Datalab Marker](https://github.com/datalab-to/marker) is not approved for integration. Its repository code is
  [GPL-3.0](https://github.com/datalab-to/marker/blob/master/LICENSE) and its
  [model license](https://github.com/datalab-to/marker/blob/master/MODEL_LICENSE) adds commercial restrictions, including a
  competing-product restriction. Do not install, call, host, redistribute, or
  use Marker-generated output in the product without a separate written
  commercial license and legal review.
- [Nutrient/PSPDFKit PDF-to-Markdown](https://github.com/PSPDFKit/pdf-to-markdown) is not approved for integration under its
  [free license](https://github.com/PSPDFKit/pdf-to-markdown/blob/main/LICENSE.md). The license is proprietary and includes a competing-product
  restriction, a 1,000-document monthly limit, and permission to transmit
  non-content usage data. Use requires a written commercial agreement and
  legal review; the public wrapper repository is not an open-source grant for
  its signed extraction engine.

## Hosted service boundary

[Mathpix PDF API](https://docs.mathpix.com/reference/post-v3-pdf) is an optional
hosted premium service, not bundled software. A call transmits the complete PDF
to Mathpix and is permitted only after manuscript-specific upload authorization
and acknowledgement of the current provider-retention policy. The adapter reads
its permissively licensed HTTP client from the separately installed
`requirements-mathpix.txt` environment. Mathpix itself remains governed by the
customer's service contract and is not redistributed by this project. The adapter
reads credentials from server-side environment variables, requests remote deletion,
and stores a non-secret deletion receipt. Deletion confirmation does not promise
instant removal from every cache, billing record, or audit system.

The adapter explicitly sends `metadata.improve_mathpix=false`. Current Mathpix
documentation says this disables quality-improvement access but still retains
request metadata for audit and billing, and that PDF page-image CDN copies can
persist until explicit deletion and cache expiry. Treat the complete upload as
external disclosure even with that setting.

Before commercial launch, review the current Mathpix pricing, privacy and
[data-retention terms](https://docs.mathpix.com/concepts/data-retention), obtain
any required data-processing agreement or written product-use confirmation, and
confirm the restriction on using service output to develop competing models.
Provider terms and prices can change independently of this repository.

No cloud OCR, hosted converter, or external model may receive a manuscript by
default. Any future external backend requires explicit user consent, a data
retention and confidentiality review, and a recorded processing policy.
