import type { ReviewEvidenceLocator } from "./review-evidence-contract.ts";

function sectionLabel(value: string) {
  return /^(?:section|sections|abstract|appendix|online appendix|front matter|end matter|table|figure|treatment|references)\b/i.test(value)
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
  const section = value.section?.trim() || "";
  const equation = value.equation?.trim() || "";
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
    section && sectionLabel(section),
    value.paragraph && `para. ${value.paragraph}`,
    value.exhibit,
    equation && !equationAlreadyCovered && equationLabel(equation),
    value.page && `p. ${value.page}`,
    value.lines && `lines ${value.lines}`,
  ].filter((part): part is string => Boolean(part));
  const unique = parts.filter((part, index) => parts.findIndex((candidate) => candidate.toLocaleLowerCase() === part.toLocaleLowerCase()) === index);
  return unique.join(" · ") || "Manuscript";
}
