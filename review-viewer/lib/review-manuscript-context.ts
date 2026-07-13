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

export function conciseSourceAnchorLabel(index: number, locator: string): string {
  const page = sourceAnchorPageLabel(locator);
  return page ? `Source ${index + 1} · ${page}` : `Source ${index + 1}`;
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
    return message(`Source anchor ${anchor.id} does not declare a text span. Use its recorded locator and the structured evidence.`);
  }
  const { start_char: start, end_char: end } = anchor;
  if (start < 0 || end < start || end > manuscript.length || hashText(manuscript.slice(start, end)) !== anchor.content_sha256) {
    return message(`Source anchor ${anchor.id} did not match the loaded manuscript text and was not highlighted. Use the structured evidence and verify the source package.`);
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
