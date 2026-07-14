export type ReviewTextAnchor = {
  id: string;
  start_char: number | null;
  end_char: number | null;
  content_sha256: string;
};

export type ManuscriptExcerpt = {
  before: string;
  highlight: string;
  after: string;
  message: string;
  exact: boolean;
};

export function sourceAnchorPageLabel(locator: string): string | null {
  const page = locator.match(/\b(?:PDF\s+)?p(?:age)?\.?\s*(\d+)\b/i)?.[1];
  return page ? `p. ${page}` : null;
}

const INTERNAL_LOCATOR_TOKEN = /(?:\b(?:SRC-\d+(?:-PDF-B\d+)?|ANC-\d+|PDF-B\d+)\b|\bbbox\b|\b(?:block|block_id|anchor_id|source_id)\s*[:=]\s*\S+|\bblock\s+id\s*[:=]\s*\S+|\b(?:extraction_method|parser_method|ocr_method)\s*[:=]\s*\S+|\bmethod\s*[:=]\s*(?:pdf_text_layer|ocr|tesseract|poppler|mathpix)\b|\bsha(?:-?256)?\s*[:=]\s*[0-9a-f]{32,64}\b|\bpage\s*=\s*\d+\b|<!--|-->)/i;

/** Return only a location that helps a reader navigate the manuscript. */
export function readerFacingSourceAnchorLocation(locator: string): string {
  const page = sourceAnchorPageLabel(locator);
  if (page) return page;
  const normalized = locator.replace(/\s+/g, " ").trim();
  return normalized && !INTERNAL_LOCATOR_TOKEN.test(normalized)
    ? normalized
    : "Manuscript location";
}

export function conciseSourceAnchorLabel(index: number, locator: string): string {
  const location = readerFacingSourceAnchorLocation(locator);
  return location === "Manuscript location"
    ? `Source ${index + 1}`
    : `Source ${index + 1} · ${location}`;
}

/** Remove ingestion-only HTML comments, including fragments at slice edges. */
export function stripGeneratedAnchorComments(value: string): string {
  let cleaned = value.replace(/<!--[\s\S]*?-->/g, "");
  const partialClose = cleaned.indexOf("-->");
  if (partialClose >= 0 && partialClose < 500 && !cleaned.slice(0, partialClose).includes("<!--")) {
    cleaned = cleaned.slice(partialClose + 3);
  }
  const partialOpen = cleaned.lastIndexOf("<!--");
  if (partialOpen >= 0 && !cleaned.slice(partialOpen).includes("-->")) cleaned = cleaned.slice(0, partialOpen);
  return cleaned.replace(/\n{3,}/g, "\n\n");
}

const WORD_CHARACTER = /[\p{L}\p{N}\p{M}_]/u;

function isWordCharacter(value: string | undefined): boolean {
  return Boolean(value && WORD_CHARACTER.test(value));
}

/** Move a bounded slice inward only when it would begin or end inside a word. */
export function alignContextToWordBoundaries(manuscript: string, start: number, end: number): [number, number] {
  let alignedStart = Math.max(0, Math.min(manuscript.length, start));
  let alignedEnd = Math.max(alignedStart, Math.min(manuscript.length, end));
  if (
    alignedStart > 0 && alignedStart < manuscript.length
    && isWordCharacter(manuscript[alignedStart - 1]) && isWordCharacter(manuscript[alignedStart])
  ) {
    while (alignedStart < alignedEnd && isWordCharacter(manuscript[alignedStart])) alignedStart += 1;
  }
  if (
    alignedEnd > alignedStart && alignedEnd < manuscript.length
    && isWordCharacter(manuscript[alignedEnd - 1]) && isWordCharacter(manuscript[alignedEnd])
  ) {
    while (alignedEnd > alignedStart && isWordCharacter(manuscript[alignedEnd - 1])) alignedEnd -= 1;
  }
  return [alignedStart, Math.max(alignedStart, alignedEnd)];
}

/** Resolve one manifest anchor without falling through to an unrelated passage. */
export function exactAnchorExcerpt(
  manuscript: string,
  anchor: ReviewTextAnchor,
  hashText: (value: string) => string,
  contextBefore = 700,
  contextAfter = 1900,
): ManuscriptExcerpt {
  const message = (value: string): ManuscriptExcerpt => ({ before: "", highlight: "", after: "", message: value, exact: false });
  if (anchor.start_char === null || anchor.end_char === null) {
    return message("This source passage does not declare a text span. Use the checked evidence and its manuscript location.");
  }
  const { start_char: start, end_char: end } = anchor;
  if (start < 0 || end < start || end > manuscript.length || hashText(manuscript.slice(start, end)) !== anchor.content_sha256) {
    return message("This source passage did not match the loaded manuscript text and was not highlighted. Use the checked evidence and verify the review package.");
  }
  const [beforeStart] = alignContextToWordBoundaries(manuscript, Math.max(0, start - contextBefore), start);
  const [, afterEnd] = alignContextToWordBoundaries(manuscript, end, Math.min(manuscript.length, end + contextAfter));
  return {
    before: stripGeneratedAnchorComments(manuscript.slice(beforeStart, start)),
    highlight: manuscript.slice(start, end),
    after: stripGeneratedAnchorComments(manuscript.slice(end, afterEnd)),
    message: "",
    exact: true,
  };
}
