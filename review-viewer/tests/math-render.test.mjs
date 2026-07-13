import assert from "node:assert/strict";
import { readFile } from "node:fs/promises";
import test from "node:test";
import React from "react";
import { renderToStaticMarkup } from "react-dom/server";
import ReactMarkdown from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";


test("renders report TeX without exposing raw delimiters", () => {
  const html = renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      { remarkPlugins: [remarkGfm, remarkMath], rehypePlugins: [rehypeKatex], skipHtml: true },
      "The estimate is $\\alpha_j = 0.76$ (or $76\\%$).",
    ),
  );

  assert.match(html, /class="katex"/);
  assert.doesNotMatch(html, /\$\\alpha_j|\$76\\%\$/);
});

test("renders the problem field outside the preceding evidence quote", () => {
  const markdown = [
    "**Relevant text**:",
    "> The quoted manuscript sentence.",
    "",
    "**Concern**: The diagnosis belongs outside the quote.",
  ].join("\n");
  const html = renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      { remarkPlugins: [remarkGfm, remarkMath], rehypePlugins: [rehypeKatex], skipHtml: true },
      markdown,
    ),
  );
  assert.match(html, /<blockquote>\s*<p>The quoted manuscript sentence\.<\/p>\s*<\/blockquote>\s*<p><strong>Concern<\/strong>/);
  assert.doesNotMatch(html, /<blockquote>[\s\S]*Concern[\s\S]*<\/blockquote>/);
});

test("renders every private test-paper comment with an isolated evidence quote when available", async (t) => {
  let markdown;
  let reports;
  try {
    const [report, writing] = await Promise.all([
      readFile(new URL("../../test_paper2/review/report.md", import.meta.url), "utf8"),
      readFile(new URL("../../test_paper2/review/writing-report.md", import.meta.url), "utf8"),
    ]);
    reports = [report, writing];
    markdown = `${report}\n${writing}`;
  } catch (error) {
    if (error?.code === "ENOENT") return t.skip("private test_paper2 package is not present");
    throw error;
  }
  const detailedSections = reports.flatMap((report) => report.split(/(?=^### \d+\. .+$)/m))
    .filter((section) => /^### \d+\. .+$/m.test(section) && !/<!-- principal_concern_id:/.test(section));
  assert.ok(detailedSections.length > 0);
  for (const section of detailedSections) {
    const html = renderToStaticMarkup(
      React.createElement(
        ReactMarkdown,
        { remarkPlugins: [remarkGfm, remarkMath], rehypePlugins: [rehypeKatex], skipHtml: true },
        section,
      ),
    );
    const blocks = html.match(/<blockquote>[\s\S]*?<\/blockquote>/g) || [];
    assert.equal(blocks.length, 1, section.match(/^### .+$/m)?.[0]);
    assert.doesNotMatch(blocks[0], /Problem and concern|Constructive feedback|Status/);
  }
  const fullHtml = renderToStaticMarkup(
    React.createElement(
      ReactMarkdown,
      { remarkPlugins: [remarkGfm, remarkMath], rehypePlugins: [rehypeKatex], skipHtml: true },
      markdown,
    ),
  );
  assert.match(fullHtml, /class="katex"/);
});
