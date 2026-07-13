import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import {
  classifyExhibitRender,
  orderExhibitRenders,
} from "../lib/review-exhibit-presentation.ts";

test("classifies common object crops and complete source pages without paper-specific paths", () => {
  assert.equal(classifyExhibitRender("evidence/pdf-ingestion/SRC-99/objects/figures/SRC-99-PDF-FIG-004.png"), "exhibit_crop");
  assert.equal(classifyExhibitRender("evidence/crops/table-2.png"), "exhibit_crop");
  assert.equal(classifyExhibitRender("evidence/figures/figure-b1-page-50.png"), "exhibit_crop");
  assert.equal(classifyExhibitRender("evidence/renders/page-0050.png"), "full_source_page");
  assert.equal(classifyExhibitRender("evidence/renders/tables/page-11.jpg"), "full_source_page");
  assert.equal(classifyExhibitRender("vendor/output/image-a.png"), "saved_exhibit_image");
});

test("makes an exhibit crop the default even when a manifest lists the full page first", () => {
  const renders = orderExhibitRenders([
    { sourcePath: "evidence/renders/page-0020.png", resolvedPath: "/review/page-0020.png" },
    { sourcePath: "evidence/objects/figures/Figure-1.png", resolvedPath: "/review/Figure-1.png" },
  ]);

  assert.deepEqual(renders.map((render) => ({ role: render.role, label: render.label, path: render.resolvedPath })), [
    { role: "exhibit_crop", label: "Exhibit crop", path: "/review/Figure-1.png" },
    { role: "full_source_page", label: "Full source page · p. 20", path: "/review/page-0020.png" },
  ]);
});

test("uses honest fallback labels and preserves stable order within a render class", () => {
  const renders = orderExhibitRenders([
    { sourcePath: "vendor/output/overview.png", resolvedPath: "blob:overview" },
    { sourcePath: "vendor/output/detail.png", resolvedPath: "blob:detail" },
    { sourcePath: "evidence/crops/object-a.png", resolvedPath: "blob:crop" },
  ]);

  assert.deepEqual(renders.map((render) => render.label), [
    "Exhibit crop",
    "Saved exhibit image 1",
    "Saved exhibit image 2",
  ]);
  assert.deepEqual(renders.map((render) => render.resolvedPath), ["blob:crop", "blob:overview", "blob:detail"]);
});

test("deduplicates identical resolved images while retaining all distinct views", () => {
  const renders = orderExhibitRenders([
    { sourcePath: "evidence/renders/page-0003.png", resolvedPath: "/page.png" },
    { sourcePath: "alternate/page-0003.png", resolvedPath: "/page.png" },
    { sourcePath: "evidence/objects/tables/TBL-003.png", resolvedPath: "/crop.png" },
  ]);

  assert.equal(renders.length, 2);
  assert.equal(renders[0].resolvedPath, "/crop.png");
  assert.equal(renders[1].resolvedPath, "/page.png");
});

test("the viewer uses the ordered render for both evidence views and exposes descriptive controls", async () => {
  const workspace = await readFile(new URL("../app/review-workspace.tsx", import.meta.url), "utf8");
  assert.match(workspace, /orderExhibitRenders/);
  assert.match(workspace, /activeExhibitRender/);
  assert.match(workspace, /aria-label=\{`Show \$\{render\.label\.toLowerCase\(\)\}/);
  assert.match(workspace, /\{render\.label\}<\/button>/);
  assert.doesNotMatch(workspace, />Render \{index \+ 1\}<\/button>/);
  assert.ok((workspace.match(/activeExhibitRender\?\.label/g) || []).length >= 4, "full and compact evidence views should describe the selected render");
});
