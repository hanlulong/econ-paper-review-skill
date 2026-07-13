import type { Metadata } from "next";
import { ReviewWorkspace } from "./review-workspace";

export const metadata: Metadata = {
  title: "Review Desk",
  description: "A local, evidence-first workspace for economics paper reviews.",
};

export default function Home() {
  return <ReviewWorkspace />;
}
