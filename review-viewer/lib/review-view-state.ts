export type ReviewQueueOrder = "priority" | "importance" | "paper";
export type ReviewUrlState = {
  view: "overview" | "comment" | "plan" | "document";
  finding: string | null;
  document: string | null;
  evidence: number;
  order: ReviewQueueOrder;
  severity: string;
  role: string;
  status: string;
  channel: string;
  dimension: string;
  reviewed: string;
  my_priority: string;
};

export type PaperPosition = {
  order?: number;
  ordinal?: number;
  source_id?: string;
  anchor_id?: string;
  section?: string | null;
  label?: string | null;
};

type PositionableFinding = {
  id: string;
  importance_rank: number;
  paper_position?: PaperPosition;
  evidence: Array<{ locator?: { section?: string | null; exhibit?: string | null; file?: string | null; page?: number | null } }>;
};

type PriorityFinding = PositionableFinding & {
  severity: "critical" | "major" | "minor" | "info";
  decision_role?: "potentially_dispositive" | "posture_material" | "revision_value" | "polish";
};

const SEVERITY_PRIORITY: Record<PriorityFinding["severity"], number> = {
  critical: 0,
  major: 1,
  minor: 2,
  info: 3,
};

const DECISION_ROLE_PRIORITY = {
  potentially_dispositive: 0,
  posture_material: 1,
  revision_value: 2,
  polish: 3,
} as const;

function reviewerPriority(finding: PriorityFinding): [number, number, number] {
  return [
    SEVERITY_PRIORITY[finding.severity],
    finding.decision_role ? DECISION_ROLE_PRIORITY[finding.decision_role] : 99,
    finding.importance_rank,
  ];
}

export function paperSection(finding: PositionableFinding): string {
  const explicit = finding.paper_position?.section || finding.paper_position?.label;
  const locator = finding.evidence[0]?.locator;
  return explicit || locator?.section || locator?.exhibit || locator?.file || "Other locations";
}

function naturalKey(value: string): string {
  return value.toLowerCase().split(/(\d+(?:\.\d+)*)/).map((part) => {
    const numeric = Number(part);
    return Number.isNaN(numeric) ? part : numeric.toString().padStart(12, "0");
  }).join("");
}

function compareOptionalNatural(left: string | null | undefined, right: string | null | undefined): number {
  if (left === right) return 0;
  if (!left) return 1;
  if (!right) return -1;
  return naturalKey(left).localeCompare(naturalKey(right));
}

/** Compare source location only, leaving exact ties to the caller's chosen stable order. */
function compareSourceLocation(left: PositionableFinding, right: PositionableFinding): number {
  const leftSource = left.paper_position?.source_id || left.evidence[0]?.locator?.file;
  const rightSource = right.paper_position?.source_id || right.evidence[0]?.locator?.file;
  const source = compareOptionalNatural(leftSource, rightSource);
  if (source) return source;
  const leftOrder = left.paper_position?.ordinal ?? left.paper_position?.order;
  const rightOrder = right.paper_position?.ordinal ?? right.paper_position?.order;
  if (leftOrder !== undefined || rightOrder !== undefined) {
    if (leftOrder === undefined) return 1;
    if (rightOrder === undefined) return -1;
    if (leftOrder !== rightOrder) return leftOrder - rightOrder;
  }
  const section = naturalKey(paperSection(left)).localeCompare(naturalKey(paperSection(right)));
  if (section) return section;
  const leftPage = left.evidence[0]?.locator?.page;
  const rightPage = right.evidence[0]?.locator?.page;
  if (leftPage !== rightPage) {
    if (leftPage == null) return 1;
    if (rightPage == null) return -1;
    return leftPage - rightPage;
  }
  return 0;
}

/** Prefer a canonical generator-provided position, with a stable locator fallback. */
export function comparePaperPosition(left: PositionableFinding, right: PositionableFinding): number {
  return compareSourceLocation(left, right);
}

/**
 * Sort a working queue without mutating canonical findings. Personal author
 * priorities remain separate and affect only the generated revision plan.
 * Every exact queue tie retains the ledger's original order.
 */
export function sortReviewFindings<T extends PriorityFinding>(
  findings: readonly T[],
  order: ReviewQueueOrder,
): T[] {
  return findings
    .map((finding, originalIndex) => ({ finding, originalIndex }))
    .sort((left, right) => {
      if (order === "importance") {
        const leftPriority = reviewerPriority(left.finding);
        const rightPriority = reviewerPriority(right.finding);
        return leftPriority[0] - rightPriority[0]
          || leftPriority[1] - rightPriority[1]
          || leftPriority[2] - rightPriority[2]
          || left.originalIndex - right.originalIndex;
      }
      if (order === "paper") {
        return compareSourceLocation(left.finding, right.finding)
          || left.originalIndex - right.originalIndex;
      }
      return SEVERITY_PRIORITY[left.finding.severity] - SEVERITY_PRIORITY[right.finding.severity]
        || compareSourceLocation(left.finding, right.finding)
        || left.originalIndex - right.originalIndex;
    })
    .map(({ finding }) => finding);
}

const allowed = <T extends string>(value: string | null, values: readonly T[], fallback: T): T => (
  values.includes(value as T) ? value as T : fallback
);

export function parseReviewUrlState(search: string): ReviewUrlState {
  const params = new URLSearchParams(search);
  const evidence = Number(params.get("evidence"));
  return {
    view: allowed(params.get("view"), ["overview", "comment", "plan", "document"] as const, params.has("finding") ? "comment" : "overview"),
    finding: params.get("finding"),
    document: params.get("document"),
    evidence: Number.isInteger(evidence) && evidence >= 0 && evidence < 500 ? evidence : 0,
    order: allowed(params.get("order"), ["priority", "importance", "paper"] as const, "importance"),
    severity: params.get("severity") || "all",
    role: params.get("role") || "all",
    status: params.get("status") || "all",
    channel: params.get("channel") || "all",
    dimension: params.get("dimension") || "all",
    reviewed: params.get("reviewed") || "all",
    my_priority: params.get("my_priority") || "all",
  };
}

/** Update only viewer-owned parameters; review selection and unrelated parameters are preserved. */
export function writeReviewUrlState(url: URL, state: ReviewUrlState): URL {
  const next = new URL(url);
  for (const key of ["rv", "view", "finding", "document", "evidence", "order", "severity", "role", "status", "channel", "dimension", "reviewed", "my_priority"]) {
    next.searchParams.delete(key);
  }
  next.searchParams.set("rv", "1");
  next.searchParams.set("view", state.view);
  if (state.view === "comment" && state.finding) next.searchParams.set("finding", state.finding);
  if (state.view === "document" && state.document) next.searchParams.set("document", state.document);
  if (state.view === "comment" && state.evidence > 0) next.searchParams.set("evidence", String(state.evidence));
  if (state.order !== "importance") next.searchParams.set("order", state.order);
  if (state.severity !== "all") next.searchParams.set("severity", state.severity);
  if (state.role !== "all") next.searchParams.set("role", state.role);
  if (state.status !== "all") next.searchParams.set("status", state.status);
  if (state.channel !== "all") next.searchParams.set("channel", state.channel);
  if (state.dimension !== "all") next.searchParams.set("dimension", state.dimension);
  if (state.reviewed !== "all") next.searchParams.set("reviewed", state.reviewed);
  if (state.my_priority !== "all") next.searchParams.set("my_priority", state.my_priority);
  return next;
}
