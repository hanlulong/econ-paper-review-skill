# EconReview

**Referee-grade AI review for economics papers.** An open Agent Skill for Claude Code and Codex that reads your paper the way a careful journal referee would: it reconstructs your argument and empirical design before judging, verifies every criticism against your own text, tables, and figures, and hands you a prioritized plan to fix what it finds. It never edits your paper.

*Built for economics — works well for finance, accounting, political economy, and other social science papers whose arguments rest on data, causal inference, or formal models.*

<!-- TODO before public launch: export a fresh screenshot of the Review Desk showing the
     synthetic review (npm run dev:bundled) and place it at docs/assets/review-desk.png -->
![Review Desk](docs/assets/review-desk.png)

## What you get

Every review is saved as a readable package — a start-here page, a substance-only **referee report**, a separate **writing report** (grammar, language consistency, references, presentation), and a dependency-ordered **fix plan** (P0 before submission → P2 polish). Reports work as plain Markdown; an optional local Review Desk adds interactive tracking.

Every comment looks like this — a verbatim quote from *your* manuscript, a concrete consequence, and the minimum repair:

> ### Section 3: The global uniqueness claim fails at the equality boundary
>
> **Issue**: The proposition asserts strict uniqueness although the stated payoff permits a tie.
>
> **Relevant text**:
> > The equilibrium action is unique for every parameter value.
>
> **Concern**: At equality both actions maximize payoff, so the model supports a set-valued prediction. The proposition and comparative-static summary currently state a stronger global conclusion. No tie-breaking rule or boundary restriction appears in the supplied manuscript.
>
> **Suggestions**: Add a tie-breaking rule or state a set-valued equilibrium at the boundary. Align Proposition 1, its proof, and the comparative static.

*(From the bundled synthetic example — a real full review of a 90-page empirical paper produces 50–60 comments like this, each independently verified.)*

## Quickstart

```bash
git clone https://github.com/hanlulong/econ-paper-review-skill.git
cd econ-paper-review-skill
python3 -m pip install -r requirements.txt
./install.sh
```

Requires Python 3.10+ and [Poppler](https://poppler.freedesktop.org/) (`brew install poppler` / `apt install poppler-utils`) for PDF reading. Then put your manuscript in your working directory (PDF, plus LaTeX/Markdown source if you have it) and ask:

```text
Use $econ-review in full mode to review this paper for a leading field journal.
Use $econ-review in quick mode and identify the three largest submission risks.
Use $econ-review to reconstruct the theory and empirical design before giving detailed comments.
```

`quick` is a bounded scan of the central claim and largest submission risks. `full` is a multi-pass review of every section, table, figure, equation, footnote, and appendix. When the run finishes, open `review/README.md` — it tells you what to read in what order.

## Why you can trust the comments

Most AI paper feedback fails in two ways: hallucinated criticism and generic checklists. EconReview's pipeline is built against both:

- **Reconstruction before judgment.** The skill re-derives key equations from your stated assumptions and rebuilds the empirical pipeline down to which specification produces each table column — critique comes from reconstruction, not pattern-matching.
- **Typed evidence on every finding.** Every comment carries a verbatim quote, equation, table cell, or figure reference with a stable location anchor. Tables and figures are read from the *rendered pages*, never from lossy text extraction.
- **Adversarial survival.** Every major finding must survive an explicit counter-argument search of your full text and appendix before it reaches the report. Findings that a reasonable author reply would defeat are deleted.
- **Fairness rules.** A disclosed, honestly-bounded data limitation is never punished. Method checks (difference-in-differences, IV, RDD, cross-cutting inference) activate only when your paper's actual design warrants them — no boilerplate robustness demands.
- **Machine-verified packages.** Schema validators, deterministic numeric re-checks, and a fail-closed finalizer gate every review before it is presented as complete.

## What it covers

Empirical, experimental, descriptive and measurement, prediction/ML, structural, theoretical, macro, evidence-synthesis, and mixed papers. The audit adapts to your paper's design, not its field label — identification strategy, inference, internal consistency, logic and proofs, magnitudes and units, contribution framing, terminology, tables and figures, references, and reproducibility. Venue norms and literature search are economics-first today; adjacent fields get the full methodological review with field norms explicitly marked as not assessed.

## What it does not do

It does not ghost-write your paper, predict acceptance probabilities, invent citations, or hide what it could not check — every review states its coverage and its boundaries. No comparative quality claims (against human referees or other tools) will be made until an independent benchmark reports precision, recall, and false-positive rates; a public benchmark harness ships in [`benchmarks/`](benchmarks/).

## The Review Desk (optional)

A local, privacy-first web viewer for working through a review: overview-first reading, importance and paper-order navigation, per-comment status tracking (fixed / challenge / defer), notes, and export for the next round. Your manuscript and review never leave your machine — no uploads, no accounts.

```bash
cd review-viewer && nvm use && npm ci && npm run dev
```

## Roadmap

- Measured cross-family benchmark with published precision/recall — before any comparative claims
- Additional conditional method lenses (RCT, shift-share, synthetic control, structural, macro-VAR)
- Challenge / deep-dive / re-review rounds as first-class workflows
- **Hosted version** (upload a PDF, get the full package — no CLI): join the waitlist at [econreview.ai](https://econreview.ai)

## Related projects

- [econ-writing-skill](https://github.com/hanlulong/econ-writing-skill) — the writing-side sibling: EconReview judges the paper, econ-write helps you draft and revise it
- [stata-mcp](https://github.com/hanlulong/stata-mcp) — run Stata from AI agents
- [awesome-ai-for-economists](https://github.com/hanlulong/awesome-ai-for-economists) — the broader toolbox

## Development, validation, and advanced installs

Backends, the v0.4 output contract, the validation suite, and the release process live in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

<!-- TODO before public launch: finalize the outbound license decision (AGPL-3.0 planned)
     and replace this section. Until then the current text is accurate. -->
License to be finalized before public release; until then the code and documentation are all rights reserved and the install commands are for the copyright holder and users covered by a separate written agreement. Third-party components remain governed by their own licenses (see `THIRD_PARTY_NOTICES.md`). Commercial licensing and the hosted version: [econreview.ai](https://econreview.ai).

---

If EconReview catches something a referee would have — star the repo so other economists find it, and open an issue for anything it got wrong: bad comments are bugs here, not opinions.
