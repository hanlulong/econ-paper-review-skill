"use client";

import { isValidElement, type HTMLAttributes, type ReactNode } from "react";
import ReactMarkdown, { type Components } from "react-markdown";
import rehypeKatex from "rehype-katex";
import remarkGfm from "remark-gfm";
import remarkMath from "remark-math";
import { markdownHeadingSlug } from "../lib/review-documents";

export type MarkdownComponents = Components;

function nodeText(value: ReactNode): string {
  if (typeof value === "string" || typeof value === "number") return String(value);
  if (Array.isArray(value)) return value.map(nodeText).join("");
  if (isValidElement<{ children?: ReactNode }>(value)) return nodeText(value.props.children);
  return "";
}

export default function MarkdownContent({
  children,
  components,
}: {
  children: string;
  components?: Components;
}) {
  const headingCounts = new Map<string, number>();
  const heading = (Tag: "h1" | "h2" | "h3" | "h4" | "h5" | "h6") => function Heading({
    children,
    node: _node,
    ...props
  }: HTMLAttributes<HTMLHeadingElement> & { node?: unknown }) {
    void _node;
    const base = markdownHeadingSlug(nodeText(children));
    const seen = headingCounts.get(base) || 0;
    headingCounts.set(base, seen + 1);
    const id = seen ? `${base}-${seen}` : base;
    return <Tag {...props} id={id}>{children}</Tag>;
  };
  const renderedComponents: Components = {
    ...components,
    h1: heading("h1"),
    h2: heading("h2"),
    h3: heading("h3"),
    h4: heading("h4"),
    h5: heading("h5"),
    h6: heading("h6"),
  };
  return (
    <ReactMarkdown
      remarkPlugins={[remarkGfm, remarkMath]}
      rehypePlugins={[rehypeKatex]}
      skipHtml
      components={renderedComponents}
    >
      {children}
    </ReactMarkdown>
  );
}
