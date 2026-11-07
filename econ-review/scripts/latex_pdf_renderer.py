#!/usr/bin/env python3
"""Render econ-review Markdown as a professional, deterministic LaTeX PDF.

The renderer deliberately implements the small Markdown grammar emitted by the
review package instead of executing raw TeX or requiring Pandoc.  It compiles
inside a disposable directory, disables shell escape, and accepts a PDF only
after strict log diagnostics pass.
"""

from __future__ import annotations

import argparse
import hashlib
import io
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import date, datetime, time as datetime_time, timezone
from pathlib import Path
from typing import Mapping, Sequence
from urllib.parse import urlsplit


DEFAULT_TEMPLATE = Path(__file__).resolve().parents[1] / "assets" / "review-report-template.tex"
SUPPORTED_RENDERERS = ("auto", "latexmk-lualatex", "lualatex", "tectonic")

NAVIGATION_BLOCK = re.compile(
    r"<!--\s*review-navigation:start\s*-->.*?"
    r"<!--\s*review-navigation:end\s*-->",
    re.IGNORECASE | re.DOTALL,
)
HTML_COMMENT = re.compile(r"<!--.*?-->", re.DOTALL)
HTML_TAG = re.compile(r"</?[A-Za-z][^>]*>")
HEADING = re.compile(r"^(#{1,6})[ \t]+(.+?)[ \t]*#*[ \t]*$")
LIST_ITEM = re.compile(r"^(?P<indent>[ \t]*)(?P<marker>[-+*]|\d+[.)])[ \t]+(?P<body>.+)$")
TASK_ITEM = re.compile(r"^\[(?P<state>[ xX])\][ \t]+(?P<body>.+)$")
TABLE_DIVIDER = re.compile(r"^:?-{3,}:?$")
FENCE = re.compile(r"^[ \t]*(```+|~~~+)(.*)$")
THEMATIC_BREAK = re.compile(r"^[ \t]*(?:-{3,}|\*{3,}|_{3,})[ \t]*$")
PREFIX = re.compile(
    r"^\[(?:Reviewer observation|Reviewer comparison|Figure observation|"
    r"Table observation|Checked absence|Computation|Rendered transcription)\]\s*",
    re.IGNORECASE,
)
LEGACY_WRITING = re.compile(r"\bWriting report\b", re.IGNORECASE)
LEGACY_DETAILED_WRITING = re.compile(r"\bDetailed Writing Comments\b", re.IGNORECASE)
REVISION_ID = re.compile(r"^[A-Z][A-Z0-9]*(?:-[A-Z0-9]+)+:\s*(.+)$")
PRIORITY_HEADING = re.compile(r"^P([0-9]+)\s*[\u2012\u2013\u2014-]\s*(.+)$", re.IGNORECASE)

# Explicit math spans are copied into the TeX source verbatim, so they are
# checked against an allowlist rather than a denylist: TeX has too many ways
# to read files or build control sequences (``\InputIfFileExists``,
# ``\makeatletter\@input``, ``\csname``, ``\luafunction``, ``^^5c`` escapes)
# for a denylist to stay complete.  Every control word below is a
# math-typesetting command defined by the bundled template (LaTeX, amsmath,
# and unicode-math) that typesets cleanly in both bundled math fonts; none
# reads files, writes files, runs Lua, changes category codes, or builds a
# control-sequence name from span text.  That last rule excludes ``\not``
# (unicode-math looks up and runs ``\not<argument>`` or ``\n<argument>``)
# and ``\smash`` (amsmath runs ``\mb@<optional argument>``); write
# ``\neq``, ``\notin``, ``\nleq`` and the other negated symbols instead.
# ``tests/test_latex_pdf_renderer.py`` typesets every word in the template.
MATH_CONTROL_WORDS = frozenset(
    """
    alpha beta gamma delta epsilon varepsilon zeta eta theta vartheta iota
    kappa varkappa lambda mu nu xi omicron pi varpi rho varrho sigma varsigma
    tau upsilon phi varphi chi psi omega
    Gamma Delta Theta Lambda Xi Pi Sigma Upsilon Phi Psi Omega
    varGamma varDelta varTheta varLambda varXi varPi varSigma varUpsilon
    varPhi varPsi varOmega
    aleph beth gimel daleth ell hbar hslash imath jmath wp Re Im partial nabla
    infty emptyset varnothing forall exists nexists neg lnot top bot angle
    measuredangle sphericalangle prime backprime triangle
    surd flat natural sharp clubsuit
    diamondsuit heartsuit spadesuit complement eth mho
    dag ddag
    pm mp times div cdot cdotp ldotp ast star circ bullet cap cup sqcap sqcup
    vee wedge lor land setminus wr oplus ominus otimes
    oslash odot bigcirc dagger ddagger amalg uplus
    triangleleft triangleright boxplus boxminus boxtimes boxdot dotplus ltimes
    rtimes curlyvee curlywedge
    leq le geq ge neq ne equiv approx approxeq sim simeq backsim cong propto
    prec succ preceq succeq ll gg lll ggg subset supset subseteq supseteq
    subsetneq supsetneq nsubseteq nsupseteq sqsubset
    sqsupset sqsubseteq sqsupseteq in ni notin owns vdash dashv models vDash
    Vdash perp mid nmid parallel nparallel smile frown asymp doteq bowtie
    leqslant geqslant lesssim gtrsim lneq gneq lneqq
    gneqq leqq geqq nleq ngeq nless ngtr nsim ncong triangleq coloneq eqcolon
    vartriangleleft vartriangleright trianglelefteq trianglerighteq precsim
    succsim preccurlyeq succcurlyeq curlyeqprec
    curlyeqsucc therefore because between lessgtr gtrless
    lesseqgtr gtreqless eqsim circeq risingdotseq fallingdotseq
    to gets leftarrow rightarrow Leftarrow Rightarrow leftrightarrow
    Leftrightarrow longleftarrow longrightarrow Longleftarrow Longrightarrow
    longleftrightarrow Longleftrightarrow mapsto longmapsto uparrow downarrow
    Uparrow Downarrow updownarrow Updownarrow nearrow searrow swarrow nwarrow
    hookleftarrow hookrightarrow implies impliedby iff rightleftharpoons
    leftrightharpoons rightharpoonup rightharpoondown leftharpoonup
    leftharpoondown upharpoonleft upharpoonright downharpoonleft
    downharpoonright twoheadrightarrow twoheadleftarrow rightsquigarrow
    nrightarrow nleftarrow nRightarrow nLeftarrow nleftrightarrow
    nLeftrightarrow leftleftarrows rightrightarrows leftrightarrows
    rightleftarrows Lsh Rsh looparrowleft looparrowright curvearrowleft
    curvearrowright xrightarrow xleftarrow
    sum prod coprod int iint iiint oint bigcup bigcap bigoplus bigotimes
    bigodot bigvee bigwedge bigsqcup biguplus
    arccos arcsin arctan arg cos cosh cot coth csc deg det dim exp gcd hom inf
    ker lg lim liminf limsup ln log max min Pr sec sin sinh sup tan tanh
    injlim projlim varliminf varlimsup operatorname bmod pmod pod mod
    hat widehat check widecheck tilde widetilde acute grave dot ddot dddot
    ddddot breve bar vec overline underline overbrace underbrace
    overrightarrow overleftarrow overleftrightarrow underrightarrow
    underleftarrow underleftrightarrow mathring
    mathrm mathbf mathit mathsf mathtt mathcal mathbb mathfrak mathscr
    mathnormal mathbfit mathbfcal mathbfscr mathbffrak mathbfsf boldsymbol
    symbf symrm symit symsf symtt symcal symbb symfrak symscr symup symbfit
    symbfup symnormal text textrm textbf textit textsf texttt textnormal
    textup textsl emph mbox
    frac dfrac tfrac cfrac binom dbinom tbinom genfrac sqrt root of over
    choose atop left right middle big Big bigg Bigg bigl bigr Bigl Bigr biggl
    biggr Biggl Biggr bigm Bigm biggm Biggm overset underset stackrel substack
    sideset limits nolimits notag nonumber displaystyle textstyle scriptstyle
    scriptscriptstyle phantom vphantom hphantom mathstrut boxed cdots
    ldots hdots dots dotsc dotsb dotsm dotsi dotso vdots ddots colon quad qquad
    enspace thinspace medspace thickspace negthinspace negmedspace
    negthickspace mathop mathbin mathrel mathord mathpunct mathopen mathclose
    mathinner langle rangle lceil rceil lfloor rfloor lvert rvert lVert
    rVert vert Vert backslash lbrace rbrace lbrack rbrack ulcorner urcorner
    llcorner lrcorner
    """.split()
)
# Single-character control symbols that only typeset spacing, delimiters, or
# escaped specials.  Every other control symbol (``\@``, ``\^``, ``\'``, ...)
# is rejected.
MATH_CONTROL_SYMBOLS = frozenset(",:;!> {}|\\%#&$_/\n\t")
# Defence in depth: names that must never be allowlisted, even by mistake.
# ``tests/test_latex_pdf_renderer.py`` asserts the allowlist stays disjoint.
FORBIDDEN_MATH_CONTROL_WORD = re.compile(
    r"^(?:lua|input|include|IfFileExists|read|expandafter|csname|makeat|"
    r"directlua|latelua|write|immediate|open|catcode|scantokens|def|edef|"
    r"gdef|xdef|let|futurelet|special|shipout|every|pdfextension|"
    r"usepackage|documentclass|newcommand|renewcommand|ExplSyntax|ShellEscape|"
    # Exact names: these build a control-sequence name from their argument.
    r"(?:not|smash)\Z)",
    re.IGNORECASE,
)
# A TeX control sequence: a backslash followed by a run of letters (in
# LuaLaTeX, non-ASCII letters have category code 11 too, so any non-ASCII
# character is treated as part of the name and rejects it), by exactly one
# other character, or by nothing at the end of the span.
MATH_CONTROL_SEQUENCE = re.compile(r"\\(?:([A-Za-z\u0080-\U0010ffff]+)|(.)|\Z)", re.DOTALL)
# ``^^5c`` and its variants synthesize arbitrary characters (including a
# backslash) when TeX reads input, so they may not appear in a math span.
# ``@`` is rejected because it is the letter of internal kernel commands such
# as ``\@input``.  Raw control characters have no place in typeset math.
MATH_UNSAFE_CHARACTERS = re.compile(r"\^\^|@|[\x00-\x08\x0b-\x1f\x7f]")
# The braced name that follows ``\begin`` or ``\end``.
MATH_ENVIRONMENT_ARGUMENT = re.compile(r"\s*\{([^{}]+)\}")
SAFE_MATH_ENVIRONMENTS = frozenset(
    {"aligned", "alignedat", "cases", "matrix", "pmatrix", "bmatrix", "smallmatrix", "split", "gathered"}
)
MISSING_GLYPH_PATTERNS = (
    re.compile(r"Missing character: There is no .+ in font", re.IGNORECASE),
    re.compile(r"missing glyph", re.IGNORECASE),
    re.compile(r"glyph .+ not found", re.IGNORECASE),
)
UNDEFINED_PATTERNS = (
    re.compile(r"Undefined control sequence", re.IGNORECASE),
    re.compile(r"LaTeX Warning: Reference .+ undefined", re.IGNORECASE),
    re.compile(r"LaTeX Warning: Citation .+ undefined", re.IGNORECASE),
    re.compile(r"There were undefined references", re.IGNORECASE),
    re.compile(r"There were undefined citations", re.IGNORECASE),
)
OVERFULL = re.compile(
    r"Overfull \\(?P<kind>[hv])box \((?P<points>[0-9]+(?:\.[0-9]+)?)pt too (?:wide|high)\)",
    re.IGNORECASE,
)

# Reports should delimit mathematics explicitly, but legacy reviews and quoted
# manuscript text sometimes contain unmistakable TeX-style symbols without
# ``$...$``.  Recognize only conservative mathematical shapes: single-letter,
# Greek, or uppercase identifiers with subscripts; simple fractions of those
# identifiers; derivatives; and standard variance/covariance calls.  Ordinary
# snake_case prose and filenames deliberately remain prose.
_MATH_BASE = r"(?:[A-Z][A-Z0-9]*|[A-Za-z]|[\u0370-\u03ff])"
_MATH_SUBSCRIPT = r"_(?:\{[A-Za-z0-9, +*/\-\u0370-\u03ff]+\}|[A-Za-z0-9\u0370-\u03ff]+)"
BARE_MATH_TOKEN = re.compile(
    rf"(?<![\w\\$])(?P<math>"
    rf"(?:Var|Cov|Corr)\([A-Za-z0-9_,.+\-*/^'|\u0370-\u03ff]{{1,80}}\)"
    rf"|d{_MATH_BASE}/d{_MATH_BASE}(?:{_MATH_SUBSCRIPT})?"
    rf"|(?:\d+/)?{_MATH_BASE}{_MATH_SUBSCRIPT}"
    rf")(?![\w])"
)


class LatexRenderError(RuntimeError):
    """Raised when no safe renderer produces an acceptable PDF."""


@dataclass(frozen=True)
class ReviewDocument:
    """One author-facing Markdown document included in the PDF."""

    title: str
    markdown: str
    role: str = "report"
    source_name: str = ""


@dataclass(frozen=True)
class RenderAttempt:
    renderer: str
    return_code: int
    outcome: str


@dataclass(frozen=True)
class RenderProfile:
    """Machine-readable provenance for integration-owned receipts."""

    renderer: str
    engine: str
    compiler_version: str
    page_count: int | None
    page_size: str
    document_count: int
    source_date_epoch: int
    template_sha256: str
    latex_sha256: str
    pdf_sha256: str
    diagnostics: tuple[str, ...]
    attempts: tuple[RenderAttempt, ...]

    def to_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class RenderResult:
    pdf_bytes: bytes
    profile: RenderProfile
    log_summary: str


@dataclass(frozen=True)
class _Toolchain:
    name: str
    engine: str
    executable: str


def _tex_escape(text: str) -> str:
    replacements = {
        "\\": r"\textbackslash{}",
        "{": r"\{",
        "}": r"\}",
        "$": r"\$",
        "&": r"\&",
        "#": r"\#",
        "%": r"\%",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    return "".join(replacements.get(character, character) for character in text)


def _plain_markdown(text: str) -> str:
    text = re.sub(r"!\[([^]]*)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"\[([^]]+)\]\([^)]+\)", r"\1", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"(\*\*|__)(.*?)\1", r"\2", text)
    text = re.sub(r"(?<!\*)\*([^*]+)\*(?!\*)", r"\1", text)
    text = re.sub(r"(?<![\w_])_([^_\n]+?)_(?![\w_])", r"\1", text)
    text = re.sub(r"\$+([^$]+)\$+", r"\1", text)
    text = text.replace(r"\(", "").replace(r"\)", "")
    text = text.replace(r"\[", "").replace(r"\]", "")
    return " ".join(text.split())


def _safe_math(content: str) -> str:
    """Return an explicit math span unchanged, or reject it before compilation.

    Only allowlisted math control words, a few spacing/delimiter control
    symbols, and the ``SAFE_MATH_ENVIRONMENTS`` may appear.  Rejection names
    the offending token so the author-facing text can be rewritten as prose.
    """
    if "\x00" in content:
        raise LatexRenderError("NUL byte in an explicit math span")
    unsafe_character = MATH_UNSAFE_CHARACTERS.search(content)
    if unsafe_character:
        raise LatexRenderError(
            f"unsafe character {unsafe_character.group(0)!r} in an explicit math span"
        )
    # Scan once, left to right, exactly as TeX tokenizes: ``\\`` is one
    # control symbol, so ``\\begin{aligned}\input`` must not be read as an
    # environment followed by an escaped backslash.  Environment names are
    # validated at the position where TeX would read them.
    for match in MATH_CONTROL_SEQUENCE.finditer(content):
        word, symbol = match.group(1), match.group(2)
        if word in {"begin", "end"}:
            environment = MATH_ENVIRONMENT_ARGUMENT.match(content, match.end())
            if not environment or environment.group(1).strip() not in SAFE_MATH_ENVIRONMENTS:
                raise LatexRenderError("unsafe environment in an explicit math span")
            continue
        if word is not None:
            if word in MATH_CONTROL_WORDS and not FORBIDDEN_MATH_CONTROL_WORD.match(word):
                continue
            raise LatexRenderError(f"unsafe TeX command \\{word} in an explicit math span")
        if symbol is not None and symbol in MATH_CONTROL_SYMBOLS:
            continue
        raise LatexRenderError(
            f"unsafe TeX control symbol {match.group(0)!r} in an explicit math span"
        )
    # Outside control sequences, a bare ``%`` comments out the rest of the
    # line, a bare ``#`` is a macro-parameter character, and unbalanced braces
    # change the group structure; all three would surface only as an opaque
    # compile failure.
    residue = MATH_CONTROL_SEQUENCE.sub(" ", content)
    if "%" in residue:
        raise LatexRenderError("unescaped % in an explicit math span (write \\% for a percent sign)")
    if "#" in residue:
        raise LatexRenderError("unescaped # in an explicit math span (write \\# for a number sign)")
    depth = 0
    for character in residue:
        if character == "{":
            depth += 1
        elif character == "}":
            depth -= 1
            if depth < 0:
                break
    if depth != 0:
        raise LatexRenderError("unbalanced braces in an explicit math span")
    return content


def _render_plain_text(text: str) -> str:
    """Escape prose while typesetting unmistakable bare math from legacy text."""
    output: list[str] = []
    position = 0
    for match in BARE_MATH_TOKEN.finditer(text):
        output.append(_tex_escape(text[position:match.start()]))
        math = match.group("math")
        math = re.sub(r"^(Var|Cov|Corr)\(", r"\\operatorname{\1}(", math)
        math = re.sub(r"_([A-Za-z]{2,})(?![A-Za-z])", r"_{\\mathrm{\1}}", math)
        output.append("$" + _safe_math(math) + "$")
        position = match.end()
    output.append(_tex_escape(text[position:]))
    return "".join(output)


def _valid_external_url(url: str) -> bool:
    try:
        parsed = urlsplit(url.strip())
    except ValueError:
        return False
    return parsed.scheme.lower() in {"http", "https", "mailto"} and bool(parsed.path or parsed.netloc)


def _find_closing(text: str, delimiter: str, start: int) -> int:
    index = start
    while True:
        index = text.find(delimiter, index)
        if index < 0:
            return -1
        if index == 0 or text[index - 1] != "\\":
            return index
        index += len(delimiter)


def render_inline(text: str) -> str:
    """Render the controlled inline Markdown grammar with strict TeX escaping."""
    output: list[str] = []
    plain: list[str] = []

    def flush_plain() -> None:
        if plain:
            output.append(_render_plain_text("".join(plain)))
            plain.clear()

    index = 0
    while index < len(text):
        if text.startswith("\\(", index):
            end = _find_closing(text, "\\)", index + 2)
            if end >= 0:
                flush_plain()
                output.append(r"\(" + _safe_math(text[index + 2:end]) + r"\)")
                index = end + 2
                continue
        if text[index] == "$" and not text.startswith("$$", index):
            end = _find_closing(text, "$", index + 1)
            if end > index + 1 and not text[index + 1].isspace() and not text[end - 1].isspace():
                flush_plain()
                output.append("$" + _safe_math(text[index + 1:end]) + "$")
                index = end + 1
                continue
        if text[index] == "`":
            end = _find_closing(text, "`", index + 1)
            if end >= 0:
                flush_plain()
                output.append(r"\texttt{" + _tex_escape(text[index + 1:end]) + "}")
                index = end + 1
                continue
        if text.startswith("**", index) or text.startswith("__", index):
            marker = text[index:index + 2]
            end = _find_closing(text, marker, index + 2)
            if end > index + 2:
                flush_plain()
                output.append(r"\textbf{" + render_inline(text[index + 2:end]) + "}")
                index = end + 2
                continue
        if text[index] in "*_":
            marker = text[index]
            end = _find_closing(text, marker, index + 1)
            valid_underscore = marker != "_" or (
                (index == 0 or not text[index - 1].isalnum())
                and (end + 1 == len(text) or not text[end + 1].isalnum())
            )
            if end > index + 1 and not text[index + 1].isspace() and valid_underscore:
                flush_plain()
                output.append(r"\emph{" + render_inline(text[index + 1:end]) + "}")
                index = end + 1
                continue
        if text[index] == "[":
            label_end = _find_closing(text, "]", index + 1)
            if label_end >= 0 and label_end + 1 < len(text) and text[label_end + 1] == "(":
                url_end = _find_closing(text, ")", label_end + 2)
                if url_end >= 0:
                    flush_plain()
                    label = render_inline(text[index + 1:label_end])
                    url = text[label_end + 2:url_end].strip()
                    if _valid_external_url(url):
                        output.append(r"\href{" + _tex_escape(url) + "}{" + label + "}")
                    else:
                        output.append(label)
                    index = url_end + 1
                    continue
        if text[index] == "!" and index + 1 < len(text) and text[index + 1] == "[":
            label_end = _find_closing(text, "]", index + 2)
            if label_end >= 0 and label_end + 1 < len(text) and text[label_end + 1] == "(":
                url_end = _find_closing(text, ")", label_end + 2)
                if url_end >= 0:
                    flush_plain()
                    alt = text[index + 2:label_end].strip()
                    output.append(r"\emph{" + _tex_escape(alt or "Figure") + "}")
                    index = url_end + 1
                    continue
        if text[index] == "\\" and index + 1 < len(text) and text[index + 1] in r"\`*_{}[]()#+-.!$":
            plain.append(text[index + 1])
            index += 2
            continue
        plain.append(text[index])
        index += 1
    flush_plain()
    return "".join(output)


def sanitize_markdown(markdown: str) -> str:
    """Remove navigation, hidden bindings, raw HTML, and legacy display labels."""
    text = markdown.replace("\r\n", "\n").replace("\r", "\n")
    text = NAVIGATION_BLOCK.sub("\n", text)
    text = HTML_COMMENT.sub("", text)
    text = HTML_TAG.sub("", text)
    text = LEGACY_DETAILED_WRITING.sub("Detailed Editing Comments", text)
    lines = []
    for line in text.splitlines():
        quote = re.match(r"^(\s*>\s*)(.*)$", line)
        if quote:
            line = quote.group(1) + PREFIX.sub("", quote.group(2))
        else:
            line = PREFIX.sub("", line)
        lines.append(line.rstrip())
    return "\n".join(lines).strip() + "\n"


def _strip_revision_workflow_paragraphs(markdown: str) -> str:
    """Keep viewer/export instructions out of the reader-facing PDF plan."""
    blocks = re.split(r"(\n[ \t]*\n)", markdown)
    kept: list[str] = []
    for block in blocks:
        folded = block.casefold()
        if "review desk" in folded or "review-actions.json" in folded:
            continue
        kept.append(block)
    return "".join(kept)


def _split_table_row(line: str) -> list[str]:
    stripped = line.strip()
    if stripped.startswith("|"):
        stripped = stripped[1:]
    if stripped.endswith("|") and not stripped.endswith(r"\|"):
        stripped = stripped[:-1]
    cells: list[str] = []
    current: list[str] = []
    escaped = False
    code = False
    for character in stripped:
        if character == "`" and not escaped:
            code = not code
        if character == "|" and not escaped and not code:
            cells.append("".join(current).strip())
            current = []
        else:
            current.append(character)
        escaped = character == "\\" and not escaped
        if character != "\\":
            escaped = False
    cells.append("".join(current).strip())
    return cells


def _is_table_start(lines: Sequence[str], index: int) -> bool:
    if index + 1 >= len(lines) or "|" not in lines[index] or "|" not in lines[index + 1]:
        return False
    dividers = _split_table_row(lines[index + 1])
    return bool(dividers) and all(TABLE_DIVIDER.fullmatch(cell.strip()) for cell in dividers)


def _table_tex(rows: Sequence[Sequence[str]]) -> str:
    columns = max(len(row) for row in rows)
    if columns < 1:
        return ""
    if columns <= 2:
        usable = 0.90
    elif columns == 3:
        usable = 0.86
    else:
        usable = 0.82
    width = usable / columns
    specification = "".join(
        rf">{{\RaggedRight\arraybackslash}}p{{{width:.4f}\textwidth}}"
        for _ in range(columns)
    )
    normalized = [list(row) + [""] * (columns - len(row)) for row in rows]
    if columns >= 5:
        # Portrait pages make five-or-more prose columns unreadably narrow.
        # Use a responsive stacked projection that preserves every header and
        # cell while remaining useful on both Letter and A4 pages.
        headers = normalized[0]
        output = [r"\begingroup", r"\small"]
        for row in normalized[1:]:
            lead = row[0] or headers[0]
            output.extend(
                [
                    r"\Needspace{11\baselineskip}",
                    r"\par\medskip",
                    r"{\sffamily\bfseries\color{ReviewInk} "
                    + render_inline(lead)
                    + r"}\par",
                    r"\smallskip",
                ]
            )
            for header, value in zip(headers[1:], row[1:]):
                if not value:
                    continue
                output.append(
                    r"\textbf{" + render_inline(header) + r".} "
                    + render_inline(value)
                    + r"\par"
                )
            output.append(r"{\color{ReviewRule}\hrule height 0.5pt}\medskip")
        output.extend([r"\endgroup"])
        return "\n".join(output)
    header = " & ".join(
        r"\textbf{" + render_inline(cell) + "}" for cell in normalized[0]
    ) + r" \\"
    font_size = r"\small" if columns >= 4 else r"\normalsize"
    output = [
        r"\Needspace{12\baselineskip}",
        r"\begingroup",
        font_size,
        r"\begin{longtable}{" + specification + "}",
        r"\toprule",
        header,
        r"\midrule",
        r"\endfirsthead",
        r"\toprule",
        header,
        r"\midrule",
        r"\endhead",
        r"\midrule",
        rf"\multicolumn{{{columns}}}{{r}}{{\sffamily\footnotesize\color{{ReviewMuted}}Continued on next page}} \\",
        r"\endfoot",
        r"\bottomrule",
        r"\endlastfoot",
    ]
    for row in normalized[1:]:
        output.append(" & ".join(render_inline(cell) for cell in row) + r" \\")
        output.append(r"\addlinespace[0.18em]")
    output.extend([r"\end{longtable}", r"\endgroup"])
    return "\n".join(output)


def _heading_tex(
    level: int,
    title: str,
    role: str,
    *,
    reserve_space: bool = True,
    reserve_lines: int | None = None,
) -> str:
    title = title.strip()
    if role == "editing_comments":
        title = LEGACY_WRITING.sub("Editing comments", title)
        title = LEGACY_DETAILED_WRITING.sub("Detailed Editing Comments", title)
    if role == "revision_plan":
        priority = PRIORITY_HEADING.fullmatch(title)
        if priority:
            title = f"P{priority.group(1)} — {priority.group(2).strip()}"
        task = REVISION_ID.fullmatch(title)
        if task:
            title = task.group(1).strip()
    rendered = render_inline(title)
    bookmark = _tex_escape(_plain_markdown(title))
    safe_title = rf"\texorpdfstring{{{rendered}}}{{{bookmark}}}"
    if level <= 2:
        need = 14
        heading = rf"\subsection{{{safe_title}}}"
    elif level == 3:
        need = 8
        heading = rf"\subsubsection{{{safe_title}}}"
    elif level == 4:
        need = 6
        heading = rf"\paragraph{{{safe_title}}}"
    else:
        need = 5
        heading = rf"\subparagraph{{{safe_title}}}"
    if reserve_space:
        if reserve_lines is not None:
            need = reserve_lines
        return "\n".join((rf"\Needspace{{{need}\baselineskip}}", heading))
    return heading


def markdown_to_latex(markdown: str, *, role: str = "report") -> str:
    """Convert the report's controlled Markdown grammar into safe LaTeX."""
    clean = sanitize_markdown(markdown)
    if role == "revision_plan":
        clean = _strip_revision_workflow_paragraphs(clean)
    lines = clean.splitlines()
    output: list[str] = []
    index = 0
    first_heading_skipped = False
    revision_action_open = False
    revision_priority_waiting = False

    def block_start(at: int) -> bool:
        if at >= len(lines):
            return True
        line = lines[at]
        stripped = line.strip()
        return (
            not stripped
            or bool(HEADING.match(line))
            or bool(FENCE.match(line))
            or stripped.startswith(">")
            or bool(LIST_ITEM.match(line))
            or THEMATIC_BREAK.match(line) is not None
            or _is_table_start(lines, at)
            or stripped.startswith("$$")
            or stripped.startswith(r"\[")
        )

    while index < len(lines):
        line = lines[index]
        stripped = line.strip()
        if not stripped:
            index += 1
            continue

        fence = FENCE.match(line)
        if fence:
            marker = fence.group(1)
            code_lines: list[str] = []
            index += 1
            while index < len(lines) and not lines[index].lstrip().startswith(marker):
                code_lines.append(lines[index])
                index += 1
            if index < len(lines):
                index += 1
            output.append(r"\begin{reviewcode}")
            for code_line in code_lines:
                output.append(_tex_escape(code_line) + r"\par")
            output.append(r"\end{reviewcode}")
            continue

        heading = HEADING.match(line)
        if heading:
            level = len(heading.group(1))
            title = heading.group(2).strip()
            next_nonblank = index + 1
            while next_nonblank < len(lines) and not lines[next_nonblank].strip():
                next_nonblank += 1
            next_heading = (
                HEADING.match(lines[next_nonblank])
                if next_nonblank < len(lines)
                else None
            )
            priority_heading = (
                role == "revision_plan"
                and level == 2
                and next_heading is not None
                and len(next_heading.group(1)) == 3
            )
            first_priority_action = (
                revision_action_open
                and revision_priority_waiting
                and role == "revision_plan"
                and level == 3
            )
            if revision_action_open and not first_priority_action:
                output.append(r"\end{samepage}")
                revision_action_open = False
                revision_priority_waiting = False
            if level == 1 and not first_heading_skipped:
                first_heading_skipped = True
            else:
                if priority_heading:
                    output.append(r"\begin{samepage}")
                    revision_action_open = True
                    revision_priority_waiting = True
                elif role == "revision_plan" and level == 3:
                    if first_priority_action:
                        revision_priority_waiting = False
                    else:
                        output.append(r"\begin{samepage}")
                        revision_action_open = True
                # The surrounding samepage block already protects the first
                # action after a priority heading.  A nested Needspace here
                # could force a break between that heading and its action.
                output.append(
                    _heading_tex(
                        level,
                        title,
                        role,
                        reserve_space=not first_priority_action,
                        reserve_lines=28 if priority_heading else None,
                    )
                )
            index += 1
            continue

        if stripped.startswith("$$") or stripped.startswith(r"\["):
            dollar = stripped.startswith("$$")
            opener, closer = ("$$", "$$") if dollar else (r"\[", r"\]")
            content = stripped[len(opener):]
            pieces: list[str] = []
            if content.endswith(closer) and content != closer:
                pieces.append(content[:-len(closer)])
                index += 1
            else:
                if content:
                    pieces.append(content)
                index += 1
                while index < len(lines):
                    candidate = lines[index]
                    if candidate.strip().endswith(closer):
                        pieces.append(candidate[: candidate.rfind(closer)])
                        index += 1
                        break
                    pieces.append(candidate)
                    index += 1
                else:
                    raise LatexRenderError("unterminated display-math block")
            math = _safe_math("\n".join(pieces).strip())
            output.append("\\[\n" + math + "\n\\]")
            continue

        if _is_table_start(lines, index):
            rows = [_split_table_row(lines[index])]
            index += 2
            while index < len(lines) and "|" in lines[index] and lines[index].strip():
                rows.append(_split_table_row(lines[index]))
                index += 1
            output.append(_table_tex(rows))
            continue

        if stripped.startswith(">"):
            quote_lines: list[str] = []
            while index < len(lines) and lines[index].lstrip().startswith(">"):
                content = re.sub(r"^\s*>\s?", "", lines[index])
                quote_lines.append(PREFIX.sub("", content))
                index += 1
            output.extend(
                (
                    r"\Needspace{5\baselineskip}",
                    r"\begin{reviewquote}",
                    render_inline(" ".join(quote_lines)),
                    r"\end{reviewquote}",
                )
            )
            continue

        list_match = LIST_ITEM.match(line)
        if list_match:
            ordered = list_match.group("marker")[0].isdigit()
            environment = "enumerate" if ordered else "itemize"
            output.append(r"\begin{" + environment + "}")
            base_indent = len(list_match.group("indent").expandtabs(4))
            while index < len(lines):
                item = LIST_ITEM.match(lines[index])
                if not item:
                    break
                item_ordered = item.group("marker")[0].isdigit()
                indent = len(item.group("indent").expandtabs(4))
                if item_ordered != ordered or indent != base_indent:
                    break
                body = item.group("body").strip()
                task = TASK_ITEM.match(body)
                # Keep the short closing fields of revision-plan items
                # together.  Reserving space at the start of the tail lets a
                # break occur between actions instead of before ``Done when``,
                # ``Effort``, or ``Dependencies``.
                field_body = task.group("body") if task else body
                tail_field = re.match(
                    r"^\*\*(Payoff|Done when|Effort|Feasibility):?\*\*",
                    field_body,
                    re.IGNORECASE,
                )
                if tail_field and not revision_action_open:
                    reserved = {
                        "payoff": 15,
                        "done when": 10,
                        "effort": 5,
                        "feasibility": 6,
                    }[tail_field.group(1).casefold()]
                    output.append(rf"\Needspace{{{reserved}\baselineskip}}")
                if task:
                    checked = task.group("state").lower() == "x"
                    checkbox = r"\ReviewChecked" if checked else r"\ReviewUnchecked"
                    output.append(r"\item[" + checkbox + "] " + render_inline(task.group("body")))
                else:
                    output.append(r"\item " + render_inline(body))
                index += 1
                continuation: list[str] = []
                while index < len(lines) and lines[index].strip() and not block_start(index):
                    continuation.append(lines[index].strip())
                    index += 1
                if continuation:
                    output.append(" " + render_inline(" ".join(continuation)))
            output.append(r"\end{" + environment + "}")
            if revision_action_open:
                output.append(r"\end{samepage}")
                revision_action_open = False
                revision_priority_waiting = False
            continue

        if THEMATIC_BREAK.match(line):
            output.append(r"\par\medskip{\color{ReviewRule}\hrule height 0.6pt}\medskip")
            index += 1
            continue

        paragraph = [stripped]
        index += 1
        while index < len(lines) and not block_start(index):
            paragraph.append(lines[index].strip())
            index += 1
        paragraph_text = " ".join(paragraph)
        field = re.match(
            r"^\*\*(Issue|Relevant text|Concern(?: and suggestions)?|Suggestions|Status):?\*\*",
            paragraph_text,
            re.IGNORECASE,
        )
        if field:
            if field.group(1).casefold() == "status":
                # Status is interactive workflow state in Markdown and Review
                # Desk. A static PDF cannot update it, so printing Pending on
                # every comment makes the finished report look unfinished.
                continue
            need = {
                "issue": 5,
                "relevant text": 8,
                "concern": 6,
                "concern and suggestions": 9,
                "suggestions": 9,
                "status": 3,
            }[field.group(1).casefold()]
            output.append(rf"\Needspace{{{need}\baselineskip}}")
        output.append(render_inline(paragraph_text) + r"\par")

    if revision_action_open:
        output.append(r"\end{samepage}")
    return "\n\n".join(output).strip()


def _normalized_document_title(document: ReviewDocument) -> str:
    title = document.title.strip()
    if document.role == "editing_comments" or LEGACY_WRITING.fullmatch(title):
        return "Editing comments"
    if document.role == "revision_plan":
        return "Revision plan"
    if title.casefold() == "referee report":
        return "Referee Report"
    return title


def running_header_title(title: str, limit: int = 55) -> str:
    """Return a compact title without cutting a word in half."""
    normalized = " ".join(title.split()).strip()
    if len(normalized) <= limit:
        return normalized
    available = max(1, limit - 1)
    words: list[str] = []
    for word in normalized.split():
        candidate = " ".join((*words, word))
        if len(candidate) > available:
            break
        words.append(word)
    shortened = " ".join(words).rstrip(" ,:;-")
    if not shortened:
        shortened = normalized[:available].rstrip(" ,:;-")
    return shortened + "…"


def build_latex_source(
    *,
    paper_title: str,
    assessment_date: date,
    documents: Sequence[ReviewDocument],
    template_path: Path = DEFAULT_TEMPLATE,
    page_size: str = "letter",
) -> str:
    """Build a complete standalone TeX source without executing user TeX."""
    if not paper_title.strip():
        raise ValueError("paper_title must be the manuscript's actual non-empty title")
    if not documents:
        raise ValueError("at least one author-facing document is required")
    if page_size not in {"letter", "a4"}:
        raise ValueError("page_size must be 'letter' or 'a4'")
    template = template_path.read_text(encoding="utf-8")
    body: list[str] = []
    for position, document in enumerate(documents):
        if position:
            body.append(r"\clearpage")
        title = _normalized_document_title(document)
        heading = rf"\texorpdfstring{{{render_inline(title)}}}{{{_tex_escape(_plain_markdown(title))}}}"
        body.append(rf"\section{{{heading}}}")
        body.append(markdown_to_latex(document.markdown, role=document.role))
    display_date = f"{assessment_date.strftime('%B')} {assessment_date.day}, {assessment_date.year}"
    header_title = running_header_title(paper_title)
    title_length = len(paper_title.strip())
    if title_length <= 55:
        title_size, title_leading = "26", "32"
    elif title_length <= 100:
        title_size, title_leading = "21.5", "27.5"
    else:
        title_size, title_leading = "19", "24.5"
    values = {
        "%%PAPER_TITLE%%": render_inline(paper_title.strip()),
        "%%PDF_TITLE%%": _tex_escape(paper_title.strip()),
        "%%HEADER_TITLE%%": _tex_escape(header_title),
        "%%ASSESSMENT_DATE%%": _tex_escape(display_date),
        "%%TITLE_FONT_SIZE%%": title_size,
        "%%TITLE_LEADING%%": title_leading,
        "%%PAGE_SIZE_OPTION%%": "letterpaper" if page_size == "letter" else "a4paper",
        "%%BODY%%": "\n\n".join(body),
    }
    source = template
    for placeholder, value in values.items():
        if placeholder not in source:
            raise LatexRenderError(f"template is missing required placeholder {placeholder}")
        source = source.replace(placeholder, value)
    unresolved = re.findall(r"%%[A-Z_]+%%", source)
    if unresolved:
        names = ", ".join(sorted(set(unresolved)))
        raise LatexRenderError(f"template contains unresolved placeholders: {names}")
    return source


def _source_date_epoch(assessment_date: date) -> int:
    # Noon UTC preserves the visible review date in PDF viewers across the
    # ordinary range of local time zones while remaining reproducible.
    instant = datetime.combine(assessment_date, datetime_time(hour=12), tzinfo=timezone.utc)
    return int(instant.timestamp())


def _toolchains(renderer: str) -> list[_Toolchain]:
    if renderer not in SUPPORTED_RENDERERS:
        raise ValueError(f"renderer must be one of {', '.join(SUPPORTED_RENDERERS)}")
    latexmk = shutil.which("latexmk")
    lualatex = shutil.which("lualatex")
    tectonic = shutil.which("tectonic")
    selected: _Toolchain | None = None
    if renderer == "auto":
        if latexmk and lualatex:
            selected = _Toolchain("latexmk-lualatex", "LuaLaTeX", latexmk)
        elif lualatex:
            selected = _Toolchain("lualatex", "LuaLaTeX", lualatex)
        elif tectonic:
            selected = _Toolchain("tectonic", "Tectonic", tectonic)
    elif renderer == "latexmk-lualatex" and latexmk and lualatex:
        selected = _Toolchain("latexmk-lualatex", "LuaLaTeX", latexmk)
    elif renderer == "lualatex" and lualatex:
        selected = _Toolchain("lualatex", "LuaLaTeX", lualatex)
    elif renderer == "tectonic" and tectonic:
        selected = _Toolchain("tectonic", "Tectonic", tectonic)
    if renderer != "auto" and selected is None:
        raise LatexRenderError(f"requested renderer is unavailable: {renderer}")
    if selected is None:
        raise LatexRenderError("no supported TeX renderer found (latexmk/LuaLaTeX or Tectonic)")
    # A content or compilation failure is authoritative.  Do not hide it by
    # retrying the same source through a different TeX implementation.
    return [selected]


def _auto_toolchains() -> list[_Toolchain]:
    """Return all installed TeX candidates in preference order."""

    latexmk = shutil.which("latexmk")
    lualatex = shutil.which("lualatex")
    tectonic = shutil.which("tectonic")
    candidates: list[_Toolchain] = []
    if latexmk and lualatex:
        candidates.append(_Toolchain("latexmk-lualatex", "LuaLaTeX", latexmk))
    if lualatex:
        candidates.append(_Toolchain("lualatex", "LuaLaTeX", lualatex))
    if tectonic:
        candidates.append(_Toolchain("tectonic", "Tectonic", tectonic))
    return candidates


def _compiler_version(toolchain: _Toolchain) -> str:
    command = [toolchain.executable, "--version"]
    if toolchain.name == "latexmk-lualatex":
        command = [toolchain.executable, "-version"]
    try:
        result = subprocess.run(
            command,
            capture_output=True,
            encoding="utf-8",
            errors="replace",
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return "unknown"
    line = (result.stdout or result.stderr).splitlines()
    return line[0].strip()[:180] if line else "unknown"


def _command(toolchain: _Toolchain, build_dir: Path) -> list[str]:
    if toolchain.name == "latexmk-lualatex":
        return [
            toolchain.executable,
            "-lualatex",
            "-interaction=nonstopmode",
            "-halt-on-error",
            "-file-line-error",
            f"-outdir={build_dir}",
            f"-auxdir={build_dir}",
            r"-pdflualatex=lualatex %O --no-shell-escape %S",
            "review.tex",
        ]
    if toolchain.name == "lualatex":
        return [
            toolchain.executable,
            "--no-shell-escape",
            "--interaction=nonstopmode",
            "--halt-on-error",
            "--file-line-error",
            f"--output-directory={build_dir}",
            "review.tex",
        ]
    return [
        toolchain.executable,
        "--untrusted",
        "--keep-logs",
        "--keep-intermediates",
        f"--outdir={build_dir}",
        "review.tex",
    ]


def _renderer_health(toolchain: _Toolchain, *, timeout: int) -> tuple[bool, str]:
    """Compile a minimal document using the real production command shape."""

    source = (
        "\\documentclass{article}\n"
        "\\begin{document}\n"
        "econ-review renderer health check\n"
        "\\end{document}\n"
    )
    with tempfile.TemporaryDirectory(prefix="econ-review-renderer-health-") as temporary:
        root = Path(temporary)
        build_dir = root / "build"
        build_dir.mkdir()
        (root / "review.tex").write_text(source, encoding="utf-8", newline="\n")
        environment = os.environ.copy()
        environment.update(
            {
                "SOURCE_DATE_EPOCH": "946728000",
                "FORCE_SOURCE_DATE": "1",
                "TZ": "UTC",
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
            }
        )
        try:
            result = subprocess.run(
                _command(toolchain, build_dir),
                cwd=root,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired:
            return False, f"timed out after {timeout}s"
        except OSError as exc:
            return False, f"could not start ({exc})"
        pdf_path = build_dir / "review.pdf"
        if result.returncode:
            return False, f"minimal compile failed ({result.returncode})"
        if not pdf_path.is_file() or not pdf_path.read_bytes().startswith(b"%PDF-"):
            return False, "minimal compile returned no valid PDF"
        return True, "healthy"


def select_healthy_renderer(*, timeout: int = 30) -> tuple[str | None, tuple[str, ...]]:
    """Select the first installed TeX backend that can actually compile.

    ``None`` tells the caller to use the built-in ReportLab renderer.  The
    compact diagnostics are suitable for provenance or a doctor command and do
    not expose compiler logs or local document content.
    """

    diagnostics: list[str] = []
    for toolchain in _auto_toolchains():
        healthy, reason = _renderer_health(toolchain, timeout=timeout)
        diagnostics.append(f"{toolchain.name}: {reason}")
        if healthy:
            return toolchain.name, tuple(diagnostics)
    if not diagnostics:
        diagnostics.append("no supported TeX renderer is installed")
    return None, tuple(diagnostics)


def _run_toolchain(
    toolchain: _Toolchain,
    *,
    root: Path,
    build_dir: Path,
    environment: Mapping[str, str],
    timeout: int,
) -> tuple[int, str, int]:
    command = _command(toolchain, build_dir)
    start = time.monotonic()
    combined: list[str] = []
    passes = 1 if toolchain.name != "lualatex" else 3
    return_code = 0
    for pass_number in range(passes):
        try:
            result = subprocess.run(
                command,
                cwd=root,
                env=dict(environment),
                capture_output=True,
                encoding="utf-8",
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except subprocess.TimeoutExpired as exc:
            elapsed_ms = round((time.monotonic() - start) * 1000)
            captured = (exc.stdout or "") + "\n" + (exc.stderr or "")
            return 124, captured + f"\nrenderer timed out after {timeout}s", elapsed_ms
        combined.append(f"--- pass {pass_number + 1} ---\n{result.stdout}\n{result.stderr}")
        return_code = result.returncode
        if return_code:
            break
    elapsed_ms = round((time.monotonic() - start) * 1000)
    return return_code, "\n".join(combined), elapsed_ms


def _log_diagnostics(log_text: str, *, material_overfull_pt: float) -> tuple[str, ...]:
    diagnostics: list[str] = []
    for pattern in MISSING_GLYPH_PATTERNS:
        match = pattern.search(log_text)
        if match:
            diagnostics.append("missing glyph: " + " ".join(match.group(0).split())[:220])
            break
    for pattern in UNDEFINED_PATTERNS:
        match = pattern.search(log_text)
        if match:
            diagnostics.append("undefined TeX object: " + " ".join(match.group(0).split())[:220])
            break
    material_boxes: list[str] = []
    for match in OVERFULL.finditer(log_text):
        points = float(match.group("points"))
        if points >= material_overfull_pt:
            material_boxes.append(f"{match.group('kind')}box {points:.2f}pt")
    if material_boxes:
        diagnostics.append("material overfull boxes: " + ", ".join(material_boxes[:8]))
    return tuple(diagnostics)


def _page_count(pdf_bytes: bytes) -> int | None:
    try:
        from pypdf import PdfReader  # type: ignore[import-not-found]

        return len(PdfReader(io.BytesIO(pdf_bytes)).pages)
    except Exception:
        matches = re.findall(rb"/Type\s*/Page\b", pdf_bytes)
        return len(matches) or None


def render_review_pdf(
    *,
    paper_title: str,
    assessment_date: date,
    documents: Sequence[ReviewDocument],
    renderer: str = "auto",
    template_path: Path = DEFAULT_TEMPLATE,
    page_size: str = "letter",
    timeout: int = 180,
    material_overfull_pt: float = 3.0,
) -> RenderResult:
    """Return PDF bytes and strict render provenance; write no persistent files."""
    source = build_latex_source(
        paper_title=paper_title,
        assessment_date=assessment_date,
        documents=documents,
        template_path=template_path,
        page_size=page_size,
    )
    template_hash = hashlib.sha256(template_path.read_bytes()).hexdigest()
    source_hash = hashlib.sha256(source.encode("utf-8")).hexdigest()
    epoch = _source_date_epoch(assessment_date)
    attempts: list[RenderAttempt] = []
    failure_notes: list[str] = []
    with tempfile.TemporaryDirectory(prefix="econ-review-latex-") as temporary:
        root = Path(temporary)
        (root / "review.tex").write_text(source, encoding="utf-8", newline="\n")
        environment = os.environ.copy()
        environment.update(
            {
                "SOURCE_DATE_EPOCH": str(epoch),
                "FORCE_SOURCE_DATE": "1",
                "TZ": "UTC",
                "LC_ALL": "C.UTF-8",
                "LANG": "C.UTF-8",
                "max_print_line": "10000",
            }
        )
        for toolchain in _toolchains(renderer):
            build_dir = root / ("build-" + toolchain.name)
            build_dir.mkdir()
            return_code, command_log, _elapsed_ms = _run_toolchain(
                toolchain,
                root=root,
                build_dir=build_dir,
                environment=environment,
                timeout=timeout,
            )
            log_path = build_dir / "review.log"
            final_log = (
                log_path.read_text(encoding="utf-8", errors="replace")
                if log_path.exists()
                else command_log
            )
            diagnostics = _log_diagnostics(final_log, material_overfull_pt=material_overfull_pt)
            pdf_path = build_dir / "review.pdf"
            if return_code != 0:
                outcome = f"compile failed ({return_code})"
            elif not pdf_path.is_file():
                outcome = "compiler returned no PDF"
            elif diagnostics:
                outcome = "; ".join(diagnostics)
            else:
                pdf_bytes = pdf_path.read_bytes()
                if not pdf_bytes.startswith(b"%PDF-"):
                    outcome = "compiler output is not a PDF"
                else:
                    attempts.append(RenderAttempt(toolchain.name, 0, "accepted"))
                    pdf_hash = hashlib.sha256(pdf_bytes).hexdigest()
                    profile = RenderProfile(
                        renderer=toolchain.name,
                        engine=toolchain.engine,
                        compiler_version=_compiler_version(toolchain),
                        page_count=_page_count(pdf_bytes),
                        page_size=page_size,
                        document_count=len(documents),
                        source_date_epoch=epoch,
                        template_sha256=template_hash,
                        latex_sha256=source_hash,
                        pdf_sha256=pdf_hash,
                        diagnostics=(),
                        attempts=tuple(attempts),
                    )
                    summary = (
                        f"{toolchain.name} produced {profile.page_count or 'an unknown number of'} pages; "
                        "no missing glyphs, undefined controls/references, or material overfull boxes."
                    )
                    return RenderResult(pdf_bytes, profile, summary)
            attempts.append(RenderAttempt(toolchain.name, return_code, outcome))
            failure_notes.append(f"{toolchain.name}: {outcome}")
    raise LatexRenderError("; ".join(failure_notes) or "LaTeX rendering failed")


def _load_review_documents(review_dir: Path) -> list[ReviewDocument]:
    candidates = (
        ("report.md", "Referee report", "referee_report"),
        ("editing-comments.md", "Editing comments", "editing_comments"),
        ("writing-report.md", "Editing comments", "editing_comments"),
        ("fix-plan.md", "Revision plan", "revision_plan"),
    )
    documents: list[ReviewDocument] = []
    seen_roles: set[str] = set()
    for filename, title, role in candidates:
        path = review_dir / filename
        if role in seen_roles or not path.is_file():
            continue
        documents.append(
            ReviewDocument(
                title=title,
                markdown=path.read_text(encoding="utf-8"),
                role=role,
                source_name=filename,
            )
        )
        seen_roles.add(role)
    if "referee_report" not in seen_roles:
        raise FileNotFoundError(f"missing referee report: {review_dir / 'report.md'}")
    return documents


def render_review_directory(
    review_dir: Path,
    *,
    paper_title: str | None = None,
    assessment_date: date | None = None,
    renderer: str = "auto",
    page_size: str = "letter",
    timeout: int = 180,
) -> RenderResult:
    """Render the reader-facing reports in a canonical review directory."""
    run_path = review_dir / "run.json"
    run: dict[str, object] = {}
    if run_path.is_file():
        loaded = json.loads(run_path.read_text(encoding="utf-8"))
        if not isinstance(loaded, dict):
            raise ValueError("run.json must contain an object")
        run = loaded
    run_title = run.get("paper_title")
    resolved_title = paper_title or (run_title if isinstance(run_title, str) else None)
    if not resolved_title:
        raise ValueError("paper_title is absent; pass the manuscript's actual title explicitly")
    resolved_date = assessment_date
    if resolved_date is None:
        raw_date = run.get("assessment_date")
        if not isinstance(raw_date, str):
            raise ValueError("assessment_date is absent; pass the review date explicitly")
        resolved_date = date.fromisoformat(raw_date)
    return render_review_pdf(
        paper_title=resolved_title,
        assessment_date=resolved_date,
        documents=_load_review_documents(review_dir),
        renderer=renderer,
        page_size=page_size,
        timeout=timeout,
    )


def _atomic_write(path: Path, payload: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(payload)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _parse_arguments(argv: Sequence[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("review_dir", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--paper-title")
    parser.add_argument("--assessment-date", type=date.fromisoformat)
    parser.add_argument("--renderer", choices=SUPPORTED_RENDERERS, default="auto")
    parser.add_argument("--page-size", choices=("letter", "a4"), default="letter")
    parser.add_argument("--profile-json", type=Path)
    parser.add_argument("--timeout", type=int, default=180)
    return parser.parse_args(argv)


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parse_arguments(argv)
    result = render_review_directory(
        arguments.review_dir,
        paper_title=arguments.paper_title,
        assessment_date=arguments.assessment_date,
        renderer=arguments.renderer,
        page_size=arguments.page_size,
        timeout=arguments.timeout,
    )
    _atomic_write(arguments.output, result.pdf_bytes)
    if arguments.profile_json:
        profile = json.dumps(result.profile.to_dict(), indent=2, ensure_ascii=False).encode("utf-8") + b"\n"
        _atomic_write(arguments.profile_json, profile)
    print(result.log_summary)
    return 0


if __name__ == "__main__":
    from cli_io import configure_utf8_stdio

    configure_utf8_stdio()
    raise SystemExit(main())
