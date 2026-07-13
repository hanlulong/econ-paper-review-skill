export const REVIEW_DOCUMENT_MANIFEST_VERSION = "0.1" as const;

export const REVIEW_DOCUMENT_GROUPS = [
  "overview",
  "reports",
  "plan",
  "audit",
] as const;

export type ReviewDocumentGroup = (typeof REVIEW_DOCUMENT_GROUPS)[number];

export type ReviewDocument = {
  id: string;
  title: string;
  group: ReviewDocumentGroup;
  path: string;
  order: number;
};

export type ReviewDocumentManifest = {
  schema_version: typeof REVIEW_DOCUMENT_MANIFEST_VERSION;
  review_id: string;
  documents: ReviewDocument[];
};

export type ResolvedReviewDocumentLink = {
  document: ReviewDocument;
  fragment: string | null;
};

export const REVIEW_DOCUMENT_GROUP_LABELS: Record<ReviewDocumentGroup, string> = {
  overview: "Overview",
  reports: "Reports",
  plan: "Revision plan",
  audit: "Audit trail",
};

const GROUP_ORDER: Record<ReviewDocumentGroup, number> = {
  overview: 0,
  reports: 1,
  plan: 2,
  audit: 3,
};

const GROUPS = new Set<string>(REVIEW_DOCUMENT_GROUPS);
const DOCUMENT_ID = /^[a-z0-9][a-z0-9-]{0,79}$/;
const SAFE_PATH_SEGMENT = /^[A-Za-z0-9][A-Za-z0-9._ ()-]*$/;
const MAX_DOCUMENTS = 200;
const MAX_TITLE_CHARS = 160;
const MAX_PATH_CHARS = 500;

const LEGACY_DOCUMENTS: Record<string, Omit<ReviewDocument, "path">> = {
  "README.md": { id: "review-home", title: "Start here", group: "overview", order: 0 },
  "report.md": { id: "referee-report", title: "Referee report", group: "overview", order: 10 },
  "writing-report.md": { id: "writing-report", title: "Writing report", group: "reports", order: 10 },
  "fix-plan.md": { id: "revision-plan", title: "Revision plan", group: "plan", order: 10 },
  "evidence/reconstruction.md": { id: "paper-reconstruction", title: "Paper reconstruction", group: "audit", order: 10 },
  "evidence/reader-claim-audit.md": { id: "reader-claim-audit", title: "Reader and claim audit", group: "audit", order: 20 },
  "evidence/analytical-audit.md": { id: "analytical-audit", title: "Analytical audit", group: "audit", order: 30 },
  "evidence/figures.md": { id: "figure-audit", title: "Figure audit", group: "audit", order: 40 },
  "evidence/tables.md": { id: "table-audit", title: "Table audit", group: "audit", order: 50 },
  "evidence/writing.md": { id: "writing-audit", title: "Writing audit", group: "audit", order: 60 },
  "evidence/coverage.md": { id: "coverage-audit", title: "Coverage audit", group: "audit", order: 70 },
  "evidence/sources.md": { id: "source-verification", title: "Source verification", group: "audit", order: 80 },
  "evidence/verification.md": { id: "package-verification", title: "Package verification", group: "audit", order: 90 },
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function assertExactKeys(value: Record<string, unknown>, allowed: readonly string[], label: string): void {
  const allowedSet = new Set(allowed);
  const extras = Object.keys(value).filter((key) => !allowedSet.has(key));
  if (extras.length) throw new Error(`${label} has unsupported fields: ${extras.sort().join(", ")}`);
}

function compareText(left: string, right: string): number {
  if (left === right) return 0;
  return left < right ? -1 : 1;
}

/** A document path is a relative, browser-safe Markdown path with no traversal or URL syntax. */
export function isSafeReviewDocumentPath(value: unknown): value is string {
  if (typeof value !== "string" || !value || value.length > MAX_PATH_CHARS || value !== value.trim()) return false;
  if (!value.endsWith(".md") || value.startsWith("/") || value.includes("\\") || value.includes(":")) return false;
  const segments = value.split("/");
  return segments.length > 0 && segments.every((segment) => (
    segment !== "."
    && segment !== ".."
    && segment === segment.trim()
    && SAFE_PATH_SEGMENT.test(segment)
  ));
}

/** Return a new, deterministic document order without mutating the manifest. */
export function sortReviewDocuments(documents: readonly ReviewDocument[]): ReviewDocument[] {
  return documents.map((document) => ({ ...document })).sort((left, right) => (
    GROUP_ORDER[left.group] - GROUP_ORDER[right.group]
    || left.order - right.order
    || compareText(left.title, right.title)
    || compareText(left.id, right.id)
    || compareText(left.path, right.path)
  ));
}

/** Match the deterministic IDs used by rendered Markdown headings and generated report links. */
export function markdownHeadingSlug(value: string): string {
  const normalized = Array.from(value.toLowerCase())
    .filter((character) => /[\p{L}\p{N} _-]/u.test(character))
    .join("")
    .replace(/[\s_]+/g, "-")
    .replace(/^-+|-+$/g, "");
  return normalized || "section";
}

function decodedFragment(value: string | undefined): string | null {
  if (value === undefined || value === "") return null;
  try {
    const decoded = decodeURIComponent(value);
    return decoded.length <= 240 && !/[\u0000-\u001f\u007f]/.test(decoded) ? decoded : null;
  } catch {
    return null;
  }
}

/** Resolve a relative Markdown link only when it targets a document already declared in this review. */
export function resolveReviewDocumentLink(
  currentPath: string | undefined,
  href: string | undefined,
  documents: readonly ReviewDocument[],
): ResolvedReviewDocumentLink | null {
  if (!currentPath || !href || href.startsWith("/") || href.includes("\\") || /^[a-z][a-z0-9+.-]*:/i.test(href)) return null;
  const [pathAndQuery, rawFragment] = href.split("#", 2);
  const relativePath = pathAndQuery.split("?", 1)[0];
  const fragment = decodedFragment(rawFragment);
  if (rawFragment !== undefined && rawFragment !== "" && fragment === null) return null;
  if (!relativePath) {
    const currentDocument = documents.find((document) => document.path === currentPath);
    return currentDocument ? { document: currentDocument, fragment } : null;
  }
  const parts = currentPath.split("/");
  parts.pop();
  for (const part of relativePath.split("/")) {
    if (!part || part === ".") continue;
    if (part === "..") {
      if (!parts.length) return null;
      parts.pop();
    } else {
      parts.push(part);
    }
  }
  const targetPath = parts.join("/");
  const document = documents.find((candidate) => candidate.path === targetPath);
  return document ? { document, fragment } : null;
}

/** Backward-compatible document-only resolver. */
export function resolveReviewDocumentHref(
  currentPath: string | undefined,
  href: string | undefined,
  documents: readonly ReviewDocument[],
): ReviewDocument | null {
  return resolveReviewDocumentLink(currentPath, href, documents)?.document || null;
}

function cloneDocument(value: unknown, label: string): ReviewDocument {
  if (!isRecord(value)) throw new Error(`${label} must be an object`);
  assertExactKeys(value, ["id", "title", "group", "path", "order"], label);
  if (typeof value.id !== "string" || !DOCUMENT_ID.test(value.id)) {
    throw new Error(`${label}.id must be a lowercase stable document ID`);
  }
  if (
    typeof value.title !== "string"
    || !value.title.trim()
    || value.title !== value.title.trim()
    || /[\r\n]/.test(value.title)
    || value.title.length > MAX_TITLE_CHARS
  ) {
    throw new Error(`${label}.title must be trimmed text of at most ${MAX_TITLE_CHARS} characters`);
  }
  if (typeof value.group !== "string" || !GROUPS.has(value.group)) {
    throw new Error(`${label}.group must be overview, reports, plan, or audit`);
  }
  if (!isSafeReviewDocumentPath(value.path)) {
    throw new Error(`${label}.path must be a safe relative Markdown path`);
  }
  if (!Number.isInteger(value.order) || (value.order as number) < 0 || (value.order as number) > 10000) {
    throw new Error(`${label}.order must be an integer from 0 through 10000`);
  }
  return {
    id: value.id,
    title: value.title,
    group: value.group as ReviewDocumentGroup,
    path: value.path,
    order: value.order as number,
  };
}

/** Validate and canonicalize a manifest; malformed or ambiguous manifests fail closed. */
export function validateReviewDocumentManifest(value: unknown): ReviewDocumentManifest {
  let raw = value;
  if (typeof raw === "string") {
    try {
      raw = JSON.parse(raw) as unknown;
    } catch (error) {
      const detail = error instanceof Error ? error.message : "invalid JSON";
      throw new Error(`review document manifest contains invalid JSON: ${detail}`);
    }
  }
  if (!isRecord(raw)) throw new Error("review document manifest must be an object");
  assertExactKeys(raw, ["schema_version", "review_id", "documents"], "review document manifest");
  if (raw.schema_version !== REVIEW_DOCUMENT_MANIFEST_VERSION) {
    throw new Error("review document manifest has an unsupported schema_version");
  }
  if (typeof raw.review_id !== "string" || !raw.review_id.trim() || raw.review_id !== raw.review_id.trim()) {
    throw new Error("review document manifest review_id must be nonempty trimmed text");
  }
  if (!Array.isArray(raw.documents) || !raw.documents.length || raw.documents.length > MAX_DOCUMENTS) {
    throw new Error(`review document manifest must contain 1 through ${MAX_DOCUMENTS} documents`);
  }
  const documents = raw.documents.map((document, index) => cloneDocument(document, `documents[${index}]`));
  const ids = documents.map((document) => document.id);
  const paths = documents.map((document) => document.path);
  if (new Set(ids).size !== ids.length) throw new Error("review document manifest IDs must be unique");
  if (new Set(paths).size !== paths.length) throw new Error("review document manifest paths must be unique");
  return {
    schema_version: REVIEW_DOCUMENT_MANIFEST_VERSION,
    review_id: raw.review_id,
    documents: sortReviewDocuments(documents),
  };
}

function titleFromPath(path: string): string {
  const stem = path.split("/").at(-1)!.replace(/\.md$/, "");
  return stem
    .split(/[-_ ]+/)
    .filter(Boolean)
    .map((word) => word.length <= 3 && word === word.toUpperCase()
      ? word
      : `${word.charAt(0).toUpperCase()}${word.slice(1).toLowerCase()}`)
    .join(" ");
}

function inferredGroup(path: string): ReviewDocumentGroup | null {
  if (LEGACY_DOCUMENTS[path]) return LEGACY_DOCUMENTS[path].group;
  const first = path.split("/", 1)[0];
  if (first === "overview") return "overview";
  if (first === "reports") return "reports";
  if (first === "plan") return "plan";
  if (first === "audit" || first === "evidence") return "audit";
  return null;
}

function inferredOrder(path: string, group: ReviewDocumentGroup): number {
  if (LEGACY_DOCUMENTS[path]) return LEGACY_DOCUMENTS[path].order;
  const groupBase = GROUP_ORDER[group] * 1000;
  return groupBase + 500;
}

function inferredId(path: string, group: ReviewDocumentGroup): string {
  const stem = path.replace(/\.md$/, "").replace(/[^a-zA-Z0-9]+/g, "-").replace(/^-|-$/g, "").toLowerCase();
  return `${group}-${stem}`.slice(0, 80).replace(/-$/, "");
}

/**
 * Discover documents from a validated manifest, or use conservative legacy folder conventions
 * when no manifest is available. Paths must be relative to the review package root.
 */
export function discoverReviewDocuments(
  availablePaths: Iterable<string>,
  manifestValue?: unknown,
): ReviewDocument[] {
  const paths = Array.from(new Set(Array.from(availablePaths).filter(isSafeReviewDocumentPath))).sort(compareText);
  const available = new Set(paths);
  if (manifestValue !== undefined && manifestValue !== null) {
    const manifest = validateReviewDocumentManifest(manifestValue);
    const missing = manifest.documents.filter((document) => !available.has(document.path)).map((document) => document.path);
    if (missing.length) throw new Error(`review document manifest references missing files: ${missing.join(", ")}`);
    return manifest.documents;
  }

  const usedIds = new Set<string>();
  const documents: ReviewDocument[] = [];
  for (const path of paths) {
    const group = inferredGroup(path);
    if (!group) continue;
    const legacy = LEGACY_DOCUMENTS[path];
    const baseId = legacy?.id || inferredId(path, group);
    let id = baseId;
    let suffix = 2;
    while (usedIds.has(id)) {
      const addition = `-${suffix}`;
      id = `${baseId.slice(0, 80 - addition.length).replace(/-$/, "")}${addition}`;
      suffix += 1;
    }
    usedIds.add(id);
    documents.push({
      id,
      title: legacy?.title || titleFromPath(path),
      group,
      path,
      order: inferredOrder(path, group),
    });
  }
  return sortReviewDocuments(documents);
}
