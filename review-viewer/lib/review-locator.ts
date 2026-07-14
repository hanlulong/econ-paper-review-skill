import type { ReviewEvidenceLocator } from "./review-evidence-contract.ts";
import { readerFacingSourceAnchorLocation } from "./review-manuscript-context.ts";

function sectionLabel(value: string) {
  return /^(?:section|sections|abstract|appendix|online appendix|front matter|end matter|table|figure|equation|block|treatment|references)\b/i.test(value)
    ? value
    : `Section ${value}`;
}

function equationLabel(value: string) {
  return /\b(?:eq\.?|equation)\b/i.test(value) ? value : `Eq. ${value}`;
}

function canonicalEquationLocation(value: string) {
  return value
    .toLocaleLowerCase()
    .replace(/\b(?:sections?|eq\.?|equations?)\b/g, " ")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();
}

/**
 * Format a manuscript location for readers. Internal package paths are
 * intentionally excluded; they remain available in canonical technical
 * metadata. Equation text is omitted when the section already names it.
 */
export function formatUserFacingLocator(value: ReviewEvidenceLocator | undefined): string {
  if (!value) return "Location unavailable";
  const readable = (raw: string | null | undefined) => {
    if (!raw?.trim()) return "";
    const location = readerFacingSourceAnchorLocation(raw);
    return location === "Manuscript location" ? "" : location;
  };
  const section = readable(value.section);
  const equation = readable(value.equation);
  const sectionEquation = canonicalEquationLocation(section);
  const equationLocation = canonicalEquationLocation(equation);
  const sectionNamesEquation = /\b(?:eq\.?|equation)\b/i.test(section);
  const equationAlreadyCovered = Boolean(
    section && equation && (
      sectionEquation === equationLocation
      || (sectionNamesEquation && equationLocation && sectionEquation.includes(equationLocation))
    )
  );

  const parts = [
    section && (/^p\.\s*\d+$/i.test(section) ? section : sectionLabel(section)),
    readable(value.paragraph) && `para. ${readable(value.paragraph)}`,
    readable(value.exhibit),
    equation && !equationAlreadyCovered && equationLabel(equation),
    value.page && `p. ${value.page}`,
    readable(value.lines) && `lines ${readable(value.lines)}`,
  ].filter((part): part is string => Boolean(part));
  const unique = parts.filter((part, index) => parts.findIndex((candidate) => candidate.toLocaleLowerCase() === part.toLocaleLowerCase()) === index);
  return unique.join(" · ") || "Manuscript";
}
