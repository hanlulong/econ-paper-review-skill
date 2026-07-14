"use client";

import { ChangeEvent, Component, KeyboardEvent, lazy, Suspense, useCallback, useDeferredValue, useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import type { MarkdownComponents } from "./markdown-content";
import {
  generateReviewActionsPayload,
  mergeReviewActionEntries,
  privacySafeSourceManuscripts,
  recordReviewActionImport,
  reconcileReviewActions,
  REVIEW_ACTION_DISPOSITIONS,
  updateReviewAction,
  type ReviewActionDisposition,
  type ReviewActionEntry,
  type ReviewActionEvent,
} from "../lib/review-actions";
import {
  clearBrowserReviewActions,
  restoreBrowserReviewActions,
  saveBrowserReviewActionSnapshot,
} from "../lib/review-action-storage";
import {
  discoverReviewDocuments,
  REVIEW_DOCUMENT_GROUP_LABELS,
  resolveReviewDocumentLink,
  safeExternalReviewDocumentHref,
  validateReviewDocumentManifest,
  type ReviewDocument,
} from "../lib/review-documents";
import { parseStrictJson } from "../lib/strict-json";
import {
  inferReviewPackageRoot,
  matchReferencedImagePaths,
  normalizePackagePath,
  normalizeSelectedPackagePath,
  referencedExhibitHashes,
  referencedExhibitPaths,
  relativeToReviewRoot,
  reviewImageMediaType,
  selectReviewPackageFilePath,
  selectManuscriptPath,
  sha256ReviewBytes,
  validateExhibitManifest,
} from "../lib/local-review-package";
import {
  indexReviewComputations,
  validateReviewComputationLinks,
  validateReviewComputations,
  type ReviewComputation,
} from "../lib/review-computations-contract";
import { sha256Hex } from "../lib/review-fingerprint";
import { equationEvidencePresentation, prepareReviewMarkdown } from "../lib/review-equation-presentation";
import { orderExhibitRenders, type ExhibitRender } from "../lib/review-exhibit-presentation";
import { formatUserFacingLocator } from "../lib/review-locator";
import { conciseSourceAnchorLabel, exactAnchorExcerpt, sourceAnchorPageLabel } from "../lib/review-manuscript-context";
import {
  authorReportDisplayMarkdown,
  evidenceDisplayText,
  EvidenceSemanticFrame,
} from "../lib/review-text-evidence-presentation";
import {
  reviewEvidenceText as evidenceText,
  validateReviewLedger as validateLedger,
  type DecisionRole,
  type Evidence,
  type Finding,
  type Ledger,
  type Severity,
} from "../lib/review-ledger-contract";
import type { ReviewEvidenceRepresentation } from "../lib/review-evidence-contract";
import {
  paperSection,
  parseReviewUrlState,
  sortReviewFindings,
  writeReviewUrlState,
} from "../lib/review-view-state";
import { validateActivatedBurdens, type ActivatedBurden } from "../lib/review-runtime-contracts";
import {
  NO_FINALIZATION_RECEIPT,
  isFinalizationArtifactPath,
  validateFinalizationReceipt,
  verifyReviewFinalization,
  type FinalizationTrust,
} from "../lib/review-finalization";
import { validateReviewRegistry, type ReviewRegistry } from "../lib/review-registry";
import {
  buildAgentResponseTemplate,
  buildRevisionTasks,
  commitRevisionNoteDrafts,
  deterministicJson,
  renderRevisionAgentBrief,
  revisionDecisionGaps,
  type RevisionDecisionGap,
  type RevisionTask,
} from "../lib/revision-plan";

type LocalStatus = ReviewActionDisposition;
type Run = {
  schema_version?: string;
  review_id: string;
  paper_family: string;
  mode?: "full" | "quick";
  target: string | { venue?: string | null; tier?: string } | null;
  counts: Record<string, number>;
  verification_passed: boolean;
  status?: "draft" | "awaiting_checkpoint" | "blocked" | "verification_failed" | "complete";
  activated_burdens?: ActivatedBurden[];
  comment_policy: { exhaustive: boolean };
  assessment_boundary?: {
    sources?: Array<{ path: string; status?: string; sha256?: string | null }>;
    figures?: string;
    equations?: string;
    appendix?: string;
    notes?: string | null;
  };
  capabilities?: { live_literature_search?: boolean; replication_code?: string };
};

type ReviewPosture = "reject" | "weak_r_and_r" | "strong_r_and_r" | "accept" | "not_assessed";
type PrincipalConcern = {
  id: string;
  title: string;
  finding_ids: string[];
  decision_effect: "potentially_dispositive" | "posture_material";
  repairability: NonNullable<Finding["repairability"]>;
  rationale: string;
  upgrade_condition: string;
};
type Synthesis = {
  schema_version: "0.1";
  review_contract_version: "0.3" | "0.4";
  review_id: string;
  overall_assessment: string;
  strengths: string[];
  review_posture: ReviewPosture;
  posture_rationale: string;
  upgrade_conditions: string[];
  principal_concerns: PrincipalConcern[];
  other_major_finding_ids: string[];
  convincingness: string;
  writing_finding_count: number;
};

type LocalEntry = ReviewActionEntry;
type LocalState = Record<string, LocalEntry>;
type UndoStatusChange = {
  findingId: string;
  previous: LocalStatus;
  next: LocalStatus;
  previousReviewed: boolean;
  nextReviewed: boolean;
};
type PendingDocumentAnchor = { documentId: string; fragment: string };
type DetailMode = "overview" | "comment" | "plan";
type QueueOrder = "priority" | "importance" | "paper";
type WorkflowDecision = "open" | "ready_for_recheck" | "deferred";
type WorkflowStatusFilter = "all" | WorkflowDecision;
type PersistenceState = "idle" | "pending" | "saved" | "error";
type ExhibitAsset = { key: string; label: string; kind: "figure" | "table"; pages: number[]; renders: ExhibitRender[]; missingPaths: string[] };
type ExhibitManifest = { figures?: unknown[]; tables?: unknown[] };
type LoadedReviewDocument = ReviewDocument & { content: string };
type SourceAnchor = { id: string; source_id: string; kind: string; start_char: number | null; end_char: number | null; content_sha256: string; locator: string };
type SourceManifest = {
  schema_version: "0.1";
  review_id: string;
  anchors: SourceAnchor[];
  sources?: Array<{
    id?: string;
    role?: string;
    path: string;
    media_type?: string;
    extraction?: { path: string } | null;
  }>;
};

const MarkdownContent = lazy(() => import("./markdown-content"));

class MarkdownRenderBoundary extends Component<
  { source: string; children: ReactNode },
  { failed: boolean }
> {
  state = { failed: false };

  static getDerivedStateFromError() {
    return { failed: true };
  }

  componentDidUpdate(previous: Readonly<{ source: string; children: ReactNode }>) {
    if (this.state.failed && previous.source !== this.props.source) this.setState({ failed: false });
  }

  render() {
    if (this.state.failed) {
      return (
        <div className="markdown-render-error" role="alert">
          <strong>Formatted view unavailable</strong>
          <span>The original review text remains available below.</span>
          <pre>{this.props.source}</pre>
        </div>
      );
    }
    return this.props.children;
  }
}

function RenderedMarkdown({ children, components }: { children: string; components?: MarkdownComponents }) {
  const prepared = prepareReviewMarkdown(children);
  return (
    <MarkdownRenderBoundary source={children}>
      <Suspense fallback={<span className="markdown-loading" role="status">Formatting review text…</span>}>
        <MarkdownContent components={components}>{prepared}</MarkdownContent>
      </Suspense>
    </MarkdownRenderBoundary>
  );
}

const MAX_JSON_BYTES = 5_000_000;
const MAX_MANUSCRIPT_BYTES = 20_000_000;
const MAX_SELECTED_FILE_COUNT = 10_000;
const MAX_LOCAL_PACKAGE_FILES = 2_500;
const MAX_LOCAL_PACKAGE_BYTES = 300_000_000;
const MAX_REFERENCED_IMAGES = 500;
const MAX_LOCAL_IMAGE_BYTES = 30_000_000;
const MAX_NOTE_CHARS = 10_000;
const STANDARD_REVIEW_DOCUMENT_PATHS = [
  "README.md", "report.md", "editing-comments.md", "fix-plan.md", "evidence/reconstruction.md",
  "evidence/reader-claim-audit.md", "evidence/analytical-audit.md", "evidence/figures.md",
  "evidence/tables.md", "evidence/writing.md", "evidence/coverage.md", "evidence/sources.md",
  "evidence/verification.md",
];

function normalizedFilePath(file: File) {
  return normalizeSelectedPackagePath(file.webkitRelativePath || file.name);
}

function parseJsonFile(fileName: string, text: string): unknown {
  try {
    return parseStrictJson(text);
  } catch (error) {
    const detail = error instanceof Error ? error.message : "invalid JSON syntax";
    throw new Error(`${fileName} contains invalid JSON: ${detail}`);
  }
}

function EquationEvidence({
  content,
  representation,
  compact = false,
  embedded = false,
}: {
  content: string;
  representation?: ReviewEvidenceRepresentation;
  compact?: boolean;
  embedded?: boolean;
}) {
  const raw = content || "No equation evidence is available.";
  const display = evidenceDisplayText(raw, representation);
  const presentation = equationEvidencePresentation(display, representation);
  const isProse = presentation.kind === "prose";
  const proseLabel = representation === "reviewer_observation" ? "Reviewer observation"
    : representation === "composite_comparison" ? "Reviewer comparison"
      : representation === "checked_absence" ? "Checked absence"
        : representation === "computed_result" ? "Computed result"
          : "Equation evidence";
  return (
    <div className={`equation-evidence${compact ? " compact" : ""}${embedded ? " embedded" : ""}`}>
      <div className={`equation-render equation-render-${presentation.kind}`} aria-label={isProse ? proseLabel : "Rendered equation"}>
        <RenderedMarkdown>{presentation.content}</RenderedMarkdown>
      </div>
      <details className="equation-raw">
        <summary>{isProse ? "View raw evidence" : "View raw equation"}</summary>
        <pre>{raw}</pre>
      </details>
    </div>
  );
}

function EvidenceContent({
  evidence,
  content,
  compact = false,
  collapsed = false,
}: {
  evidence: Evidence | undefined;
  content: string;
  compact?: boolean;
  collapsed?: boolean;
}) {
  const fallback = evidence?.type === "quote" ? "No quoted evidence is available."
    : ["code", "table_cell"].includes(evidence?.type || "") ? "No structured evidence is available."
      : "No narrative evidence is available.";
  const display = evidenceDisplayText(content, evidence?.representation);
  const rendered = evidence?.type === "equation"
    ? <EquationEvidence content={display} representation={evidence.representation} compact={compact} embedded />
    : ["code", "table_cell"].includes(evidence?.type || "")
      ? <pre className="structured-evidence">{display || fallback}</pre>
      : evidence?.type === "quote"
        ? <RenderedMarkdown>{display || fallback}</RenderedMarkdown>
        : <div className="prose-evidence"><RenderedMarkdown>{display || fallback}</RenderedMarkdown></div>;
  return (
    <EvidenceSemanticFrame representation={evidence?.representation} compact={compact} collapsed={collapsed}>
      {rendered}
    </EvidenceSemanticFrame>
  );
}

function ComputationProvenance({
  computationId,
  computation,
  sourceAnchors,
}: {
  computationId: string | null | undefined;
  computation: ReviewComputation | undefined;
  sourceAnchors: Record<string, SourceAnchor>;
}) {
  if (!computationId) {
    return <div className="missing-computation" role="status"><strong>Calculation details unavailable</strong><span>The saved review does not include enough information to inspect this calculation.</span></div>;
  }
  if (!computation) {
    return <div className="missing-computation" role="status"><strong>Calculation details unavailable</strong><span>The evidence statement remains visible, but its underlying calculation cannot be inspected here.</span></div>;
  }
  const checkedLocations = computation.input_anchor_ids
    .map((anchorId) => sourceAnchors[anchorId]?.locator || "")
    .filter(Boolean);
  return (
    <section className="computation-provenance" aria-labelledby={`computation-${computation.id}`}>
      <div className="computation-heading">
        <span id={`computation-${computation.id}`}>Calculation details</span>
      </div>
      <p className="computation-result"><strong>Result</strong><span>{computation.result}</span></p>
      <dl>
        <div><dt>Tool</dt><dd>{computation.tool}</dd></div>
        <div><dt>Tolerance</dt><dd>{computation.tolerance}</dd></div>
        <div className="computation-wide"><dt>Method</dt><dd>{computation.method}</dd></div>
        {checkedLocations.length > 0 && <div className="computation-wide"><dt>Inputs checked</dt><dd>{checkedLocations.map((locator, index) => {
          const page = sourceAnchorPageLabel(locator);
          return <span className="computation-anchor" key={`${locator}-${index}`} title={locator}><span>{page || locator}</span>{index < checkedLocations.length - 1 && <span className="computation-anchor-separator" aria-hidden="true">; </span>}</span>;
        })}</dd></div>}
      </dl>
      <p className="computation-boundary">Review Desk shows the saved result; it does not rerun the calculation.</p>
    </section>
  );
}

function ExhibitImage({ src, alt, compact = false }: { src: string; alt: string; compact?: boolean }) {
  const [failed, setFailed] = useState(false);
  if (failed) {
    return <div className="missing-exhibit" role="status"><strong>Exhibit image unavailable</strong><span>The saved image could not be loaded. Use the source location to inspect it in the paper.</span></div>;
  }
  // Local object URLs and bundled static assets cannot use the optimization pipeline.
  // eslint-disable-next-line @next/next/no-img-element
  return <img src={src} alt={alt} loading={compact ? "lazy" : "eager"} onError={() => setFailed(true)} />;
}

function exhibitKey(kind: "figure" | "table", label: string) {
  const normalized = label
    .replace(/^Appendix\s+(Figure|Table)\s+/i, "")
    .replace(/^(Figure|Table)\s+/i, "")
    .trim()
    .toLowerCase();
  return `${kind}:${normalized}`;
}

function manifestAssets(
  tables: unknown,
  figures: unknown,
  resolvePath: (path: string) => string | null,
) {
  const assets: Record<string, ExhibitAsset> = {};
  const aliases = new Map<string, ExhibitAsset[]>();
  const add = (rows: unknown, kind: "figure" | "table", pathField: "render_paths" | "extraction_paths") => {
    if (!Array.isArray(rows)) return;
    for (const row of rows) {
      if (!isRecord(row) || typeof row.label !== "string") continue;
      type RawExhibitAsset = { path: string; declaredRole?: "exhibit_crop" | "full_source_page"; pdfPage?: number | null };
      const legacyPaths: RawExhibitAsset[] = Array.isArray(row[pathField])
        ? row[pathField].filter((value): value is string => typeof value === "string").map((path) => ({ path }))
        : [];
      const currentAssets: RawExhibitAsset[] = Array.isArray(row.rendered_assets)
        ? row.rendered_assets.flatMap((asset) => isRecord(asset) && typeof asset.path === "string"
          ? [{
              path: asset.path,
              declaredRole: asset.render_type === "crop" ? "exhibit_crop" as const
                : asset.render_type === "full_page" ? "full_source_page" as const
                  : undefined,
              pdfPage: Number.isInteger(asset.pdf_page) ? Number(asset.pdf_page) : null,
            }]
          : [])
        : [];
      const rawAssets = currentAssets.length ? currentAssets : legacyPaths;
      const resolved = rawAssets.map((asset) => ({ ...asset, resolved: resolvePath(asset.path) }));
      const renders = orderExhibitRenders(resolved.flatMap((item) => item.resolved
        ? [{ sourcePath: item.path, resolvedPath: item.resolved, declaredRole: item.declaredRole }]
        : []));
      const key = exhibitKey(kind, row.label);
      const declaredPages = Array.isArray(row.pdf_pages)
        ? row.pdf_pages.filter((value): value is number => Number.isInteger(value))
        : [];
      const asset = {
        key,
        label: row.label,
        kind,
        pages: Array.from(new Set([
          ...declaredPages,
          ...resolved.flatMap((item) => item.pdfPage ? [item.pdfPage] : []),
        ])).sort((left, right) => left - right),
        renders,
        missingPaths: resolved.filter((item) => !item.resolved).map((item) => item.path),
      };
      if (assets[key]) throw new Error(`Duplicate exhibit label in ${kind} manifest: ${row.label}`);
      assets[key] = asset;
      const labelPart = key.slice(kind.length + 1);
      const shortLabel = labelPart.split(":", 1)[0];
      if (shortLabel !== labelPart) {
        const alias = `${kind}:${shortLabel}`;
        aliases.set(alias, [...(aliases.get(alias) || []), asset]);
      }
    }
  };
  add(isRecord(tables) ? tables.tables : undefined, "table", "render_paths");
  add(isRecord(figures) ? figures.figures : undefined, "figure", "extraction_paths");
  for (const [alias, candidates] of aliases) {
    if (candidates.length === 1 && !assets[alias]) assets[alias] = candidates[0];
  }
  return assets;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return Boolean(value) && typeof value === "object" && !Array.isArray(value);
}

function validateRun(value: unknown): Run {
  if (
    !isRecord(value) || typeof value.review_id !== "string" || !value.review_id.trim() || typeof value.paper_family !== "string"
    || typeof value.verification_passed !== "boolean" || !isRecord(value.counts) || !isRecord(value.comment_policy)
  ) {
    throw new Error("run.json does not have the required review_id and paper_family");
  }
  if (value.schema_version !== undefined && !["0.1", "0.2", "0.3", "0.4"].includes(String(value.schema_version))) {
    throw new Error("run.json has an unsupported schema_version");
  }
  for (const key of ["critical", "major", "minor", "info", "essential"]) {
    if (!Number.isInteger(value.counts[key]) || Number(value.counts[key]) < 0) throw new Error(`run.json count ${key} must be a nonnegative integer`);
  }
  if (typeof value.comment_policy.exhaustive !== "boolean") throw new Error("run.json comment_policy.exhaustive must be boolean");
  if (value.status !== undefined && !["draft", "awaiting_checkpoint", "blocked", "verification_failed", "complete"].includes(String(value.status))) {
    throw new Error("run.json has an unsupported status");
  }
  if (value.mode !== "full" && value.mode !== "quick") throw new Error("run.json has an unsupported review mode");
  if (value.schema_version === "0.4") validateActivatedBurdens(value.activated_burdens);
  if (
    !(value.target === null || typeof value.target === "string" || (
      isRecord(value.target)
      && (value.target.venue === undefined || value.target.venue === null || typeof value.target.venue === "string")
      && (value.target.tier === undefined || typeof value.target.tier === "string")
    ))
  ) throw new Error("run.json target must be text, null, or an object with text venue/tier fields");
  return value as Run;
}

function validateSynthesis(value: unknown): Synthesis | null {
  if (value === null || value === undefined || (isRecord(value) && !Object.keys(value).length)) return null;
  if (
    !isRecord(value) || value.schema_version !== "0.1" || !["0.3", "0.4"].includes(String(value.review_contract_version))
    || typeof value.review_id !== "string" || !value.review_id.trim()
    || typeof value.overall_assessment !== "string" || !value.overall_assessment.trim()
    || typeof value.posture_rationale !== "string" || !value.posture_rationale.trim()
    || typeof value.convincingness !== "string" || !value.convincingness.trim()
    || !["reject", "weak_r_and_r", "strong_r_and_r", "accept", "not_assessed"].includes(String(value.review_posture))
    || !Array.isArray(value.strengths) || value.strengths.some((item) => typeof item !== "string" || !item.trim())
    || !Array.isArray(value.upgrade_conditions) || value.upgrade_conditions.some((item) => typeof item !== "string" || !item.trim())
    || !Array.isArray(value.other_major_finding_ids) || value.other_major_finding_ids.some((item) => typeof item !== "string" || !item.trim())
    || !Number.isInteger(value.writing_finding_count) || Number(value.writing_finding_count) < 0
    || !Array.isArray(value.principal_concerns)
  ) throw new Error("synthesis.json does not have the required v0.3 assessment structure");
  for (const [index, concern] of value.principal_concerns.entries()) {
    if (
      !isRecord(concern) || typeof concern.id !== "string" || !/^PC-[0-9]{2,}$/.test(concern.id)
      || typeof concern.title !== "string" || !concern.title.trim()
      || !Array.isArray(concern.finding_ids) || !concern.finding_ids.length
      || concern.finding_ids.some((item) => typeof item !== "string" || !item.trim())
      || !["potentially_dispositive", "posture_material"].includes(String(concern.decision_effect))
      || !["within_current_design", "claim_narrowing", "additional_analysis", "new_evidence", "redesign", "unclear", "no_clear_fix"].includes(String(concern.repairability))
      || typeof concern.rationale !== "string" || !concern.rationale.trim()
      || typeof concern.upgrade_condition !== "string" || !concern.upgrade_condition.trim()
    ) throw new Error(`synthesis.json has an invalid principal concern at position ${index + 1}`);
  }
  return value as Synthesis;
}

function validateSourceManifest(value: unknown): SourceManifest | null {
  if (value === null || value === undefined || (isRecord(value) && !Object.keys(value).length)) return null;
  if (!isRecord(value) || value.schema_version !== "0.1" || typeof value.review_id !== "string" || !Array.isArray(value.sources) || !Array.isArray(value.anchors)) {
    throw new Error("source-manifest.json does not have the required source-anchor structure");
  }
  const ids = new Set<string>();
  const sourceIds = new Set<string>();
  for (const [index, source] of value.sources.entries()) {
    if (
      !isRecord(source) || typeof source.id !== "string" || sourceIds.has(source.id)
      || typeof source.role !== "string" || typeof source.media_type !== "string" || !source.media_type.trim()
      || typeof source.path !== "string" || normalizePackagePath(source.path) !== source.path
    ) throw new Error(`source-manifest.json has an invalid source at position ${index + 1}`);
    if (source.extraction !== undefined && source.extraction !== null && (
      !isRecord(source.extraction) || typeof source.extraction.path !== "string"
      || normalizePackagePath(source.extraction.path) !== source.extraction.path
    )) throw new Error(`source-manifest.json has an invalid extraction at source position ${index + 1}`);
    sourceIds.add(source.id);
  }
  for (const [index, anchor] of value.anchors.entries()) {
    if (
      !isRecord(anchor) || typeof anchor.id !== "string" || ids.has(anchor.id)
      || typeof anchor.source_id !== "string" || !sourceIds.has(anchor.source_id) || typeof anchor.kind !== "string"
      || !(anchor.start_char === null || Number.isInteger(anchor.start_char) && Number(anchor.start_char) >= 0)
      || !(anchor.end_char === null || Number.isInteger(anchor.end_char) && Number(anchor.end_char) >= 0)
      || typeof anchor.content_sha256 !== "string" || !/^[a-f0-9]{64}$/.test(anchor.content_sha256)
      || typeof anchor.locator !== "string" || !anchor.locator.trim()
    ) throw new Error(`source-manifest.json has an invalid anchor at position ${index + 1}`);
    if (typeof anchor.start_char === "number" && typeof anchor.end_char === "number" && anchor.end_char < anchor.start_char) {
      throw new Error(`source-manifest.json anchor ${anchor.id} ends before it starts`);
    }
    ids.add(anchor.id);
  }
  return value as unknown as SourceManifest;
}

function validateLedgerAnchors(ledger: Ledger, manifest: SourceManifest | null): void {
  if (ledger.schema_version !== "0.4") return;
  if (!manifest) throw new Error("v0.4 findings require evidence/source-manifest.json");
  const anchors = new Map(manifest.anchors.map((anchor) => [anchor.id, anchor]));
  for (const finding of ledger.findings) {
    const positionAnchor = finding.paper_position?.anchor_id;
    const positionSource = finding.paper_position?.source_id;
    if (!positionAnchor || !anchors.has(positionAnchor)) throw new Error(`finding ${finding.id} has an unresolved paper-position anchor`);
    if (positionSource && anchors.get(positionAnchor)?.source_id !== positionSource) throw new Error(`finding ${finding.id} paper position has inconsistent source and anchor IDs`);
    for (const evidence of finding.evidence) {
      if (evidence.anchor_id && !anchors.has(evidence.anchor_id)) throw new Error(`finding ${finding.id} evidence ${evidence.id || "item"} has an unresolved source anchor`);
      for (const anchorId of evidence.anchor_ids || []) {
        if (!anchors.has(anchorId)) throw new Error(`finding ${finding.id} evidence ${evidence.id || "item"} has an unresolved comparison anchor ${anchorId}`);
      }
    }
  }
}

function validatePackageLinks(ledger: Ledger, run: Run, synthesis: Synthesis | null): void {
  const active = ledger.findings.filter((finding) => !["dismissed", "resolved"].includes(finding.status));
  for (const severity of ["critical", "major", "minor", "info"] as const) {
    const actual = active.filter((finding) => finding.severity === severity).length;
    if (run.counts[severity] !== actual) throw new Error(`run.json ${severity} count does not match findings.json`);
  }
  const essential = active.filter((finding) => finding.essential).length;
  if (run.counts.essential !== essential) throw new Error("run.json essential count does not match findings.json");
  if (!synthesis) return;
  const ids = new Set(ledger.findings.map((finding) => finding.id));
  for (const concern of synthesis.principal_concerns) {
    for (const id of concern.finding_ids) if (!ids.has(id)) throw new Error(`synthesis concern ${concern.id} references unknown finding ${id}`);
  }
  for (const id of synthesis.other_major_finding_ids) if (!ids.has(id)) throw new Error(`synthesis references unknown finding ${id}`);
}

function locator(finding: Finding, evidenceIndex = 0) {
  const value = finding.evidence[evidenceIndex]?.locator || finding.evidence[0]?.locator;
  return formatUserFacingLocator(value);
}

function shortTitle(finding: Finding) {
  return (finding.title || finding.issue.split(". ", 1)[0]).replace(/\.$/, "");
}

function commentLabel(findings: readonly Finding[], findingId: string) {
  const index = findings.findIndex((finding) => finding.id === findingId);
  return index >= 0 ? `Comment #${index + 1}: ${shortTitle(findings[index])}` : "This comment";
}

function channelLabel(finding: Finding) {
  return finding.report_channel === "writing" ? "Editing comments" : "Substance";
}

function readableState(value: string | undefined) {
  return (value || "not available").replaceAll("_", " ");
}

/**
 * The saved would_change_my_mind field is written either as a noun phrase or as
 * a full sentence ending in "would change this assessment"; normalize it so the
 * displayed line stays grammatical after the "What would change…" label.
 */
function confidenceChangeText(value: string) {
  const trimmed = value.trim().replace(/\s*would change (?:this|my) (?:assessment|conclusion|mind)\.?$/i, "").trim();
  if (!trimmed) return "";
  return /[.!?]$/.test(trimmed) ? trimmed : `${trimmed}.`;
}

const READY_FOR_REVIEW_DISPOSITIONS = new Set<LocalStatus>(["ready_for_recheck", "challenged"]);
const SET_ASIDE_DISPOSITIONS = new Set<LocalStatus>(["deferred", "not_relevant", "not_addressable"]);

/** Keep the saved action contract compatible while presenting one clear decision model. */
function workflowDecision(value: LocalStatus): WorkflowDecision {
  if (READY_FOR_REVIEW_DISPOSITIONS.has(value)) return "ready_for_recheck";
  if (SET_ASIDE_DISPOSITIONS.has(value)) return "deferred";
  return "open";
}

function normalizeWorkflowStatusFilter(value: string | undefined): WorkflowStatusFilter {
  if (value === "all") return "all";
  if ((REVIEW_ACTION_DISPOSITIONS as readonly string[]).includes(value || "")) {
    return workflowDecision(value as LocalStatus);
  }
  return "all";
}

function workflowDecisionLabel(value: LocalStatus | WorkflowDecision): string {
  const decision = workflowDecision(value as LocalStatus);
  if (decision === "ready_for_recheck") return "Ready for review";
  if (decision === "deferred") return "Set aside";
  return "Open";
}

function dispositionDetailLabel(value: LocalStatus): string {
  if (value === "challenged") return "Ready for review — reasoned response";
  if (value === "ready_for_recheck") return "Ready for review";
  if (value === "deferred") return "Set aside — revisit later";
  if (value === "not_relevant") return "Set aside — does not apply";
  if (value === "not_addressable") return "Set aside — cannot address";
  return "Open";
}

function missingDecisionLabel(value: RevisionDecisionGap["missing"][number]) {
  if (value === "user_priority") return "assign P0, P1, or P2";
  if (value === "user_comment") return "add an instruction, response, or set-aside reason";
  return "mark reviewed";
}

function safeDownloadStem(value: string) {
  return value.normalize("NFC").replace(/[^\p{L}\p{N}._-]+/gu, "-").replace(/^[.-]+|[.-]+$/g, "").slice(0, 100) || "review";
}

function actionExportTime(entries: Readonly<Record<string, ReviewActionEntry>>) {
  const newest = Object.values(entries).reduce((maximum, entry) => Math.max(maximum, Date.parse(entry.updated_at)), Date.now());
  return new Date(newest).toISOString();
}

function actionEventLabel(event: ReviewActionEvent) {
  if (event.type === "disposition_changed") return event.disposition ? `Marked ${dispositionDetailLabel(event.disposition)}` : "Updated decision";
  if (event.type === "priority_changed") return event.user_priority ? `Set personal priority to ${event.user_priority}` : "Cleared personal priority";
  if (event.type === "reviewed_changed") return event.reviewed ? "Marked reviewed" : "Marked not reviewed";
  if (event.type === "reversed") return event.disposition
    ? `Reversed to ${dispositionDetailLabel(event.disposition)}`
    : "Reversed an author-note change";
  if (event.type === "note_revised") return event.note ? "Updated author note" : "Cleared author note";
  return "Imported from an action handoff";
}

function mergeDistinctText(first: string | undefined, second: string | undefined) {
  const left = " ".concat(first || "").trim().replace(/\s+/g, " ");
  const right = " ".concat(second || "").trim().replace(/\s+/g, " ");
  if (!left) return right;
  if (!right) return left;
  const normalize = (value: string) => value.toLowerCase().replace(/[^a-z0-9]+/g, "");
  const leftKey = normalize(left);
  const rightKey = normalize(right);
  if (leftKey === rightKey || rightKey.includes(leftKey)) return right;
  if (leftKey.includes(rightKey)) return left;
  return `${left} ${right}`;
}

const DECISION_ROLE_LABELS: Record<DecisionRole, string> = {
  potentially_dispositive: "Could prevent publication",
  posture_material: "Could affect the recommendation",
  revision_value: "Strengthens the revision",
  polish: "Polish",
};

function reviewLoadMessage(error: unknown): string {
  const message = error instanceof Error ? error.message.toLowerCase() : "";
  if (/schema|contract|unsupported.*version|version.*unsupported/.test(message)) {
    return "This review was created by an unsupported older or newer version. Update Review Desk or regenerate the review, then try again.";
  }
  if (/sha-?256|hash|finaliz|receipt|artifact|integrity|gate|different review id|ids do not match/.test(message)) {
    return "Some files changed after the review was generated. Reopen the untouched finished review folder or regenerate the review.";
  }
  if (/size|too many|more than|processing limit/.test(message)) {
    return "This folder is too large to open safely. Choose the finished review folder itself, without unrelated files.";
  }
  return "This is not a complete review folder. Open the finished review folder that contains the report and its supporting files.";
}

const SHORT_DECISION_ROLE_LABELS: Record<DecisionRole, string> = {
  potentially_dispositive: "Could prevent publication",
  posture_material: "Affects recommendation",
  revision_value: "Strengthens revision",
  polish: "Polish",
};

const POSTURE_LABELS: Record<ReviewPosture, string> = {
  reject: "Reject",
  weak_r_and_r: "Weak revise & resubmit",
  strong_r_and_r: "Strong revise & resubmit",
  accept: "Accept",
  not_assessed: "Not assessed",
};

function decisionRoleLabel(value: DecisionRole | undefined) {
  return value ? DECISION_ROLE_LABELS[value] : "Publication role not available";
}

function shortDecisionRoleLabel(value: DecisionRole | undefined) {
  return value ? SHORT_DECISION_ROLE_LABELS[value] : "Unclassified";
}

function displayEvidenceIndex(finding: Finding): number {
  if (!finding.display_evidence_id) return 0;
  const index = finding.evidence.findIndex((evidence) => evidence.id === finding.display_evidence_id);
  return index < 0 ? 0 : index;
}

function defaultEntry(findingId: string): LocalEntry {
  return {
    finding_id: findingId,
    disposition: "open",
    response_note: "",
    changed_locations: [],
    user_priority: null,
    reviewed: false,
    updated_at: "1970-01-01T00:00:00.000Z",
    status_history: [{ disposition: "open", at: "1970-01-01T00:00:00.000Z" }],
    events: [{
      event_id: "00000000-0000-4000-8000-000000000000",
      type: "disposition_changed",
      at: "1970-01-01T00:00:00.000Z",
      disposition: "open",
      parent_event_id: null,
      origin: "local",
    }],
  };
}

export function ReviewWorkspace() {
  const [ledger, setLedger] = useState<Ledger | null>(null);
  const [ledgerFingerprint, setLedgerFingerprint] = useState("");
  const [run, setRun] = useState<Run | null>(null);
  const [synthesis, setSynthesis] = useState<Synthesis | null>(null);
  const [manuscript, setManuscript] = useState("");
  const [documents, setDocuments] = useState<LoadedReviewDocument[]>([]);
  const [reportView, setReportView] = useState("none");
  const [detailMode, setDetailMode] = useState<DetailMode>("overview");
  const [queueOrder, setQueueOrder] = useState<QueueOrder>("importance");
  const [selectedId, setSelectedId] = useState("");
  const [localState, setLocalState] = useState<LocalState>({});
  const [noteDrafts, setNoteDrafts] = useState<Record<string, string>>({});
  const [query, setQuery] = useState("");
  const [severity, setSeverity] = useState<"all" | Severity>("all");
  const [decisionRole, setDecisionRole] = useState<"all" | DecisionRole>("all");
  const [status, setStatus] = useState<WorkflowStatusFilter>("all");
  const [channel, setChannel] = useState<"all" | "substance" | "writing">("all");
  const [dimension, setDimension] = useState("all");
  const [reviewedFilter, setReviewedFilter] = useState<"all" | "reviewed" | "unreviewed">("all");
  const [personalPriorityFilter, setPersonalPriorityFilter] = useState<"all" | "P0" | "P1" | "P2" | "unassigned">("all");
  const [showEvidence, setShowEvidence] = useState(true);
  const [expandedEvidence, setExpandedEvidence] = useState(false);
  const [evidenceIndex, setEvidenceIndex] = useState(0);
  const [sourceAnchorSelection, setSourceAnchorSelection] = useState({ evidenceKey: "", index: 0 });
  const [assetPathIndex, setAssetPathIndex] = useState(0);
  const [loadError, setLoadError] = useState("");
  const [announcement, setAnnouncement] = useState("");
  const [actionNotice, setActionNotice] = useState("");
  const [undoStatusChange, setUndoStatusChange] = useState<UndoStatusChange | null>(null);
  const [pendingDocumentAnchor, setPendingDocumentAnchor] = useState<PendingDocumentAnchor | null>(null);
  const [exhibitAssets, setExhibitAssets] = useState<Record<string, ExhibitAsset>>({});
  const [sourceAnchors, setSourceAnchors] = useState<Record<string, SourceAnchor>>({});
  const [computationsById, setComputationsById] = useState<Record<string, ReviewComputation>>({});
  const [registry, setRegistry] = useState<ReviewRegistry | null>(null);
  const [reviewSlug, setReviewSlug] = useState("");
  const [isBundleLoading, setIsBundleLoading] = useState(false);
  const [isLocalLoading, setIsLocalLoading] = useState(false);
  const [persistenceWarning, setPersistenceWarning] = useState("");
  const [persistenceState, setPersistenceState] = useState<PersistenceState>("idle");
  const [handoffWarning, setHandoffWarning] = useState("");
  const [finalizationTrust, setFinalizationTrust] = useState<FinalizationTrust>({ ...NO_FINALIZATION_RECEIPT });
  const [persistenceMode, setPersistenceMode] = useState<"local" | "session">("local");
  const [registryUnavailable, setRegistryUnavailable] = useState(false);
  const [mobilePane, setMobilePane] = useState<"queue" | "comment" | "evidence">("queue");
  const fileInput = useRef<HTMLInputElement>(null);
  const folderInput = useRef<HTMLInputElement>(null);
  const actionsInput = useRef<HTMLInputElement>(null);
  const searchInput = useRef<HTMLInputElement>(null);
  const noteInput = useRef<HTMLTextAreaElement>(null);
  const reportReader = useRef<HTMLElement>(null);
  const reportHeading = useRef<HTMLHeadingElement>(null);
  const reportBackButton = useRef<HTMLButtonElement>(null);
  const overviewHeading = useRef<HTMLHeadingElement>(null);
  const revisionPlanHeading = useRef<HTMLHeadingElement>(null);
  const topMenu = useRef<HTMLDetailsElement>(null);
  const readyDecisionMenu = useRef<HTMLDetailsElement>(null);
  const setAsideDecisionMenu = useRef<HTMLDetailsElement>(null);
  const commentHeading = useRef<HTMLHeadingElement>(null);
  const evidenceHeading = useRef<HTMLHeadingElement>(null);
  const commentPane = useRef<HTMLElement>(null);
  const commentScroll = useRef<HTMLDivElement>(null);
  const documentPane = useRef<HTMLElement>(null);
  const noResultsRef = useRef<HTMLElement>(null);
  const findingRefs = useRef(new Map<string, HTMLButtonElement>());
  const localObjectUrls = useRef<string[]>([]);
  const loadedReviewSlug = useRef("");
  const localLoadSequence = useRef(0);
  const localStateRef = useRef<LocalState>({});
  const noteDraftsRef = useRef<Record<string, string>>({});
  const persistenceModeRef = useRef<"local" | "session">("local");
  const persistenceContextRef = useRef<{
    reviewId: string;
    reviewFingerprint: string;
    sourceManuscripts: ReturnType<typeof privacySafeSourceManuscripts>;
  } | null>(null);
  const focusAfterFilter = useRef(false);
  const persistenceWarningRef = useRef("");
  const applyingHistoryState = useRef(false);

  const showActionNotice = useCallback((message: string, undo: UndoStatusChange | null = null) => {
    setActionNotice(message);
    setUndoStatusChange(undo);
  }, []);

  const replaceNoteDrafts = useCallback((next: Record<string, string>) => {
    noteDraftsRef.current = next;
    setNoteDrafts(next);
  }, []);

  const updateNoteDraft = useCallback((id: string, value: string) => {
    const next = { ...noteDraftsRef.current, [id]: value.slice(0, MAX_NOTE_CHARS) };
    noteDraftsRef.current = next;
    setNoteDrafts(next);
    if (persistenceModeRef.current === "local") setPersistenceState("pending");
  }, []);

  const flushBrowserActions = useCallback(() => {
    const context = persistenceContextRef.current;
    if (!context) return false;
    const draftSnapshot = noteDraftsRef.current;
    try {
      const result = saveBrowserReviewActionSnapshot(window.localStorage, {
        persistence_mode: persistenceModeRef.current,
        source_review_id: context.reviewId,
        source_review_fingerprint: context.reviewFingerprint,
        source_manuscripts: context.sourceManuscripts,
        entries: localStateRef.current,
        draft_notes: draftSnapshot,
      });
      if (!result.persisted) return false;
      if (Object.keys(draftSnapshot).length) {
        localStateRef.current = result.entries;
        noteDraftsRef.current = {};
        setLocalState(result.entries);
        setNoteDrafts({});
      }
      if (persistenceWarningRef.current) {
        persistenceWarningRef.current = "";
        setPersistenceWarning("");
      }
      setPersistenceState("saved");
      return true;
    } catch {
      const warning = "Progress is available for this tab, but the browser could not save it locally.";
      if (warning !== persistenceWarningRef.current) {
        persistenceWarningRef.current = warning;
        setPersistenceWarning(warning);
      }
      setPersistenceState("error");
      return false;
    }
  }, []);

  useEffect(() => {
    if (!actionNotice) return;
    const timeout = window.setTimeout(() => {
      setActionNotice("");
      setUndoStatusChange(null);
    }, 5500);
    return () => window.clearTimeout(timeout);
  }, [actionNotice]);

  useEffect(() => {
    fetch("/reviews/index.json")
      .then(async (response) => {
        if (!response.ok) throw new Error("Review registry is unavailable");
        const declaredSize = Number(response.headers.get("content-length"));
        if (Number.isFinite(declaredSize) && declaredSize > MAX_JSON_BYTES) throw new Error("Review registry is oversized");
        const bytes = new Uint8Array(await response.arrayBuffer());
        if (bytes.byteLength > MAX_JSON_BYTES) throw new Error("Review registry is oversized");
        let text: string;
        try {
          text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
        } catch {
          throw new Error("Review registry is not valid UTF-8");
        }
        return parseJsonFile("/reviews/index.json", text);
      })
      .then((value: unknown) => {
        const checked = validateReviewRegistry(value);
        const requested = new URLSearchParams(window.location.search).get("review");
        const initial = checked.reviews.some((entry) => entry.slug === requested) ? requested! : checked.default_review;
        setRegistry(checked);
        setReviewSlug(initial);
      })
      .catch(() => setRegistryUnavailable(true));
  }, []);

  useEffect(() => {
    const entry = registry?.reviews.find((candidate) => candidate.slug === reviewSlug);
    if (!entry) return;
    if (entry.slug === loadedReviewSlug.current && ledger && run) {
      setIsBundleLoading(false);
      return;
    }
    flushBrowserActions();
    let cancelled = false;
    const sequence = ++localLoadSequence.current;
    setIsLocalLoading(false);
    setIsBundleLoading(true);
    const decodeText = async (response: Response, path: string, limit: number) => {
      const declaredSize = Number(response.headers.get("content-length"));
      if (Number.isFinite(declaredSize) && declaredSize > limit) {
        throw new Error(`Review text exceeds the browser processing limit: ${path}`);
      }
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength > limit) throw new Error(`Review text exceeds the browser processing limit: ${path}`);
      try {
        return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
      } catch {
        throw new Error(`Review text is not valid UTF-8: ${path}`);
      }
    };
    const requiredText = async (path: string, limit = MAX_MANUSCRIPT_BYTES) => {
      const response = await fetch(path);
      if (!response.ok) throw new Error(`Required review file is unavailable: ${path}`);
      return decodeText(response, path, limit);
    };
    const requiredBytes = async (path: string) => {
      const response = await fetch(path);
      if (!response.ok) throw new Error(`Finalized review artifact is unavailable: ${path}`);
      const declaredSize = Number(response.headers.get("content-length"));
      if (Number.isFinite(declaredSize) && declaredSize > MAX_LOCAL_PACKAGE_BYTES) {
        throw new Error(`Finalized review artifact exceeds the browser verification limit: ${path}`);
      }
      const bytes = new Uint8Array(await response.arrayBuffer());
      if (bytes.byteLength > MAX_LOCAL_PACKAGE_BYTES) throw new Error(`Finalized review artifact exceeds the browser verification limit: ${path}`);
      return bytes;
    };
    const requiredJson = async (path: string) => parseJsonFile(path, await requiredText(path, MAX_JSON_BYTES));
    const optionalJson = async (path: string) => {
      const response = await fetch(path);
      if (response.status === 404) return {};
      if (!response.ok) throw new Error(`Optional review file could not be read: ${path}`);
      return parseJsonFile(path, await decodeText(response, path, MAX_JSON_BYTES));
    };
    const optionalManifest = async (path: string) => {
      const response = await fetch(path);
      if (response.status === 404) return null;
      if (!response.ok) throw new Error(`Optional review manifest could not be read: ${path}`);
      return parseJsonFile(path, await decodeText(response, path, MAX_JSON_BYTES));
    };
    const optionalText = async (path: string, limit = MAX_MANUSCRIPT_BYTES) => {
      const response = await fetch(path);
      if (response.status === 404) return "";
      if (!response.ok) throw new Error(`Optional review file could not be read: ${path}`);
      return decodeText(response, path, limit);
    };
    Promise.all([
      requiredText(`${entry.base_path}/findings.json`, MAX_JSON_BYTES),
      requiredJson(`${entry.base_path}/run.json`),
      optionalJson(`${entry.base_path}/synthesis.json`),
      optionalJson(`${entry.base_path}/evidence/tables.json`),
      optionalJson(`${entry.base_path}/evidence/figures.json`),
      optionalManifest(`${entry.base_path}/review-manifest.json`),
      optionalJson(`${entry.base_path}/evidence/source-manifest.json`),
      optionalJson(`${entry.base_path}/evidence/computations.json`),
      optionalJson(`${entry.base_path}/evidence/analytical-audit.json`),
      optionalJson(`${entry.base_path}/evidence/claims.json`),
      optionalText(`${entry.base_path}/finalization.json`, MAX_JSON_BYTES),
    ])
      .then(async ([nextLedgerText, nextRun, nextSynthesis, nextTables, nextFigures, manifestValue, sourceManifestValue, computationsValue, analyticalAuditValue, claimsAuditValue, finalizationText]) => {
        if (cancelled || sequence !== localLoadSequence.current) return;
        const checkedLedger = validateLedger(parseJsonFile("findings.json", nextLedgerText as string));
        const nextLedgerFingerprint = sha256Hex(nextLedgerText as string);
        const checkedRun = validateRun(nextRun);
        const checkedSynthesis = validateSynthesis(nextSynthesis);
        const checkedSourceManifest = validateSourceManifest(sourceManifestValue);
        const checkedComputations = validateReviewComputations(computationsValue);
        const checkedTables = validateExhibitManifest(nextTables, "tables", checkedLedger.review_id) as ExhibitManifest | null;
        const checkedFigures = validateExhibitManifest(nextFigures, "figures", checkedLedger.review_id) as ExhibitManifest | null;
        validateLedgerAnchors(checkedLedger, checkedSourceManifest);
        validateReviewComputationLinks(checkedLedger, checkedComputations, checkedSourceManifest, {
          analyticalAudit: analyticalAuditValue,
          claimsAudit: claimsAuditValue,
        }, checkedRun.mode || null);
        if (checkedLedger.review_id !== checkedRun.review_id) throw new Error("Bundled review IDs do not match");
        if (checkedLedger.schema_version !== checkedRun.schema_version) throw new Error("Bundled review schema versions do not match");
        if (checkedSynthesis && checkedSynthesis.review_id !== checkedLedger.review_id) throw new Error("Bundled synthesis ID does not match findings.json");
        if (checkedSourceManifest && checkedSourceManifest.review_id !== checkedLedger.review_id) throw new Error("Bundled source manifest ID does not match findings.json");
        validatePackageLinks(checkedLedger, checkedRun, checkedSynthesis);
        const hasManifest = manifestValue !== null;
        const checkedManifest = hasManifest ? validateReviewDocumentManifest(manifestValue) : null;
        const definitions = (checkedManifest
          ? checkedManifest.documents
          : discoverReviewDocuments(STANDARD_REVIEW_DOCUMENT_PATHS))
          .filter((document) => document.group !== "audit");
        if (checkedManifest && checkedManifest.review_id !== checkedLedger.review_id) {
          throw new Error("Bundled review manifest ID does not match findings.json");
        }
        const manuscriptSources = checkedSourceManifest?.sources?.filter((source) => source.role === "manuscript") || [];
        // A package may declare several manuscript-role sources (for example a
        // PDF plus its LaTeX source). Read the extracted text surface when one
        // exists; otherwise fall back to a directly readable text source.
        const manuscriptSource = manuscriptSources.find((source) => source.extraction?.path)
          || manuscriptSources.find((source) => /^text\/|markdown|tex$/i.test(source.media_type || ""))
          || manuscriptSources[0];
        const manuscriptPath = manuscriptSource?.extraction?.path
          || (/^text\/|markdown|tex$/i.test(manuscriptSource?.media_type || "") ? manuscriptSource?.path : undefined);
        const nextManuscript = manuscriptPath
          ? await requiredText(`${entry.base_path}/${normalizePackagePath(manuscriptPath)}`)
          : "";
        const contents = await Promise.all(definitions.map((document) => (
          checkedManifest
            ? requiredText(`${entry.base_path}/${document.path}`)
            : optionalText(`${entry.base_path}/${document.path}`)
        )));
        const nextDocuments = definitions
          .map((document, index) => ({ ...document, content: contents[index] }))
          .filter((document) => document.content.trim());
        let nextFinalizationTrust: FinalizationTrust = { ...NO_FINALIZATION_RECEIPT };
        if (finalizationText.trim()) {
          try {
            const receiptValue = parseJsonFile("finalization.json", finalizationText);
            const receipt = validateFinalizationReceipt(receiptValue);
            const artifactPaths = Object.keys(receipt.artifacts);
            if (artifactPaths.length > MAX_LOCAL_PACKAGE_FILES) throw new Error("The finalized artifact inventory exceeds the browser verification limit.");
            const artifactBytes = new Map<string, Uint8Array>();
            let totalArtifactBytes = 0;
            for (const path of artifactPaths) {
              if (cancelled || sequence !== localLoadSequence.current) return;
              const bytes = await requiredBytes(`${entry.base_path}/${path}`);
              totalArtifactBytes += bytes.byteLength;
              if (totalArtifactBytes > MAX_LOCAL_PACKAGE_BYTES) throw new Error("The finalized artifact inventory exceeds the browser verification limit.");
              artifactBytes.set(path, bytes);
            }
            nextFinalizationTrust = await verifyReviewFinalization({
              receipt: receiptValue,
              reviewId: checkedLedger.review_id,
              reviewContractVersion: checkedRun.schema_version,
              reviewMode: checkedRun.mode,
              hasPdfSource: Boolean(checkedSourceManifest?.sources?.some((source) => source.media_type === "application/pdf")),
              artifactBytes,
              requireExactInventory: false,
            });
          } catch (error) {
            nextFinalizationTrust = {
              status: "unverified",
              receipt_present: true,
              receipt_version: null,
              detail: error instanceof Error ? error.message : "The bundled finalization receipt could not be verified.",
            };
          }
        }
        if (cancelled || sequence !== localLoadSequence.current) return;
        setLedger(checkedLedger);
        setLedgerFingerprint(nextLedgerFingerprint);
        setRun(checkedRun);
        setSynthesis(checkedSynthesis);
        setManuscript(nextManuscript);
        setDocuments(nextDocuments);
        const urlState = parseReviewUrlState(window.location.search);
        const linkedFinding = checkedLedger.findings.find((finding) => finding.id === urlState.finding);
        const linkedDocument = nextDocuments.find((document) => document.id === urlState.document);
        setReportView(urlState.view === "document" && linkedDocument ? linkedDocument.id : "none");
        setDetailMode(urlState.view === "comment" && linkedFinding ? "comment" : urlState.view === "plan" ? "plan" : "overview");
        setSelectedId(linkedFinding?.id || checkedLedger.findings[0]?.id || "");
        const restoredActions = restoreBrowserReviewActions(window.localStorage, {
          review_id: checkedLedger.review_id,
          review_fingerprint: nextLedgerFingerprint,
          finding_ids: checkedLedger.findings.map((finding) => finding.id),
        });
        localStateRef.current = restoredActions.entries;
        setLocalState(restoredActions.entries);
        replaceNoteDrafts({});
        persistenceContextRef.current = {
          reviewId: checkedLedger.review_id,
          reviewFingerprint: nextLedgerFingerprint,
          sourceManuscripts: privacySafeSourceManuscripts(checkedRun.assessment_boundary?.sources || []),
        };
        setPersistenceState("saved");
        setHandoffWarning(restoredActions.warning);
        setQuery("");
        setSeverity((["critical", "major", "minor", "info"] as string[]).includes(urlState.severity) ? urlState.severity as Severity : "all");
        setDecisionRole((["potentially_dispositive", "posture_material", "revision_value", "polish"] as string[]).includes(urlState.role) ? urlState.role as DecisionRole : "all");
        setStatus(normalizeWorkflowStatusFilter(urlState.status));
        setChannel((["substance", "writing"] as string[]).includes(urlState.channel) ? urlState.channel as "substance" | "writing" : "all");
        setDimension(checkedLedger.findings.some((finding) => finding.dimension === urlState.dimension) ? urlState.dimension : "all");
        setReviewedFilter((["reviewed", "unreviewed"] as string[]).includes(urlState.reviewed) ? urlState.reviewed as "reviewed" | "unreviewed" : "all");
        setPersonalPriorityFilter((["P0", "P1", "P2", "unassigned"] as string[]).includes(urlState.my_priority) ? urlState.my_priority as "P0" | "P1" | "P2" | "unassigned" : "all");
        setEvidenceIndex(linkedFinding ? Math.min(urlState.evidence, linkedFinding.evidence.length - 1) : 0);
        setAssetPathIndex(0);
        try {
          const params = new URLSearchParams(window.location.search);
          const savedOrder = window.localStorage.getItem(`review-desk:queue-order:${checkedLedger.review_id}`);
          setQueueOrder(params.has("order") ? urlState.order : ["priority", "importance", "paper"].includes(savedOrder || "") ? savedOrder as QueueOrder : "importance");
        } catch { setQueueOrder("importance"); }
        setActionNotice("");
        setUndoStatusChange(null);
        setPendingDocumentAnchor(null);
        setMobilePane(["comment", "document", "plan"].includes(urlState.view) ? "comment" : "queue");
        setExhibitAssets(manifestAssets(checkedTables, checkedFigures, (path) => `${entry.base_path}/${path}`));
        setSourceAnchors(Object.fromEntries((checkedSourceManifest?.anchors || []).map((anchor) => [anchor.id, anchor])));
        setComputationsById(indexReviewComputations(checkedComputations));
        setFinalizationTrust(nextFinalizationTrust);
        loadedReviewSlug.current = entry.slug;
        setIsBundleLoading(false);
        setLoadError("");
        const url = new URL(window.location.href);
        url.searchParams.set("review", entry.slug);
        window.history.replaceState({}, "", url);
        setAnnouncement(restoredActions.rereview_required_finding_ids.length
          ? `Loaded ${entry.title}. Notes and personal priorities were carried forward for ${restoredActions.rereview_required_finding_ids.length} surviving comments, which must now be reviewed again.`
          : `Loaded ${entry.title} with ${checkedLedger.findings.length} comments.`);
      })
      .catch((error: unknown) => {
        if (cancelled || sequence !== localLoadSequence.current) return;
        setIsBundleLoading(false);
        const previous = loadedReviewSlug.current;
        if (previous && previous !== entry.slug) {
          setReviewSlug(previous);
          const url = new URL(window.location.href);
          url.searchParams.set("review", previous);
          window.history.replaceState({}, "", url);
          setLoadError(`${reviewLoadMessage(error)} The previous review was restored.`);
        } else {
          setLoadError(reviewLoadMessage(error));
        }
      });
    return () => { cancelled = true; };
  }, [flushBrowserActions, ledger, registry, replaceNoteDrafts, reviewSlug, run]);

  useEffect(() => {
    if (!ledger?.review_id || !ledgerFingerprint || persistenceMode !== "local") return;
    const timeout = window.setTimeout(() => flushBrowserActions(), 300);
    return () => window.clearTimeout(timeout);
  }, [flushBrowserActions, ledger, ledgerFingerprint, localState, noteDrafts, persistenceMode]);

  useEffect(() => {
    const onPageHide = () => { flushBrowserActions(); };
    const onVisibilityChange = () => {
      if (document.visibilityState === "hidden") flushBrowserActions();
    };
    window.addEventListener("pagehide", onPageHide);
    document.addEventListener("visibilitychange", onVisibilityChange);
    return () => {
      window.removeEventListener("pagehide", onPageHide);
      document.removeEventListener("visibilitychange", onVisibilityChange);
    };
  }, [flushBrowserActions]);

  useEffect(() => {
    if (!loadedReviewSlug.current || !ledger || applyingHistoryState.current) return;
    const url = writeReviewUrlState(new URL(window.location.href), {
      view: reportView !== "none" ? "document" : detailMode,
      finding: selectedId || null,
      document: reportView !== "none" ? reportView : null,
      evidence: evidenceIndex,
      order: queueOrder,
      severity,
      role: decisionRole,
      status,
      channel,
      dimension,
      reviewed: reviewedFilter,
      my_priority: personalPriorityFilter,
    });
    window.history.replaceState({ reviewDesk: true }, "", url);
  }, [channel, decisionRole, detailMode, dimension, evidenceIndex, ledger, personalPriorityFilter, queueOrder, reportView, reviewedFilter, selectedId, severity, status]);

  useEffect(() => () => {
    for (const url of localObjectUrls.current) URL.revokeObjectURL(url);
  }, []);

  const findings = useMemo(
    () =>
      (ledger?.findings || [])
        .filter((finding) => !["dismissed", "resolved"].includes(finding.status)),
    [ledger],
  );

  const deferredQuery = useDeferredValue(query.trim().toLowerCase());
  const searchIndex = useMemo(() => new Map(findings.map((finding) => {
    const entry = localState[finding.id] || defaultEntry(finding.id);
    return [finding.id, [
      finding.id, finding.title, finding.decision_role, finding.repairability, finding.dimension,
      channelLabel(finding), finding.issue, finding.why_it_matters, finding.reader_effect,
      finding.fix.what, finding.fix.how, finding.fix.resolved_when, finding.counterargument.author_reply,
      finding.counterargument.search_scope, finding.counterargument.notes, entry.response_note,
      ...entry.changed_locations,
      ...finding.evidence.flatMap((item, index) => [item.type, item.source, item.content, item.scope_checked, locator(finding, index)]),
    ].filter(Boolean).join(" ").toLowerCase()] as const;
  })), [findings, localState]);

  const filtered = useMemo(() => {
    const needle = deferredQuery;
    const matching = findings.filter((finding) => {
      const entry = localState[finding.id] || defaultEntry(finding.id);
      const haystack = searchIndex.get(finding.id) || "";
      return (
        (severity === "all" || finding.severity === severity) &&
        (decisionRole === "all" || finding.decision_role === decisionRole) &&
        (status === "all" || workflowDecision(entry.disposition) === status) &&
        (channel === "all" || (finding.report_channel || "substance") === channel) &&
        (dimension === "all" || finding.dimension === dimension) &&
        (reviewedFilter === "all" || entry.reviewed === (reviewedFilter === "reviewed")) &&
        (personalPriorityFilter === "all" || (entry.user_priority || "unassigned") === personalPriorityFilter) &&
        (!needle || haystack.includes(needle))
      );
    });
    return sortReviewFindings(matching, queueOrder);
  }, [channel, decisionRole, deferredQuery, dimension, findings, localState, personalPriorityFilter, queueOrder, reviewedFilter, searchIndex, severity, status]);

  const selected = filtered.find((finding) => finding.id === selectedId) || filtered[0] || findings[0];
  const selectedEntry = selected ? localState[selected.id] || defaultEntry(selected.id) : defaultEntry("EMPTY-00");
  const selectedNote = selected ? noteDrafts[selected.id] ?? selectedEntry.response_note : "";
  const selectedNoteIsDraft = Boolean(selected && Object.prototype.hasOwnProperty.call(noteDrafts, selected.id)
    && noteDrafts[selected.id] !== selectedEntry.response_note);
  const selectedNoteState = selectedNoteIsDraft
    ? persistenceMode === "local" && persistenceState === "pending" ? "Saving…" : "Unsaved"
    : selectedEntry.response_note.trim()
      ? persistenceMode === "session"
        ? "Saved in this tab"
        : persistenceState === "saved" ? "Saved" : persistenceState === "error" ? "Not saved in browser" : "Saving…"
      : "Required for handoff";
  const selectedIsSetAside = SET_ASIDE_DISPOSITIONS.has(selectedEntry.disposition);
  const selectedIsPersistentSetAside = ["not_relevant", "not_addressable"].includes(selectedEntry.disposition);
  const selectedActionEvents = selectedEntry.events
    .filter((event, index, events) => (
      event.event_id !== "00000000-0000-4000-8000-000000000000"
      && !(index === 0 && events.length > 1 && event.type === "disposition_changed"
        && event.disposition === "open" && event.origin === "local" && event.at === events[1].at)
    ))
    .slice()
    .reverse();
  const reviewedCount = findings.filter((finding) => localState[finding.id]?.reviewed).length;
  const setAsideCount = findings.filter((finding) => SET_ASIDE_DISPOSITIONS.has(
    localState[finding.id]?.disposition || "open",
  )).length;
  const revisionTasks = useMemo(() => buildRevisionTasks({
    source_review_id: ledger?.review_id || "review",
    source_review_fingerprint: ledger ? ledgerFingerprint : "",
    findings,
    entries: localState,
    draft_notes: noteDrafts,
  }), [findings, ledger, ledgerFingerprint, localState, noteDrafts]);
  const revisionGaps = useMemo(() => revisionDecisionGaps(revisionTasks), [revisionTasks]);
  const handoffReady = revisionTasks.handoff_ready;
  const revisionGroups = useMemo(() => (["P0", "P1", "P2", null] as const).map((priority) => ({
    priority,
    tasks: revisionTasks.tasks.filter((task) => task.user_priority === priority),
  })), [revisionTasks]);
  const revisionEvidenceByFinding = useMemo(() => new Map(findings.map((finding) => [
    finding.id,
    finding.evidence[displayEvidenceIndex(finding)] || finding.evidence[0],
  ])), [findings]);
  const dimensions = useMemo(() => Array.from(new Set(findings.map((finding) => finding.dimension))).sort(), [findings]);
  const substanceCount = findings.filter((finding) => finding.report_channel !== "writing").length;
  const editingCount = findings.filter((finding) => finding.report_channel === "writing").length;
  const filteredPosition = selected ? filtered.findIndex((finding) => finding.id === selected.id) : -1;
  const activeFilters = [severity !== "all", decisionRole !== "all", status !== "all", channel !== "all", dimension !== "all", reviewedFilter !== "all", personalPriorityFilter !== "all", Boolean(query.trim())].filter(Boolean).length;
  const isReviewLoading = isBundleLoading || isLocalLoading;

  const pushViewState = useCallback((next: Partial<ReturnType<typeof parseReviewUrlState>>, replace = false) => {
    if (!loadedReviewSlug.current) return;
    const current = parseReviewUrlState(window.location.search);
    const url = writeReviewUrlState(new URL(window.location.href), { ...current, ...next });
    window.history[replace ? "replaceState" : "pushState"]({ reviewDesk: true }, "", url);
  }, []);

  const selectAndFocus = useCallback((id: string, replaceHistory = false) => {
    const finding = findings.find((candidate) => candidate.id === id);
    setDetailMode("comment");
    setReportView("none");
    setSelectedId(id);
    setEvidenceIndex(finding ? displayEvidenceIndex(finding) : 0);
    setAssetPathIndex(0);
    setExpandedEvidence(false);
    pushViewState({ view: "comment", finding: id, document: null, evidence: finding ? displayEvidenceIndex(finding) : 0 }, replaceHistory);
    requestAnimationFrame(() => findingRefs.current.get(id)?.focus());
  }, [findings, pushViewState]);

  /** Reveal an exact canonical finding from reports/permalinks, clearing filters that could hide it. */
  const openFinding = useCallback((id: string, message?: string, replaceHistory = false, clearIncompatibleFilters = true) => {
    const finding = findings.find((candidate) => candidate.id === id);
    if (!finding) {
      setAnnouncement("This linked comment is no longer active in this review.");
      return false;
    }
    if (clearIncompatibleFilters) {
      setQuery("");
      setSeverity("all");
      setDecisionRole("all");
      setStatus("all");
      setChannel("all");
      setDimension("all");
      setReviewedFilter("all");
      setPersonalPriorityFilter("all");
    }
    setReportView("none");
    setDetailMode("comment");
    setSelectedId(id);
    const displayIndex = displayEvidenceIndex(finding);
    setEvidenceIndex(displayIndex);
    setAssetPathIndex(0);
    setExpandedEvidence(false);
    setMobilePane("comment");
    pushViewState({
      view: "comment", finding: id, document: null, evidence: displayIndex,
      ...(clearIncompatibleFilters ? { severity: "all", role: "all", status: "all", channel: "all", dimension: "all", reviewed: "all", my_priority: "all" } : {}),
    }, replaceHistory);
    setAnnouncement(message || `Opened ${commentLabel(findings, id)}`);
    requestAnimationFrame(() => commentHeading.current?.focus());
    return true;
  }, [findings, pushViewState]);

  const updateLocal = useCallback((id: string, patch: Partial<Pick<LocalEntry, "disposition" | "response_note" | "changed_locations" | "user_priority" | "reviewed">>) => {
    const current = localStateRef.current;
    const existing = current[id];
    const nextDisposition = patch.disposition ?? existing?.disposition ?? "open";
    // Let the action contract create a fresh, finding-specific initial event.
    // Reusing the display-only fallback entry would give multiple findings the
    // same placeholder UUID and make a multi-finding export invalid.
    const nextEntry = updateReviewAction(existing, id, { ...patch, disposition: nextDisposition });
    const nextState = { ...current, [id]: nextEntry };
    localStateRef.current = nextState;
    setLocalState(nextState);
    if (persistenceModeRef.current === "local") setPersistenceState("pending");
  }, []);

  const commitNote = useCallback((id: string) => {
    const draft = noteDraftsRef.current[id];
    if (draft === undefined) return;
    const current = localStateRef.current[id] || defaultEntry(id);
    if (draft !== current.response_note) updateLocal(id, { response_note: draft });
    if (!(id in noteDraftsRef.current)) return;
    const next = { ...noteDraftsRef.current };
    delete next[id];
    replaceNoteDrafts(next);
  }, [replaceNoteDrafts, updateLocal]);

  const markFindingStatus = useCallback((id: string, nextStatus: LocalStatus) => {
    const entry = localStateRef.current[id] || defaultEntry(id);
    const label = commentLabel(findings, id);
    if (entry.disposition === nextStatus) {
      showActionNotice(`${label} is already ${dispositionDetailLabel(nextStatus)}.`);
      return;
    }
    if (status !== "all" && status !== workflowDecision(nextStatus)) focusAfterFilter.current = true;
    const marksReviewed = nextStatus !== "open";
    const nextReviewed = marksReviewed ? true : entry.reviewed;
    if (marksReviewed && reviewedFilter === "unreviewed") focusAfterFilter.current = true;
    updateLocal(id, { disposition: nextStatus, reviewed: nextReviewed });
    if (readyDecisionMenu.current) readyDecisionMenu.current.open = false;
    if (setAsideDecisionMenu.current) setAsideDecisionMenu.current.open = false;
    const stateLabel = dispositionDetailLabel(nextStatus);
    setAnnouncement(`${label} marked ${stateLabel}`);
    showActionNotice(`${label}: ${stateLabel}. The next review still checks this decision.`, {
      findingId: id,
      previous: entry.disposition,
      next: nextStatus,
      previousReviewed: entry.reviewed,
      nextReviewed,
    });
  }, [findings, reviewedFilter, showActionNotice, status, updateLocal]);

  const setPersonalPriority = useCallback((id: string, userPriority: LocalEntry["user_priority"]) => {
    const entry = localStateRef.current[id] || defaultEntry(id);
    if (entry.user_priority === userPriority) return;
    if (personalPriorityFilter !== "all" && (userPriority || "unassigned") !== personalPriorityFilter) focusAfterFilter.current = true;
    updateLocal(id, { user_priority: userPriority });
    const label = userPriority || "unassigned";
    const comment = commentLabel(findings, id);
    setAnnouncement(`${comment} personal priority set to ${label}`);
    showActionNotice(`${comment} personal priority is ${label}. This changes only your work plan; reviewer severity and priority are unchanged.`);
  }, [findings, personalPriorityFilter, showActionNotice, updateLocal]);

  const toggleReviewed = useCallback((id: string) => {
    const entry = localStateRef.current[id] || defaultEntry(id);
    const label = commentLabel(findings, id);
    if (["not_relevant", "not_addressable"].includes(entry.disposition)) {
      showActionNotice(`${label} is already reviewed by this set-aside decision. Reopen it before reconsidering the comment.`);
      return;
    }
    const reviewed = !entry.reviewed;
    if (reviewedFilter !== "all" && reviewed !== (reviewedFilter === "reviewed")) focusAfterFilter.current = true;
    updateLocal(id, { reviewed });
    setAnnouncement(`${label} marked ${entry.reviewed ? "not reviewed" : "reviewed"}`);
    showActionNotice(`${label} is ${entry.reviewed ? "not yet reviewed" : "reviewed"}.`);
  }, [findings, reviewedFilter, showActionNotice, updateLocal]);

  const undoLastStatusChange = useCallback(() => {
    if (!undoStatusChange) return;
    const current = localStateRef.current[undoStatusChange.findingId] || defaultEntry(undoStatusChange.findingId);
    if (current.disposition !== undoStatusChange.next) {
      showActionNotice("That status has changed again, so the earlier change cannot be undone safely.");
      return;
    }
    const currentState = localStateRef.current;
    const reversed = updateReviewAction(
      current,
      undoStatusChange.findingId,
      { disposition: undoStatusChange.previous, reviewed: undoStatusChange.previousReviewed },
      new Date().toISOString(),
      { type: "reversed" },
    );
    const nextState = { ...currentState, [undoStatusChange.findingId]: reversed };
    localStateRef.current = nextState;
    setLocalState(nextState);
    if (persistenceModeRef.current === "local") setPersistenceState("pending");
    const label = commentLabel(findings, undoStatusChange.findingId);
    const restoredLabel = dispositionDetailLabel(undoStatusChange.previous);
    setAnnouncement(`${label} restored to ${restoredLabel}`);
    showActionNotice(`${label} returned to ${restoredLabel}. The reversal was added to its action history.`);
  }, [findings, showActionNotice, undoStatusChange]);

  const moveSelection = useCallback(
    (delta: number) => {
      if (!filtered.length) return;
      const index = Math.max(0, filtered.findIndex((finding) => finding.id === selected?.id));
      const next = filtered[(index + delta + filtered.length) % filtered.length];
      selectAndFocus(next.id, true);
      setAnnouncement(`Selected ${commentLabel(findings, next.id)}`);
    },
    [filtered, findings, selectAndFocus, selected?.id],
  );

  const moveDetailSelection = useCallback((delta: number) => {
    if (!filtered.length) return;
    const index = Math.max(0, filtered.findIndex((finding) => finding.id === selected?.id));
    const next = filtered[(index + delta + filtered.length) % filtered.length];
    setDetailMode("comment");
    setReportView("none");
    setSelectedId(next.id);
    setEvidenceIndex(displayEvidenceIndex(next));
    setAssetPathIndex(0);
    setExpandedEvidence(false);
    setAnnouncement(`Selected ${commentLabel(findings, next.id)}`);
    requestAnimationFrame(() => commentHeading.current?.focus());
  }, [filtered, findings, selected?.id]);

  const moveToNextOpen = useCallback(() => {
    if (!filtered.length) return;
    const start = Math.max(0, filtered.findIndex((finding) => finding.id === selected?.id));
    const next = [...filtered.slice(start + 1), ...filtered.slice(0, start + 1)]
      .find((finding) => (localState[finding.id]?.disposition || "open") === "open");
    if (!next) {
      setAnnouncement("No other open comment in the current filter");
      return;
    }
    setSelectedId(next.id);
    setEvidenceIndex(displayEvidenceIndex(next));
    setAssetPathIndex(0);
    setExpandedEvidence(false);
    setAnnouncement(`Next open ${commentLabel(findings, next.id)}`);
    requestAnimationFrame(() => commentHeading.current?.focus());
  }, [filtered, findings, localState, selected?.id]);

  const moveToNextUnreviewed = useCallback(() => {
    if (!filtered.length) return;
    const start = Math.max(0, filtered.findIndex((finding) => finding.id === selected?.id));
    const next = [...filtered.slice(start + 1), ...filtered.slice(0, start + 1)]
      .find((finding) => !localState[finding.id]?.reviewed);
    if (!next) {
      setAnnouncement("No other unreviewed comment in the current filter");
      return;
    }
    selectAndFocus(next.id);
    setAnnouncement(`Next unreviewed ${commentLabel(findings, next.id)}`);
  }, [filtered, findings, localState, selectAndFocus, selected?.id]);

  const clearFilters = useCallback(() => {
    setQuery("");
    setSeverity("all");
    setDecisionRole("all");
    setStatus("all");
    setChannel("all");
    setDimension("all");
    setReviewedFilter("all");
    setPersonalPriorityFilter("all");
    setMobilePane("queue");
    setAnnouncement(`Filters cleared. ${findings.length} comments shown.`);
    requestAnimationFrame(() => searchInput.current?.focus());
  }, [findings.length]);

  const openPrincipalConcern = useCallback((concern: PrincipalConcern) => {
    const findingId = concern.finding_ids.find((id) => findings.some((finding) => finding.id === id));
    if (!findingId) {
      setAnnouncement("This principal concern has no active linked comment in the current review.");
      return;
    }
    openFinding(findingId, `Opened principal concern: ${concern.title}`);
  }, [findings, openFinding]);

  const openMobilePane = useCallback((pane: "queue" | "comment" | "evidence") => {
    setMobilePane(pane);
    requestAnimationFrame(() => {
      if (pane === "queue") (selected && findingRefs.current.get(selected.id) || searchInput.current)?.focus();
      else if (pane === "comment") commentHeading.current?.focus();
      else evidenceHeading.current?.focus();
    });
  }, [selected]);

  const openOverview = useCallback(() => {
    setReportView("none");
    setDetailMode("overview");
    setMobilePane("comment");
    setAnnouncement("Opened review overview");
    pushViewState({ view: "overview", finding: null, document: null, evidence: 0 });
    requestAnimationFrame(() => overviewHeading.current?.focus());
  }, [pushViewState]);

  const openRevisionPlan = useCallback(() => {
    setReportView("none");
    setDetailMode("plan");
    setMobilePane("comment");
    setAnnouncement(`Opened ${handoffReady ? "my revision plan" : "draft revision plan"}`);
    pushViewState({ view: "plan", finding: null, document: null, evidence: 0 });
    requestAnimationFrame(() => revisionPlanHeading.current?.focus());
  }, [handoffReady, pushViewState]);

  useEffect(() => {
    const closeDecisionMenus = (event: PointerEvent) => {
      const target = event.target instanceof Node ? event.target : null;
      if (!target) return;
      if (readyDecisionMenu.current?.contains(target) || setAsideDecisionMenu.current?.contains(target)) return;
      if (readyDecisionMenu.current) readyDecisionMenu.current.open = false;
      if (setAsideDecisionMenu.current) setAsideDecisionMenu.current.open = false;
    };
    document.addEventListener("pointerdown", closeDecisionMenus);
    return () => document.removeEventListener("pointerdown", closeDecisionMenus);
  }, []);

  useEffect(() => {
    const onPopState = () => {
      const requestedReview = new URLSearchParams(window.location.search).get("review");
      if (registry && requestedReview && registry.reviews.some((entry) => entry.slug === requestedReview) && requestedReview !== reviewSlug) {
        setReviewSlug(requestedReview);
        return;
      }
      const state = parseReviewUrlState(window.location.search);
      applyingHistoryState.current = true;
      setQueueOrder(state.order);
      setSeverity((["critical", "major", "minor", "info"] as string[]).includes(state.severity) ? state.severity as Severity : "all");
      setDecisionRole((["potentially_dispositive", "posture_material", "revision_value", "polish"] as string[]).includes(state.role) ? state.role as DecisionRole : "all");
      setStatus(normalizeWorkflowStatusFilter(state.status));
      setChannel((["substance", "writing"] as string[]).includes(state.channel) ? state.channel as "substance" | "writing" : "all");
      setDimension(findings.some((finding) => finding.dimension === state.dimension) ? state.dimension : "all");
      setReviewedFilter((["reviewed", "unreviewed"] as string[]).includes(state.reviewed) ? state.reviewed as "reviewed" | "unreviewed" : "all");
      setPersonalPriorityFilter((["P0", "P1", "P2", "unassigned"] as string[]).includes(state.my_priority) ? state.my_priority as "P0" | "P1" | "P2" | "unassigned" : "all");
      if (state.view === "comment" && state.finding && findings.some((finding) => finding.id === state.finding)) {
        const target = findings.find((finding) => finding.id === state.finding)!;
        const filtersIncludeTarget = (state.severity === "all" || target.severity === state.severity)
          && (state.role === "all" || target.decision_role === state.role)
          && (normalizeWorkflowStatusFilter(state.status) === "all" || workflowDecision(localStateRef.current[target.id]?.disposition || "open") === normalizeWorkflowStatusFilter(state.status))
          && (state.channel === "all" || (target.report_channel || "substance") === state.channel)
          && (state.dimension === "all" || target.dimension === state.dimension)
          && (state.reviewed === "all" || Boolean(localStateRef.current[target.id]?.reviewed) === (state.reviewed === "reviewed"))
          && (state.my_priority === "all" || (localStateRef.current[target.id]?.user_priority || "unassigned") === state.my_priority);
        openFinding(state.finding, `Opened ${state.finding} from browser history`, true, !filtersIncludeTarget);
        setEvidenceIndex(Math.min(state.evidence, Math.max(0, target.evidence.length - 1)));
      } else if (state.view === "document" && state.document && documents.some((document) => document.id === state.document)) {
        setReportView(state.document);
        setDetailMode("overview");
        setMobilePane("comment");
        setAnnouncement(`Opened ${documents.find((document) => document.id === state.document)!.title} from browser history`);
      } else if (state.view === "plan") {
        setReportView("none");
        setDetailMode("plan");
        setMobilePane("comment");
        setAnnouncement("Opened my revision plan from browser history");
        requestAnimationFrame(() => revisionPlanHeading.current?.focus());
      } else {
        setReportView("none");
        setDetailMode("overview");
        setMobilePane("comment");
        setAnnouncement("Opened review overview from browser history");
        requestAnimationFrame(() => overviewHeading.current?.focus());
      }
      window.setTimeout(() => { applyingHistoryState.current = false; }, 0);
    };
    window.addEventListener("popstate", onPopState);
    return () => window.removeEventListener("popstate", onPopState);
  }, [documents, findings, openFinding, registry, reviewSlug]);

  useEffect(() => {
    // The comment pane clips overflow; its inner scroll container is what moves.
    commentScroll.current?.scrollTo({ top: 0 });
    commentPane.current?.scrollTo({ top: 0 });
    documentPane.current?.scrollTo({ top: 0 });
    (documentPane.current?.querySelector(".evidence-sheet") as HTMLElement | null)?.scrollTo({ top: 0 });
  }, [selected?.id]);

  useEffect(() => {
    if (reportView === "none") return;
    reportReader.current?.scrollTo({ top: 0 });
    requestAnimationFrame(() => reportBackButton.current?.focus());
  }, [reportView]);

  useEffect(() => {
    const onKey = (event: globalThis.KeyboardEvent) => {
      if (event.isComposing || event.metaKey || event.ctrlKey || event.altKey) return;
      const target = event.target instanceof HTMLElement ? event.target : null;
      const interactive = target?.closest("input, textarea, select, button, a, summary, [contenteditable='true'], [role='dialog']");
      if (event.key === "Escape" && topMenu.current?.open) {
        event.preventDefault();
        topMenu.current.open = false;
        (topMenu.current.querySelector(":scope > summary") as HTMLElement | null)?.focus();
        return;
      }
      if (event.key === "Escape" && (readyDecisionMenu.current?.open || setAsideDecisionMenu.current?.open)) {
        event.preventDefault();
        const activeMenu = readyDecisionMenu.current?.open ? readyDecisionMenu.current : setAsideDecisionMenu.current;
        if (readyDecisionMenu.current) readyDecisionMenu.current.open = false;
        if (setAsideDecisionMenu.current) setAsideDecisionMenu.current.open = false;
        (activeMenu?.querySelector(":scope > summary") as HTMLElement | null)?.focus();
        return;
      }
      if (event.key === "Escape" && mobilePane === "evidence") {
        event.preventDefault();
        openMobilePane("comment");
        return;
      }
      if (event.key === "Escape" && reportView !== "none") {
        event.preventDefault();
        openOverview();
        return;
      }
      if (event.key === "Escape" && detailMode === "plan") {
        event.preventDefault();
        openOverview();
        return;
      }
      if (interactive) return;
      if (event.key.toLowerCase() === "o") {
        event.preventDefault();
        openOverview();
        return;
      }
      if (reportView === "none" && detailMode === "overview" && ["j", "k"].includes(event.key.toLowerCase())) {
        const first = filtered[0] || findings[0];
        if (first) {
          event.preventDefault();
          selectAndFocus(first.id);
          setMobilePane("comment");
          setAnnouncement(`Started with ${commentLabel(findings, first.id)}`);
        }
        return;
      }
      if (reportView !== "none" || !filtered.length || !selected || !filtered.some((finding) => finding.id === selected.id)) return;
      if (event.key === "/") {
        event.preventDefault();
        searchInput.current?.focus();
      } else if (event.key.toLowerCase() === "j") {
        event.preventDefault();
        moveSelection(1);
      } else if (event.key.toLowerCase() === "k") {
        event.preventDefault();
        moveSelection(-1);
      } else if (event.key.toLowerCase() === "r" && selected) {
        if (event.repeat) return;
        event.preventDefault();
        if (setAsideDecisionMenu.current) setAsideDecisionMenu.current.open = false;
        if (readyDecisionMenu.current) {
          readyDecisionMenu.current.open = true;
          (readyDecisionMenu.current.querySelector(":scope > summary") as HTMLElement | null)?.focus();
        }
      } else if (event.key.toLowerCase() === "s" && selected) {
        if (event.repeat) return;
        event.preventDefault();
        if (readyDecisionMenu.current) readyDecisionMenu.current.open = false;
        if (setAsideDecisionMenu.current) {
          setAsideDecisionMenu.current.open = true;
          (setAsideDecisionMenu.current.querySelector(":scope > summary") as HTMLElement | null)?.focus();
        }
      } else if (event.key.toLowerCase() === "n") {
        event.preventDefault();
        noteInput.current?.focus();
        setAnnouncement("Author note focused");
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [detailMode, filtered, findings, markFindingStatus, mobilePane, moveSelection, openMobilePane, openOverview, reportView, selectAndFocus, selected]);

  useEffect(() => {
    if (filtered.length && !filtered.some((finding) => finding.id === selectedId)) {
      const next = filtered[0];
      const shouldFocus = focusAfterFilter.current;
      focusAfterFilter.current = false;
      const frame = requestAnimationFrame(() => {
        setSelectedId(next.id);
        setEvidenceIndex(displayEvidenceIndex(next));
        setAssetPathIndex(0);
        if (shouldFocus) findingRefs.current.get(next.id)?.focus();
      });
      return () => cancelAnimationFrame(frame);
    } else if (!filtered.length && findings.length && focusAfterFilter.current) {
      focusAfterFilter.current = false;
      const frame = requestAnimationFrame(() => noResultsRef.current?.focus());
      return () => cancelAnimationFrame(frame);
    }
  }, [filtered, findings.length, selectedId]);

  async function loadFiles(event: ChangeEvent<HTMLInputElement>) {
    const files = Array.from(event.target.files || []);
    await loadSelectedFiles(files);
    event.target.value = "";
  }

  async function loadSelectedFiles(files: File[]) {
    if (!files.length) return;
    flushBrowserActions();
    const sequence = ++localLoadSequence.current;
    const stagedObjectUrls: string[] = [];
    setIsLocalLoading(true);
    setLoadError("");
    try {
      if (files.length > MAX_SELECTED_FILE_COUNT) {
        throw new Error(`The selected folder contains more than ${MAX_SELECTED_FILE_COUNT.toLocaleString()} files. Choose the review package itself or a smaller parent folder.`);
      }
      const paths = files.map(normalizedFilePath);
      if (new Set(paths.map((path) => path.toLowerCase())).size !== paths.length) {
        throw new Error("Duplicate relative file paths were selected");
      }
      const reviewRoot = inferReviewPackageRoot(paths);
      const relativePath = (file: File) => relativeToReviewRoot(normalizedFilePath(file), reviewRoot);
      const canonicalFile = (name: string, required = false, fallbackNames: string[] = []) => {
        const selectedPath = selectReviewPackageFilePath({
          paths,
          reviewRoot,
          canonicalPath: name,
          fallbackPaths: fallbackNames,
        });
        if (required && !selectedPath) throw new Error(`The inferred review package is missing ${name}.`);
        return selectedPath
          ? files.find((file) => normalizedFilePath(file) === selectedPath) || null
          : null;
      };
      const readText = async (file: File, limit: number) => {
        if (file.size > limit) throw new Error(`${file.name} exceeds the local size limit`);
        const bytes = new Uint8Array(await file.arrayBuffer());
        try {
          return new TextDecoder("utf-8", { fatal: true, ignoreBOM: true }).decode(bytes);
        } catch {
          throw new Error(`${file.name} is not valid BOM-free UTF-8 text`);
        }
      };

      const findingsFile = canonicalFile("findings.json", true)!;
      const runFile = canonicalFile("run.json", true)!;
      const synthesisFile = canonicalFile("synthesis.json");
      const finalizationFile = canonicalFile("finalization.json");
      const manifestFile = canonicalFile("review-manifest.json");
      const sourceManifestFile = canonicalFile("evidence/source-manifest.json", false, ["source-manifest.json"]);
      const computationsFile = canonicalFile("evidence/computations.json", false, ["computations.json"]);
      const analyticalAuditFile = canonicalFile("evidence/analytical-audit.json", false, ["analytical-audit.json"]);
      const claimsAuditFile = canonicalFile("evidence/claims.json", false, ["claims.json"]);
      const tablesFile = canonicalFile("evidence/tables.json", false, ["tables.json"]);
      const figuresFile = canonicalFile("evidence/figures.json", false, ["figures.json"]);
      const [findingsText, runText, synthesisText, finalizationText, manifestText, sourceManifestText, computationsText, analyticalAuditText, claimsAuditText, tablesText, figuresText] = await Promise.all([
        readText(findingsFile, MAX_JSON_BYTES),
        readText(runFile, MAX_JSON_BYTES),
        synthesisFile ? readText(synthesisFile, MAX_JSON_BYTES) : Promise.resolve(null),
        finalizationFile ? readText(finalizationFile, MAX_JSON_BYTES) : Promise.resolve(null),
        manifestFile ? readText(manifestFile, MAX_JSON_BYTES) : Promise.resolve(null),
        sourceManifestFile ? readText(sourceManifestFile, MAX_JSON_BYTES) : Promise.resolve(null),
        computationsFile ? readText(computationsFile, MAX_JSON_BYTES) : Promise.resolve(null),
        analyticalAuditFile ? readText(analyticalAuditFile, MAX_JSON_BYTES) : Promise.resolve(null),
        claimsAuditFile ? readText(claimsAuditFile, MAX_JSON_BYTES) : Promise.resolve(null),
        tablesFile ? readText(tablesFile, MAX_JSON_BYTES) : Promise.resolve(null),
        figuresFile ? readText(figuresFile, MAX_JSON_BYTES) : Promise.resolve(null),
      ]);
      if (sequence !== localLoadSequence.current) return;

      const nextLedger = validateLedger(parseJsonFile("findings.json", findingsText));
      const nextLedgerFingerprint = sha256Hex(findingsText);
      const nextRun = validateRun(parseJsonFile("run.json", runText));
      const nextSynthesis = synthesisText === null ? null : validateSynthesis(parseJsonFile("synthesis.json", synthesisText));
      let finalizationValue: unknown | null = null;
      let parsedFinalization = false;
      let nextFinalizationTrust: FinalizationTrust = { ...NO_FINALIZATION_RECEIPT };
      if (finalizationText !== null) {
        try {
          finalizationValue = parseJsonFile("finalization.json", finalizationText);
          validateFinalizationReceipt(finalizationValue);
          parsedFinalization = true;
        } catch (error) {
          nextFinalizationTrust = {
            status: "unverified",
            receipt_present: true,
            receipt_version: null,
            detail: error instanceof Error ? error.message : "The selected finalization receipt could not be verified.",
          };
        }
      }
      const nextManifest = manifestText === null ? undefined : validateReviewDocumentManifest(manifestText);
      const nextSourceManifest = sourceManifestText === null ? null : validateSourceManifest(parseJsonFile("source-manifest.json", sourceManifestText));
      const nextComputations = computationsText === null ? null : validateReviewComputations(parseJsonFile("computations.json", computationsText));
      const nextAnalyticalAudit = analyticalAuditText === null ? null : parseJsonFile("analytical-audit.json", analyticalAuditText);
      const nextClaimsAudit = claimsAuditText === null ? null : parseJsonFile("claims.json", claimsAuditText);
      validateLedgerAnchors(nextLedger, nextSourceManifest);
      validateReviewComputationLinks(nextLedger, nextComputations, nextSourceManifest, {
        analyticalAudit: nextAnalyticalAudit,
        claimsAudit: nextClaimsAudit,
      }, nextRun.mode || null);
      const nextTables = validateExhibitManifest(
        tablesText === null ? null : parseJsonFile("tables.json", tablesText),
        "tables",
        nextLedger.review_id,
      ) as ExhibitManifest | null;
      const nextFigures = validateExhibitManifest(
        figuresText === null ? null : parseJsonFile("figures.json", figuresText),
        "figures",
        nextLedger.review_id,
      ) as ExhibitManifest | null;
      if (nextLedger.review_id !== nextRun.review_id) throw new Error("findings.json and run.json have different review IDs");
      if (nextLedger.schema_version !== nextRun.schema_version) throw new Error("findings.json and run.json have different schema versions");
      if (nextSynthesis && nextSynthesis.review_id !== nextLedger.review_id) throw new Error("synthesis.json has a different review ID");
      if (nextManifest && nextManifest.review_id !== nextLedger.review_id) throw new Error("review-manifest.json has a different review ID");
      if (nextSourceManifest && nextSourceManifest.review_id !== nextLedger.review_id) throw new Error("source-manifest.json has a different review ID");
      validatePackageLinks(nextLedger, nextRun, nextSynthesis);

      const declaredDocumentPaths = nextManifest?.documents.map((document) => document.path) || [];
      const manuscriptPath = selectManuscriptPath({
        paths,
        reviewRoot,
        declaredDocumentPaths,
        sourcePaths: [
          ...(nextSourceManifest?.sources || []).flatMap((source) => [source.extraction?.path, source.path]),
          ...(nextRun.assessment_boundary?.sources || []).map((source) => source.path),
        ].filter((path): path is string => Boolean(path)),
      });
      const manuscriptFile = manuscriptPath ? files.find((file) => normalizedFilePath(file) === manuscriptPath) || null : null;
      const availableDocumentPaths = files
        .filter((file) => /\.(md|markdown)$/i.test(file.name) && normalizedFilePath(file) !== manuscriptPath)
        .map((file) => relativePath(file))
        .filter((path): path is string => Boolean(path));
      const definitions = discoverReviewDocuments(availableDocumentPaths, nextManifest)
        .filter((document) => document.group !== "audit");
      const documentFiles = definitions.map((document) => {
        const matches = files.filter((file) => relativePath(file) === document.path);
        if (matches.length !== 1) throw new Error(`Review document ${document.path} is missing or ambiguous in the selected package.`);
        return { definition: document, file: matches[0] };
      });

      const references = referencedExhibitPaths(nextTables, nextFigures);
      const expectedImageHashes = referencedExhibitHashes(nextTables, nextFigures);
      if (references.length > MAX_REFERENCED_IMAGES) {
        throw new Error(`The exhibit manifests reference more than ${MAX_REFERENCED_IMAGES.toLocaleString()} images.`);
      }
      const imageFiles = files.filter((file) => /\.(png|jpe?g|webp)$/i.test(file.name));
      const imageMatches = matchReferencedImagePaths(imageFiles.map(normalizedFilePath), reviewRoot, references);
      const resolvedImagePaths = new Set(Array.from(imageMatches.values()).filter((path): path is string => Boolean(path)));
      const resolvedImageFiles = imageFiles.filter((file) => resolvedImagePaths.has(normalizedFilePath(file)));
      for (const file of resolvedImageFiles) {
        if (file.size > MAX_LOCAL_IMAGE_BYTES) throw new Error(`${file.name} exceeds the local image size limit`);
      }
      const packageArtifactFiles = parsedFinalization
        ? files.filter((file) => {
          const path = relativePath(file);
          return path !== null && isFinalizationArtifactPath(path);
        })
        : [];
      const relevantFiles = Array.from(new Set([
        findingsFile, runFile, synthesisFile, finalizationFile, manifestFile, sourceManifestFile, computationsFile, tablesFile, figuresFile, manuscriptFile,
        ...documentFiles.map(({ file }) => file), ...resolvedImageFiles, ...packageArtifactFiles,
      ].filter((file): file is File => Boolean(file))));
      const relevantBytes = relevantFiles.reduce((sum, file) => sum + file.size, 0);
      if (relevantFiles.length > MAX_LOCAL_PACKAGE_FILES || relevantBytes > MAX_LOCAL_PACKAGE_BYTES) {
        throw new Error("The inferred review package exceeds the local processing limit. Choose a smaller package with only its review artifacts and referenced renders.");
      }

      const [nextManuscript, documentContents] = await Promise.all([
        manuscriptFile ? readText(manuscriptFile, MAX_MANUSCRIPT_BYTES) : Promise.resolve(""),
        Promise.all(documentFiles.map(({ file }) => readText(file, MAX_MANUSCRIPT_BYTES))),
      ]);
      if (sequence !== localLoadSequence.current) return;
      const nextDocuments = documentFiles.map(({ definition }, index) => ({ ...definition, content: documentContents[index] }));

      if (parsedFinalization) {
        const artifactBytes = new Map<string, Uint8Array>();
        for (const file of packageArtifactFiles) {
          const path = relativePath(file);
          if (path) artifactBytes.set(path, new Uint8Array(await file.arrayBuffer()));
        }
        nextFinalizationTrust = await verifyReviewFinalization({
          receipt: finalizationValue,
          reviewId: nextLedger.review_id,
          reviewContractVersion: nextRun.schema_version,
          reviewMode: nextRun.mode,
          hasPdfSource: Boolean(nextSourceManifest?.sources?.some((source) => source.media_type === "application/pdf")),
          artifactBytes,
        });
      }

      const urlByFilePath = new Map<string, string>();
      for (const file of resolvedImageFiles) {
        const filePath = normalizedFilePath(file);
        const bytes = new Uint8Array(await file.arrayBuffer());
        const mediaType = reviewImageMediaType(filePath, bytes);
        const relativePath = relativeToReviewRoot(filePath, reviewRoot);
        const expectedHash = relativePath ? expectedImageHashes.get(relativePath) : undefined;
        if (expectedHash && await sha256ReviewBytes(bytes) !== expectedHash) {
          throw new Error(`Referenced exhibit ${relativePath} does not match its declared SHA-256 hash`);
        }
        const url = URL.createObjectURL(new Blob([bytes], { type: mediaType }));
        urlByFilePath.set(filePath, url);
        stagedObjectUrls.push(url);
      }
      const urlByReference = new Map<string, string>();
      for (const [reference, matchedPath] of imageMatches) {
        if (matchedPath && urlByFilePath.has(matchedPath)) urlByReference.set(reference, urlByFilePath.get(matchedPath)!);
      }

      if (sequence !== localLoadSequence.current) {
        for (const url of stagedObjectUrls) URL.revokeObjectURL(url);
        stagedObjectUrls.length = 0;
        return;
      }
      for (const url of localObjectUrls.current) URL.revokeObjectURL(url);
      localObjectUrls.current = [...stagedObjectUrls];
      stagedObjectUrls.length = 0;
      setLedger(nextLedger);
      setLedgerFingerprint(nextLedgerFingerprint);
      setRun(nextRun);
      setSynthesis(nextSynthesis);
      setManuscript(nextManuscript);
      setDocuments(nextDocuments);
      setReportView("none");
      setDetailMode("overview");
      setSelectedId(nextLedger.findings?.[0]?.id || "");
      const restoredActions = restoreBrowserReviewActions(window.localStorage, {
        review_id: nextLedger.review_id,
        review_fingerprint: nextLedgerFingerprint,
        finding_ids: nextLedger.findings.map((finding) => finding.id),
      });
      localStateRef.current = restoredActions.entries;
      setLocalState(restoredActions.entries);
      replaceNoteDrafts({});
      persistenceContextRef.current = {
        reviewId: nextLedger.review_id,
        reviewFingerprint: nextLedgerFingerprint,
        sourceManuscripts: privacySafeSourceManuscripts(nextRun.assessment_boundary?.sources || []),
      };
      setPersistenceState("saved");
      setHandoffWarning(restoredActions.warning);
      setQuery("");
      setSeverity("all");
      setDecisionRole("all");
      setStatus("all");
      setChannel("all");
      setDimension("all");
      setReviewedFilter("all");
      setPersonalPriorityFilter("all");
      setEvidenceIndex(0);
      setAssetPathIndex(0);
      try {
        const savedOrder = window.localStorage.getItem(`review-desk:queue-order:${nextLedger.review_id}`);
        setQueueOrder(["priority", "importance", "paper"].includes(savedOrder || "") ? savedOrder as QueueOrder : "importance");
      } catch { setQueueOrder("importance"); }
      setActionNotice("");
      setUndoStatusChange(null);
      setPendingDocumentAnchor(null);
      setMobilePane("comment");
      loadedReviewSlug.current = "";
      setReviewSlug("");
      const url = new URL(window.location.href);
      url.searchParams.delete("review");
      window.history.replaceState({}, "", url);
      setExhibitAssets(manifestAssets(nextTables, nextFigures, (path) => urlByReference.get(normalizePackagePath(path)) || null));
      setSourceAnchors(Object.fromEntries((nextSourceManifest?.anchors || []).map((anchor) => [anchor.id, anchor])));
      setComputationsById(indexReviewComputations(nextComputations));
      setFinalizationTrust(nextFinalizationTrust);
      setAnnouncement(restoredActions.rereview_required_finding_ids.length
        ? `Loaded the review. Notes and personal priorities were carried forward for ${restoredActions.rereview_required_finding_ids.length} surviving comments, which must now be reviewed again.`
        : `Loaded the review with ${nextLedger.findings.length} comments${nextManuscript ? " and manuscript context" : "; no manuscript was loaded"}.`);
    } catch (error) {
      for (const url of stagedObjectUrls) URL.revokeObjectURL(url);
      if (sequence === localLoadSequence.current) {
        setLoadError(reviewLoadMessage(error));
      }
    } finally {
      if (sequence === localLoadSequence.current) setIsLocalLoading(false);
    }
  }

  function commitAllNoteDrafts() {
    const drafts = noteDraftsRef.current;
    const committed = commitRevisionNoteDrafts(localStateRef.current, drafts);
    if (Object.keys(drafts).length) {
      localStateRef.current = committed;
      setLocalState(committed);
      replaceNoteDrafts({});
      if (persistenceModeRef.current === "local") setPersistenceState("pending");
    }
    return committed;
  }

  function committedRevisionArtifacts() {
    if (!ledger) return null;
    const entries = commitAllNoteDrafts();
    const tasks = buildRevisionTasks({
      source_review_id: ledger.review_id,
      source_review_fingerprint: ledgerFingerprint,
      findings,
      entries,
    });
    return {
      entries,
      tasks,
      brief: renderRevisionAgentBrief(tasks),
      response: buildAgentResponseTemplate(tasks),
    };
  }

  function exportSession() {
    if (!ledger) return;
    let url = "";
    try {
      const entries = commitAllNoteDrafts();
      const payload = JSON.stringify(generateReviewActionsPayload({
        source_review_id: ledger.review_id,
        source_review_fingerprint: ledgerFingerprint,
        source_manuscripts: privacySafeSourceManuscripts(run?.assessment_boundary?.sources || []),
        exported_at: actionExportTime(entries),
        entries,
      }), null, 2);
      url = URL.createObjectURL(new Blob([payload], { type: "application/json" }));
      const anchor = document.createElement("a");
      anchor.href = url;
      anchor.download = `${safeDownloadStem(ledger.review_id)}-review-actions.json`;
      anchor.click();
      window.setTimeout(() => URL.revokeObjectURL(url), 1000);
      setLoadError("");
      showActionNotice("Review actions exported. Import this file with the next review round to reconcile exact finding IDs.");
    } catch {
      if (url) URL.revokeObjectURL(url);
      setLoadError("The browser could not export the action handoff. Your current actions remain available in this tab.");
    }
  }

  function downloadTextFile(fileName: string, content: string, type: string) {
    const url = URL.createObjectURL(new Blob([content], { type }));
    const anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = fileName;
    anchor.click();
    window.setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function exportRevisionTasks() {
    const snapshot = committedRevisionArtifacts();
    if (!snapshot) return;
    downloadTextFile("revision-tasks.json", deterministicJson(snapshot.tasks), "application/json");
    showActionNotice(snapshot.tasks.handoff_ready
      ? "Downloaded the machine-readable revision tasks bound to this review and action state."
      : "Downloaded draft revision tasks. Missing decisions remain explicit, and the implementation agent should not act yet.");
  }

  function exportRevisionBrief() {
    const snapshot = committedRevisionArtifacts();
    if (!snapshot) return;
    downloadTextFile("revision-agent-brief.md", snapshot.brief, "text/markdown");
    showActionNotice(`Downloaded the ${snapshot.tasks.handoff_ready ? "revision agent brief" : "draft revision agent brief with missing decisions"}.`);
  }

  function exportRevisionResponseTemplate() {
    const snapshot = committedRevisionArtifacts();
    if (!snapshot) return;
    downloadTextFile("revision-response.template.json", deterministicJson(snapshot.response), "application/json");
    showActionNotice(snapshot.tasks.handoff_ready
      ? "Downloaded the structured response template for the implementation agent."
      : "Downloaded a response template bound to a draft plan. Complete the missing decisions before implementation.");
  }

  async function copyRevisionPlan() {
    try {
      const snapshot = committedRevisionArtifacts();
      if (!snapshot) return;
      await navigator.clipboard.writeText(snapshot.brief);
      setAnnouncement(`Copied the ${snapshot.tasks.handoff_ready ? "revision agent brief" : "draft revision agent brief"}`);
      showActionNotice("Copied the revision agent brief.");
    } catch {
      setLoadError("The browser blocked clipboard access. Download the Markdown brief instead.");
    }
  }

  async function importActions(event: ChangeEvent<HTMLInputElement>) {
    const file = event.target.files?.[0];
    event.target.value = "";
    if (!file || !ledger) return;
    try {
      if (file.size > MAX_JSON_BYTES) throw new Error("The review-actions file exceeds the local size limit");
      const result = reconcileReviewActions(await file.text(), {
        review_id: ledger.review_id,
        review_fingerprint: ledgerFingerprint,
        finding_ids: findings.map((finding) => finding.id),
      });
      if (!result.review_id_matches) throw new Error(result.warnings.map((warning) => warning.message).join(" "));
      const merged = mergeReviewActionEntries(localStateRef.current, result.entries);
      const importedAt = new Date().toISOString();
      const entriesWithProvenance = { ...merged.entries };
      for (const findingId of merged.applied_finding_ids) {
        entriesWithProvenance[findingId] = recordReviewActionImport(entriesWithProvenance[findingId], importedAt);
      }
      const appliedRereviewCount = result.rereview_required_finding_ids
        .filter((findingId) => merged.applied_finding_ids.includes(findingId)).length;
      localStateRef.current = entriesWithProvenance;
      setLocalState(entriesWithProvenance);
      replaceNoteDrafts({});
      if (persistenceModeRef.current === "local") setPersistenceState("pending");
      const details = [
        `${merged.applied_finding_ids.length} applied`,
        merged.stale_finding_ids.length ? `${merged.stale_finding_ids.length} stale` : "",
        merged.conflict_finding_ids.length ? `${merged.conflict_finding_ids.length} conflicts kept local` : "",
        result.unmatched_entry_ids.length ? `${result.unmatched_entry_ids.length} unmatched` : "",
        !result.fingerprint_matches ? `${appliedRereviewCount} current comments need review again` : "",
      ].filter(Boolean).join(" · ");
      setHandoffWarning([
        ...result.warnings.map((warning) => warning.message),
        ...merged.warnings.map((warning) => warning.message),
      ].join(" "));
      showActionNotice(!result.fingerprint_matches
        ? `Review actions: ${details}. Prior notes and personal priorities were carried forward; current comments were reopened for this round.`
        : `Review actions: ${details}. Imported changes remain author claims until rechecked.`);
      setAnnouncement(!result.fingerprint_matches
        ? `Applied changed-round actions. Notes and personal priorities were carried forward; ${appliedRereviewCount} current comments need review again.`
        : `Applied actions for ${merged.applied_finding_ids.length} findings; ${merged.conflict_finding_ids.length} conflicts kept local`);
      setLoadError("");
    } catch (error) {
      setLoadError(error instanceof Error ? error.message : "The review-actions file could not be imported.");
    }
  }

  async function copyRevisionBrief() {
    if (!selected) return;
    const activeEvidence = selected.evidence[activeEvidenceIndex];
    const text = `${commentLabel(findings, selected.id)}\nCategory: ${channelLabel(selected)}\nReviewer assessment: ${decisionRoleLabel(selected.decision_role)}\nSeverity: ${selected.severity}\nDecision: ${dispositionDetailLabel(selectedEntry.disposition)}\nMy priority: ${selectedEntry.user_priority || "Unassigned"}\nReviewed: ${selectedEntry.reviewed ? "Yes" : "No"}\n\nIssue: ${selected.issue}\n\nRelevant text (${readableState(activeEvidence?.type)}): ${evidenceText(activeEvidence)}\nSource: ${activeEvidence?.source || "not available"}\nLocation: ${locator(selected, activeEvidenceIndex)}\n\nConcern: ${mergeDistinctText(selected.why_it_matters, selected.reader_effect)}\n\nSuggestions: ${mergeDistinctText(selected.fix.what, selected.fix.how)}\n\nReady to close when: ${selected.fix.resolved_when || "Complete the stated revision path."}\n\nOptional author note: ${(noteDrafts[selected.id] ?? selectedEntry.response_note) || "None"}`;
    try {
      await navigator.clipboard.writeText(text);
      setAnnouncement(`Copied revision brief for ${commentLabel(findings, selected.id)}`);
      setLoadError("");
      showActionNotice(`Copied the revision brief for ${commentLabel(findings, selected.id)}.`);
    } catch {
      setLoadError("The browser blocked clipboard access. Select and copy the comment text manually.");
    }
  }

  function onListKey(event: KeyboardEvent<HTMLButtonElement>, index: number) {
    if (["ArrowDown", "ArrowUp", "Home", "End"].includes(event.key)) {
      event.preventDefault();
      const nextIndex = event.key === "Home" ? 0
        : event.key === "End" ? filtered.length - 1
          : index + (event.key === "ArrowDown" ? 1 : -1);
      const next = filtered[nextIndex];
      const wrapped = next || filtered[event.key === "ArrowDown" ? 0 : filtered.length - 1];
      if (wrapped) {
        selectAndFocus(wrapped.id);
        setAnnouncement(`Selected ${commentLabel(findings, wrapped.id)}`);
      }
    }
  }

  const activeEvidenceIndex = Math.min(evidenceIndex, Math.max(0, (selected?.evidence.length || 1) - 1));
  const evidence = selected?.evidence[activeEvidenceIndex] || selected?.evidence[0];
  const evidenceAnchorIds = evidence?.representation === "composite_comparison"
    ? evidence.anchor_ids || []
    : evidence?.anchor_id ? [evidence.anchor_id] : [];
  const sourceEvidenceKey = `${selected?.id || "none"}:${evidence?.id || activeEvidenceIndex}`;
  const activeSourceAnchorIndex = sourceAnchorSelection.evidenceKey === sourceEvidenceKey
    ? Math.min(sourceAnchorSelection.index, Math.max(0, evidenceAnchorIds.length - 1))
    : 0;
  const activeSourceAnchorId = evidenceAnchorIds[activeSourceAnchorIndex];
  const activeSourceAnchor = activeSourceAnchorId ? sourceAnchors[activeSourceAnchorId] : undefined;
  const computation = evidence?.computation_id ? computationsById[evidence.computation_id] : undefined;
  const evidenceKind = evidence?.type === "figure" ? "figure" : evidence?.type === "table_cell" ? "table" : null;
  const exhibit = evidenceKind && evidence?.locator.exhibit ? exhibitAssets[exhibitKey(evidenceKind, evidence.locator.exhibit)] : undefined;
  const activeExhibitRender = exhibit?.renders[Math.min(assetPathIndex, exhibit.renders.length - 1)];
  const activeExhibitPath = activeExhibitRender?.resolvedPath;
  const loadingReviewTitle = isLocalLoading ? "local review package" : registry?.reviews.find((entry) => entry.slug === reviewSlug)?.title || "review";
  const bannerMessage = loadError || persistenceWarning || handoffWarning;
  const packageWarnings = [] as string[];
  if (run?.status && run.status !== "complete") {
    packageWarnings.push("This review is still being prepared, so comments and reports may change.");
  }
  if (run && !run.verification_passed) {
    packageWarnings.push("Some planned review checks were not completed. Read the scope note before relying on the assessment.");
  }
  if (finalizationTrust.status !== "verified") {
    if (run?.status === "complete") {
      packageWarnings.push("The selected review files could not be confirmed as one complete matching set. Reopen the finished review folder before relying on it.");
    }
  }
  const packageWarning = packageWarnings.join(" ");
  const reviewedScope = [
    run?.assessment_boundary?.sources?.length
      ? `${run.assessment_boundary.sources.length} source ${run.assessment_boundary.sources.length === 1 ? "file" : "files"}`
      : "Source coverage not stated",
    run?.assessment_boundary?.figures ? `figures: ${readableState(run.assessment_boundary.figures)}` : "",
    run?.assessment_boundary?.equations ? `equations: ${readableState(run.assessment_boundary.equations)}` : "",
  ].filter(Boolean).join(" · ");
  const uncheckedScope = [
    ["not_available", "not_supplied", "unavailable"].includes(run?.assessment_boundary?.appendix || "")
      ? "No appendix was available."
      : "",
    run?.capabilities?.live_literature_search === false
      ? "The live literature was not independently checked."
      : "",
    ["not_supplied", "not_available", "not_permitted"].includes(run?.capabilities?.replication_code || "")
      ? "The reported results were not rerun because replication code was unavailable."
      : run?.capabilities?.replication_code === "static_only" ? "Replication code was read but not executed." : "",
    run?.assessment_boundary?.notes || "",
  ].filter(Boolean);
  const activeDocument = documents.find((document) => document.id === reportView) || documents[0];
  const activeReport = activeDocument?.content || "";
  const refereeReport = documents.find((document) => document.path === "report.md");
  /** Turn generator finding-link markers into buttons that open the matching detailed comments. */
  const withCommentJumpLinks = (markdown: string) => {
    const jumpButtons = (ids: string[]) => ids
      .filter((id) => findings.some((finding) => finding.id === id))
      .map((id) => `[Go to comment ${findings.findIndex((finding) => finding.id === id) + 1} →](#finding=${id})`)
      .join(" ");
    return markdown.split("\n").map((line) => {
      // Current generator format: machine-readable markers in HTML comments.
      const linkedMarker = line.match(/^<!--\s*linked_finding_ids:\s*([^>]*?)\s*-->\s*$/);
      if (linkedMarker) {
        const buttons = jumpButtons(linkedMarker[1].split(/[,\s]+/).filter(Boolean));
        return buttons || line;
      }
      const singleMarker = line.match(/^<!--\s*finding_id:\s*([A-Za-z0-9-]+)\s*-->\s*$/);
      if (singleMarker) {
        const buttons = jumpButtons([singleMarker[1]]);
        return buttons || line;
      }
      // Older format: a visible "Linked findings: `ID`, `ID`." line.
      if (!line.startsWith("Linked findings:")) return line;
      const body = line.slice("Linked findings:".length);
      const idList = body.match(/^\s*(?:`[^`]+`[,\s]*)+\.?/)?.[0] || "";
      const buttons = jumpButtons(Array.from(idList.matchAll(/`([^`]+)`/g), (token) => token[1]));
      if (!buttons) return line;
      const remainder = body.slice(idList.length).trim();
      return remainder ? `${buttons}\n\n*${remainder}*` : buttons;
    }).join("\n");
  };
  const reportComponentsFor = (sourceDocument: ReviewDocument | undefined): MarkdownComponents => ({
    img: ({ alt }) => <span className="blocked-report-image">[Image omitted from report view{alt ? `: ${alt}` : ""}]</span>,
    a: ({ children, href }) => {
      if (href?.startsWith("#finding=")) {
        const target = findings.find((finding) => finding.id === decodeURIComponent(href.slice("#finding=".length)));
        if (target) {
          return <button type="button" className="report-jump-link" title={shortTitle(target)} onClick={() => openFinding(
            target.id,
            `Opened ${commentLabel(findings, target.id)} from ${sourceDocument?.title || "review document"}`,
          )}>{children}</button>;
        }
      }
      const linked = resolveReviewDocumentLink(sourceDocument?.path, href, documents);
      if (linked) {
        return <button type="button" className="report-document-link" onClick={() => {
          setReportView(linked.document.id);
          pushViewState({ view: "document", document: linked.document.id, finding: null, evidence: 0 });
          if (linked.fragment) {
            setPendingDocumentAnchor({ documentId: linked.document.id, fragment: linked.fragment });
            setAnnouncement(`Opening ${linked.document.title} at the linked section.`);
          } else {
            setPendingDocumentAnchor(null);
            setAnnouncement(`Opened review document: ${linked.document.title}`);
            requestAnimationFrame(() => reportHeading.current?.focus());
          }
        }}>{children}</button>;
      }
      const external = safeExternalReviewDocumentHref(href);
      return external
        ? <a href={external} target="_blank" rel="noopener noreferrer">{children}<span className="visually-hidden"> (opens in a new tab)</span></a>
        : <span className="blocked-report-link" title="This link is not a declared review document or an HTTP(S) destination">{children}</span>;
    },
    code: ({ children }) => {
      const token = String(children).trim();
      const linkedFinding = findings.find((finding) => finding.id === token);
      return linkedFinding ? <button type="button" className="report-finding-link" onClick={() => openFinding(
        linkedFinding.id,
        `Opened ${commentLabel(findings, linkedFinding.id)} from ${sourceDocument?.title || "review document"}`,
      )}>{token}</button> : <code>{children}</code>;
    },
  });
  const reportComponents = reportComponentsFor(activeDocument);
  const documentGroups = Object.entries(REVIEW_DOCUMENT_GROUP_LABELS).map(([group, label]) => ({
    group,
    label,
    documents: documents.filter((document) => document.group === group),
  })).filter((group) => group.documents.length);
  const evidenceContent = evidenceText(evidence);
  const manuscriptExcerpt = useMemo(() => {
    const message = (value: string) => ({ before: "", highlight: "", after: "", message: value, exact: false });
    if (!manuscript) return message("No manuscript text is loaded for this review. The evidence excerpt remains available.");
    if (!evidenceContent || evidence?.type === "absence_scope") return message("Use the evidence and location shown for this checked absence; no unrelated manuscript passage is displayed.");
    if (activeSourceAnchor) return exactAnchorExcerpt(manuscript, activeSourceAnchor, sha256Hex);
    if (activeSourceAnchorId) return message("The saved manuscript location could not be matched. Use the evidence excerpt and location shown.");
    const clean = evidenceContent.replace(/[“”]/g, '"').replace(/\.\.\..*$/, "");
    const normalizedManuscript = manuscript.replace(/[“”]/g, '"');
    const tokens = clean.match(/[\p{L}\p{N}]+/gu)?.filter((token) => token.length > 1).slice(0, 12) || [];
    if (tokens.length < 4) return message("The excerpt is too short for a safe manuscript match. Use the source and location shown.");
    const escape = (value: string) => value.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
    const anchor = new RegExp(tokens.map(escape).join("[^\\p{L}\\p{N}]+"), "iu");
    const index = anchor.exec(normalizedManuscript)?.index ?? -1;
    if (index < 0) return message("The quoted passage could not be matched safely in the loaded manuscript. Use the source and location shown; no unrelated passage is displayed.");
    return { before: manuscript.slice(Math.max(0, index - 700), Math.min(manuscript.length, index + 1900)), highlight: "", after: "", message: "", exact: false };
  }, [activeSourceAnchor, activeSourceAnchorId, evidence?.type, evidenceContent, manuscript]);

  useEffect(() => {
    if (!pendingDocumentAnchor || activeDocument?.id !== pendingDocumentAnchor.documentId) return;
    const container = reportReader.current;
    if (!container) return;
    let finished = false;
    const focusTarget = () => {
      const target = container.ownerDocument.getElementById(pendingDocumentAnchor.fragment);
      if (!target || !container.contains(target)) return false;
      finished = true;
      if (!target.hasAttribute("tabindex")) target.setAttribute("tabindex", "-1");
      target.scrollIntoView({ block: "start" });
      target.focus({ preventScroll: true });
      setAnnouncement(`Opened ${activeDocument.title} at ${target.textContent?.trim() || "the linked section"}.`);
      setPendingDocumentAnchor(null);
      return true;
    };
    if (focusTarget()) return;
    const observer = new MutationObserver(() => {
      if (focusTarget()) observer.disconnect();
    });
    observer.observe(container, { childList: true, subtree: true });
    const timeout = window.setTimeout(() => {
      if (finished) return;
      observer.disconnect();
      setAnnouncement(`Opened ${activeDocument.title}, but the linked section #${pendingDocumentAnchor.fragment} was not found.`);
      setPendingDocumentAnchor(null);
      reportHeading.current?.focus();
    }, 1500);
    return () => {
      observer.disconnect();
      window.clearTimeout(timeout);
    };
  }, [activeDocument, activeReport, pendingDocumentAnchor]);

  if (!ledger || !run) {
    if (isLocalLoading) {
      return (
        <main className="loading-shell" aria-busy="true">
          <div className="loading-mark" aria-hidden="true">RD</div>
          <p>Checking the local review package…</p>
        </main>
      );
    }
    if (registryUnavailable || loadError) {
      return (
        <main className="welcome-shell">
          <section className="welcome-card" aria-labelledby="welcome-title">
            <div className="loading-mark" aria-hidden="true">RD</div>
            <span className="eyebrow">Local Review Desk</span>
            <h1 id="welcome-title">Open a review without uploading it.</h1>
            <p>Choose the paper folder to load its nested review files together. They stay in this browser and are never sent to a server.</p>
            <div className="file-requirements">
              <div><strong>Best choice</strong><span>Open the complete review folder.</span></div>
              <div><strong>Optional context</strong><span>Include the manuscript and saved table or figure images when available.</span></div>
            </div>
            {loadError && <div className="welcome-error" role="alert">{loadError}</div>}
            <div
              className="drop-zone"
              onDragOver={(event) => event.preventDefault()}
              onDrop={(event) => { event.preventDefault(); void loadSelectedFiles(Array.from(event.dataTransfer.files)); }}
            >
              <div className="drop-zone-actions">
                <button onClick={() => folderInput.current?.click()}>Open review folder</button>
                <button className="secondary" onClick={() => fileInput.current?.click()}>Choose individual files</button>
              </div>
              <span>Folder mode keeps reports, manuscript context, and saved exhibit images together; file mode is available for a small review.</span>
            </div>
            <p className="privacy-note">The review itself stays unchanged. Your progress and notes are stored separately in this browser.</p>
          </section>
          <input id="review-files" name="review-files" accept=".json,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp" aria-label="Choose local review files" ref={fileInput} className="visually-hidden" type="file" multiple onChange={loadFiles} />
          <input id="review-folder" name="review-folder" aria-label="Choose local review folder" ref={folderInput} className="visually-hidden" type="file" multiple {...{ webkitdirectory: "", directory: "" }} onChange={loadFiles} />
        </main>
      );
    }
    return (
      <main className="loading-shell">
        <div className="loading-mark">RD</div>
        <p>{loadError || "Opening the review…"}</p>
        {loadError && <button onClick={() => folderInput.current?.click()}>Open review folder</button>}
        <input id="review-files" name="review-files" accept=".json,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp" aria-label="Choose local review files" ref={fileInput} className="visually-hidden" type="file" multiple onChange={loadFiles} />
        <input id="review-folder" name="review-folder" aria-label="Choose local review folder" ref={folderInput} className="visually-hidden" type="file" multiple {...{ webkitdirectory: "", directory: "" }} onChange={loadFiles} />
      </main>
    );
  }

  if (!selected) {
    if (isReviewLoading) {
      return (
        <main className="loading-shell" aria-busy="true">
          <div className="loading-mark" aria-hidden="true">RD</div>
          <p>Checking {loadingReviewTitle}…</p>
        </main>
      );
    }
    return (
      <main className="complete-review-shell">
        <section className="complete-review-card">
          <span className="eyebrow">Review</span>
          <h1>No comments are recorded in this review.</h1>
          <p>Available review documents remain below. Any incomplete checks are identified separately.</p>
          {packageWarning && <div className="package-warning" role="alert"><strong>Review files need attention</strong><span>{packageWarning}</span></div>}
          {synthesis && synthesis.review_posture !== "not_assessed" && (
            <section className="complete-synthesis" aria-label="Overall review assessment">
              <span className={`posture-chip posture-${synthesis.review_posture}`}>{POSTURE_LABELS[synthesis.review_posture]}</span>
              <p>{synthesis.overall_assessment}</p>
            </section>
          )}
          <div className="complete-review-actions">
            <button onClick={() => folderInput.current?.click()}>Open another folder</button>
            <button onClick={exportSession}>Export actions</button>
          </div>
          {documents.length ? <>
            <label className="report-picker">
              <span>Choose a review document</span>
              <select value={activeDocument?.id || documents[0].id} onChange={(event) => { setReportView(event.target.value); pushViewState({ view: "document", document: event.target.value, finding: null, evidence: 0 }); }}>
                {documentGroups.map((group) => (
                  <optgroup key={group.group} label={group.label}>
                    {group.documents.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}
                  </optgroup>
                ))}
              </select>
            </label>
            <article ref={reportReader} className="report-document">
              <RenderedMarkdown components={reportComponents}>{authorReportDisplayMarkdown(activeReport)}</RenderedMarkdown>
            </article>
          </> : <p>No narrative document was included in this package.</p>}
        </section>
        <input id="complete-review-folder" name="complete-review-folder" aria-label="Choose local review folder" ref={folderInput} className="visually-hidden" type="file" multiple {...{ webkitdirectory: "", directory: "" }} onChange={loadFiles} />
      </main>
    );
  }

  return (
    <main className="app-shell" aria-busy={isReviewLoading}>
      <a className="skip-link" href="#findings-panel">Skip to comments</a>
      <a className="skip-link" href="#review-detail">Skip to review detail</a>
      <h1 className="visually-hidden">Review Desk</h1>
      <header className="topbar" data-testid="compact-header">
        <div className="brand-lockup">
          <span className="brand-mark" aria-hidden="true">RD</span>
          <strong>Review Desk</strong>
        </div>
        {registry ? (
          <label className="review-picker header-review-picker">
            <span className="visually-hidden">Choose bundled review</span>
            <select id="bundled-review" name="bundled-review" aria-label="Choose bundled review" value={reviewSlug} disabled={isReviewLoading} onChange={(event) => { setLoadError(""); setReviewSlug(event.target.value); }}>
              {!reviewSlug && <option value="">Local review</option>}
              {registry.reviews.map((entry) => <option key={entry.slug} value={entry.slug}>{entry.title}</option>)}
            </select>
          </label>
        ) : <span className="local-review-title">Local review</span>}
        <div className="compact-review-summary" aria-label="Review status summary">
          <span className="compact-progress" role="progressbar" aria-label="Comments reviewed" aria-valuemin={0} aria-valuemax={findings.length} aria-valuenow={reviewedCount} aria-valuetext={`Reviewed ${reviewedCount} of ${findings.length} comments`}><span className="compact-progress-track" aria-hidden="true"><i className="reviewed-segment" style={{ width: `${findings.length ? (reviewedCount / findings.length) * 100 : 0}%` }} /></span>{reviewedCount}/{findings.length} reviewed{setAsideCount ? ` · ${setAsideCount} set aside` : ""}</span>
        </div>
        <details className="top-menu" ref={topMenu}>
          <summary aria-label="Open review menu">Menu</summary>
          <div className="top-menu-panel">
            <button disabled={isReviewLoading} onClick={() => { if (topMenu.current) topMenu.current.open = false; folderInput.current?.click(); }}>Open folder</button>
            <button disabled={isReviewLoading || !documents.length} onClick={() => { if (topMenu.current) topMenu.current.open = false; const id = documents[0]?.id; if (id) { setReportView(id); setMobilePane("comment"); pushViewState({ view: "document", document: id, finding: null, evidence: 0 }); } }}>Documents</button>
            <button disabled={isReviewLoading || !findings.length} onClick={() => { if (topMenu.current) topMenu.current.open = false; openRevisionPlan(); }}>My revision plan</button>
            <button disabled={isReviewLoading} onClick={() => { if (topMenu.current) topMenu.current.open = false; actionsInput.current?.click(); }}>Import actions</button>
            <button disabled={isReviewLoading} onClick={() => { if (topMenu.current) topMenu.current.open = false; exportSession(); }}>Export actions</button>
            <div className="privacy-controls" role="group" aria-label="Browser storage for actions">
              <strong>Action storage</strong>
              <button aria-pressed={persistenceMode === "local"} onClick={() => {
                persistenceModeRef.current = "local";
                setPersistenceMode("local");
                persistenceWarningRef.current = "";
                setPersistenceWarning("");
                setPersistenceState("pending");
                flushBrowserActions();
                showActionNotice("Actions will be saved in this browser after changes.");
              }}>Save in this browser</button>
              <button aria-pressed={persistenceMode === "session"} onClick={() => {
                persistenceModeRef.current = "session";
                setPersistenceMode("session");
                persistenceWarningRef.current = "";
                setPersistenceWarning("");
                setPersistenceState("idle");
                showActionNotice("Future changes will stay in this tab. Existing browser snapshots are unchanged.");
              }}>This tab only</button>
              <button className="danger-text" onClick={() => {
                if (!ledger || !window.confirm(`Clear every saved action snapshot for ${ledger.review_id}? The current tab will keep its present actions until closed.`)) return;
                const removed = clearBrowserReviewActions(window.localStorage, ledger.review_id);
                window.localStorage.removeItem(`review-desk:queue-order:${ledger.review_id}`);
                persistenceModeRef.current = "session";
                setPersistenceMode("session");
                setPersistenceState("idle");
                setHandoffWarning("");
                showActionNotice(`Cleared ${removed} saved action snapshot${removed === 1 ? "" : "s"}. Current actions remain in this tab.`);
              }}>Clear saved snapshots</button>
            </div>
            <details className="shortcut-menu"><summary>Keyboard shortcuts</summary><p><kbd>J</kbd>/<kbd>K</kbd> move · <kbd>R</kbd> ready choices · <kbd>S</kbd> set-aside choices · <kbd>N</kbd> note · <kbd>O</kbd> overview · <kbd>Esc</kbd> close context</p></details>
          </div>
        </details>
        <input id="review-files" name="review-files" accept=".json,.md,.markdown,.txt,.png,.jpg,.jpeg,.webp" aria-label="Choose local review files" ref={fileInput} className="visually-hidden" type="file" multiple disabled={isReviewLoading} onChange={loadFiles} />
        <input id="review-folder" name="review-folder" aria-label="Choose local review folder" ref={folderInput} className="visually-hidden" type="file" multiple disabled={isReviewLoading} {...{ webkitdirectory: "", directory: "" }} onChange={loadFiles} />
        <input id="review-actions" name="review-actions" accept=".json" aria-label="Import review actions" ref={actionsInput} className="visually-hidden" type="file" disabled={isReviewLoading} onChange={importActions} />
      </header>

      {!isReviewLoading && (bannerMessage || packageWarning) && <div className="notice-stack">
        {bannerMessage && <div className="error-banner" role={loadError ? "alert" : "status"}>{bannerMessage}</div>}
        {packageWarning && <div className="package-warning" role="alert"><strong>Review files need attention</strong><span>{packageWarning}</span></div>}
      </div>}
      {actionNotice && <div className="action-toast" role="status"><span>{actionNotice}</span>{undoStatusChange && <button onClick={undoLastStatusChange}>Undo status</button>}</div>}

      {isReviewLoading ? (
        <section id="review-detail" className="bundle-loading-panel" role="status" aria-live="polite" tabIndex={-1}>
          <div className="loading-mark" aria-hidden="true">RD</div>
          <h1>Loading {loadingReviewTitle}</h1>
          <p>{isLocalLoading ? "The current review is hidden until the selected local package has passed compatibility checks." : "The current review is hidden until the selected bundle has loaded and passed compatibility checks."}</p>
        </section>
      ) : <div className="workspace-grid">
        <nav className="mobile-view-switcher" aria-label="Review workspace panes">
          <button aria-pressed={mobilePane === "queue"} onClick={() => openMobilePane("queue")}>Queue</button>
          <button aria-pressed={mobilePane === "comment"} onClick={() => openMobilePane("comment")}>{reportView !== "none" ? "Document" : detailMode === "overview" ? "Overview" : detailMode === "plan" ? "Plan" : "Comment"}</button>
          <button aria-pressed={mobilePane === "evidence"} disabled={!filtered.length || detailMode !== "comment" || reportView !== "none"} onClick={() => openMobilePane("evidence")}>Evidence</button>
        </nav>
        <aside id="findings-panel" className={`finding-rail ${mobilePane !== "queue" ? "mobile-hidden" : ""}`} aria-label="Review findings" tabIndex={-1}>
          <div className="rail-controls">
          {synthesis && (
            <button className="overview-link" onClick={openOverview} aria-current={detailMode === "overview" && reportView === "none" ? "page" : undefined}>
              <span className="overview-link-copy">
                <span className="overview-link-title">Review overview</span>
                <span className="overview-link-meta">{synthesis.principal_concerns.length} principal {synthesis.principal_concerns.length === 1 ? "concern" : "concerns"}</span>
              </span>
              <span className="overview-link-chevron" aria-hidden="true">›</span>
            </button>
          )}
          <div className="rail-header">
            <h2>Comments</h2>
            <span className="rail-count" aria-label={`${filtered.length} of ${findings.length} comments shown`}>{activeFilters ? `${filtered.length} of ${findings.length}` : findings.length}</span>
          </div>
          <div className="queue-order" role="group" aria-label="Order comments">
            <button aria-pressed={queueOrder === "importance"} onClick={() => { setQueueOrder("importance"); try { if (persistenceMode === "local") window.localStorage.setItem(`review-desk:queue-order:${ledger.review_id}`, "importance"); } catch { /* preference remains session-local */ } }}>Reviewer priority</button>
            <button aria-pressed={queueOrder === "priority"} onClick={() => { setQueueOrder("priority"); try { if (persistenceMode === "local") window.localStorage.setItem(`review-desk:queue-order:${ledger.review_id}`, "priority"); } catch { /* preference remains session-local */ } }}>Severity</button>
            <button aria-pressed={queueOrder === "paper"} onClick={() => { setQueueOrder("paper"); try { if (persistenceMode === "local") window.localStorage.setItem(`review-desk:queue-order:${ledger.review_id}`, "paper"); } catch { /* preference remains session-local */ } }}>Paper order</button>
          </div>
          <label className="search-field">
            <span className="visually-hidden">Search comments</span>
            <input id="review-search" name="review-search" aria-keyshortcuts="/" ref={searchInput} value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search object, evidence, fix, or note" />
            <kbd>/</kbd>
          </label>
          <details className="filter-popover">
            <summary>Filters{activeFilters ? ` · ${activeFilters} active` : ""}</summary>
            <div className="filter-row">
            <select id="status-filter" name="status-filter" value={status} onChange={(event) => setStatus(event.target.value as WorkflowStatusFilter)} aria-label="Filter by progress">
              <option value="all">All progress</option>
              <option value="open">Open</option>
              <option value="ready_for_recheck">Ready for review</option>
              <option value="deferred">Set aside</option>
            </select>
            <select id="channel-filter" name="channel-filter" value={channel} onChange={(event) => setChannel(event.target.value as "all" | "substance" | "writing")} aria-label="Filter by comment category">
              <option value="all">All comments ({findings.length})</option>
              <option value="substance">Substance ({substanceCount})</option>
              <option value="writing">Editing comments ({editingCount})</option>
            </select>
              <select id="severity-filter" name="severity-filter" value={severity} onChange={(event) => setSeverity(event.target.value as "all" | Severity)} aria-label="Filter by severity">
                <option value="all">All severities</option>
                <option value="critical">Critical</option>
                <option value="major">Major</option>
                <option value="minor">Minor</option>
                <option value="info">Information</option>
              </select>
              <select id="decision-role-filter" name="decision-role-filter" value={decisionRole} onChange={(event) => setDecisionRole(event.target.value as "all" | DecisionRole)} aria-label="Filter by publication relevance">
                <option value="all">All publication roles</option>
                <option value="potentially_dispositive">Could prevent publication</option>
                <option value="posture_material">Recommendation material</option>
                <option value="revision_value">Revision value</option>
                <option value="polish">Polish</option>
              </select>
              <select id="dimension-filter" name="dimension-filter" value={dimension} onChange={(event) => setDimension(event.target.value)} aria-label="Filter by review dimension">
                <option value="all">All dimensions</option>
                {dimensions.map((value) => <option key={value} value={value}>{value}</option>)}
              </select>
              <select id="reviewed-filter" name="reviewed-filter" value={reviewedFilter} onChange={(event) => { focusAfterFilter.current = true; setReviewedFilter(event.target.value as "all" | "reviewed" | "unreviewed"); }} aria-label="Filter by reviewed state">
                <option value="all">All review states</option>
                <option value="reviewed">Reviewed</option>
                <option value="unreviewed">Not reviewed</option>
              </select>
              <select id="personal-priority-filter" name="personal-priority-filter" value={personalPriorityFilter} onChange={(event) => { focusAfterFilter.current = true; setPersonalPriorityFilter(event.target.value as "all" | "P0" | "P1" | "P2" | "unassigned"); }} aria-label="Filter by my priority">
                <option value="all">All personal priorities</option>
                <option value="P0">P0</option>
                <option value="P1">P1</option>
                <option value="P2">P2</option>
                <option value="unassigned">Unassigned</option>
              </select>
            </div>
            <p className="filter-help">Severity shows how much an issue affects the paper. Publication relevance reflects the reviewer’s assessment of how it could affect the recommendation.</p>
            {activeFilters > 0 && <button className="clear-filters" onClick={clearFilters}>Clear all filters</button>}
          </details>
          </div>
          <nav className="finding-list" aria-label={`${filtered.length} findings in the current filter`}>
            {filtered.map((finding, index) => {
              const entry = localState[finding.id] || defaultEntry(finding.id);
              const showSection = queueOrder === "paper" && (index === 0 || paperSection(filtered[index - 1]) !== paperSection(finding));
              return (
                <div key={finding.id} className="finding-group-row">
                {showSection && <h3 className="finding-section-heading">{paperSection(finding)}</h3>}
                <button
                  ref={(node) => { if (node) findingRefs.current.set(finding.id, node); else findingRefs.current.delete(finding.id); }}
                  className={`finding-row ${finding.id === selected.id ? "selected" : ""} severity-${finding.severity}`}
                  onClick={() => { selectAndFocus(finding.id); setMobilePane("comment"); setAnnouncement(`Selected ${commentLabel(findings, finding.id)}`); requestAnimationFrame(() => commentHeading.current?.focus()); }}
                  onKeyDown={(event) => onListKey(event, index)}
                  aria-keyshortcuts="J K R S N"
                  aria-current={finding.id === selected.id ? "true" : undefined}
                  tabIndex={finding.id === selected.id ? 0 : -1}
                >
                  <span className="rank">{finding.importance_rank}</span>
                  <span className="finding-copy">
                    <span className="finding-kicker">{channelLabel(finding)}</span>
                    <strong>{shortTitle(finding)}</strong>
                    <span className="row-semantics">
                      {entry.user_priority && <span className={`personal-priority priority-${entry.user_priority.toLowerCase()}`}>{entry.user_priority}</span>}
                      {entry.reviewed && <span className="reviewed-label">Reviewed</span>}
                      <span className={`row-severity severity-${finding.severity}`}>{finding.severity}</span>
                      <span className={`row-role role-${finding.decision_role || "unclassified"}`}>{shortDecisionRoleLabel(finding.decision_role)}</span>
                    </span>
                  </span>
                  <span className={`status-dot status-${workflowDecision(entry.disposition)}`} role="img" aria-label={`Author decision: ${dispositionDetailLabel(entry.disposition)}`} />
                </button>
                </div>
              );
            })}
            {!filtered.length && <p className="empty-state">No comments match these filters.</p>}
          </nav>
        </aside>

        {reportView !== "none" ? (
        <section id="review-detail" ref={reportReader} className={`report-reader side-by-side-reader ${mobilePane !== "comment" ? "mobile-hidden" : ""}`} aria-labelledby="report-reader-title" tabIndex={-1}>
          <h2 id="report-reader-title" ref={reportHeading} className="visually-hidden" tabIndex={-1}>Review document reader</h2>
          <div className="report-toolbar">
            <button ref={reportBackButton} className="report-close" onClick={openOverview}>← Overview</button>
            <label className="report-picker">
              <span>Document</span>
              <select value={activeDocument?.id || ""} onChange={(event) => { setReportView(event.target.value); pushViewState({ view: "document", document: event.target.value, finding: null, evidence: 0 }); }}>
                {documentGroups.map((group) => <optgroup key={group.group} label={group.label}>{group.documents.map((document) => <option key={document.id} value={document.id}>{document.title}</option>)}</optgroup>)}
              </select>
            </label>
          </div>
          <article className="report-document">
            <RenderedMarkdown components={reportComponents}>{withCommentJumpLinks(authorReportDisplayMarkdown(activeReport || "This report file was not included in the selected review bundle."))}</RenderedMarkdown>
          </article>
        </section>
        ) : detailMode === "plan" ? (
        <article id="review-detail" className={`comment-pane revision-plan-pane ${mobilePane !== "comment" ? "mobile-hidden" : ""}`} aria-labelledby="revision-plan-title" tabIndex={-1}>
          <div className="revision-plan-scroll">
            <button className="overview-crumb" onClick={openOverview}>← Overview</button>
            <div className="revision-plan-heading">
              <span className="eyebrow">{handoffReady ? "Ready to hand off" : "Draft handoff"}</span>
              <h2 id="revision-plan-title" ref={revisionPlanHeading} tabIndex={-1}>My revision plan</h2>
              <p>{handoffReady
                ? "Every comment is reviewed, each active task has a priority, and every item carries your instruction, response, or set-aside reason. These files are ready for the implementation round."
                : `${revisionGaps.length} comment${revisionGaps.length === 1 ? " has" : "s have"} missing decisions. You can inspect or export this clearly marked draft, but the implementation agent should not act on it yet.`}</p>
              <div className="plan-progress" role="progressbar" aria-label="Revision decisions reviewed" aria-valuemin={0} aria-valuemax={findings.length} aria-valuenow={reviewedCount} aria-valuetext={`Reviewed ${reviewedCount} of ${findings.length} comments`}>
                <span><i style={{ width: `${findings.length ? (reviewedCount / findings.length) * 100 : 0}%` }} /></span>
                <strong>{reviewedCount}/{findings.length} reviewed</strong>
              </div>
            </div>
            {!handoffReady && <section className="plan-missing-decisions" aria-labelledby="missing-decisions-title">
              <h3 id="missing-decisions-title">Finish these decisions before handoff</h3>
              <ol>{revisionGaps.map((gap) => <li key={gap.finding_id}>
                <button onClick={() => openFinding(gap.finding_id, `Opened ${commentLabel(findings, gap.finding_id)} to complete its revision decision`)}>
                  <strong>{findings.find((finding) => finding.id === gap.finding_id)?.title || "Comment awaiting a decision"}</strong>
                  <span>{gap.missing.map(missingDecisionLabel).join(" · ")}</span>
                </button>
              </li>)}</ol>
            </section>}
            <div className="revision-plan-actions" aria-label="Revision handoff exports">
              <button onClick={exportSession}>Download decisions</button>
              <button onClick={exportRevisionBrief}>Instructions for my editing agent</button>
              <button onClick={copyRevisionPlan}>Copy agent instructions</button>
              <button onClick={exportRevisionResponseTemplate}>Agent response form</button>
              <button onClick={exportRevisionTasks}>Advanced task file</button>
            </div>
            <section className="agent-instructions" aria-labelledby="agent-instructions-title">
              <h3 id="agent-instructions-title">Instructions for the implementation agent</h3>
              <ul>
                <li>Modify only the manuscript or source files placed in scope.</li>
                <li>Work through P0 before P1 and P2 unless a dependency requires a different order; explain any departure.</li>
                <li>Follow each user note; never invent evidence, results, citations, or completed checks.</li>
                <li>Report exact changed files and locations, summaries, checks, and blockers in the response template.</li>
                <li>Do not self-declare reviewer findings resolved; the next review round verifies every claimed change.</li>
                <li>Use <code>response_only</code> for a reasoned no-change answer; file edits are not required when the evidence supports the response.</li>
              </ul>
            </section>
            {revisionGroups.map(({ priority, tasks }) => (
              <section className="revision-task-group" key={priority || "unassigned"} aria-labelledby={`plan-${priority || "unassigned"}`}>
                <h3 id={`plan-${priority || "unassigned"}`}>{priority || "Priority unassigned"} <span>{tasks.length}</span></h3>
                {tasks.length ? <ol>{tasks.map((task: RevisionTask) => {
                  const taskEvidence = revisionEvidenceByFinding.get(task.finding_id);
                  return <li key={task.finding_id}>
                  <button onClick={() => openFinding(task.finding_id, `Opened ${commentLabel(findings, task.finding_id)} from my revision plan`)}>
                    <span>{workflowDecisionLabel(task.disposition)} · {task.reviewed ? "reviewed" : "needs review"}</span>
                    <strong>{task.title}</strong>
                    <small>{task.source_location}</small>
                  </button>
                  <dl className="revision-task-details">
                    <div><dt>Issue</dt><dd>{task.issue}</dd></div>
                    {task.relevant_text && <div><dt>Relevant text</dt><dd><EvidenceContent evidence={taskEvidence} content={task.relevant_text} compact /></dd></div>}
                    <div><dt>Suggestions</dt><dd>{task.suggestions}</dd></div>
                    <div><dt>Done when</dt><dd>{task.done_when}</dd></div>
                  </dl>
                  {task.user_comment && <pre aria-label={`User comment for ${task.title}`}>{task.user_comment}</pre>}
                </li>})}</ol> : <p>No tasks in this group.</p>}
              </section>
            ))}
            <section className="revision-task-group excluded-plan-group" aria-labelledby="excluded-plan-title">
              <h3 id="excluded-plan-title">Set aside <span>{revisionTasks.excluded.length}</span></h3>
              <p>These comments are outside the current implementation list. Their reasons remain attached for the next review round.</p>
              {revisionTasks.excluded.length ? <ol>{revisionTasks.excluded.map((task) => <li key={task.finding_id}>
                <button onClick={() => openFinding(task.finding_id, `Opened set-aside ${commentLabel(findings, task.finding_id)}`)}><span>{dispositionDetailLabel(task.disposition)} · {task.reviewed ? "reviewed" : "needs review"}</span><strong>{task.title}</strong></button>
                {task.user_comment && <pre aria-label={`User reason for ${task.title}`}>{task.user_comment}</pre>}
              </li>)}</ol> : <p>No comments are set aside.</p>}
            </section>
            <section className="next-round-note" aria-labelledby="next-round-title">
              <h3 id="next-round-title">Next round</h3>
              <p>Give the agent instructions, response form, and paper sources to your editing agent. Keep the decisions file for the next review. The next round checks the agent’s reported changes against the revised paper, decides which earlier concerns remain, and looks for new issues.</p>
            </section>
          </div>
        </article>
        ) : detailMode === "overview" ? (
        <article id="review-detail" className={`comment-pane overview-pane ${mobilePane !== "comment" ? "mobile-hidden" : ""}`} aria-labelledby="overview-title" tabIndex={-1}>
          <div className="overview-scroll">
            <div className="overview-heading">
              <span className="eyebrow">Referee report · {run.mode === "quick" ? "Quick review" : "Full review"}{(() => { const venue = typeof run.target === "string" ? run.target : run.target?.venue; return venue ? ` · Prepared for ${venue}` : ""; })()}</span>
              <h2 id="overview-title" ref={overviewHeading} tabIndex={-1}>{registry?.reviews.find((entry) => entry.slug === reviewSlug)?.title || "Review overview"}</h2>
              <div className="masthead-meta">
                {synthesis && synthesis.review_posture !== "not_assessed" && <span className={`posture-chip posture-${synthesis.review_posture}`}>{POSTURE_LABELS[synthesis.review_posture]}</span>}
                <span>{substanceCount} substantive {substanceCount === 1 ? "comment" : "comments"}{editingCount ? ` · ${editingCount} editing ${editingCount === 1 ? "comment" : "comments"}` : ""}</span>
                <span>{reviewedCount}/{findings.length} reviewed</span>
              </div>
              <div className="overview-actions masthead-actions">
                <button className="overview-primary" onClick={() => { const first = filtered[0] || findings[0]; if (first) openFinding(first.id, `Started with ${commentLabel(findings, first.id)}`); }}>Start with the first comment →</button>
                <button onClick={openRevisionPlan}>{handoffReady ? "My revision plan" : "Draft revision plan"}</button>
              </div>
            </div>
            {refereeReport ? (
              <article className="report-document overview-report">
                <RenderedMarkdown components={reportComponentsFor(refereeReport)}>{(() => {
                  // The landing shows the assessment letter; the detailed comments
                  // live in the interactive queue instead of being repeated here.
                  const cleaned = withCommentJumpLinks(authorReportDisplayMarkdown(refereeReport.content));
                  const detailedStart = cleaned.search(/^##\s+Detailed Comments/im);
                  const letter = detailedStart > 0 ? cleaned.slice(0, detailedStart) : cleaned;
                  return letter.replace(/^\s*#(?!#)[^\n]*\n+/, "").trimEnd();
                })()}</RenderedMarkdown>
                <div className="report-continuation">
                  <div className="report-continuation-copy">
                    <strong>Detailed comments ({substanceCount})</strong>
                    <span>Every comment continues in the queue with its manuscript evidence, suggested fix, and your decision controls{editingCount ? `, followed by ${editingCount} editing ${editingCount === 1 ? "comment" : "comments"}` : ""}.</span>
                  </div>
                  <button className="overview-primary" onClick={() => { const first = filtered[0] || findings[0]; if (first) openFinding(first.id, `Started with ${commentLabel(findings, first.id)}`); }}>Start with the first comment →</button>
                </div>
              </article>
            ) : <>
            {synthesis && synthesis.review_posture !== "not_assessed" && <div className="overview-posture"><span>Publication recommendation</span><strong>{POSTURE_LABELS[synthesis.review_posture]}</strong><p>{synthesis.posture_rationale}</p></div>}
            <p className="overview-assessment">{synthesis?.overall_assessment || "Start with the referee report, then work through the detailed comments."}</p>
            {synthesis?.principal_concerns.length ? <section className="overview-concerns" aria-labelledby="principal-concerns-title">
              <h3 id="principal-concerns-title">Principal concerns</h3>
              <ol className="concern-list">{synthesis.principal_concerns.map((concern, index) => <li key={concern.id}><button onClick={() => openPrincipalConcern(concern)}><span className="concern-index" aria-hidden="true">{String(index + 1).padStart(2, "0")}</span><span className="concern-copy"><strong>{concern.title}</strong><small>{concern.finding_ids.length} linked {concern.finding_ids.length === 1 ? "comment" : "comments"}</small></span><span className="concern-chevron" aria-hidden="true">›</span></button></li>)}</ol>
            </section> : null}
            <section className="overview-reading" aria-labelledby="reading-order-title">
              <h3 id="reading-order-title">Recommended path</h3>
              <ol><li>Read the assessment and principal concerns.</li><li>Resolve critical comments first, then major comments, before editing details.</li><li>Export actions for the next review round.</li></ol>
            </section>
            </>}
            <section className="overview-scope" aria-labelledby="reviewed-scope-title">
              <h3 id="reviewed-scope-title">What was reviewed</h3>
              <p>{reviewedScope}</p>
            </section>
            {uncheckedScope.length ? <section className="overview-scope" aria-labelledby="unchecked-scope-title">
              <h3 id="unchecked-scope-title">What could not be checked</h3>
              <ul>{uncheckedScope.map((item) => <li key={item}>{item}</li>)}</ul>
            </section> : null}
            {!refereeReport && <div className="overview-actions">
              <button className="overview-primary" onClick={() => { const first = filtered[0] || findings[0]; if (first) openFinding(first.id, `Started with ${commentLabel(findings, first.id)}`); }}>Start with the first comment →</button>
              <button onClick={openRevisionPlan}>{handoffReady ? "Open my revision plan" : "Open draft revision plan"}</button>
            </div>}
          </div>
        </article>
        ) : filtered.length ? <>
        {mobilePane === "evidence" && <div className="evidence-backdrop" aria-hidden="true" onClick={() => openMobilePane("comment")} />}
        <section id="evidence-panel" ref={documentPane} data-testid="evidence-context" className={`document-pane ${mobilePane !== "evidence" ? "mobile-hidden" : ""}`} aria-labelledby="evidence-heading">
          <div className="pane-heading">
            <div>
              <span className="eyebrow">Manuscript context</span>
              <h2 id="evidence-heading" ref={evidenceHeading} tabIndex={-1}>{locator(selected, activeEvidenceIndex)}</h2>
            </div>
            <div className="view-switcher" role="group" aria-label="Choose evidence view">
              <button aria-pressed={showEvidence} onClick={() => setShowEvidence(true)}>Evidence</button>
              <button aria-pressed={!showEvidence} onClick={() => setShowEvidence(false)}>Manuscript</button>
              <button className="evidence-close" aria-label="Close evidence context" onClick={() => openMobilePane("comment")}>Close</button>
            </div>
          </div>
          {evidenceAnchorIds.length > 1 && <div className="comparison-source-switcher" role="group" aria-label="Comparison passages">
            {evidenceAnchorIds.map((anchorId, index) => <button key={anchorId} aria-pressed={index === activeSourceAnchorIndex} title={sourceAnchors[anchorId]?.locator || anchorId} data-source-anchor={anchorId} onClick={() => {
              setSourceAnchorSelection({ evidenceKey: sourceEvidenceKey, index });
              setAnnouncement(`Showing source ${index + 1} for ${commentLabel(findings, selected.id)}`);
            }}><strong>{conciseSourceAnchorLabel(index, sourceAnchors[anchorId]?.locator || "")}</strong></button>)}
          </div>}
          {showEvidence ? (
            <div className="evidence-sheet">
              {selected.evidence.length > 1 && (
                <div className="evidence-switcher" role="group" aria-label="Evidence items">
                  {selected.evidence.map((item, index) => (
                    <button key={`${item.source}-${index}`} className={index === activeEvidenceIndex ? "active" : ""} aria-pressed={index === activeEvidenceIndex} onClick={() => { setEvidenceIndex(index); setAssetPathIndex(0); setExpandedEvidence(false); }}>
                      {index + 1}. {readableState(item.type)}
                    </button>
                  ))}
                </div>
              )}
              <div className="evidence-label"><span>{readableState(evidence?.type)}</span></div>
              <EvidenceContent evidence={evidence} content={evidenceContent} collapsed={evidence?.type === "quote" && !expandedEvidence && evidenceContent.length > 900} />
              {evidence?.type === "computation" && <ComputationProvenance computationId={evidence.computation_id} computation={computation} sourceAnchors={sourceAnchors} />}
              {evidence?.type === "quote" && evidenceContent.length > 900 && <button className="evidence-expand" aria-expanded={expandedEvidence} onClick={() => setExpandedEvidence((value) => !value)}>{expandedEvidence ? "Collapse evidence" : "Show full evidence"}</button>}
              {exhibit && activeExhibitPath && (
                <figure className="exhibit-preview">
                  {exhibit.renders.length > 1 && (
                    <div className="render-switcher" role="group" aria-label="Saved exhibit renders">
                      {exhibit.renders.map((render, index) => (
                        <button key={render.resolvedPath} aria-label={`Show ${render.label.toLowerCase()} for ${exhibit.label}`} aria-pressed={index === Math.min(assetPathIndex, exhibit.renders.length - 1)} onClick={() => setAssetPathIndex(index)}>{render.label}</button>
                      ))}
                    </div>
                  )}
                  <a className="exhibit-image-link" href={activeExhibitPath} target="_blank" rel="noopener noreferrer" aria-label={`Open ${activeExhibitRender?.label.toLowerCase() || "exhibit image"} for ${exhibit.label} at full size in a new tab`}>
                    <ExhibitImage src={activeExhibitPath} alt={`${exhibit.kind} ${exhibit.label}, ${activeExhibitRender?.label.toLowerCase() || "saved exhibit image"}${exhibit.pages.length ? `, PDF page ${exhibit.pages.join(", ")}` : ""}`} />
                  </a>
                  <figcaption><span>{activeExhibitRender?.label || "Saved exhibit image"} · {exhibit.label}{exhibit.pages.length ? ` · PDF p. ${exhibit.pages.join(", ")}` : ""}</span><a href={activeExhibitPath} target="_blank" rel="noopener noreferrer">Open full size</a></figcaption>
                </figure>
              )}
              {evidenceKind && evidence?.locator.exhibit && !activeExhibitPath && <div className="missing-exhibit" role="status"><strong>Exhibit image unavailable</strong><span>{exhibit?.missingPaths.length ? `${exhibit.missingPaths.length} saved image ${exhibit.missingPaths.length === 1 ? "was" : "were"} not included or could not be opened.` : "No saved image is available for this exhibit."} The evidence text and source location remain available.</span></div>}
              <dl className="source-grid">
                <div><dt>Source</dt><dd>{evidence?.source}</dd></div>
                <div><dt>Location</dt><dd>{locator(selected, activeEvidenceIndex)}</dd></div>
                <div><dt>Evidence type</dt><dd>{readableState(evidence?.type)}</dd></div>
              </dl>
              {selected.evidence_boundary && <div className="evidence-boundary"><strong>What this evidence establishes</strong><RenderedMarkdown>{selected.evidence_boundary}</RenderedMarkdown></div>}
            </div>
          ) : (
            <>
              <div className="manuscript-extraction-note">Plain-text reading copy of the manuscript source. Equations and symbols may not read as typeset; the Evidence view shows the checked excerpt.</div>
              <pre className="manuscript-sheet">{manuscriptExcerpt.message || <>{manuscriptExcerpt.before}{manuscriptExcerpt.highlight && <mark title="Matched manuscript passage">{manuscriptExcerpt.highlight}</mark>}{manuscriptExcerpt.after}{manuscriptExcerpt.exact && <span className="visually-hidden"> Exact manuscript passage matched.</span>}</>}</pre>
            </>
          )}
          <div className="document-footnote">The review text stays unchanged. Your progress and notes stay in this browser.</div>
        </section>

        <article id="review-detail" ref={commentPane} className={`comment-pane ${mobilePane !== "comment" ? "mobile-hidden" : ""}`} aria-labelledby="selected-comment-title" tabIndex={-1}>
          <div className="comment-scroll" data-testid="comment-scroll" ref={commentScroll}>
          <button className="overview-crumb" onClick={openOverview}>← Overview</button>
          <div className="comment-heading">
            <div className="comment-tags">
              <span className={`channel-pill channel-${selected.report_channel || "substance"}`}>{channelLabel(selected)}</span>
              <span className={`severity-pill severity-${selected.severity}`}>{selected.severity}</span>
              {selected.decision_role && <span className={`decision-role-pill role-${selected.decision_role}`}>{decisionRoleLabel(selected.decision_role)}</span>}
              <span>{selected.dimension}</span>
            </div>
            <div className="comment-position"><span>{Math.max(1, filteredPosition + 1)} of {filtered.length}</span></div>
          </div>
          <div className="comment-title-row">
            <h2 id="selected-comment-title" ref={commentHeading} tabIndex={-1}>{shortTitle(selected)}</h2>
            <div className="comment-navigation" aria-label="Move through filtered comments">
              <button aria-label="Previous comment" onClick={() => moveDetailSelection(-1)}>←</button>
              <button aria-label="Next comment" onClick={() => moveDetailSelection(1)}>→</button>
            </div>
          </div>
          {selected.confidence && <p className="confidence-note"><strong>Confidence: {selected.confidence.level}.</strong>{confidenceChangeText(selected.confidence.would_change_my_mind) && <> What would change the assessment: {confidenceChangeText(selected.confidence.would_change_my_mind)}</>}</p>}

          <section className="decision-block question-block">
            <span className="section-number">01</span>
            <div><h3>Issue</h3><RenderedMarkdown>{selected.issue}</RenderedMarkdown></div>
          </section>
          <section className="decision-block compact-evidence-block">
            <span className="section-number">02</span>
            <div>
              <h3>Relevant text</h3>
              <EvidenceContent evidence={evidence} content={evidenceContent} compact />
              {exhibit && activeExhibitPath && <figure className="inline-exhibit-preview">
                <ExhibitImage compact src={activeExhibitPath} alt={`${exhibit.kind} ${exhibit.label}, ${activeExhibitRender?.label.toLowerCase() || "saved exhibit image"}`} />
                <figcaption>{activeExhibitRender?.label || "Saved exhibit image"} · {exhibit.label}</figcaption>
              </figure>}
              {evidenceKind && evidence?.locator.exhibit && !activeExhibitPath && <div className="missing-exhibit compact" role="status"><strong>Exhibit image unavailable</strong><span>Open the evidence context for the source location.</span></div>}
              <button className="evidence-expand" onClick={() => openMobilePane("evidence")}>Open evidence context</button>
            </div>
          </section>
          <section className="decision-block">
            <span className="section-number">03</span>
            <div><h3>Concern</h3><RenderedMarkdown>{mergeDistinctText(selected.why_it_matters, selected.reader_effect)}</RenderedMarkdown></div>
          </section>
          <section className="revision-block recommendation-block">
            <div className="revision-heading"><span>Suggestions</span><small>{selected.fix.effort}</small></div>
            <RenderedMarkdown>{mergeDistinctText(selected.fix.what, selected.fix.how)}</RenderedMarkdown>
            <div className="completion-check"><strong>Ready to close when</strong><div className="completion-content"><RenderedMarkdown>{selected.fix.resolved_when || "Complete the stated revision path and reconcile the linked claims and evidence."}</RenderedMarkdown></div></div>
          </section>
          <section className="author-workspace">
            {!selectedIsSetAside && <div className="personal-priority-control" role="group" aria-label={`My priority for ${shortTitle(selected)}`}>
              <span>My priority <small>Orders my revision plan · does not change reviewer severity</small></span>
              <div>
                {(["P0", "P1", "P2"] as const).map((value) => <button
                  key={value}
                  type="button"
                  title={value === "P0" ? "Do first" : value === "P1" ? "Important next step" : "Address after higher-priority work"}
                  aria-label={value === "P0" ? "Set my priority to P0, do first" : value === "P1" ? "Set my priority to P1, important next step" : "Set my priority to P2, address later"}
                  aria-pressed={selectedEntry.user_priority === value}
                  className={selectedEntry.user_priority === value ? "active" : ""}
                  onClick={() => setPersonalPriority(selected.id, value)}
                ><strong>{value}</strong><small>{value === "P0" ? "Do first" : value === "P1" ? "Next" : "Later"}</small></button>)}
                <button
                  type="button"
                  className="priority-clear"
                  aria-label="Clear my personal priority"
                  disabled={!selectedEntry.user_priority}
                  onClick={() => setPersonalPriority(selected.id, null)}
                >Clear</button>
              </div>
            </div>}
            <button
              type="button"
              className={`reviewed-toggle ${selectedEntry.reviewed ? "active" : ""}`}
              aria-pressed={selectedEntry.reviewed}
              disabled={selectedIsPersistentSetAside}
              title={selectedIsPersistentSetAside ? "Reopen this comment before reconsidering the decision" : undefined}
              onClick={() => toggleReviewed(selected.id)}
            >
              <span className="reviewed-box" aria-hidden="true">{selectedEntry.reviewed || selectedIsPersistentSetAside ? "✓" : ""}</span>
              <span className="reviewed-copy">
                {selectedIsPersistentSetAside ? "Reviewed by decision" : selectedEntry.reviewed ? "Read and decided" : "Mark as read and decided"}
                <small>Counts toward review progress · set automatically when you choose Ready for review or Set aside</small>
              </span>
            </button>
            {selectedIsSetAside && <p className="plan-exclusion-note" role="status">{selectedEntry.disposition === "deferred"
              ? "Revisit later keeps this comment out of the current plan and brings it back for consideration next round."
              : "This comment stays outside later active rounds unless you reopen it. Record the reason below."}</p>}
            <label>
              <span>{selectedIsSetAside ? "Reason for setting aside" : "Instruction or response"} <small className={selectedNoteIsDraft || (persistenceMode === "local" && persistenceState !== "saved" && Boolean(selectedEntry.response_note.trim())) ? "note-unsaved" : ""}>{selectedNoteState}</small></span>
              <textarea id="author-note" name="author-note" ref={noteInput} maxLength={MAX_NOTE_CHARS} value={selectedNote} onChange={(event) => updateNoteDraft(selected.id, event.target.value)} onBlur={() => commitNote(selected.id)} placeholder={selectedIsSetAside ? "Explain this decision for the next review round…" : "Tell the editing agent what to change, or give a reasoned no-change response…"} />
              {selectedNote.length >= 9000 && <small id="note-character-limit" className="note-limit">{selectedNote.length.toLocaleString()} / {MAX_NOTE_CHARS.toLocaleString()}</small>}
            </label>
            <div className="handoff-actions">
              <button className="copy-button" onClick={copyRevisionBrief}>Copy revision brief</button>
              <button className="next-open-button" onClick={moveToNextOpen}>Next open comment</button>
              <button className="next-open-button" onClick={moveToNextUnreviewed}>Next unreviewed</button>
            </div>
            <details className="action-history">
              <summary>Action history <span>{selectedActionEvents.length}</span></summary>
              {selectedActionEvents.length ? <ol>{selectedActionEvents.map((event) => (
                <li key={event.event_id}>
                  <span>{actionEventLabel(event)}</span>
                  <time dateTime={event.at}>{new Date(event.at).toLocaleString(undefined, { dateStyle: "medium", timeStyle: "short" })}</time>
                </li>
              ))}</ol> : <p>No author actions have been recorded for this comment.</p>}
            </details>
          </section>
          </div>
          <section className="author-action-bar" data-testid="author-action-dock" aria-label="Author action for selected comment">
            <span className="dock-label" aria-hidden="true">My decision</span>
            <div className="workspace-actions" role="group" aria-label="Decision for this comment">
              <button title="This comment still needs work" aria-pressed={workflowDecision(selectedEntry.disposition) === "open"} className={workflowDecision(selectedEntry.disposition) === "open" ? "active" : ""} onClick={() => markFindingStatus(selected.id, "open")}>Open</button>
              <details ref={readyDecisionMenu} className={`decision-menu ${workflowDecision(selectedEntry.disposition) === "ready_for_recheck" ? "active" : ""}`} onToggle={(event) => { if (event.currentTarget.open && setAsideDecisionMenu.current) setAsideDecisionMenu.current.open = false; }}>
                <summary aria-label="Choose why this comment is ready for review"><span>Ready for review</span><span aria-hidden="true">⌃</span></summary>
                <div className="decision-menu-panel" role="group" aria-label="Ready for review options">
                  <button role="radio" aria-checked={selectedEntry.disposition === "ready_for_recheck"} onClick={() => markFindingStatus(selected.id, "ready_for_recheck")}><strong>Change made</strong><small>The revision is ready to check</small></button>
                  <button role="radio" aria-checked={selectedEntry.disposition === "challenged"} onClick={() => markFindingStatus(selected.id, "challenged")}><strong>Reasoned response</strong><small>No change; the response is ready to assess</small></button>
                </div>
              </details>
              <details ref={setAsideDecisionMenu} className={`decision-menu ${selectedIsSetAside ? "active" : ""}`} onToggle={(event) => { if (event.currentTarget.open && readyDecisionMenu.current) readyDecisionMenu.current.open = false; }}>
                <summary aria-label="Choose why this comment is set aside"><span>Set aside</span><span aria-hidden="true">⌃</span></summary>
                <div className="decision-menu-panel" role="group" aria-label="Set aside options">
                  <button role="radio" aria-checked={selectedEntry.disposition === "deferred"} onClick={() => markFindingStatus(selected.id, "deferred")}><strong>Revisit later</strong><small>Returns for consideration next round</small></button>
                  <button role="radio" aria-checked={selectedEntry.disposition === "not_relevant"} onClick={() => markFindingStatus(selected.id, "not_relevant")}><strong>Does not apply</strong><small>Stays out unless reopened</small></button>
                  <button role="radio" aria-checked={selectedEntry.disposition === "not_addressable"} onClick={() => markFindingStatus(selected.id, "not_addressable")}><strong>Cannot address</strong><small>Stays out unless reopened</small></button>
                </div>
              </details>
            </div>
          </section>
        </article>
        </> : (
          <section id="review-detail" ref={noResultsRef} className="no-filter-results" tabIndex={-1} aria-live="polite">
            <span className="eyebrow">{findings.length ? "No matching comments" : "Review"}</span>
            <h2>{findings.length ? "The active filters exclude every finding." : "No comments are recorded in this review."}</h2>
            <p>{findings.length ? "The detail and manuscript panes are intentionally blank so they cannot show an item outside the filtered queue." : "You can still read every available report and plan from the Documents button."}</p>
            {findings.length ? <button onClick={clearFilters}>Clear filters</button> : documents.length ? <button onClick={() => { setReportView(documents[0].id); pushViewState({ view: "document", document: documents[0].id, finding: null, evidence: 0 }); }}>Open documents</button> : null}
          </section>
        )}
      </div>}
      <div className="visually-hidden" aria-live="polite" aria-atomic="true">{announcement}</div>
    </main>
  );
}
