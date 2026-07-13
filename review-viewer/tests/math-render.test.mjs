import assert from "node:assert/strict";
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

test("renders every synthetic detailed comment with one isolated evidence quote", () => {
  const reports = [
    [
      "### 1. Boundary multiplicity",
      "**Issue**: The proposition states uniqueness at an equality boundary.",
      "",
      "**Relevant text**:",
      "> At $\\theta=0$, both actions maximize payoff.",
      "",
      "**Concern**: The displayed proposition and its boundary case conflict.",
      "",
      "**Suggestions**: State a tie-breaking rule or a set-valued result.",
      "",
      "**Status**: [Pending]",
    ].join("\n"),
    [
      "### 1. Subject-verb agreement",
      "**Issue**: A singular subject takes a plural verb.",
      "",
      "**Relevant text**:",
      "> The result imply a unique action away from the boundary.",
      "",
      "**Concern**: The agreement error interrupts an otherwise concise summary.",
      "",
      "**Suggestions**: Replace ‘imply’ with ‘implies’.",
      "",
      "**Status**: [Pending]",
    ].join("\n"),
  ];
  const markdown = reports.join("\n");
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
    assert.doesNotMatch(blocks[0], /Concern|Suggestions|Status/);
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
