export type ReviewQueueOrder = "importance" | "paper";
export type ReviewUrlState = {
  view: "overview" | "comment" | "document";
  finding: string | null;
  document: string | null;
  evidence: number;
  order: ReviewQueueOrder;
  severity: string;
  role: string;
  status: string;
  channel: string;
  dimension: string;
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

/** Prefer a canonical generator-provided position, with a stable locator fallback for older ledgers. */
export function comparePaperPosition(left: PositionableFinding, right: PositionableFinding): number {
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
  return left.importance_rank - right.importance_rank || left.id.localeCompare(right.id);
}

const allowed = <T extends string>(value: string | null, values: readonly T[], fallback: T): T => (
  values.includes(value as T) ? value as T : fallback
);

export function parseReviewUrlState(search: string): ReviewUrlState {
  const params = new URLSearchParams(search);
  const evidence = Number(params.get("evidence"));
  return {
    view: allowed(params.get("view"), ["overview", "comment", "document"] as const, params.has("finding") ? "comment" : "overview"),
    finding: params.get("finding"),
    document: params.get("document"),
    evidence: Number.isInteger(evidence) && evidence >= 0 && evidence < 500 ? evidence : 0,
    order: allowed(params.get("order"), ["importance", "paper"] as const, "importance"),
    severity: params.get("severity") || "all",
    role: params.get("role") || "all",
    status: params.get("status") || "all",
    channel: params.get("channel") || "all",
    dimension: params.get("dimension") || "all",
  };
}

/** Update only viewer-owned parameters; review selection and unrelated parameters are preserved. */
export function writeReviewUrlState(url: URL, state: ReviewUrlState): URL {
  const next = new URL(url);
  for (const key of ["rv", "view", "finding", "document", "evidence", "order", "severity", "role", "status", "channel", "dimension"]) {
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
  return next;
}
