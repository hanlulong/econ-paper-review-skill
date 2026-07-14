const CORE_REVIEW_FILES = new Set([
  "findings.json",
  "run.json",
  "tables.json",
  "figures.json",
  "review-manifest.json",
]);

const REVIEW_DOCUMENT_NAMES = new Set([
  "readme.md",
  "report.md",
  "editing-comments.md",
  "fix-plan.md",
  "reconstruction.md",
  "reader-claim-audit.md",
  "figures.md",
  "tables.md",
  "analytical-audit.md",
  "writing.md",
  "coverage.md",
  "sources.md",
  "verification.md",
]);

const WINDOWS_DEVICE_BASENAMES = new Set([
  "CON", "PRN", "AUX", "NUL", "CLOCK$",
  ...Array.from({ length: 9 }, (_, index) => `COM${index + 1}`),
  ...Array.from({ length: 9 }, (_, index) => `LPT${index + 1}`),
]);

function basename(path: string) {
  return path.split("/").at(-1) || path;
}

function dirname(path: string) {
  const parts = path.split("/");
  parts.pop();
  return parts.join("/");
}

export function normalizePackagePath(path: string) {
  if (
    !path
    || path !== path.trim()
    || path !== path.normalize("NFC")
    || path.startsWith("/")
    || path.includes("\\")
    || path.includes(":")
    || /[\u0000-\u001f\u007f]/.test(path)
  ) throw new Error(`Unsafe relative path in the selected package: ${path}`);
  const parts = path.split("/");
  if (parts.some((part) => (
    !part
    || part === "."
    || part === ".."
    || part !== part.trim()
    || part.endsWith(".")
    || WINDOWS_DEVICE_BASENAMES.has(part.split(".", 1)[0].toLocaleUpperCase("en-US"))
  ))) {
    throw new Error(`Unsafe relative path in the selected package: ${path}`);
  }
  return parts.join("/");
}

/** Normalize the Unicode form supplied by an OS file picker, then enforce the package contract. */
export function normalizeSelectedPackagePath(path: string) {
  return normalizePackagePath(path.normalize("NFC"));
}

/** Find the one directory that contains a findings/run pair. Its name is deliberately unrestricted. */
export function inferReviewPackageRoot(paths: Iterable<string>) {
  const roots = new Map<string, Set<string>>();
  for (const rawPath of paths) {
    const path = normalizePackagePath(rawPath);
    const name = basename(path).toLowerCase();
    if (name !== "findings.json" && name !== "run.json") continue;
    const root = dirname(path);
    const names = roots.get(root) || new Set<string>();
    names.add(name);
    roots.set(root, names);
  }
  const candidates = Array.from(roots.entries())
    .filter(([, names]) => names.has("findings.json") && names.has("run.json"))
    .map(([root]) => root);
  if (!candidates.length) throw new Error("Select both findings.json and run.json from the same review package.");
  if (candidates.length > 1) throw new Error("Multiple complete review packages were selected. Open one package at a time.");
  return candidates[0];
}

export function relativeToReviewRoot(rawPath: string, rawRoot: string) {
  const path = normalizePackagePath(rawPath);
  const root = rawRoot ? normalizePackagePath(rawRoot) : "";
  if (!root) return path;
  if (!path.startsWith(`${root}/`)) return null;
  return path.slice(root.length + 1);
}

/**
 * Select a package file by its canonical review-relative path, with ordered
 * compatibility fallbacks. Canonical paths always win when both layouts are
 * present; ambiguous case variants fail closed instead of depending on file
 * picker order.
 */
export function selectReviewPackageFilePath(options: {
  paths: Iterable<string>;
  reviewRoot: string;
  canonicalPath: string;
  fallbackPaths?: Iterable<string>;
}) {
  const paths = Array.from(options.paths, normalizePackagePath);
  const candidates = [options.canonicalPath, ...Array.from(options.fallbackPaths || [])]
    .map(normalizePackagePath);

  for (const candidate of candidates) {
    const matches = paths.filter((path) => (
      relativeToReviewRoot(path, options.reviewRoot)?.toLowerCase() === candidate.toLowerCase()
    ));
    if (matches.length > 1) {
      throw new Error(`Multiple ${candidate} files occur at the inferred review root.`);
    }
    if (matches.length === 1) return matches[0];
  }
  return null;
}

function sourceMatches(candidate: string, source: string) {
  const normalizedCandidate = normalizePackagePath(candidate).toLowerCase();
  const normalizedSource = source.replaceAll("\\", "/").replace(/^\/+/, "").replace(/^\.\//, "").toLowerCase();
  if (!normalizedSource) return false;
  return normalizedCandidate === normalizedSource
    || normalizedCandidate.endsWith(`/${normalizedSource}`)
    || normalizedSource.endsWith(`/${normalizedCandidate}`)
    || basename(normalizedCandidate) === basename(normalizedSource);
}

/**
 * Select manuscript text conservatively. When run.json names source files, only an exact/suffix/basename
 * match is accepted; otherwise a single unambiguous text candidate is allowed.
 */
export function selectManuscriptPath(options: {
  paths: Iterable<string>;
  reviewRoot: string;
  declaredDocumentPaths?: Iterable<string>;
  sourcePaths?: Iterable<string>;
}) {
  const declared = new Set(Array.from(options.declaredDocumentPaths || [], (path) => normalizePackagePath(path).toLowerCase()));
  const sources = Array.from(options.sourcePaths || []).filter(Boolean);
  const candidates = Array.from(options.paths, normalizePackagePath).filter((path) => {
    const name = basename(path).toLowerCase();
    if (!/\.(md|markdown|txt)$/i.test(name) || REVIEW_DOCUMENT_NAMES.has(name) || CORE_REVIEW_FILES.has(name)) return false;
    const relative = relativeToReviewRoot(path, options.reviewRoot);
    if (relative && declared.has(relative.toLowerCase())) return false;
    return true;
  });

  if (sources.length) {
    const matched = candidates.filter((candidate) => sources.some((source) => sourceMatches(candidate, source)));
    if (matched.length > 1) {
      throw new Error(`Multiple manuscript files match run.json (${matched.map(basename).join(", ")}). Select one unambiguous source file.`);
    }
    return matched[0] || null;
  }

  const plausible = candidates.filter((path) => {
    const relative = relativeToReviewRoot(path, options.reviewRoot);
    if (relative === null || !options.reviewRoot) return true;
    return /^(manuscript|paper|source)(?:[-_. ]|$)/i.test(basename(path));
  });
  if (plausible.length > 1) {
    throw new Error(`Multiple manuscript files were selected (${plausible.map(basename).join(", ")}). Select exactly one manuscript.`);
  }
  return plausible[0] || null;
}

export function referencedExhibitPaths(tables: unknown, figures: unknown) {
  const paths = new Set<string>();
  const add = (value: unknown, collection: "tables" | "figures", field: "render_paths" | "extraction_paths") => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return;
    const rows = (value as Record<string, unknown>)[collection];
    if (!Array.isArray(rows)) return;
    for (const row of rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) continue;
      const rawPaths = (row as Record<string, unknown>)[field];
      if (!Array.isArray(rawPaths)) continue;
      for (const path of rawPaths) if (typeof path === "string" && path.trim()) paths.add(normalizePackagePath(path));
    }
  };
  add(tables, "tables", "render_paths");
  add(figures, "figures", "extraction_paths");
  for (const [manifest, collection] of [[tables, "tables"], [figures, "figures"]] as const) {
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) continue;
    const rows = (manifest as Record<string, unknown>)[collection];
    if (Array.isArray(rows)) {
      for (const row of rows) {
        if (!row || typeof row !== "object" || Array.isArray(row)) continue;
        const assets = (row as Record<string, unknown>).rendered_assets;
        if (!Array.isArray(assets)) continue;
        for (const asset of assets) {
          if (!asset || typeof asset !== "object" || Array.isArray(asset)) continue;
          const path = (asset as Record<string, unknown>).path;
          if (typeof path === "string" && path.trim()) paths.add(normalizePackagePath(path));
        }
      }
    }
  }
  return Array.from(paths);
}

const ASSESSMENT_BOUNDARY_KEYS = new Set([
  "checked_scope",
  "status_basis",
  "reason",
  "missing_input",
  "decisive_evidence_needed",
]);
const ASSESSMENT_BOUNDARY_BASES = new Set([
  "unreadable_render",
  "ambiguous_visual_identity",
  "incomplete_extraction",
  "missing_surrounding_context",
  "unavailable_source",
  "other",
]);
const VISIBLE_IDENTITY_BASES: Record<"tables" | "figures", Set<string>> = {
  figures: new Set([
    "figure_label",
    "caption_or_title",
    "panel_or_axis_text",
    "legend_or_annotation",
    "distinctive_visible_text",
    "visual_structure",
  ]),
  tables: new Set([
    "table_label",
    "caption_or_title",
    "panel_or_header_text",
    "row_or_column_text",
    "notes_or_annotation",
    "distinctive_visible_text",
    "visual_structure",
  ]),
};

function nonEmptyString(value: unknown) {
  return typeof value === "string" && Boolean(value.trim());
}

function positiveIntegerPages(value: unknown, label: string) {
  if (!Array.isArray(value)
    || value.some((page) => !Number.isInteger(page) || Number(page) < 1)
    || new Set(value).size !== value.length) {
    throw new Error(`${label} must be a unique list of positive page numbers`);
  }
  return value as number[];
}

function samePageSet(left: number[], right: number[]) {
  return left.length === right.length && left.every((page) => right.includes(page));
}

function validateAssessmentBoundary(value: unknown, bounded: boolean, label: string) {
  if (!bounded) {
    if (value !== null) throw new Error(`${label} must set assessment_boundary to null when no state is bounded`);
    return;
  }
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${label} requires a structured assessment_boundary for its bounded state`);
  }
  const boundary = value as Record<string, unknown>;
  const keys = Object.keys(boundary);
  if (keys.length !== ASSESSMENT_BOUNDARY_KEYS.size
    || keys.some((key) => !ASSESSMENT_BOUNDARY_KEYS.has(key))) {
    throw new Error(`${label} has a malformed assessment_boundary`);
  }
  for (const key of ["checked_scope", "reason", "missing_input", "decisive_evidence_needed"]) {
    if (!nonEmptyString(boundary[key])) throw new Error(`${label} has a malformed assessment_boundary`);
  }
  if (!ASSESSMENT_BOUNDARY_BASES.has(String(boundary.status_basis))) {
    throw new Error(`${label} has a malformed assessment_boundary`);
  }
}

function rowHasBoundedState(
  record: Record<string, unknown>,
  collection: "tables" | "figures",
  identityBounded: boolean,
) {
  const fields = collection === "tables"
    ? ["render_status", "extraction_status", "visual_status", "claim_correspondence_status"]
    : ["visual_status", "caption_text_status", "claim_correspondence_status"];
  if (identityBounded || fields.some((field) => record[field] === "bounded")) return true;
  if (collection !== "tables" || !record.checks || typeof record.checks !== "object" || Array.isArray(record.checks)) return false;
  return Object.values(record.checks as Record<string, unknown>).some((check) => (
    check && typeof check === "object" && !Array.isArray(check)
    && (check as Record<string, unknown>).status === "bounded"
  ));
}

/** Check the viewer-facing identity and asset contract before resolving files. */
export function validateExhibitManifest(
  value: unknown,
  collection: "tables" | "figures",
  reviewId: string,
): Record<string, unknown> | null {
  if (value === null || value === undefined) return null;
  if (!value || typeof value !== "object" || Array.isArray(value)) {
    throw new Error(`${collection}.json must contain an object`);
  }
  const manifest = value as Record<string, unknown>;
  const supported = ["0.1", "0.2"];
  if (!supported.includes(String(manifest.schema_version))) {
    throw new Error(`${collection}.json has an unsupported schema_version`);
  }
  if (manifest.review_id !== reviewId) throw new Error(`${collection}.json has a different review ID`);
  const rows = manifest[collection];
  if (!Array.isArray(rows)) throw new Error(`${collection}.json is missing its ${collection} array`);
  const emptyFlag = collection === "tables" ? manifest.no_tables_confirmed : manifest.no_figures_confirmed;
  if (typeof emptyFlag !== "boolean") throw new Error(`${collection}.json is missing its confirmed-empty state`);
  if (emptyFlag === (rows.length > 0)) throw new Error(`${collection}.json inventory state contradicts its exhibit rows`);
  const labels = new Set<string>();
  const assetOwners = new Map<string, { row: number; renderType: string; page: number | null; sha256: string }>();
  for (const [index, row] of rows.entries()) {
    if (!row || typeof row !== "object" || Array.isArray(row)) throw new Error(`${collection}.json row ${index + 1} must be an object`);
    const record = row as Record<string, unknown>;
    if (typeof record.label !== "string" || !record.label.trim()) throw new Error(`${collection}.json row ${index + 1} has no label`);
    const labelKey = record.label.trim().toLowerCase();
    if (labels.has(labelKey)) throw new Error(`${collection}.json contains a duplicate exhibit label: ${record.label}`);
    labels.add(labelKey);
    if (manifest.schema_version === "0.2") {
      if (typeof record.source_id !== "string" || !/^SRC-[0-9]{2,}$/.test(record.source_id)) {
        throw new Error(`${collection}.json row ${index + 1} has no valid source binding`);
      }
      if (!Array.isArray(record.identity_keys) || !record.identity_keys.length) {
        throw new Error(`${collection}.json row ${index + 1} has no identity keys`);
      }
      if (record.identity_keys.some((key) => !nonEmptyString(key) || String(key).trim().length < 2)
        || new Set(record.identity_keys).size !== record.identity_keys.length) {
        throw new Error(`${collection}.json row ${index + 1} has invalid or duplicate identity keys`);
      }
      const declaredPages = positiveIntegerPages(record.pdf_pages, `${collection}.json row ${index + 1} pdf_pages`);
      const locator = record.source_locator;
      if (!locator || typeof locator !== "object" || Array.isArray(locator)
        || (locator as Record<string, unknown>).source_id !== record.source_id
        || !Array.isArray((locator as Record<string, unknown>).pages)) {
        throw new Error(`${collection}.json row ${index + 1} has no valid source locator`);
      }
      const locatorRecord = locator as Record<string, unknown>;
      if (Object.keys(locatorRecord).some((key) => !["source_id", "pages", "context"].includes(key))
        || ("context" in locatorRecord && !nonEmptyString(locatorRecord.context))) {
        throw new Error(`${collection}.json row ${index + 1} has no valid source locator`);
      }
      const locatorPages = positiveIntegerPages(locatorRecord.pages, `${collection}.json row ${index + 1} source locator pages`);
      if (!samePageSet(locatorPages, declaredPages)) {
        throw new Error(`${collection}.json row ${index + 1} source locator pages differ from pdf_pages`);
      }
      if (!("assessment_boundary" in record)) {
        throw new Error(`${collection}.json row ${index + 1} has no explicit assessment boundary state`);
      }
      if (!Array.isArray(record.rendered_assets)) throw new Error(`${collection}.json row ${index + 1} has no rendered assets`);
      if (!record.rendered_assets.length && (collection === "figures" || record.render_status !== "bounded")) {
        throw new Error(`${collection}.json row ${index + 1} has no rendered assets`);
      }
      const rowPaths = new Set<string>();
      const fullPageRoles = new Set<string>();
      const fullPagePages = new Set<number>();
      const cropObjectIds = new Set<string>();
      let identityBounded = false;
      let identityMismatch = false;
      for (const [assetIndex, asset] of record.rendered_assets.entries()) {
        if (!asset || typeof asset !== "object" || Array.isArray(asset)) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} must be an object`);
        }
        const rendered = asset as Record<string, unknown>;
        if (typeof rendered.path !== "string") throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has no path`);
        const assetPath = normalizePackagePath(rendered.path);
        if (rowPaths.has(assetPath)) throw new Error(`${collection}.json row ${index + 1} contains a duplicate rendered asset path`);
        rowPaths.add(assetPath);
        if (typeof rendered.sha256 !== "string" || !/^[a-f0-9]{64}$/.test(rendered.sha256)) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has an invalid hash`);
        }
        if (!["crop", "full_page"].includes(String(rendered.render_type))) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has an invalid render type`);
        }
        if (!("pdf_page" in rendered) || !(rendered.pdf_page === null || (Number.isInteger(rendered.pdf_page) && Number(rendered.pdf_page) >= 1))) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has an invalid page`);
        }
        if (!("source_object_id" in rendered)
          || !(rendered.source_object_id === null || (typeof rendered.source_object_id === "string" && rendered.source_object_id.trim()))) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has an invalid source object binding`);
        }
        if (rendered.render_type === "full_page" && rendered.source_object_id !== null) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} binds a full page to an object`);
        }
        const page = rendered.pdf_page as number | null;
        if ((page === null && declaredPages.length) || (page !== null && !declaredPages.includes(page))) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} page differs from pdf_pages`);
        }
        if (rendered.render_type === "full_page") {
          const role = `full_page:${page === null ? "unpaged" : page}`;
          if (fullPageRoles.has(role)) throw new Error(`${collection}.json row ${index + 1} contains a duplicate full-page role`);
          fullPageRoles.add(role);
          if (page !== null) fullPagePages.add(page);
        } else if (typeof rendered.source_object_id === "string") {
          if (cropObjectIds.has(rendered.source_object_id)) {
            throw new Error(`${collection}.json row ${index + 1} contains a duplicate crop object role`);
          }
          cropObjectIds.add(rendered.source_object_id);
        }
        const identity = rendered.visible_identity;
        if (!identity || typeof identity !== "object" || Array.isArray(identity)
          || Object.keys(identity).length !== 4
          || Object.keys(identity).some((key) => !["basis", "text", "status", "notes"].includes(key))
          || !VISIBLE_IDENTITY_BASES[collection].has(String((identity as Record<string, unknown>).basis))
          || !nonEmptyString((identity as Record<string, unknown>).text)
          || !nonEmptyString((identity as Record<string, unknown>).notes)
          || !["matched", "mismatch", "bounded"].includes(String((identity as Record<string, unknown>).status))) {
          throw new Error(`${collection}.json row ${index + 1} asset ${assetIndex + 1} has no valid visible identity`);
        }
        if ((identity as Record<string, unknown>).status === "bounded") identityBounded = true;
        if ((identity as Record<string, unknown>).status === "mismatch") identityMismatch = true;
        const owner = assetOwners.get(assetPath);
        const assetRecord = {
          row: index,
          renderType: String(rendered.render_type),
          page,
          sha256: rendered.sha256,
        };
        const reusableFullPage = owner
          && owner.row !== index
          && owner.renderType === "full_page"
          && assetRecord.renderType === "full_page"
          && owner.page === assetRecord.page
          && owner.sha256 === assetRecord.sha256;
        if (owner && !reusableFullPage) {
          throw new Error(`${collection}.json assigns one rendered asset path to conflicting rows or roles`);
        }
        if (!owner) assetOwners.set(assetPath, assetRecord);
      }
      if (collection === "figures"
        && (!fullPageRoles.size || !samePageSet(Array.from(fullPagePages), declaredPages))) {
        throw new Error(`${collection}.json row ${index + 1} full-page assets do not cover pdf_pages`);
      }
      if (identityBounded && record.visual_status !== "bounded") {
        throw new Error(`${collection}.json row ${index + 1} has bounded visible identity without bounded visual status`);
      }
      if (identityMismatch && record.visual_status !== "issue") {
        throw new Error(`${collection}.json row ${index + 1} has mismatched visible identity without issue visual status`);
      }
      validateAssessmentBoundary(
        record.assessment_boundary,
        rowHasBoundedState(record, collection, identityBounded),
        `${collection}.json row ${index + 1}`,
      );
    }
  }
  return manifest;
}

/** Return immutable hashes declared by current exhibit manifests. */
export function referencedExhibitHashes(tables: unknown, figures: unknown) {
  const hashes = new Map<string, string>();
  for (const [manifest, collection] of [[tables, "tables"], [figures, "figures"]] as const) {
    if (!manifest || typeof manifest !== "object" || Array.isArray(manifest)) continue;
    const rows = (manifest as Record<string, unknown>)[collection];
    if (!Array.isArray(rows)) continue;
    for (const row of rows) {
      if (!row || typeof row !== "object" || Array.isArray(row)) continue;
      const assets = (row as Record<string, unknown>).rendered_assets;
      if (!Array.isArray(assets)) continue;
      for (const asset of assets) {
        if (!asset || typeof asset !== "object" || Array.isArray(asset)) continue;
        const record = asset as Record<string, unknown>;
        if (typeof record.path !== "string" || typeof record.sha256 !== "string") continue;
        const path = normalizePackagePath(record.path);
        if (!/^[a-f0-9]{64}$/.test(record.sha256)) throw new Error(`Invalid exhibit hash for ${path}`);
        const prior = hashes.get(path);
        if (prior && prior !== record.sha256) throw new Error(`Conflicting exhibit hashes are declared for ${path}`);
        hashes.set(path, record.sha256);
      }
    }
  }
  return hashes;
}

export type ReviewImageMediaType = "image/png" | "image/jpeg" | "image/webp";

/** Fail closed before creating a browser object URL for a selected local file. */
export function reviewImageMediaType(path: string, bytes: Uint8Array): ReviewImageMediaType {
  const normalized = normalizePackagePath(path).toLowerCase();
  const extension = normalized.slice(normalized.lastIndexOf("."));
  const png = bytes.length >= 8
    && [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a].every((value, index) => bytes[index] === value);
  const jpeg = bytes.length >= 3 && bytes[0] === 0xff && bytes[1] === 0xd8 && bytes[2] === 0xff;
  const webp = bytes.length >= 12
    && String.fromCharCode(...bytes.slice(0, 4)) === "RIFF"
    && String.fromCharCode(...bytes.slice(8, 12)) === "WEBP";
  if (png && extension === ".png") return "image/png";
  if (jpeg && [".jpg", ".jpeg"].includes(extension)) return "image/jpeg";
  if (webp && extension === ".webp") return "image/webp";
  throw new Error(`Referenced exhibit ${path} is not a valid PNG, JPEG, or WebP file matching its extension`);
}

/** Hash browser-selected bytes without interpreting or executing the asset. */
export async function sha256ReviewBytes(bytes: Uint8Array): Promise<string> {
  if (!globalThis.crypto?.subtle) throw new Error("This browser cannot verify exhibit hashes");
  const digest = await globalThis.crypto.subtle.digest("SHA-256", bytes as BufferSource);
  return Array.from(new Uint8Array(digest), (value) => value.toString(16).padStart(2, "0")).join("");
}

/** Resolve only manifest-referenced image paths; ambiguous suffix matches intentionally remain unresolved. */
export function matchReferencedImagePaths(imagePaths: Iterable<string>, reviewRoot: string, references: Iterable<string>) {
  const images = Array.from(imagePaths, normalizePackagePath);
  const result = new Map<string, string | null>();
  for (const rawReference of references) {
    const reference = normalizePackagePath(rawReference);
    const matches = images.filter((path) => {
      const relative = relativeToReviewRoot(path, reviewRoot);
      if (reviewRoot && relative === null) return false;
      return relative === reference || Boolean(relative?.endsWith(`/${reference}`))
        || (!reviewRoot && (path === reference || path.endsWith(`/${reference}`)));
    });
    result.set(reference, matches.length === 1 ? matches[0] : null);
  }
  return result;
}
