import React from "react";
import { createRoot } from "react-dom/client";
import "katex/dist/katex.min.css";
import "../../app/globals.css";
import { ReviewWorkspace } from "../../app/review-workspace";

const root = document.getElementById("root");
if (!root) throw new Error("Review Desk root element is missing");

createRoot(root).render(
  <React.StrictMode>
    <ReviewWorkspace />
  </React.StrictMode>,
);
