import { createElement, type ReactNode } from "react";
import type { ReviewEvidenceRepresentation } from "./review-evidence-contract.ts";

export type TextEvidencePresentation = {
  kind: "source_excerpt" | "evidence_note";
  label: string;
};

const SOURCE_EXCERPT_LABELS: Partial<Record<ReviewEvidenceRepresentation, string>> = {
  verbatim: "Verbatim source excerpt",
  normalized_transcription: "Rendered source transcription",
};

const EVIDENCE_NOTE_LABELS: Partial<Record<ReviewEvidenceRepresentation, string>> = {
  reviewer_observation: "Reviewer observation",
  composite_comparison: "Reviewer comparison",
  computed_result: "Computed result",
  checked_absence: "Checked absence",
};

const INTERNAL_PREFIXES: Partial<Record<ReviewEvidenceRepresentation, RegExp>> = {
  normalized_transcription: /^\[Rendered transcription\]\s*/,
  reviewer_observation: /^\[(?:Reviewer|Figure|Table) observation\]\s*/,
  composite_comparison: /^\[Reviewer comparison\]\s*/,
  computed_result: /^\[Computation\]\s*/,
  checked_absence: /^\[Checked absence\]\s*/,
};

/** Remove a matching legacy storage token from visible evidence text. */
export function evidenceDisplayText(
  content: string,
  representation?: ReviewEvidenceRepresentation,
): string {
  const prefix = representation ? INTERNAL_PREFIXES[representation] : undefined;
  return prefix ? content.replace(prefix, "") : content;
}

/** Clean old generated report blocks without changing their stored Markdown. */
export function authorReportDisplayMarkdown(markdown: string): string {
  const lines = markdown
    // The review-package navigation block is for people reading the files
    // directly; Review Desk provides its own navigation.
    .replace(/<!-- review-navigation:start -->[\s\S]*?<!-- review-navigation:end -->\n?/g, "")
    .split("\n")
    // Per-comment "[Pending]" status lines are workflow boilerplate; Review Desk
    // tracks each comment's real decision state itself.
    .filter((line) => !/^\*\*Status\*\*:\s*\[Pending\]\s*$/.test(line));
  let derivedBlock = false;
  return lines.map((line) => {
    const derived = line.match(
      /^>\s*\[(?:Reviewer observation|Figure observation|Table observation|Reviewer comparison|Checked absence|Computation)\]\s*(.*)$/,
    );
    if (derived) {
      derivedBlock = true;
      return derived[1];
    }
    if (derivedBlock) {
      const continuation = line.match(/^>\s?(.*)$/);
      if (continuation) return continuation[1];
      derivedBlock = false;
    }
    return line.replace(/^>\s*\[Rendered transcription\]\s*/, "> ");
  }).join("\n");
}

/**
 * Choose outer semantics for canonical evidence. Quotation styling depends on
 * provenance representation, not the source object's type. Missing legacy
 * metadata falls back conservatively to a neutral note rather than implying a
 * verbatim quotation.
 */
export function textEvidencePresentation(
  representation?: ReviewEvidenceRepresentation,
): TextEvidencePresentation {
  const sourceLabel = representation ? SOURCE_EXCERPT_LABELS[representation] : undefined;
  if (sourceLabel) return { kind: "source_excerpt", label: sourceLabel };

  const noteLabel = representation ? EVIDENCE_NOTE_LABELS[representation] : undefined;
  return { kind: "evidence_note", label: noteLabel || "Evidence note" };
}

/** A representation-first semantic frame shared by full and compact evidence views. */
export function EvidenceSemanticFrame({
  representation,
  compact = false,
  collapsed = false,
  children,
}: {
  representation?: ReviewEvidenceRepresentation;
  compact?: boolean;
  collapsed?: boolean;
  children: ReactNode;
}) {
  const presentation = textEvidencePresentation(representation);
  const className = [
    presentation.kind === "source_excerpt" ? "source-excerpt" : "evidence-note",
    compact ? "compact" : "",
    collapsed ? "evidence-collapsed" : "",
  ].filter(Boolean).join(" ");
  if (presentation.kind === "source_excerpt") {
    return createElement("blockquote", { className, "aria-label": presentation.label }, children);
  }
  return createElement("div", { className, role: "note", "aria-label": presentation.label }, children);
}
