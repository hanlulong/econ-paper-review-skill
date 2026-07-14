import type { ReviewEvidenceRepresentation } from "./review-evidence-contract.ts";

export type EquationEvidencePresentation = {
  kind: "display_math" | "markdown_math" | "prose";
  content: string;
};

const EMPTY_EQUATION_EVIDENCE = "No equation evidence is available.";
const EVIDENCE_LABEL = /^\s*\[(?:Rendered transcription|Reviewer comparison|Figure observation|Table observation|Checked absence|Computation)\]/i;
const PROSE_REPRESENTATIONS: ReadonlySet<ReviewEvidenceRepresentation> = new Set([
  "composite_comparison",
  "reviewer_observation",
  "checked_absence",
  "computed_result",
]);

/**
 * Detect math that the Markdown pipeline can render without changing the
 * author's evidence string. A matched pair is required so currency symbols or
 * an isolated OCR dollar sign do not switch an entire sentence into math mode.
 */
export function hasDelimitedMath(content: string): boolean {
  return (
    /\$\$[\s\S]+?\$\$/.test(content)
    || /\\\[[\s\S]+?\\\]/.test(content)
    || /\\\([\s\S]+?\\\)/.test(content)
    || /(^|[^\\])\$(?!\s)(?:\\.|[^$\n])+?\$(?!\d)/m.test(content)
  );
}

const MARKDOWN_PROTECTED_SPAN = /(```[\s\S]*?```|~~~[\s\S]*?~~~|`[^`\n]*`|\$\$[\s\S]*?\$\$|\\\[[\s\S]*?\\\]|\\\([\s\S]*?\\\)|(^|[^\\])\$(?!\s)(?:\\.|[^$\n])+?\$(?!\d)|!?\[[^\]\n]*\]\([^)\n]+\)|<https?:\/\/[^>\n]+>)/gm;
const SIMPLE_UNDELIMITED_SUBSCRIPT = /(?<![\p{L}\p{N}_])([\p{L}])_\{?([\p{L}\p{N}]+)\}?(?![\p{L}\p{N}_])/gu;

/**
 * Make isolated TeX-style variables readable in otherwise ordinary prose.
 *
 * Canonical review text should delimit mathematics explicitly. Older reviews
 * sometimes contain prose such as `R_b times b_j`, however. Wrapping only a
 * single-letter base with a subscript removes the raw underscores without
 * guessing that filenames, snake_case fields, links, code, or existing math
 * are equations.
 */
export function prepareReviewMarkdown(content: string): string {
  let cursor = 0;
  const output: string[] = [];
  for (const match of content.matchAll(MARKDOWN_PROTECTED_SPAN)) {
    const index = match.index ?? 0;
    const leading = match[2] || "";
    const protectedStart = index + leading.length;
    const plain = content.slice(cursor, protectedStart);
    output.push(plain.replace(SIMPLE_UNDELIMITED_SUBSCRIPT, (_value, base, subscript) => `$${base}_{${subscript}}$`));
    output.push(content.slice(protectedStart, index + match[0].length));
    cursor = index + match[0].length;
  }
  output.push(content.slice(cursor).replace(
    SIMPLE_UNDELIMITED_SUBSCRIPT,
    (_value, base, subscript) => `$${base}_{${subscript}}$`,
  ));
  return output.join("");
}

function proseWordProfile(content: string) {
  const withoutTexCommands = content
    .replace(/\\(?:begin|end)\s*\{[^}]*\}/g, " ")
    .replace(/\\[A-Za-z]+\*?/g, " ")
    .replace(/[A-Za-z]+\s*_/g, " ");
  const words = withoutTexCommands.match(/\p{L}{2,}/gu) ?? [];
  const commonWords = words.filter((word) => /^(?:a|an|and|are|as|at|be|because|but|by|called|dividing|equation|for|from|has|in|is|it|of|on|or|printed|that|the|their|this|to|under|using|when|while|with|writes)$/i.test(word));
  return { wordCount: words.length, commonWordCount: commonWords.length };
}

function mathScore(content: string) {
  let score = 0;
  if (/[=<>]|\\(?:leq?|geq?|approx|propto|sim)\b/.test(content)) score += 3;
  if (/\\(?:frac|dfrac|tfrac|sum|prod|int|partial|sqrt|lim|mathbb|mathbf|boldsymbol|begin|left|right)\b/.test(content)) score += 2;
  if (/(?:[A-Za-zΑ-Ωα-ω](?:(?:_|\^)\{?[^}\s]+\}?)?|[0-9]+)\s*[+*/-]\s*(?:[A-Za-zΑ-Ωα-ω](?:(?:_|\^)\{?[^}\s]+\}?)?|[0-9]+)/.test(content)) score += 2;
  if (/^\s*[A-Za-zΑ-Ωα-ω](?:(?:_|\^)\{?[^}\s]+\}?)?\s*[([][^\])]+[\])]\s*$/.test(content)) score += 2;
  if (/(?:_|\^)(?:\{|[A-Za-z0-9])/.test(content)) score += 1;
  if (/[{}]/.test(content)) score += 1;
  if (/^\s*(?:\\[A-Za-z]+|[A-Za-zΑ-Ωα-ω]\s*(?:[_^[(+*/-]|=)|[0-9]+\s*[+\-*/=])/.test(content)) score += 1;
  return score;
}

function proseScore(content: string) {
  const { wordCount, commonWordCount } = proseWordProfile(content);
  let score = 0;
  if (EVIDENCE_LABEL.test(content)) score += 8;
  if (/^\s*(?:\[[^\]]+\]\s*)?[“"][\s\S]*[”"]\s*$/.test(content)) score += 4;
  if (wordCount >= 1 && /^[^=<>]{1,80}:\s*/u.test(content)) score += 3;
  if (/^\s*(?:Equation|Eq\.)\s*\(?[A-Za-z0-9.-]+\)?/i.test(content)) score += 4;
  if (commonWordCount >= 1) score += 2;
  if (wordCount >= 7) score += 2;
  if (/[.!?][”"']?\s*$/.test(content)) score += 1;
  return score;
}

/**
 * Decide how an `equation` evidence payload should be displayed.
 *
 * The evidence type identifies the source object, not necessarily the syntax
 * of `content`: reviewer observations and normalized render transcriptions can
 * be ordinary prose that happens to mention symbols. We only add display-math
 * delimiters when the payload is equation-shaped. Existing Markdown math is
 * passed through unchanged, and everything else remains literal prose.
 */
export function equationEvidencePresentation(
  content: string,
  representation?: ReviewEvidenceRepresentation,
): EquationEvidencePresentation {
  const value = content.trim();
  if (!value) return { kind: "prose", content: EMPTY_EQUATION_EVIDENCE };
  if (hasDelimitedMath(value)) return { kind: "markdown_math", content: value };
  // Preserve malformed or unmatched delimiters literally. Adding an outer
  // display wrapper would otherwise produce invalid or misleading KaTeX.
  if (/\$|\\[()[\]]/.test(value)) return { kind: "prose", content: value };
  // These representations are reviewer-derived or computed prose by contract.
  // Requiring explicit delimiters prevents English-only heuristics from turning
  // short or non-English observations containing `=` into a KaTeX expression.
  if (representation && PROSE_REPRESENTATIONS.has(representation)) return { kind: "prose", content: value };

  const equationLikelihood = mathScore(value);
  const proseLikelihood = proseScore(value);
  if (equationLikelihood >= 3 && equationLikelihood > proseLikelihood) {
    return { kind: "display_math", content: `$$\n${value}\n$$` };
  }
  return { kind: "prose", content: value };
}
