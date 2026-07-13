const CORE_REVIEW_FILES = new Set([
  "findings.json",
  "run.json",
  "tables.json",
  "figures.json",
  "review-manifest.json",
]);

const LEGACY_DOCUMENT_NAMES = new Set([
  "readme.md",
  "report.md",
  "writing-report.md",
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

function basename(path: string) {
  return path.split("/").at(-1) || path;
}

function dirname(path: string) {
  const parts = path.split("/");
  parts.pop();
  return parts.join("/");
}

export function normalizePackagePath(path: string) {
  const parts = path.replaceAll("\\", "/").replace(/^\.\//, "").split("/");
  if (parts.some((part) => part === "..")) throw new Error(`Unsafe relative path in the selected package: ${path}`);
  return parts.filter((part) => part && part !== ".").join("/");
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
  const root = normalizePackagePath(rawRoot);
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
    if (!/\.(md|markdown|txt)$/i.test(name) || LEGACY_DOCUMENT_NAMES.has(name) || CORE_REVIEW_FILES.has(name)) return false;
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
  return Array.from(paths);
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
