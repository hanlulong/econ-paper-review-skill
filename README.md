# Econ Paper Review Skill

**Get a tough, fair referee report on your economics paper — before a real referee sees it.**

`econ-review` is a free Agent Skill for Claude Code and Codex. It reads your paper the way a careful journal referee would: first it works out what you are claiming and how your evidence supports it, then it checks everything it can verify — identification, tables, proofs, numbers, references, writing — and gives you a referee report plus a step-by-step plan for fixing what it found. It never rewrites your paper. That part stays yours.

*Built for economics. Also works well for finance, accounting, political economy, and other social science papers that rest on data, causal inference, or formal models.*

<!-- TODO before public launch: export a fresh screenshot of the Review Desk showing the
     synthetic review (npm run dev:bundled) and place it at docs/assets/review-desk.png -->
![Review Desk](docs/assets/review-desk.png)

## What you get

A finished review lands in a `review/` folder next to your paper:

- **`report.md`** — the referee report: an overall assessment, the issues that could sink the paper at a journal, and detailed comments.
- **`fix-plan.md`** — the same findings turned into an ordered to-do list: what must be fixed before submission, what would strengthen the paper, what is polish.
- **`writing-report.md`** — grammar, typos, consistent terminology, references, and table/figure presentation, kept separate so the main report stays about substance.
- **`review/README.md`** — a one-page summary that tells you what to read first.

Every comment quotes your own paper, explains why the issue matters, and says what to do about it:

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

*(From the bundled example. A full review of a 90-page empirical paper typically produces 50–60 comments like this.)*

## Install

Paste this into Claude Code or Codex and it will install itself:

```text
Install the econ-review skill: clone https://github.com/hanlulong/econ-paper-review-skill.git,
then from the cloned folder run "python3 -m pip install -r requirements.txt" and "./install.sh".
If Poppler is missing, install it too (brew install poppler / apt install poppler-utils).
Confirm the skill is installed at the end.
```

<details>
<summary>Manual installation</summary>

```bash
git clone https://github.com/hanlulong/econ-paper-review-skill.git
cd econ-paper-review-skill
python3 -m pip install -r requirements.txt
./install.sh
```

Requires Python 3.10+ and [Poppler](https://poppler.freedesktop.org/) for PDF reading (`brew install poppler` on Mac, `apt install poppler-utils` on Linux). See [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) for Claude-only, Codex-only, and project-local installs.

</details>

## Use it

Put your manuscript in your working directory — the PDF, plus the LaTeX or Markdown source if you have it — and ask:

```text
Use $econ-review in full mode to review this paper for a leading field journal.
Use $econ-review in quick mode and identify the three largest submission risks.
Use $econ-review to reconstruct the theory and empirical design before giving detailed comments.
```

`quick` gives you the biggest risks fast. `full` goes through every section, table, figure, equation, footnote, and appendix. When it finishes, open `review/README.md` and start there.

## Why you can trust the comments

AI feedback on papers usually fails in one of two ways: it makes things up, or it hands you a generic checklist. This skill was built specifically against both:

- **It reads your paper before it judges it.** It re-derives your key equations from your own assumptions and traces how each table was produced. Comments come from understanding the paper, not from pattern-matching on keywords.
- **Every comment quotes the paper.** The exact sentence, table cell, or figure — read from the rendered PDF pages, so a garbled text extraction can't produce a phantom error.
- **It argues with itself before it argues with you.** Before a major comment reaches the report, the skill searches your paper and appendix for the strongest reply you could make. If your reply would win, the comment is deleted.
- **It is fair about data limits.** If your data can't do something, you say so in the paper, and your claims stay within those limits, that is not a flaw — and the review won't treat it as one.
- **It checks what fits your paper.** Difference-in-differences, IV, and RDD checks switch on only when your paper actually uses those designs. No demands for robustness checks that make no sense for your setting.

Every review also passes a set of automatic consistency checks before it is shown to you as finished.

## What it covers

Any kind of economics paper: empirical, experimental, descriptive, prediction and machine learning, structural, theoretical, macro, and mixed. The review adapts to how your paper actually works — its identification, inference, logic and proofs, magnitudes, framing of the contribution, terminology, exhibits, references, and reproducibility. Journal norms and literature search are economics-first for now; papers from neighboring fields get the full methodological review, and anything field-specific it can't assess is said plainly rather than guessed.

## What it does not do

It won't write your paper, estimate your acceptance odds, or invent citations. When it couldn't check something — a dataset it didn't have, a figure it couldn't read — it says so instead of pretending. And we make no claims about beating human referees or other tools until we can show measured results: a public benchmark harness ships in [`benchmarks/`](benchmarks/), and the numbers will be published when they exist.

## The Review Desk (optional)

A local web viewer for working through a long review: read the overall assessment first, go comment by comment in importance or paper order, mark each one fixed / challenged / deferred, and export your progress for the next round. Everything stays on your machine — no uploads, no accounts.

```bash
cd review-viewer && nvm use && npm ci && npm run dev
```

## Roadmap

- A measured benchmark with published precision and recall — before any comparative claims
- More design-specific checks (RCT, shift-share, synthetic control, structural, macro-VAR)
- Follow-up rounds as a first-class workflow: challenge a comment, request a deeper look, re-review a revision
- **A hosted version** — upload a PDF, get the full review, no command line: join the waitlist at [econreview.ai](https://econreview.ai)

## Related projects

- [econ-writing-skill](https://github.com/hanlulong/econ-writing-skill) — the writing-side sibling: this skill judges the paper, that one helps you write it
- [stata-mcp](https://github.com/hanlulong/stata-mcp) — run Stata from AI agents
- [awesome-ai-for-economists](https://github.com/hanlulong/awesome-ai-for-economists) — the broader toolbox

## Development and advanced installation

PDF backends, the output contract, the validation suite, and the release process are documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

<!-- TODO before public launch: finalize the outbound license decision (AGPL-3.0 planned)
     and replace this section. Until then the current text is accurate. -->
License to be finalized before public release; until then the code and documentation are all rights reserved, and the install commands are for the copyright holder and users covered by a separate written agreement. Third-party components remain under their own licenses (see `THIRD_PARTY_NOTICES.md`). Commercial licensing and the hosted version: [econreview.ai](https://econreview.ai).

---

If this catches something a referee would have caught, star the repo so other economists find it — and if it gets something wrong, open an issue. Bad comments are bugs here, not opinions.
