import type { Finding } from "./review-ledger-contract.ts";
import {
  updateReviewAction,
  type ReviewActionEntry,
  type ReviewActionDisposition,
  type ReviewActionPriority,
} from "./review-actions.ts";
import { formatUserFacingLocator } from "./review-locator.ts";
import { sha256Hex } from "./review-fingerprint.ts";
import { evidenceDisplayText } from "./review-text-evidence-presentation.ts";
import { comparePaperPosition } from "./review-view-state.ts";

export const REVISION_TASKS_SCHEMA_VERSION = "0.1" as const;
export const REVISION_TASKS_KIND = "econ-review-revision-tasks" as const;
export const AGENT_RESPONSE_SCHEMA_VERSION = "0.1" as const;
export const AGENT_RESPONSE_KIND = "econ-review-agent-response" as const;

export type RevisionTask = {
  finding_id: string;
  user_priority: ReviewActionPriority | null;
  reviewed: boolean;
  disposition: ReviewActionDisposition;
  user_comment: string;
  title: string;
  issue: string;
  relevant_text: string;
  suggestions: string;
  done_when: string;
  source_location: string;
};

export type ExcludedRevisionTask = Pick<
  RevisionTask,
  "finding_id" | "disposition" | "user_priority" | "reviewed" | "user_comment" | "title"
>;

export type RevisionTasksPayload = {
  schema_version: typeof REVISION_TASKS_SCHEMA_VERSION;
  kind: typeof REVISION_TASKS_KIND;
  plan_id: string;
  source_review_id: string;
  source_review_fingerprint: string;
  generated_at: string;
  all_comments_reviewed: boolean;
  handoff_ready: boolean;
  tasks: RevisionTask[];
  excluded: ExcludedRevisionTask[];
};

export type AgentResponseTemplate = {
  schema_version: typeof AGENT_RESPONSE_SCHEMA_VERSION;
  kind: typeof AGENT_RESPONSE_KIND;
  plan_id: string;
  source_review_id: string;
  source_review_fingerprint: string;
  responded_at: null;
  entries: Array<{
    finding_id: string;
    status: "not_attempted";
    response: string;
    changed_files: string[];
    changed_locations: Array<{ path: string; locator: string; summary: string }>;
    verification: Array<{ check: string; result: "passed" | "failed" | "not_run"; details: string }>;
    blocker: null;
  }>;
};

const PRIORITY_ORDER: Record<ReviewActionPriority, number> = { P0: 0, P1: 1, P2: 2 };
const EXCLUDED_DISPOSITIONS = new Set<ReviewActionDisposition>(["deferred", "not_relevant", "not_addressable"]);

function normalizeNewlines(value: string | undefined): string {
  return (value || "").replace(/\r\n?/g, "\n");
}

function mergeDistinctText(first: string | undefined, second: string | undefined): string {
  const left = normalizeNewlines(first).trim().replace(/\s+/g, " ");
  const right = normalizeNewlines(second).trim().replace(/\s+/g, " ");
  if (!left) return right;
  if (!right) return left;
  const key = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "");
  const leftKey = key(left);
  const rightKey = key(right);
  if (leftKey === rightKey || rightKey.includes(leftKey)) return right;
  if (leftKey.includes(rightKey)) return left;
  return `${left} ${right}`;
}

function selectedEvidence(finding: Finding) {
  return finding.evidence.find((evidence) => evidence.id === finding.display_evidence_id) || finding.evidence[0];
}

function findingOrder(findingsById: Map<string, Finding>, leftId: string, rightId: string): number {
  const left = findingsById.get(leftId)!;
  const right = findingsById.get(rightId)!;
  return left.importance_rank - right.importance_rank
    || comparePaperPosition(left, right)
    || left.id.localeCompare(right.id);
}

function taskOrder(findingsById: Map<string, Finding>, left: RevisionTask, right: RevisionTask): number {
  const priority = (left.user_priority === null ? 3 : PRIORITY_ORDER[left.user_priority])
    - (right.user_priority === null ? 3 : PRIORITY_ORDER[right.user_priority]);
  return priority || findingOrder(findingsById, left.finding_id, right.finding_id);
}

function stableUuid(seed: string): string {
  const digest = sha256Hex(seed);
  return `${digest.slice(0, 8)}-${digest.slice(8, 12)}-5${digest.slice(13, 16)}-a${digest.slice(17, 20)}-${digest.slice(20, 32)}`;
}

function currentEntryTime(entries: Readonly<Record<string, ReviewActionEntry>>): string {
  const times = Object.values(entries).map((entry) => entry.updated_at).sort();
  return times.at(-1) || "1970-01-01T00:00:00.000Z";
}

/** Commit every visible note draft to the append-only action ledger before export. */
export function commitRevisionNoteDrafts(
  entries: Readonly<Record<string, ReviewActionEntry>>,
  drafts: Readonly<Record<string, string>>,
  at = new Date().toISOString(),
): Record<string, ReviewActionEntry> {
  const committed = { ...entries };
  for (const findingId of Object.keys(drafts).sort()) {
    const current = committed[findingId];
    if (current?.response_note === drafts[findingId]) continue;
    const effectiveAt = current && Date.parse(current.updated_at) > Date.parse(at) ? current.updated_at : at;
    committed[findingId] = updateReviewAction(current, findingId, { response_note: drafts[findingId] }, effectiveAt);
  }
  return committed;
}

/** Build the immutable machine binding passed to an implementation agent. */
export function buildRevisionTasks(options: {
  source_review_id: string;
  source_review_fingerprint: string;
  findings: readonly Finding[];
  entries: Readonly<Record<string, ReviewActionEntry>>;
  draft_notes?: Readonly<Record<string, string>>;
}): RevisionTasksPayload {
  const findings = options.findings.filter((finding) => !["dismissed", "resolved"].includes(finding.status));
  const findingsById = new Map(findings.map((finding) => [finding.id, finding]));
  const tasks: RevisionTask[] = [];
  const excluded: ExcludedRevisionTask[] = [];
  let reviewedCount = 0;

  for (const finding of findings) {
    const entry = options.entries[finding.id];
    if (entry?.reviewed) reviewedCount += 1;
    const evidence = selectedEvidence(finding);
    const userComment = normalizeNewlines(options.draft_notes?.[finding.id] ?? entry?.response_note);
    const common = {
      finding_id: finding.id,
      user_priority: entry?.user_priority || null,
      reviewed: entry?.reviewed || false,
      disposition: entry?.disposition || "open",
      user_comment: userComment,
      title: finding.title || finding.issue,
    };
    if (EXCLUDED_DISPOSITIONS.has(common.disposition)) {
      excluded.push(common);
      continue;
    }
    const relevantText = normalizeNewlines(
      evidence?.content
        ? evidenceDisplayText(evidence.content, evidence.representation)
        : evidence?.scope_checked || "",
    );
    tasks.push({
      ...common,
      issue: finding.issue,
      relevant_text: relevantText,
      suggestions: mergeDistinctText(finding.fix.what, finding.fix.how),
      done_when: finding.fix.resolved_when || finding.verification,
      source_location: formatUserFacingLocator(evidence?.locator),
    });
  }

  tasks.sort((left, right) => taskOrder(findingsById, left, right));
  excluded.sort((left, right) => findingOrder(findingsById, left.finding_id, right.finding_id));
  const allCommentsReviewed = reviewedCount === findings.length;
  const handoffReady = allCommentsReviewed
    && tasks.every((task) => task.user_priority !== null && Boolean(task.user_comment.trim()))
    && excluded.every((task) => Boolean(task.user_comment.trim()));
  const generatedAt = currentEntryTime(options.entries);
  const binding = {
    source_review_id: options.source_review_id,
    source_review_fingerprint: options.source_review_fingerprint,
    generated_at: generatedAt,
    all_comments_reviewed: allCommentsReviewed,
    handoff_ready: handoffReady,
    tasks,
    excluded,
  };
  return {
    schema_version: REVISION_TASKS_SCHEMA_VERSION,
    kind: REVISION_TASKS_KIND,
    plan_id: stableUuid(JSON.stringify(binding)),
    source_review_id: options.source_review_id,
    source_review_fingerprint: options.source_review_fingerprint,
    generated_at: binding.generated_at,
    all_comments_reviewed: binding.all_comments_reviewed,
    handoff_ready: binding.handoff_ready,
    tasks,
    excluded,
  };
}

function markdownInline(value: string): string {
  return normalizeNewlines(value).replace(/\s+/g, " ").trim().replace(/([\\`*_[\]<>#])/g, "\\$1");
}

function fencedText(label: string, value: string, qualifier = "verbatim"): string[] {
  if (!value) return [`- **${label}:** None recorded`];
  const longest = Math.max(0, ...Array.from(value.matchAll(/`+/g), (match) => match[0].length));
  const fence = "`".repeat(Math.max(3, longest + 1));
  return [`- **${label} (${qualifier}):**`, "", `${fence}text`, normalizeNewlines(value), fence];
}

function dispositionLabel(value: ReviewActionDisposition): string {
  if (value === "ready_for_recheck") return "Ready for review — change made";
  if (value === "challenged") return "Ready for review — reasoned response";
  if (value === "deferred") return "Set aside — revisit later";
  if (value === "not_relevant") return "Set aside — does not apply";
  if (value === "not_addressable") return "Set aside — cannot address";
  return "Open";
}

export type RevisionDecisionGap = {
  finding_id: string;
  missing: Array<"reviewed" | "user_priority" | "user_comment">;
};

/** Explain exactly why a plan is still a draft without changing its task order. */
export function revisionDecisionGaps(payload: RevisionTasksPayload): RevisionDecisionGap[] {
  const gaps: RevisionDecisionGap[] = [];
  for (const task of payload.tasks) {
    const missing: RevisionDecisionGap["missing"] = [];
    if (!task.reviewed) missing.push("reviewed");
    if (task.user_priority === null) missing.push("user_priority");
    if (!task.user_comment.trim()) missing.push("user_comment");
    if (missing.length) gaps.push({ finding_id: task.finding_id, missing });
  }
  for (const task of payload.excluded) {
    const missing: RevisionDecisionGap["missing"] = [];
    if (!task.reviewed) missing.push("reviewed");
    if (!task.user_comment.trim()) missing.push("user_comment");
    if (missing.length) gaps.push({ finding_id: task.finding_id, missing });
  }
  return gaps;
}

function decisionGapLabel(value: RevisionDecisionGap["missing"][number]): string {
  if (value === "user_priority") return "assign P0, P1, or P2";
  if (value === "user_comment") return "add an instruction, response, or set-aside reason";
  return "mark reviewed";
}

/** Readable, deterministic instructions and tasks for an implementation agent. */
export function renderRevisionAgentBrief(payload: RevisionTasksPayload): string {
  const gaps = revisionDecisionGaps(payload);
  const lines = [
    "# Revision Agent Brief",
    "",
    `**Plan ID:** ${payload.plan_id}`,
    `**Source review:** ${markdownInline(payload.source_review_id)}`,
    `**Handoff status:** ${payload.handoff_ready ? "Ready for implementation" : `Draft — ${gaps.length} comment${gaps.length === 1 ? " has" : "s have"} missing decisions`}`,
    `**Review progress:** ${payload.all_comments_reviewed ? "All comments reviewed" : "Some comments have not been reviewed"}`,
    "",
    "## Agent instructions",
    "",
    "- Modify only the manuscript or source files placed in scope by the user.",
    "- Work through P0 before P1 and P2 unless a stated dependency requires a different order; explain any departure.",
    "- Follow the user's comment for each finding while preserving the paper's argument and evidence.",
    "- Do not invent evidence, results, citations, data, or completed checks.",
    "- In `response`, explain the change or the reasoned no-change answer; report exact changed files and locations, checks performed, and blockers.",
    "- Never declare a reviewer finding resolved. The next econ-review round verifies and adjudicates every claim.",
    "- Return the completed response using `revision-response.template.json` and keep finding IDs unchanged.",
    "- Use `changed` for implemented file changes with passed checks; `response_only` for a reasoned answer or evidence with no file change; `partial` when closure is unmet; `blocked` for a precise blocker; and `not_attempted` only for untouched tasks.",
    "",
  ];
  if (gaps.length) {
    lines.push(
      "## Missing decisions — do not implement this draft",
      "",
      ...gaps.map((gap) => `- **${markdownInline(gap.finding_id)}:** ${gap.missing.map(decisionGapLabel).join("; ")}`),
      "",
    );
  }
  if (!payload.tasks.length) lines.push("## Active tasks", "", "No active implementation tasks.", "");
  for (const task of payload.tasks) {
    lines.push(
      `## ${task.user_priority || "Unassigned"} · ${markdownInline(task.finding_id)} — ${markdownInline(task.title)}`,
      "",
      `- **Disposition:** ${dispositionLabel(task.disposition)}`,
      `- **Reviewed:** ${task.reviewed ? "Yes" : "No"}`,
      `- **Source location:** ${markdownInline(task.source_location)}`,
      `- **Issue:** ${markdownInline(task.issue)}`,
      ...fencedText("Relevant text", task.relevant_text, "as recorded"),
      `- **Suggestions:** ${markdownInline(task.suggestions)}`,
      `- **Done when:** ${markdownInline(task.done_when)}`,
      ...fencedText("User comment", task.user_comment),
      "",
    );
  }
  lines.push("## Set-aside comments", "");
  if (!payload.excluded.length) lines.push("No comments are set aside.", "");
  for (const task of payload.excluded) {
    lines.push(
      `### ${markdownInline(task.finding_id)} — ${markdownInline(task.title)}`,
      "",
      `- **Disposition:** ${dispositionLabel(task.disposition)}`,
      `- **Reviewed:** ${task.reviewed ? "Yes" : "No"}`,
      `- **My priority:** ${task.user_priority || "Unassigned"}`,
      ...fencedText("User comment", task.user_comment),
      "",
    );
  }
  // Preserve the user's note byte-for-byte apart from newline normalization.
  // Collapsing blank lines globally would silently rewrite text inside a fence.
  return `${lines.join("\n").trimEnd()}\n`;
}

export function buildAgentResponseTemplate(payload: RevisionTasksPayload): AgentResponseTemplate {
  return {
    schema_version: AGENT_RESPONSE_SCHEMA_VERSION,
    kind: AGENT_RESPONSE_KIND,
    plan_id: payload.plan_id,
    source_review_id: payload.source_review_id,
    source_review_fingerprint: payload.source_review_fingerprint,
    responded_at: null,
    entries: payload.tasks.map((task) => ({
      finding_id: task.finding_id,
      status: "not_attempted",
      response: "",
      changed_files: [],
      changed_locations: [],
      verification: [],
      blocker: null,
    })),
  };
}

export function deterministicJson(value: unknown): string {
  return `${JSON.stringify(value, null, 2)}\n`;
}
