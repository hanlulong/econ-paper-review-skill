import {
  isValidReviewEvidence,
  type ReviewEvidenceLocator,
  type ReviewEvidenceRepresentation,
  type ReviewEvidenceType,
} from "./review-evidence-contract.ts";
import type { PaperPosition } from "./review-view-state.ts";

export type Severity = "critical" | "major" | "minor" | "info";
export type DecisionRole = "potentially_dispositive" | "posture_material" | "revision_value" | "polish";

export type Evidence = {
  id?: string;
  type: ReviewEvidenceType;
  representation?: ReviewEvidenceRepresentation;
  anchor_id?: string | null;
  anchor_ids?: string[];
  computation_id?: string | null;
  source_record_id?: string | null;
  content: string | null;
  scope_checked?: string | null;
  source: string;
  locator: ReviewEvidenceLocator;
};

export type Finding = {
  id: string;
  title?: string;
  decision_role?: DecisionRole;
  repairability?: "within_current_design" | "claim_narrowing" | "additional_analysis" | "new_evidence" | "redesign" | "unclear" | "no_clear_fix";
  importance_rank: number;
  report_channel?: "substance" | "writing";
  dimension: string;
  severity: Severity;
  essential: boolean;
  status: string;
  support_state: string;
  issue: string;
  why_it_matters: string;
  reader_effect: string;
  confidence?: { level: "low" | "medium" | "high"; would_change_my_mind: string };
  paper_position?: PaperPosition;
  evidence_boundary?: string;
  minimum_repair?: string;
  display_evidence_id?: string;
  related_evidence_ids?: string[];
  related_locations?: string[];
  evidence: Evidence[];
  counterargument: {
    result: "survived" | "weakened" | "refuted" | "not_run";
    author_reply: string;
    search_scope?: string;
    notes: string;
  };
  fix: {
    what: string;
    how: string;
    effort: string;
    publishability: string;
    resolved_when?: string;
  };
  verification: string;
};

export type Ledger = { schema_version?: string; review_id: string; findings: Finding[] };

/** Normalize a validated evidence record for the viewer's text surfaces. */
export function reviewEvidenceText(evidence: Evidence | undefined): string {
  if (!evidence) return "";
  const content = evidence.content
    ? (evidence.type === "quote" ? evidence.content
      .split("\n")
      .map((line) => line.replace(/^\s*>\s?/, ""))
      .join("\n") : evidence.content).trim()
    : "";
  const scope = (evidence.type === "absence_scope" || evidence.representation === "checked_absence")
    ? evidence.scope_checked?.trim()
    : "";
  if (!scope) return content;
  const scopeLine = `Scope checked: ${scope}`;
  return content ? `${content}\n\n${scopeLine}` : scopeLine;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

/** Validate the viewer-facing invariants of a canonical findings ledger. */
export function validateReviewLedger(value: unknown): Ledger {
  if (!isRecord(value) || typeof value.review_id !== "string" || !value.review_id.trim() || !Array.isArray(value.findings)) {
    throw new Error("findings.json does not have the required review_id and findings array");
  }
  if (value.schema_version !== undefined && !["0.1", "0.2", "0.3", "0.4"].includes(String(value.schema_version))) {
    throw new Error("findings.json has an unsupported schema_version");
  }
  const ids = new Set<string>();
  for (const [index, raw] of value.findings.entries()) {
    if (!isRecord(raw) || typeof raw.id !== "string" || !raw.id.trim() || ids.has(raw.id)) {
      throw new Error(`findings.json has an invalid or duplicate finding at position ${index + 1}`);
    }
    if (!Number.isInteger(raw.importance_rank) || !["critical", "major", "minor", "info"].includes(String(raw.severity))) {
      throw new Error(`finding ${raw.id} has an invalid rank or severity`);
    }
    if (raw.report_channel !== undefined && !["substance", "writing"].includes(String(raw.report_channel))) {
      throw new Error(`finding ${raw.id} has an invalid report channel`);
    }
    if (["0.3", "0.4"].includes(String(value.schema_version)) && (
      typeof raw.title !== "string" || !raw.title.trim()
      || !["potentially_dispositive", "posture_material", "revision_value", "polish"].includes(String(raw.decision_role))
      || !["within_current_design", "claim_narrowing", "additional_analysis", "new_evidence", "redesign", "unclear", "no_clear_fix"].includes(String(raw.repairability))
    )) {
      throw new Error(`v0.3 finding ${raw.id} is missing title, decision role, or repairability`);
    }
    if (
      typeof raw.issue !== "string" || typeof raw.why_it_matters !== "string" || typeof raw.reader_effect !== "string"
      || typeof raw.dimension !== "string" || typeof raw.status !== "string" || typeof raw.support_state !== "string"
      || typeof raw.verification !== "string" || typeof raw.essential !== "boolean"
    ) {
      throw new Error(`finding ${raw.id} is missing required review text or state`);
    }
    if (!Array.isArray(raw.evidence) || !raw.evidence.length || raw.evidence.some((item) => (
      !isValidReviewEvidence(item, value.schema_version)
    ))) {
      throw new Error(`finding ${raw.id} has invalid evidence data`);
    }
    if (raw.confidence !== undefined && (
      !isRecord(raw.confidence)
      || !["low", "medium", "high"].includes(String(raw.confidence.level))
      || typeof raw.confidence.would_change_my_mind !== "string"
      || !raw.confidence.would_change_my_mind.trim()
    )) throw new Error(`finding ${raw.id} has malformed confidence data`);
    if (raw.paper_position !== undefined) {
      if (!isRecord(raw.paper_position)) throw new Error(`finding ${raw.id} has malformed paper_position data`);
      const paperPosition = raw.paper_position;
      const positionNumber = paperPosition.ordinal ?? paperPosition.order;
      if (
        typeof positionNumber !== "number" || !Number.isFinite(positionNumber) || positionNumber < 0
        || !["section", "label", "source_id", "anchor_id"].every((key) => paperPosition[key] === undefined || paperPosition[key] === null || typeof paperPosition[key] === "string")
      ) throw new Error(`finding ${raw.id} has malformed paper_position data`);
    }
    if (value.schema_version === "0.4" && (
      typeof raw.evidence_boundary !== "string" || !raw.evidence_boundary.trim()
      || typeof raw.minimum_repair !== "string" || !raw.minimum_repair.trim()
      || typeof raw.display_evidence_id !== "string" || !raw.evidence.some((item) => isRecord(item) && item.id === raw.display_evidence_id)
      || !Array.isArray(raw.related_evidence_ids) || raw.related_evidence_ids.some((item) => typeof item !== "string")
      || !Array.isArray(raw.related_locations) || raw.related_locations.some((item) => typeof item !== "string")
    )) throw new Error(`v0.4 finding ${raw.id} is missing source-linked display metadata`);
    if (
      !isRecord(raw.fix) || typeof raw.fix.what !== "string" || typeof raw.fix.how !== "string" || typeof raw.fix.effort !== "string"
      || typeof raw.fix.publishability !== "string" || !(typeof raw.fix.resolved_when === "string" || raw.fix.resolved_when === undefined)
      || !isRecord(raw.counterargument) || typeof raw.counterargument.result !== "string"
      || typeof raw.counterargument.author_reply !== "string" || typeof raw.counterargument.notes !== "string"
      || !(typeof raw.counterargument.search_scope === "string" || raw.counterargument.search_scope === undefined)
    ) {
      throw new Error(`finding ${raw.id} is missing fix or fairness data`);
    }
    ids.add(raw.id);
  }
  return value as Ledger;
}
