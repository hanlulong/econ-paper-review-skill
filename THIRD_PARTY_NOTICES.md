# Third-Party Components and PDF Backend Policy

This file records the present dependency boundary. It is not a substitute for
legal advice. Recheck package versions and license terms before any public or
commercial release.

Policy links and terms below were last rechecked on 2026-07-13. A date-stamped
check is evidence of review, not a guarantee that provider terms remain
unchanged.

## Used by the local core

| Component | License | Current use | Distribution boundary |
|---|---|---|---|
| `jsonschema` | MIT | Review-contract validation | Python dependency; not vendored |
| `defusedxml` | Python Software Foundation license | Defensive parsing of Poppler-generated XHTML | Python dependency; not vendored |
| `pdfplumber` / `pdfminer.six` | MIT | PDF geometry and table candidates | Python dependencies; not vendored |
| `pypdf` | BSD-3-Clause | PDF structural and safety inspection | Python dependency; not vendored |
| Pillow | HPND | Image inspection and deterministic crops | Python dependency; not vendored |
| PyYAML | MIT | Agent-skill package validation | Python dependency; not vendored |
| `packaging` | Apache-2.0 or BSD-2-Clause | Offline PEP 440/508 checks against bundled requirement manifests | Python dependency; not vendored |
| Tesseract | Apache-2.0 | Optional local prose OCR | External executable; not bundled |
| Poppler utilities | GPL | Page metadata, text geometry, and rendering | External executables; not bundled |

Invoking a separately installed executable is not permission to redistribute
its binary. If an online or desktop distribution later bundles Poppler or
Tesseract, perform a new packaging and license review first.

## Used only by the optional hosted adapter

| Component | License | Current use | Distribution boundary |
|---|---|---|---|
| `requests` | Apache-2.0 | Server-side calls to an explicitly authorized Mathpix job | Optional Python dependency; not vendored |

## Review Desk dependency boundary

The Review Desk's direct JavaScript dependencies are declared in
`review-viewer/package.json`, and `package-lock.json` records the exact resolved
tree. They are downloaded by npm and are not vendored in this source archive.
The tree is predominantly permissively licensed, but the current lockfile also
records MPL-2.0 components, libvips platform packages under
LGPL-3.0-or-later, and smaller numbers of CC-BY-4.0, Python-2.0,
BlueOak-1.0.0, and 0BSD components. A production build or hosted deployment
may therefore carry attribution, notice, source-availability, relinking, or
other obligations that do not arise merely from publishing this source tree.
The generated viewer build also embeds font files; include their applicable
font license and notices in the deployment review even though generated build
directories are excluded from this source archive.

Before a commercial deployment, generate an SBOM from the exact lockfile,
identify which transitive components enter the deployed artifact, preserve all
required notices, and obtain a legal review of the resulting distribution and
hosting model. `npm audit` checks known security advisories; it is not a license
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
