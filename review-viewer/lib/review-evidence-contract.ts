/**
 * Evidence kinds accepted by the canonical econ-review findings contract.
 *
 * Keep this list synchronized with
 * `econ-review/assets/findings.schema.json#/$defs/evidence/properties/type`.
 * The contract-sync regression test intentionally fails when either side
 * changes without the other.
 */
export const REVIEW_EVIDENCE_TYPES = [
  "quote",
  "equation",
  "table_cell",
  "figure",
  "code",
  "literature",
  "absence_scope",
  "computation",
] as const;

export type ReviewEvidenceType = (typeof REVIEW_EVIDENCE_TYPES)[number];

const REVIEW_EVIDENCE_TYPE_SET: ReadonlySet<string> = new Set(REVIEW_EVIDENCE_TYPES);

export function isReviewEvidenceType(value: unknown): value is ReviewEvidenceType {
  return typeof value === "string" && REVIEW_EVIDENCE_TYPE_SET.has(value);
}

export const REVIEW_EVIDENCE_REPRESENTATIONS = [
  "verbatim",
  "normalized_transcription",
  "composite_comparison",
  "reviewer_observation",
  "checked_absence",
  "computed_result",
] as const;

export type ReviewEvidenceRepresentation = (typeof REVIEW_EVIDENCE_REPRESENTATIONS)[number];

export type ReviewEvidenceLocator = {
  section?: string | null;
  page?: number | null;
  paragraph?: string | null;
  exhibit?: string | null;
  equation?: string | null;
  lines?: string | null;
  file?: string | null;
};

const REVIEW_EVIDENCE_REPRESENTATION_SET: ReadonlySet<string> = new Set(REVIEW_EVIDENCE_REPRESENTATIONS);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

export function isValidReviewEvidenceLocator(value: unknown): value is ReviewEvidenceLocator {
  if (!isRecord(value)) return false;
  for (const key of ["section", "paragraph", "exhibit", "equation", "lines", "file"]) {
    const field = value[key];
    if (!(typeof field === "string" || field === null || field === undefined)) return false;
  }
  const page = value.page;
  return typeof page === "number" ? Number.isFinite(page) : page === null || page === undefined;
}

/**
 * Check the viewer-facing invariants of one canonical evidence record.
 * Full cross-file provenance validation remains the Python validator's job.
 */
export function isValidReviewEvidence(value: unknown, schemaVersion: unknown): boolean {
  if (
    !isRecord(value) || !isReviewEvidenceType(value.type)
    || typeof value.source !== "string" || !isValidReviewEvidenceLocator(value.locator)
    || !(typeof value.content === "string" || value.content === null)
    || !(typeof value.scope_checked === "string" || value.scope_checked === null || value.scope_checked === undefined)
  ) return false;

  const anchorIds = value.anchor_ids;
  if (anchorIds !== undefined && (
    !Array.isArray(anchorIds) || new Set(anchorIds).size !== anchorIds.length
    || anchorIds.some((anchorId) => typeof anchorId !== "string" || !/^ANC-[0-9]{2,}$/.test(anchorId))
  )) return false;
  if (value.representation === "composite_comparison" && (
    !Array.isArray(anchorIds) || anchorIds.length < 2 || value.anchor_id !== null
  )) return false;

  return schemaVersion !== "0.4" || (
    typeof value.id === "string" && Boolean(value.id.trim())
    && typeof value.representation === "string"
    && REVIEW_EVIDENCE_REPRESENTATION_SET.has(value.representation)
  );
}
