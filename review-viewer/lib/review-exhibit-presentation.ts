export type ExhibitRenderRole = "exhibit_crop" | "saved_exhibit_image" | "full_source_page";

export type ExhibitRenderInput = {
  sourcePath: string;
  resolvedPath: string;
  declaredRole?: ExhibitRenderRole;
};

export type ExhibitRender = ExhibitRenderInput & {
  role: ExhibitRenderRole;
  label: string;
};

function pathWithoutQuery(value: string) {
  return value.split(/[?#]/, 1)[0].replace(/\\/g, "/").toLowerCase();
}

export function classifyExhibitRender(sourcePath: string): ExhibitRenderRole {
  const path = pathWithoutQuery(sourcePath);
  const basename = path.slice(path.lastIndexOf("/") + 1);

  // A page-only filename is the strongest portable signal that an image is a
  // complete PDF page, including manifests that store those pages in a
  // figure- or table-named directory.
  if (/^page[-_ ]*0*\d+\.[a-z0-9]+$/i.test(basename)) return "full_source_page";

  // Ingestion backends use different names, but object/crop directories and
  // figure/table object filenames consistently describe an isolated exhibit.
  if (
    /(?:^|\/)(?:objects?|crops?|extractions?)(?:\/|$)/i.test(path)
    || /(?:^|[-_. ])(?:crop|cropped|object)(?:[-_. ]|$)/i.test(basename)
    || /^(?:fig(?:ure)?|tbl|table)[-_ ]*[a-z0-9]+/i.test(basename)
  ) return "exhibit_crop";

  // Keep this deliberately narrower than a generic "page" substring: an
  // exhibit crop may legitimately include its source page in its filename.
  if (/(?:^|\/)(?:pages?|page-renders?)(?:\/|$)/i.test(path)) return "full_source_page";

  return "saved_exhibit_image";
}

function pageNumber(sourcePath: string) {
  const basename = pathWithoutQuery(sourcePath).slice(pathWithoutQuery(sourcePath).lastIndexOf("/") + 1);
  const match = /^page[-_ ]*0*(\d+)\.[a-z0-9]+$/i.exec(basename);
  return match ? Number(match[1]) : null;
}

function baseLabel(role: ExhibitRenderRole, sourcePath: string) {
  if (role === "exhibit_crop") return "Exhibit crop";
  if (role === "full_source_page") {
    const page = pageNumber(sourcePath);
    return page === null ? "Full source page" : `Full source page · p. ${page}`;
  }
  return "Saved exhibit image";
}

const rolePriority: Record<ExhibitRenderRole, number> = {
  exhibit_crop: 0,
  saved_exhibit_image: 1,
  full_source_page: 2,
};

/**
 * Orders an exhibit's saved images by reader usefulness. An isolated crop is
 * the default whenever one is available; the complete source page remains
 * available as context. Unknown producer-specific images retain their input
 * order between those two known classes.
 */
export function orderExhibitRenders(inputs: ExhibitRenderInput[]): ExhibitRender[] {
  const seen = new Set<string>();
  const classified = inputs
    .filter((input) => {
      if (seen.has(input.resolvedPath)) return false;
      seen.add(input.resolvedPath);
      return true;
    })
    .map((input, originalIndex) => ({
      ...input,
      originalIndex,
      role: input.declaredRole || classifyExhibitRender(input.sourcePath),
    }))
    .sort((left, right) => rolePriority[left.role] - rolePriority[right.role] || left.originalIndex - right.originalIndex);

  const totals = classified.reduce<Record<ExhibitRenderRole, number>>((counts, render) => {
    counts[render.role] += 1;
    return counts;
  }, { exhibit_crop: 0, saved_exhibit_image: 0, full_source_page: 0 });
  const positions: Record<ExhibitRenderRole, number> = { exhibit_crop: 0, saved_exhibit_image: 0, full_source_page: 0 };

  return classified.map((render) => {
    positions[render.role] += 1;
    const base = baseLabel(render.role, render.sourcePath);
    const label = totals[render.role] > 1 && !base.includes("· p.")
      ? `${base} ${positions[render.role]}`
      : base;
    return {
      sourcePath: render.sourcePath,
      resolvedPath: render.resolvedPath,
      role: render.role,
      label,
    };
  });
}
