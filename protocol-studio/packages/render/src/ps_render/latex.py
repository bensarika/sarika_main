"""Render AST -> LaTeX source, and LaTeX -> PDF via Tectonic.

``to_latex`` is deterministic (no timestamps beyond what the caller puts in
``RenderMeta``) so golden-file tests can diff it. The preamble is small and
uses only packages in Tectonic's default bundle: geometry, booktabs, longtable,
array, xcolor, hyperref, fancyhdr, draftwatermark-free watermark via
``\\AddToHook`` is avoided; the watermark is a header note instead.
"""

from __future__ import annotations

import re
import shutil
import subprocess
from pathlib import Path

from ps_render.ast import BulletList, Document, Heading, Note, Paragraph, Table

_ESC = {
    "\\": r"\textbackslash{}",
    "&": r"\&",
    "%": r"\%",
    "$": r"\$",
    "#": r"\#",
    "_": r"\_",
    "{": r"\{",
    "}": r"\}",
    "~": r"\textasciitilde{}",
    "^": r"\textasciicircum{}",
    "—": "---",
    "–": "--",
    "·": r"\textperiodcentered{}",
    "§": r"\S{}",
    "≥": r"$\geq$",
    "≤": r"$\leq$",
    "×": r"$\times$",
    "±": r"$\pm$",
    "“": "``",
    "”": "''",
    "’": "'",
}
_ESC_RE = re.compile("|".join(re.escape(k) for k in _ESC))
_BOLD = re.compile(r"\*\*(.+?)\*\*")
_ITAL = re.compile(r"(?<!\*)\*(?!\*)(.+?)(?<!\*)\*(?!\*)")


def escape(text: str) -> str:
    return _ESC_RE.sub(lambda m: _ESC[m.group(0)], text)


def inline(text: str) -> str:
    """Escape, then apply **bold** / *italic* markers."""
    out = escape(text)
    out = _BOLD.sub(r"\\textbf{\1}", out)
    out = _ITAL.sub(r"\\emph{\1}", out)
    return out


_PREAMBLE = r"""\documentclass[11pt,a4paper]{article}
\usepackage[margin=25mm]{geometry}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage{booktabs,longtable,array,xcolor,fancyhdr,enumitem,ragged2e}
\usepackage[hidelinks]{hyperref}
\setcounter{secnumdepth}{0}\setcounter{tocdepth}{1}
\definecolor{psink}{HTML}{1F2937}
\definecolor{psmuted}{HTML}{6B7280}
\definecolor{pswarn}{HTML}{B45309}
\definecolor{pserr}{HTML}{B91C1C}
\newcommand{\psnote}[2]{\par\noindent\colorbox{#1!8}{\parbox{\dimexpr\linewidth-2\fboxsep}{\small\color{#1}#2}}\par}
\newcommand{\psannot}[1]{\marginpar{\footnotesize\color{psmuted}#1}}
\pagestyle{fancy}\fancyhf{}
\renewcommand{\headrulewidth}{0.2pt}
\fancyhead[L]{\small\color{psmuted}@@HEADER@@}
\fancyfoot[L]{\footnotesize\color{psmuted}@@FOOTER@@}
\fancyfoot[R]{\footnotesize\thepage}
\setlength{\parskip}{6pt}\setlength{\parindent}{0pt}
\begin{document}
"""


def to_latex(doc: Document) -> str:
    header = escape(doc.title)[:90]
    out: list[str] = [_PREAMBLE.replace("@@HEADER@@", header).replace("@@FOOTER@@", escape(doc.footer))]
    # Title page
    out.append(r"\begin{titlepage}\vspace*{30mm}")
    out.append(r"{\color{psmuted}\large " + escape(doc.subtitle) + r"}\par\vspace{6mm}")
    out.append(r"{\Huge\bfseries\color{psink}\RaggedRight " + escape(doc.title) + r"}\par\vspace{14mm}")
    out.append(r"\begin{tabular}{@{}>{\color{psmuted}}p{45mm}p{100mm}@{}}")
    for label, value in doc.identifiers:
        out.append(f"{escape(label)} & {escape(value)} \\\\")
    out.append(r"\end{tabular}\vfill")
    out.append(r"{\small\color{psmuted}" + escape(doc.footer) + r"}")
    out.append(r"\end{titlepage}")
    out.append(r"\tableofcontents\newpage")

    for b in doc.blocks:
        if isinstance(b, Heading):
            cmd = {1: "section", 2: "subsection", 3: "subsubsection"}[min(b.level, 3)]
            out.append(f"\\{cmd}{{{escape(b.number)}\\quad {escape(b.text)}}}\\label{{{b.anchor}}}")
        elif isinstance(b, Paragraph):
            ann = ""
            if b.annotation == "mismatch":
                ann = r"\psannot{\color{pserr}claim mismatch}"
            elif b.annotation == "unbound":
                ann = r"\psannot{\color{pswarn}unverified claim}"
            elif b.annotation == "generated":
                ann = r"\psannot{generated}"
            out.append(inline(b.text) + ann + "\n")
        elif isinstance(b, BulletList):
            out.append(r"\begin{itemize}[leftmargin=*,itemsep=2pt]")
            out.extend(f"\\item {inline(i)}" for i in b.items)
            out.append(r"\end{itemize}")
        elif isinstance(b, Table):
            out.append(_table(b))
        elif isinstance(b, Note):
            col = "pswarn" if b.kind == "warning" else "psmuted"
            out.append(f"\\psnote{{{col}}}{{{inline(b.text)}}}")
    out.append(r"\end{document}")
    return "\n".join(out) + "\n"


def _table(t: Table) -> str:
    n = len(t.header)
    # first column a bit wider; remaining share the rest
    first = 0.28 if n > 2 else 0.35
    rest = (0.98 - first) / max(n - 1, 1)
    spec = f">{{\\RaggedRight}}p{{{first:.2f}\\linewidth}}" + "".join(
        f">{{\\RaggedRight}}p{{{rest:.2f}\\linewidth}}" for _ in range(n - 1)
    )
    lines = [r"\begin{longtable}{@{}" + spec + "@{}}"]
    lines.append(r"\caption{" + inline(t.caption) + r"}\\ \toprule")
    lines.append(" & ".join(f"\\textbf{{\\small {inline(h)}}}" for h in t.header) + r" \\ \midrule\endfirsthead")
    lines.append(" & ".join(f"\\textbf{{\\small {inline(h)}}}" for h in t.header) + r" \\ \midrule\endhead")
    for row in t.rows:
        cells = list(row) + [""] * (n - len(row))
        lines.append(" & ".join(f"\\small {inline(c)}" for c in cells[:n]) + r" \\")
    lines.append(r"\bottomrule")
    for f in t.footnotes:
        lines.append(
            f"\\multicolumn{{{n}}}{{@{{}}p{{0.98\\linewidth}}@{{}}}}{{\\footnotesize\\color{{psmuted}}{inline(f)}}}\\\\"
        )
    lines.append(r"\end{longtable}")
    return "\n".join(lines)


def tectonic_available() -> bool:
    return shutil.which("tectonic") is not None


def compile_pdf(latex: str, workdir: Path, *, name: str = "protocol") -> Path:
    """Compile with Tectonic into ``workdir/<name>.pdf``. Raises RuntimeError with the log on failure."""
    exe = shutil.which("tectonic")
    if exe is None:
        raise RuntimeError("tectonic binary not found on PATH")
    workdir.mkdir(parents=True, exist_ok=True)
    tex = workdir / f"{name}.tex"
    tex.write_text(latex, encoding="utf-8")
    proc = subprocess.run(
        [exe, "--keep-logs", "--outdir", str(workdir), str(tex)],
        capture_output=True,
        text=True,
        timeout=600,
        check=False,
    )
    pdf = workdir / f"{name}.pdf"
    if proc.returncode != 0 or not pdf.exists():
        raise RuntimeError(f"tectonic failed ({proc.returncode}):\n{proc.stderr[-4000:]}")
    return pdf
