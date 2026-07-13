import assert from "node:assert/strict";
import test from "node:test";
import {
  equationEvidencePresentation,
  hasDelimitedMath,
} from "../lib/review-equation-presentation.ts";

test("keeps a rendered-transcription sentence literal instead of wrapping it in KaTeX", () => {
  const content = "[Rendered transcription] “Dividing by μ is to ensure that the steady state is identical to that under perfect banking competition when looking at the transitory dynamics.”";
  assert.deepEqual(equationEvidencePresentation(content, "reviewer_observation"), {
    kind: "prose",
    content,
  });
});

test("keeps mixed prose and raw symbols readable", () => {
  const content = "[Rendered transcription] Λ_{t,t+s} is printed with c_t/c_{t+1}; the multi-period denominator should be c_{t+s}.";
  assert.deepEqual(equationEvidencePresentation(content, "reviewer_observation"), {
    kind: "prose",
    content,
  });
});

test("treats reviewer-derived representations as prose unless math is explicitly delimited", () => {
  for (const representation of ["reviewer_observation", "composite_comparison", "checked_absence", "computed_result"]) {
    const content = "Observado: R_t^b = R_t + μ_t.";
    assert.deepEqual(equationEvidencePresentation(content, representation), { kind: "prose", content });
  }
  assert.equal(
    equationEvidencePresentation(String.raw`Observed: $R_t^b = R_t + \mu_t$.`, "reviewer_observation").kind,
    "markdown_math",
  );
});

test("wraps a genuine undelimited TeX equation as display math", () => {
  const content = String.raw`R_t^b = \frac{R_t}{\mu_t}`;
  assert.deepEqual(equationEvidencePresentation(content, "verbatim"), {
    kind: "display_math",
    content: `$$\n${content}\n$$`,
  });
});

test("recognizes a short genuine formula without an equality sign", () => {
  assert.deepEqual(equationEvidencePresentation("x+y", "normalized_transcription"), {
    kind: "display_math",
    content: "$$\nx+y\n$$",
  });
  assert.equal(equationEvidencePresentation("cost-benefit discussion", "reviewer_observation").kind, "prose");
});

test("recognizes short legacy equations without representation metadata", () => {
  assert.equal(equationEvidencePresentation("x=y").kind, "display_math");
  assert.equal(equationEvidencePresentation("x<y").kind, "display_math");
  assert.equal(equationEvidencePresentation("U(c,l)").kind, "display_math");
  assert.equal(equationEvidencePresentation("Equation (3): x=y", "verbatim").kind, "prose");
});

test("passes already delimited prose and math through to the Markdown renderer", () => {
  const content = String.raw`Equation (36) implies $\beta_3 = 1 - \alpha_k$, not an additive HHI term.`;
  assert.equal(hasDelimitedMath(content), true);
  assert.deepEqual(equationEvidencePresentation(content, "normalized_transcription"), {
    kind: "markdown_math",
    content,
  });
});

test("does not mistake a currency sign or empty payload for a raw equation", () => {
  assert.equal(hasDelimitedMath("The fee is $5 per account."), false);
  assert.equal(equationEvidencePresentation("x=$y", "verbatim").kind, "prose");
  assert.equal(equationEvidencePresentation(String.raw`\(x=y`, "verbatim").kind, "prose");
  assert.deepEqual(equationEvidencePresentation("", "verbatim"), {
    kind: "prose",
    content: "No equation evidence is available.",
  });
});
