# Econ Paper Review Skill

**Get a tough, fair referee report on your economics paper — before a real referee sees it.**

`econ-review` is an Agent Skill for Claude Code and Codex. It reads your paper the way a careful journal referee would: first it works out what you are claiming and how your evidence supports it, then it checks everything it can verify — identification, tables, proofs, numbers, references, writing — and gives you a referee report plus a step-by-step plan for fixing what it found. It never rewrites your paper. That part stays yours.

*Built for economics. Also works well for finance, accounting, political economy, and other social science papers that rest on data, causal inference, or formal models.*

## What you get

A finished review lands in a clean `review/` folder next to your paper:

- **`paper-review.pdf`** — the primary report: a professionally typeset, bookmarked PDF containing the referee report, exhaustive detailed comments, editing comments, and revision plan. Its cover shows only the manuscript title, “Referee Report,” and the assessment date; its contents page includes the report's useful sections without listing every comment.
- **`reports/`** — the referee report, editing comments, and revision plan as Markdown for editing or agent use.
- **`review/README.md`** — a one-page summary that tells you what to read first.
- **`supporting/`** — working files used by the Review Desk and later review rounds; most authors do not need to open them.

Every comment identifies the relevant manuscript text or, when the issue comes from a checked comparison or calculation, states the basis directly. It explains why the issue matters and what to do about it:

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
>
> **Status**: [Pending]

*(From the bundled example. Full reviews keep every verified issue—up to 100 substantive comments and 30 editing comments. These are output capacities, not targets or stopping rules.)*

## Install

Paste this into Claude Code or Codex and it will install itself:

```text
Install econ-review from https://github.com/hanlulong/econ-paper-review-skill for
Claude Code and Codex by following docs/INSTALL.md. Use my existing GitHub login;
never ask me to paste a token, and preserve uncommitted work. Run the dry run, then
the managed global setup for both agents with --with-review-desk. Do not install
system packages, TeX, Pandoc, or anything requiring administrator access. Report
both skill paths, PDF/report readiness, the Review Desk command and URL, anything
still missing, and remind me to reload my agent sessions.
```

The expanded, security-preserving prompt and project-local variants are in [docs/INSTALL.md](docs/INSTALL.md).

<details>
<summary>Manual installation</summary>

```bash
git clone https://github.com/hanlulong/econ-paper-review-skill.git
cd econ-paper-review-skill
python3 scripts/install_econ_review.py --dry-run --global --all --with-review-desk
python3 scripts/install_econ_review.py --global --all --with-review-desk
```

On native Windows, replace `python3` with `py -3` and use PowerShell path syntax. Requires Python 3.10+ and [Poppler](https://poppler.freedesktop.org/) for PDF reading. If compatible LuaLaTeX or Tectonic is already installed, the report uses the professional LaTeX renderer; otherwise it uses the maintained built-in PDF renderer. A LaTeX compilation error stops the build instead of silently changing renderers. The installer does not install TeX or require Pandoc. Review Desk is prebuilt and needs no Node.js or npm. See [docs/INSTALL.md](docs/INSTALL.md) for skill-only, Claude-only, Codex-only, and project-local installs.

</details>

## Use it

Put your manuscript in your working directory — the PDF, plus the LaTeX or Markdown source if you have it — and ask:

```text
Use $econ-review in full mode to review this paper for a leading field journal.
Use $econ-review in quick mode and identify the three largest submission risks.
Use $econ-review to reconstruct the theory and empirical design before giving detailed comments.
```

`quick` gives you the biggest risks fast. `full` goes through every section, table, figure, equation, footnote, and appendix. When it finishes, open `review/paper-review.pdf`; use `review/README.md` for the file map and next-round workflow.

## Why you can trust the comments

AI feedback on papers usually fails in one of two ways: it makes things up, or it hands you a generic checklist. This skill was built specifically against both:

- **It reads your paper before it judges it.** It reconstructs the argument first and, where the supplied inputs permit, re-derives key equations and traces reported results. Comments come from understanding the paper, not from pattern-matching on keywords.
- **It checks comments against the source.** Quotations, equations, tables, and figures are checked against the supplied source or rendered PDF pages when those inputs are available; reviewer-derived comparisons and calculations are labeled in plain language instead of presented as quotations.
- **It argues with itself before it argues with you.** Before a major comment reaches the report, the skill searches your paper and appendix for the strongest reply you could make. If your reply would win, the comment is deleted.
- **It checks the paper's contribution against live literature.** It turns each novelty, priority, and important citation claim into a targeted economics search. It screens candidate papers against that claim, confirms authors, dates, and versions, and reads the available full text before calling a citation missing or a contribution overstated. When decisive evidence is unavailable, it says the conclusion is limited.
- **It is fair about data limits.** If your data can't do something, you say so in the paper, and your claims stay within those limits, that is not a flaw — and the review won't treat it as one.
- **It checks what fits your paper.** Difference-in-differences, IV, and RDD checks switch on only when your paper actually uses those designs. No demands for robustness checks that make no sense for your setting.

Every review also passes a set of automatic consistency checks before it is shown to you as finished.

## What it covers

Any kind of economics paper: empirical, experimental, descriptive, prediction and machine learning, structural, theoretical, macro, and mixed. The review adapts to how your paper actually works — its identification, inference, logic and proofs, magnitudes, framing of the contribution, terminology, exhibits, references, and reproducibility. Journal norms and literature search are economics-first for now; papers from neighboring fields get the full methodological review, and anything field-specific it can't assess is said plainly rather than guessed.

## What it does not do

It won't write your paper, estimate your acceptance odds, or invent citations. When it couldn't check something — a dataset it didn't have, a figure it couldn't read — it says so instead of pretending. And we make no claims about beating human referees or other tools until we can show measured results: a public benchmark harness ships in [`benchmarks/`](benchmarks/), and the numbers will be published when they exist.

## The Review Desk (optional)

A local web viewer for working through a long review. For every comment, add your instruction or disagreement, choose P0/P1/P2, and make one clear decision: keep it **Open**, mark it **Ready for review** after a change or reasoned response, or **Set aside** because it should return later, does not apply, or cannot be addressed. Review Desk then builds a prioritized task plan and a structured response template for your implementation agents. The next review checks every carried concern and runs a fresh full-paper sweep for new problems. Everything stays on your machine—no uploads or accounts.

The recommended installer includes a verified, prebuilt copy with
`--with-review-desk`; it prints one stable Python launch command and opens
`http://127.0.0.1:48127/`. Users do not need Node.js or npm. Node is required
only to change or rebuild the viewer; see [review-viewer/README.md](review-viewer/README.md).

## Roadmap

- A measured benchmark with published precision and recall — before any comparative claims
- More design-specific checks (RCT, shift-share, synthetic control, structural, macro-VAR)
- Round-by-round usability improvements for author, implementation-agent, and re-review handoffs
- **A hosted version** — upload a PDF and receive the full review without a command line. Coming later.

## Related projects

- [econ-writing-skill](https://github.com/hanlulong/econ-writing-skill) — the writing-side sibling: this skill judges the paper, that one helps you write it
- [stata-mcp](https://github.com/hanlulong/stata-mcp) — run Stata from AI agents
- [awesome-ai-for-economists](https://github.com/hanlulong/awesome-ai-for-economists) — the broader toolbox

## Development and advanced installation

PDF backends, the output contract, the validation suite, and the release process are documented in [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md).

## License

License to be finalized before public release; until then the code and documentation are all rights reserved, and the install commands are for the copyright holder and users covered by a separate written agreement. Third-party components remain under their own licenses (see `THIRD_PARTY_NOTICES.md`). Commercial licensing and the hosted version are planned.

---

If this catches something a referee would have caught, star the repo so other economists find it — and if it gets something wrong, open an issue. Bad comments are bugs here, not opinions.
