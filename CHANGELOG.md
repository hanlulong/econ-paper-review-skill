# Changelog

All notable changes to Econ Review are recorded here. Versions follow
[Semantic Versioning](https://semver.org/), and each release is tagged
`econ-review--vX.Y.Z`. The version is declared in both
`econ-review/.claude-plugin/plugin.json` and `econ-review/.codex-plugin/plugin.json`.

## 0.3.2 — 2026-11-07

A documentation patch release. In the skill itself, apart from the version
number, only one citation in the RDD gate changes: both of its links and its
verification date. The scripts, requirements and Review Desk bundle are
unchanged, so reviews made with 0.3.1 validate and finalize unchanged.

### Documentation

- The RDD gate cites the `rdrobust` and `rddensity` GitHub repositories. The
  earlier rdpackages.github.io pages for each package now only redirect there.
- The README and its Chinese translation say that the bundled sample review
  suggests never-treated controls, which the demonstration manuscript does not
  have: every municipality is connected by 2018. Since 0.3.0 the DiD gate says
  never to recommend never-treated controls when every unit is eventually
  treated. The sample itself was not regenerated.

## 0.3.1 — 2026-11-07

A patch release: installer messages that say what will actually change, Python
discovery on macOS, a wider synced-folder check, and documentation and test
fixes. Rerun the standalone install prompt to pick it up. After a native plugin
update, ask the agent to run econ-review-setup as usual; the core requirements
and the Review Desk bundle are unchanged, so it reuses the managed runtime and
the installed Review Desk. Reviews made with 0.3.0 validate and finalize
unchanged.

### Fixed

- `scripts/install.sh` finds a supported Python when `python3` is too old. On
  macOS, `python3` often stays the system 3.9 after a newer Python is installed;
  the script now tries `python3`, then `python3.14` down to `python3.10`, then
  the same names in `~/.local/bin` (where `uv python install` puts them), and
  uses the first 3.10+ interpreter for every step. When none is found, and when
  `setup_econ_review.py` runs under a too-old Python, the message says to rerun
  with the versioned interpreter, for example `python3.12` instead of `python3`.
  README and INSTALL now say that 3.15 worked in a macOS test but that some
  dependencies do not yet ship ready-made 3.15 packages, so 3.13 or 3.14 is the
  safer choice.
- Dry-run and re-run messages say what will actually change. A dry run against a
  current install said "Would already current" and promised a core-requirements
  install for a runtime it would reuse. It now says "Would keep current", says
  when a runtime would be created or replaced, and reports a current runtime
  record and Review Desk launcher. A re-run still rewrites the runtime record,
  which restores its private permissions, but reports it as already current.
  When no skill files changed, the restart hint becomes a note to restart only
  if the client does not list Econ Review yet, and `install.sh` no longer prints
  the hint on a dry run. Showing a notice only when there is something to act on
  is an idea adapted from
  [Spark-To-Paper-Skills/paperjury](https://github.com/Spark-To-Paper-Skills/paperjury)
  (MIT; idea only, no code copied).
- The synced-folder warning now covers Box and any macOS File Provider folder. A
  folder under `Library/CloudStorage/` (such as `Box-Box` or `pCloudDrive`) is
  reported with its provider's name, and a top-level `~/Box` folder counts as
  Box. Before, the confidentiality question was never asked for these folders.
  An Overleaf project still gets only the Overleaf notice.
- The delivered `review/README.md` reprints the Review Desk launch command
  without changing anything. It told the agent to rerun support setup, which
  takes the setup lock, rewrites the runtime record and can rebuild the runtime.
  It now adds `--dry-run`, which prints the same command, and tells the agent to
  offer the real setup if that dry run would create the runtime or install
  Review Desk or its launcher. `SKILL.md` gives the same rule. A review
  finalized by 0.3.0 keeps its earlier README until it is finalized again.

### Changed

- The review never judges whether a manuscript, or a passage in it, was written
  with AI. Prose style is not evidence of how a paper was produced, and
  automated detectors often misclassify writing by non-native English speakers
  (Liang et al. 2023, [arXiv:2304.02819](https://arxiv.org/abs/2304.02819)).
  Formulaic or unclear prose is still raised as an editing comment about its
  effect on the reader, and verifiable defects, such as a reference that cannot
  be found or leftover assistant or placeholder text, are still reported as
  those defects.

### Added

- A "Report a missed issue" form for a real problem the review did not raise,
  and a "What went wrong" choice plus model and version fields on the
  bad-comment form. The version field is optional, because a standalone copy
  does not show its version. The form structure is adapted from
  [blader/humanizer](https://github.com/blader/humanizer) and
  [Spark-To-Paper-Skills/paperjury](https://github.com/Spark-To-Paper-Skills/paperjury)
  (both MIT; idea only, labels written fresh).
- Benchmarks: each evaluated case reports `active_substance_count` and
  `active_writing_count`, so that required-issue recall can be read against how
  many findings a package has. The idea comes from the
  [Dawes-Institute/ai-peer-review-benchmark](https://github.com/Dawes-Institute/ai-peer-review-benchmark)
  write-up (MIT; idea only, no code copied).
- `CITATION.cff`, so GitHub offers "Cite this repository" for researchers who
  cite the tool. Its `version` and `date-released` are bumped with the plugin
  manifests, and a test checks that the versions agree.

### Documentation

- INSTALL no longer says that `install.sh` accepts `--check` (only the Python
  installer does) or that the installer prints the Review Desk integrity check
  (the printed launch command does, with `--check` appended).
- The plugin manifests now say to run econ-review-setup after a direct plugin
  install and again after each plugin update, as README and INSTALL already did.
- `SKILL.md` links the DiD, IV and RDD gates by file, and `docs/DEVELOPMENT.md`
  says that the fixture PDF checks need latexmk plus LuaLaTeX.

### Tests

- The fixture finalizer check and the stale-PDF check skip with a reason when
  latexmk or LuaLaTeX is missing, because the fixture records the
  latexmk-lualatex renderer. The fixture's validator check still runs without
  TeX.
- The MarkItDown tests ask the same question as `pdf_ingestion.py doctor` (the
  pinned package in this runtime plus its command) instead of only looking for a
  `markitdown` command on `PATH`, which failed when the command came from
  another environment.
- The active-content PDF fixture builds its document JavaScript directly instead
  of calling the deprecated `PdfWriter.add_js`, so the file runs clean with
  deprecation warnings treated as errors.
- New tests cover the `install.sh` Python fallback, the dry-run and re-run
  messages, the Box and File Provider notice, and the delivered README's dry-run
  command.

## 0.3.0 — 2026-11-07

A security, install-layout, PDF-ingestion and report-generator release. Rerun
the standalone install prompt to pick it up. After a native plugin update, also
send "Run econ-review-setup now and finish its user-level setup with Review
Desk." so the shared Review Desk moves to this release's bundle. It is a minor
release because the standalone layout, PDF ingestion and generated
reports all change; v0.2.3 was planned but never tagged, and its changes are
included here.

### Security

- Explicit math spans in reports are now checked against an allowlist of
  math-typesetting commands before they reach LuaLaTeX. The previous denylist
  missed `\InputIfFileExists` and `\makeatletter\@input`, so TeX copied from a
  hostile manuscript into `$...$` could read a local file into the delivered
  PDF. Spans containing `@`, `^^` escapes, control characters, or any file,
  Lua, category-code, or expansion command are now rejected with a message that
  names the offending token, and so are spans with a bare `%` or `#` or
  unbalanced braces, which would otherwise fail the compile without saying
  why. Bare `Var(...)`/`Cov(...)` in prose are typeset as math only when the
  argument is made of identifier characters. Shell escape stays disabled; `openin_any=p` is
  deliberately not used because it breaks LuaLaTeX font loading.
- The allowlist also leaves out `\not` and `\smash`, whose unicode-math and
  amsmath definitions look up a command named after their argument, and every
  command that errors or lacks a glyph in either bundled math font (such as
  `\Box`, `\intercal`, and `\Cap`). Such spans are now refused with a named
  command instead of passing the check and failing the render. `\hdots`,
  `\notag`, and `\nonumber` are accepted. `references/output-contracts.md`
  lists the usual rewrites, for example `\not\in` to `\notin`.
- The bundled Review Desk now renders math with KaTeX 0.18.10 throughout
  (previously 0.16.47 markup with 0.17.0 styles), outside the
  GHSA-238p-pmpm-9mq7 range. `econ-review/assets/review-desk.zip` is rebuilt.
- The viewer's development and hosted toolchain moves to Next.js 16.4.5 and
  postcss 8.5.32, clearing the critical Next.js advisory and the postcss,
  nanoid, and source-map-js advisories. The installed Review Desk does not use
  Next.js.

### Fixed

- PDF ingestion no longer fails on two common economics layouts. Text that runs
  past the page edge (an overfull regression table, including Table 2 of the
  bundled demo paper) is clipped to the page box and reported as a page
  warning that the exhibit is probably cut off, instead of failing verification
  with "invalid or out-of-page bounds". Landscape pages (`/Rotate 90` or `270`,
  as from `pdflscape`) are recorded in their displayed orientation, so the
  render-size check matches. A failed verification now says what to do next.
  Regression tests cover both layouts and an end-to-end ingest of the demo
  paper.
- Updates are idempotent again. Running a bundled script from the installed
  skill (the INSTALL verification step, or `finalize_review.py` during every
  review) wrote `__pycache__`, and the next update then backed up an unchanged
  copy as "Preserved modified prior copy". Bytecode caches for declared modules
  no longer count as edits (an otherwise current copy has them deleted, so
  Python always loads the verified source), `install.sh` ignores the Python installer's state
  file, and a byte-identical copy left by `install.sh` is replaced without a
  backup. An older copy without an install record (such as one from
  `install.sh` before 0.3.0) is still backed up, because local edits cannot be
  ruled out, but it is reported as "Preserved prior copy" rather than as
  modified.
- "Comment N" now means the same issue in every document. The revision plan
  labels each item with its referee-report number (`Comment N`) or its
  editing-comment number (`Editing comment N`) instead of numbering its own
  items, and editing-comment cross-references say "Editing comment N". Within
  a priority level the plan lists prerequisites first and otherwise keeps the
  report's order of importance. The validator accepts the new labels and
  packages finalized by earlier releases, including their "Comment N"
  editing-comment cross-references. `finalize_review.py --check` re-renders the
  plan with the 0.3.0 numbering, so finalize an older package again to bring
  it current. Review Desk's own numbering and Suggestions text are unchanged
  in 0.3.0: it still numbers every comment "Comment #N" in list order and merges
  `fix.what` and `fix.how` only when one repeats the other.
- Suggestions drop most restated repairs. Sentences of `fix.how` that restate
  `minimum_repair` or `fix.what` in other words are dropped, and Concern drops
  sentences that restate the Issue. Exact-substring checks missed these
  paraphrases, which appeared in about ten comments of the bundled sample; the
  heuristic still misses some. A sentence is never dropped when it states a
  contingency, adds a number, quoted text or identifier (such as `DOI` or
  `F`), or adds a content word other than a generic repair verb. Words in any
  script count (Chinese, Japanese and Korean text is compared by character
  pairs), and locators such as "Sec. 3" or "p. 7" are not split. The revision plan's Action line keeps the
  full `fix.how`, merging only exact repeats as before.
- Verbatim quotes rejoin the line breaks of the PDF text layer (a line ending
  in a hyphen keeps the hyphen and joins without a space, and Windows line
  endings are normalized), and the comment guidance asks for quotations that
  run to a sentence boundary and keep the words the concern depends on.
- The revision plan names a target tier in prose ("a leading field journal")
  instead of the schema value `leading-field`.
- Comparator citations in "Closest literature" print the venue and DOI.
- The delivered `review/README.md` explains how to open the review in Review
  Desk, that decisions are stored per browser and port, and the round-2 steps;
  its contents sentence lists only the documents the PDF contains.
- Standalone installs no longer copy the native-plugin payload
  (`.claude-plugin/`, `.codex-plugin/`, `skills/`). With it, Claude Code loaded
  a standalone copy as the namespaced `econ-review@skills-dir` plugin and Codex
  listed `econ-review:econ-review` twice plus the plugin-only
  `econ-review-setup`, so the short `/econ-review` and `$econ-review` names did
  not work. Both installers replace an older plugin-shaped copy atomically, and
  an unmarked plugin-shaped legacy Codex copy is recognized as generated.
- `validate_skill_package.py` has `plugin` and `standalone` profiles; the
  default `auto` profile applies the plugin contract whenever any plugin
  payload is present.
- The public-release contract now declares the bad-comment issue form, both
  README sample screenshots, and `README.zh-CN.md`, so `build_public_release.py
  --check` passes and release archives keep the Chinese README. A new test
  requires every tracked file to be declared.
- The severity rules and completion stop-conditions in `SKILL.md` now come
  before the workflow, inside the part of the skill that is re-attached after
  context compaction.
- Installer tests no longer inherit an exported `CLAUDE_CONFIG_DIR` or
  `CODEX_HOME`, and viewer-dependent tests skip when the viewer is not built.

### Added

- Before a review, the skill asks whether the user is an author or has the
  journal's permission when the request reads as refereeing someone else's
  manuscript, and summarizes the AEA, Econometric Society, Elsevier and
  Springer Nature reviewer AI policies (checked 2026-11-06) in
  `references/red-lines.md`. The Reject/R&R recommendation stays in the report.
- `econ-review/scripts/review_location.py` reports when `review/` would be
  written into an Overleaf project in Dropbox, another Dropbox, iCloud Drive,
  OneDrive or Google Drive folder, or a git work tree, including through a
  symlinked folder, so the agent asks first. The default location is
  unchanged.
- The DiD gate covers universal rollouts (no never-treated controls, where
  not-yet-treated comparisons run out, normalization of fully dynamic event
  studies, citing Borusyak, Jaravel and Spiess 2024) and bad controls read as
  mechanism evidence; the empirical preset asks about post-treatment controls.
- The replication audit checks a data availability statement against the Data
  and Code Availability Standard (DCAS v1.0) when an endorsing economics venue
  is named.
- `docs/sample-review/review/` is a small synthetic review package that Review
  Desk can open before a first review finishes.
- INSTALL documents a standalone uninstall and a macOS route to Python 3.10+
  (Python 3.13 or 3.14 from python.org, Homebrew, or uv), and accepts
  equivalent forms of the repository origin. The uninstall removes the shared
  support data only when no other Econ Review copy remains, and the
  `econ-review-setup` skill gives the same Python guidance.

### Changed

- The bundled sample review (`docs/sample-review/paper-review.pdf`) predates
  this release and is unchanged: it was produced by a model run, and no
  structured data is stored from which to re-render it. The README says which
  settings produced it.
- README (English and Chinese) drops the promise of published precision and
  recall in favour of a blind benchmark on the roadmap, since the bundled cases
  test routing rather than recall.
- Review Desk keeps the KaTeX 0.18.10 override under `rehype-katex` 7.0.1,
  which declares `katex ^0.16`; the viewer's math rendering tests pass with it.
- The managed runtime's `pip install` uses `--prefer-binary`, so a platform
  without a wheel for a dependency's newest release (such as cryptography on
  Intel macOS) gets the newest release that has one instead of a source build
  that needs a compiler, and a failed install names that likely cause.
- Optional backends: `markitdown[pdf]==0.1.7` (was 0.1.6) and
  `requests>=2.34.2,<3` for Mathpix. The core requirements, and therefore the
  managed-runtime hash, are unchanged.
- Dependabot leaves satisfied version ranges alone, groups minor and patch
  updates, and keeps `@types/node` on Node 22.
- README (English and Chinese): the sample excerpt is now comment 8 of the
  bundled sample review, the license is described as free for noncommercial use
  and source-available, and the Refine.ink comparison notes its free first
  document.
- `INSTALL.md` documents the standalone layout, verifies it with
  `--profile standalone`, and explains how to repair a pre-0.3.0 copy.

## 0.2.2 — 2026-07-15

- Made standalone installation the default route.

## 0.2.1 — 2026-07-14

- Streamlined native plugin setup and updates.

## 0.2.0 — 2026-07-14

- First native plugin release with a self-contained plugin package.
