# Changelog

All notable changes to Econ Review are recorded here. Versions follow
[Semantic Versioning](https://semver.org/), and each release is tagged
`econ-review--vX.Y.Z`. The version is declared in both
`econ-review/.claude-plugin/plugin.json` and `econ-review/.codex-plugin/plugin.json`.

## 0.2.3 — 2026-11-06

A security and install-layout release. Rerun the standalone install prompt (or
the native plugin update) to pick it up.

### Security

- Explicit math spans in reports are now checked against an allowlist of
  math-typesetting commands before they reach LuaLaTeX. The previous denylist
  missed `\InputIfFileExists` and `\makeatletter\@input`, so TeX copied from a
  hostile manuscript into `$...$` could read a local file into the delivered
  PDF. Spans containing `@`, `^^` escapes, control characters, or any file,
  Lua, category-code, or expansion command are now rejected with a message that
  names the offending token. Shell escape stays disabled; `openin_any=p` is
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

### Changed

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
  `--profile standalone`, and explains how to repair a pre-0.2.3 copy.

## 0.2.2 — 2026-07-15

- Made standalone installation the default route.

## 0.2.1 — 2026-07-14

- Streamlined native plugin setup and updates.

## 0.2.0 — 2026-07-14

- First native plugin release with a self-contained plugin package.
