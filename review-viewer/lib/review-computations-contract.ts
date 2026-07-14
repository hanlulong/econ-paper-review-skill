import type { Ledger } from "./review-ledger-contract.ts";

export type ReviewComputation = {
  id: string;
  finding_ids: string[];
  audit_links?: Array<{
    kind: "analytical_entry" | "magnitude_assessment";
    id: string;
  }>;
  input_anchor_ids: string[];
  tool: string;
  method: string;
  result: string;
  artifact_path: string;
  artifact_sha256: string;
  tolerance: string;
};

export type ReviewComputationsLedger = {
  schema_version: "0.1" | "0.2";
  review_id: string;
  computations: ReviewComputation[];
};

type SourceAnchorIndex = {
  review_id: string;
  anchors: Array<{ id: string }>;
};

export type ReviewComputationAuditLedgers = {
  analyticalAudit: unknown;
  claimsAudit: unknown;
};

const COMPUTATION_LEDGER_KEYS = new Set(["schema_version", "review_id", "computations"]);
const COMPUTATION_KEYS = new Set([
  "id", "finding_ids", "audit_links", "input_anchor_ids", "tool", "method",
  "result", "artifact_path", "artifact_sha256", "tolerance",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function nonemptyText(value: unknown): value is string {
  return typeof value === "string" && Boolean(value.trim());
}

function hasOnlyKeys(value: Record<string, unknown>, allowed: Set<string>) {
  return Object.keys(value).every((key) => allowed.has(key));
}

function uniqueStringArray(value: unknown, pattern: RegExp, allowEmpty = false): value is string[] {
  return Array.isArray(value)
    && (allowEmpty || value.length > 0)
    && value.every((item) => nonemptyText(item) && pattern.test(item))
    && new Set(value).size === value.length;
}

function validAuditLinks(value: unknown, allowEmpty = true): value is ReviewComputation["audit_links"] {
  if (!Array.isArray(value) || (!allowEmpty && value.length === 0)) return false;
  const keys = new Set<string>();
  for (const link of value) {
    if (!isRecord(link) || Object.keys(link).some((key) => key !== "kind" && key !== "id")) return false;
    const kind = link.kind;
    const id = link.id;
    if (
      !(
        kind === "analytical_entry" && nonemptyText(id) && /^ANA-[A-Z]+-[0-9]{2,}$/.test(id)
      ) && !(
        kind === "magnitude_assessment" && nonemptyText(id) && /^MAG-[0-9]{2,}$/.test(id)
      )
    ) return false;
    const key = `${kind}:${id}`;
    if (keys.has(key)) return false;
    keys.add(key);
  }
  return true;
}

/**
 * Match the package validator's containment rule without opening the artifact.
 * Review Desk presents immutable provenance metadata only; it never reads or
 * executes a computation artifact.
 */
export function isSafeComputationArtifactPath(value: unknown): value is string {
  if (!nonemptyText(value) || value.includes("\0")) return false;
  const normalized = value.replaceAll("\\", "/");
  if (normalized.startsWith("/") || /^[A-Za-z]:\//.test(normalized) || /^[A-Za-z][A-Za-z0-9+.-]*:/.test(normalized)) return false;
  const parts = normalized.split("/");
  return parts.every((part) => Boolean(part) && part !== "." && part !== "..");
}

/** Validate the viewer-facing invariants of evidence/computations.json. */
export function validateReviewComputations(value: unknown): ReviewComputationsLedger | null {
  if (value === null || value === undefined || (isRecord(value) && !Object.keys(value).length)) return null;
  if (
    !isRecord(value) || !["0.1", "0.2"].includes(String(value.schema_version))
    || !hasOnlyKeys(value, COMPUTATION_LEDGER_KEYS)
    || !nonemptyText(value.review_id) || !Array.isArray(value.computations)
  ) throw new Error("computations.json does not have the required review_id and computations array");

  const ids = new Set<string>();
  const schemaVersion = value.schema_version;
  for (const [index, computation] of value.computations.entries()) {
    if (
      !isRecord(computation) || !nonemptyText(computation.id) || !/^CMP-[0-9]{2,}$/.test(computation.id)
      || ids.has(computation.id) || !hasOnlyKeys(computation, COMPUTATION_KEYS)
    ) throw new Error(`computations.json has an invalid or duplicate computation at position ${index + 1}`);
    if (!uniqueStringArray(computation.finding_ids, /^.+$/, schemaVersion === "0.2")) {
      throw new Error(`computation ${computation.id} has invalid or duplicate finding IDs`);
    }
    if (schemaVersion === "0.1" && computation.audit_links !== undefined && !validAuditLinks(computation.audit_links)) {
      throw new Error(`computation ${computation.id} has invalid audit links`);
    }
    if (schemaVersion === "0.1" && Array.isArray(computation.audit_links) && computation.audit_links.length) {
      throw new Error(`computation ${computation.id} cannot declare audit links under schema 0.1`);
    }
    if (schemaVersion === "0.2" && !validAuditLinks(computation.audit_links)) {
      throw new Error(`computation ${computation.id} has invalid or duplicate audit links`);
    }
    if (
      schemaVersion === "0.2" && computation.finding_ids.length === 0
      && Array.isArray(computation.audit_links) && computation.audit_links.length === 0
    ) throw new Error(`computation ${computation.id} must link a finding or audit row`);
    if (!uniqueStringArray(computation.input_anchor_ids, /^ANC-[0-9]{2,}$/)) {
      throw new Error(`computation ${computation.id} has invalid or duplicate input anchors`);
    }
    if (
      !nonemptyText(computation.tool) || !nonemptyText(computation.method)
      || !nonemptyText(computation.result) || !nonemptyText(computation.tolerance)
      || !isSafeComputationArtifactPath(computation.artifact_path)
      || typeof computation.artifact_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(computation.artifact_sha256)
    ) throw new Error(`computation ${computation.id} has invalid provenance metadata`);
    ids.add(computation.id);
  }
  return value as unknown as ReviewComputationsLedger;
}

function computationReferences(value: unknown): Set<string> {
  if (!Array.isArray(value)) return new Set();
  return new Set(value.flatMap((reference) => (
    isRecord(reference) && reference.kind === "computation" && nonemptyText(reference.id)
      ? [reference.id]
      : []
  )));
}

function indexComputationAuditLinks(
  auditLedgers: ReviewComputationAuditLedgers,
  reviewId: string,
  computationIds: Set<string>,
) {
  const { analyticalAudit, claimsAudit } = auditLedgers;
  if (!isRecord(analyticalAudit) || !isRecord(claimsAudit)) {
    throw new Error(
      "Schema 0.2 computations require evidence/analytical-audit.json and evidence/claims.json from a complete Python-validated review package.",
    );
  }
  if (analyticalAudit.review_id !== reviewId || claimsAudit.review_id !== reviewId) {
    throw new Error("Computation audit ledgers have a different review ID");
  }
  if (!Array.isArray(analyticalAudit.domains)) {
    throw new Error("analytical-audit.json cannot provide a computation audit index");
  }
  const argumentAudit = claimsAudit.argument_audit;
  const magnitudeAssessments = isRecord(argumentAudit) ? argumentAudit.magnitude_assessments : null;
  if (!isRecord(magnitudeAssessments) || !Array.isArray(magnitudeAssessments.entries)) {
    throw new Error("claims.json cannot provide a magnitude-assessment computation index");
  }

  const knownTargets = new Set<string>();
  const actualLinks = new Map<string, Set<string>>();
  const recordLink = (computationId: string, target: string) => {
    if (!computationIds.has(computationId)) {
      throw new Error(`Audit row ${target} references unknown computation ${computationId}`);
    }
    const targets = actualLinks.get(computationId) || new Set<string>();
    targets.add(target);
    actualLinks.set(computationId, targets);
  };

  for (const domain of analyticalAudit.domains) {
    if (!isRecord(domain) || !Array.isArray(domain.entries)) {
      throw new Error("analytical-audit.json has a malformed domain computation index");
    }
    for (const entry of domain.entries) {
      if (!isRecord(entry) || !nonemptyText(entry.id) || !/^ANA-[A-Z]+-[0-9]{2,}$/.test(entry.id)) {
        throw new Error("analytical-audit.json has an invalid analytical entry ID");
      }
      const target = `analytical_entry:${entry.id}`;
      if (knownTargets.has(target)) throw new Error(`Duplicate computation audit target ${target}`);
      knownTargets.add(target);
      const directReferences = computationReferences(entry.evidence_refs);
      if (!Array.isArray(entry.evidence_locators)) continue;
      for (const locator of entry.evidence_locators) {
        if (!isRecord(locator) || !isRecord(locator.record_ref)) continue;
        const reference = locator.record_ref;
        if (reference.kind === "computation" && nonemptyText(reference.id) && directReferences.has(reference.id)) {
          recordLink(reference.id, target);
        }
      }
    }
  }

  for (const entry of magnitudeAssessments.entries) {
    if (!isRecord(entry) || !nonemptyText(entry.id) || !/^MAG-[0-9]{2,}$/.test(entry.id)) {
      throw new Error("claims.json has an invalid magnitude-assessment ID");
    }
    const target = `magnitude_assessment:${entry.id}`;
    if (knownTargets.has(target)) throw new Error(`Duplicate computation audit target ${target}`);
    knownTargets.add(target);
    const directReferences = computationReferences(entry.evidence_refs);
    if (nonemptyText(entry.computation_id) && directReferences.has(entry.computation_id)) {
      recordLink(entry.computation_id, target);
    }
  }

  return { knownTargets, actualLinks };
}

/**
 * Check every cross-file join used by the computation evidence panel. A
 * missing optional ledger is harmless only when findings do not cite one.
 */
export function validateReviewComputationLinks(
  ledger: Ledger,
  computations: ReviewComputationsLedger | null,
  sourceManifest: SourceAnchorIndex | null,
  auditLedgers: ReviewComputationAuditLedgers | null = null,
  reviewMode: "full" | "quick" | null = null,
): void {
  const computationEvidence = ledger.findings.flatMap((finding) => finding.evidence
    .filter((evidence) => evidence.type === "computation" || evidence.computation_id !== null && evidence.computation_id !== undefined)
    .map((evidence) => ({ finding, evidence })));

  if (!computations) {
    if (computationEvidence.length) throw new Error("findings.json references computation evidence but evidence/computations.json is missing");
    return;
  }
  if (computations.review_id !== ledger.review_id) throw new Error("computations.json has a different review ID");
  if (sourceManifest && sourceManifest.review_id !== computations.review_id) throw new Error("computations.json and source-manifest.json have different review IDs");
  if (computations.computations.length && !sourceManifest) {
    throw new Error("Computations require source-manifest.json from a complete Python-validated review package");
  }

  const findingIds = new Set(ledger.findings.map((finding) => finding.id));
  const computationById = new Map(computations.computations.map((computation) => [computation.id, computation]));
  const anchorIds = sourceManifest ? new Set(sourceManifest.anchors.map((anchor) => anchor.id)) : null;
  const evidenceLinks = new Map<string, Set<string>>();
  if (computations.schema_version === "0.2" && computations.computations.length && reviewMode === null) {
    throw new Error("Schema 0.2 computation validation requires the review mode from run.json");
  }
  const auditIndex = computations.schema_version === "0.2" && computations.computations.length && reviewMode === "full"
    ? indexComputationAuditLinks(
      auditLedgers || { analyticalAudit: null, claimsAudit: null },
      computations.review_id,
      new Set(computationById.keys()),
    )
    : null;

  for (const { finding, evidence } of computationEvidence) {
    if (evidence.type !== "computation") {
      throw new Error(`finding ${finding.id} attaches a computation ID to non-computation evidence`);
    }
    if (typeof evidence.computation_id !== "string" || !/^CMP-[0-9]{2,}$/.test(evidence.computation_id)) {
      throw new Error(`finding ${finding.id} has computation evidence without a valid computation ID`);
    }
    const computation = computationById.get(evidence.computation_id);
    if (!computation) throw new Error(`finding ${finding.id} references unknown computation ${evidence.computation_id}`);
    if (!computation.finding_ids.includes(finding.id)) {
      throw new Error(`computation ${computation.id} does not declare its link to finding ${finding.id}`);
    }
    const linkedFindings = evidenceLinks.get(computation.id) || new Set<string>();
    linkedFindings.add(finding.id);
    evidenceLinks.set(computation.id, linkedFindings);
  }

  for (const computation of computations.computations) {
    for (const findingId of computation.finding_ids) {
      if (!findingIds.has(findingId)) throw new Error(`computation ${computation.id} references unknown finding ${findingId}`);
      if (!evidenceLinks.get(computation.id)?.has(findingId)) {
        throw new Error(`computation ${computation.id} lists finding ${findingId}, but that finding does not cite it`);
      }
    }
    if (anchorIds) {
      for (const anchorId of computation.input_anchor_ids) {
        if (!anchorIds.has(anchorId)) throw new Error(`computation ${computation.id} references unknown input anchor ${anchorId}`);
      }
    }
    if (auditIndex) {
      const declared = new Set((computation.audit_links || []).map((link) => `${link.kind}:${link.id}`));
      for (const target of declared) {
        if (!auditIndex.knownTargets.has(target)) {
          throw new Error(`computation ${computation.id} references unknown audit row ${target}`);
        }
      }
      const actual = auditIndex.actualLinks.get(computation.id) || new Set<string>();
      const missingCanonicalCitation = [...declared].filter((target) => !actual.has(target));
      const undeclaredCanonicalCitation = [...actual].filter((target) => !declared.has(target));
      if (missingCanonicalCitation.length || undeclaredCanonicalCitation.length) {
        const detail = [
          missingCanonicalCitation.length ? `not cited by audit rows: ${missingCanonicalCitation.join(", ")}` : "",
          undeclaredCanonicalCitation.length ? `undeclared audit rows: ${undeclaredCanonicalCitation.join(", ")}` : "",
        ].filter(Boolean).join("; ");
        throw new Error(`computation ${computation.id} audit links are not reciprocal (${detail})`);
      }
    }
  }
}

export function indexReviewComputations(computations: ReviewComputationsLedger | null): Record<string, ReviewComputation> {
  return Object.fromEntries((computations?.computations || []).map((computation) => [computation.id, computation]));
}
