import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";

const css = await readFile(new URL("../app/globals.css", import.meta.url), "utf8");

function declarations(selector) {
  const escaped = selector.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const match = new RegExp(`${escaped}\\s*\\{([^}]+)\\}`).exec(css);
  assert.ok(match, `missing CSS rule for ${selector}`);
  return match[1];
}

test("evidence-sheet content keeps its intrinsic height and scrolls with the sheet", () => {
  assert.match(declarations(".evidence-sheet > *"), /flex-shrink:\s*0/);
});

test("ordinary evidence notes remain visible while deliberate collapsed notes clip", () => {
  const ordinary = declarations(".evidence-note");
  assert.match(ordinary, /overflow:\s*visible/);
  assert.doesNotMatch(ordinary, /overflow:\s*hidden/);

  const collapsed = declarations(".evidence-note.evidence-collapsed");
  assert.match(collapsed, /max-height:\s*320px/);
  assert.match(collapsed, /overflow:\s*hidden/);
});
