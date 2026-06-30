#!/usr/bin/env python
"""Render the DCTwin code-handoff PDF from a sections JSON (block schema).

Usage: make_handoff.py sections.json out.tex
Blocks: para | subhead | bullets | commands | table  (see workflow schema)."""
import sys, json, re, os

ESC = {'&': r'\&', '%': r'\%', '$': r'\$', '#': r'\#', '_': r'\_',
       '{': r'\{', '}': r'\}', '~': r'\textasciitilde{}', '^': r'\textasciicircum{}',
       '\\': r'\textbackslash{}'}
def esc(s):
    s = s or ""
    out = []
    for ch in s:
        out.append(ESC.get(ch, ch))
    s = "".join(out)
    # nicer arrows / degree
    s = s.replace("->", r"$\rightarrow$").replace("=>", r"$\Rightarrow$")
    s = s.replace("<=", r"$\leq$").replace(">=", r"$\geq$")
    s = s.replace("→", r"$\rightarrow$").replace("°", r"$^\circ$")
    s = s.replace("±", r"$\pm$").replace("≤", r"$\leq$").replace("≥", r"$\geq$")
    s = s.replace("×", r"$\times$").replace("σ", r"$\sigma$").replace("µ", r"$\mu$")
    s = s.replace("≈", r"$\approx$").replace("…", "...")
    # allow long path-like tokens to break after '/' and '_' (no hyphen)
    s = s.replace("/", r"/\allowbreak{}")
    s = s.replace(r"\_", r"\_\allowbreak{}")
    return s

CODEHDR = ("path", "file", "symbol", "command", "endpoint", "method", "term", "var")

def render_table(b):
    header = b.get("header", []); rows = b.get("rows", [])
    n = len(header) if header else (len(rows[0]) if rows else 2)
    if n <= 1:
        spec = "X"
    elif n == 2:
        spec = r"@{}>{\ttfamily\small}p{0.30\linewidth} X@{}"
        mono0 = True
    elif n == 3:
        spec = r"@{}>{\ttfamily\scriptsize}p{0.24\linewidth} p{0.30\linewidth} X@{}"
        mono0 = True
    else:
        spec = "@{}" + " ".join(["X"] * n) + "@{}"
        mono0 = False
    mono0 = header and header[0].strip().lower().split()[0] in CODEHDR
    if not mono0 and n in (2, 3):
        spec = (r"@{}p{0.30\linewidth} X@{}" if n == 2 else r"@{}p{0.24\linewidth} p{0.30\linewidth} X@{}")
    out = [r"\vspace{1pt}\begin{tabularx}{\linewidth}{%s}" % spec, r"\toprule"]
    if header:
        out.append(" & ".join(r"\textbf{%s}" % esc(h) for h in header) + r" \\")
        out.append(r"\midrule")
    for row in rows:
        cells = []
        for j, c in enumerate(row):
            cells.append(esc(c))
        out.append(" & ".join(cells) + r" \\")
    out += [r"\bottomrule", r"\end{tabularx}\vspace{2pt}"]
    return "\n".join(out)

def render_block(b):
    t = b.get("type")
    if t == "para":
        return esc(b.get("text", "")) + "\n"
    if t == "subhead":
        return r"\smallskip\noindent\textbf{%s}\\[1pt]" % esc(b.get("text", ""))
    if t == "bullets":
        items = b.get("items", [])
        return (r"\begin{itemize}" + "\n" +
                "\n".join(r"\item %s" % esc(i) for i in items) + "\n" + r"\end{itemize}")
    if t == "commands":
        cap = b.get("caption", ""); lines = b.get("lines", [])
        head = (r"\smallskip\noindent\textit{\small %s}\\[1pt]" % esc(cap)) if cap else ""
        body = "\n".join(lines)
        return head + "\n" + r"\begin{cmd}" + "\n" + body + "\n" + r"\end{cmd}"
    if t == "table":
        return render_table(b)
    return ""

def render_section(s):
    out = [r"\section*{%s}" % esc(s.get("title", ""))]
    for b in s.get("blocks", []):
        out.append(render_block(b))
    return "\n".join(out)

PREAMBLE = r"""\documentclass[10pt]{article}
\usepackage[utf8]{inputenc}
\usepackage[T1]{fontenc}
\usepackage{lmodern}
\usepackage[a4paper,margin=0.70in]{geometry}
\usepackage{booktabs}
\usepackage{tabularx}
\usepackage{array}
\usepackage{enumitem}
\usepackage{titlesec}
\usepackage[table]{xcolor}
\usepackage{fancyvrb}
\usepackage{microtype}
\usepackage[hidelinks]{hyperref}

\definecolor{nv}{HTML}{1F4E79}
\definecolor{cmdrule}{HTML}{B9C4D0}
\definecolor{cmdbg}{HTML}{F4F6F9}

\setlength{\parskip}{2.5pt}\setlength{\parindent}{0pt}
\setlist{nosep,leftmargin=1.25em,topsep=2pt,itemsep=1.5pt}
\titlespacing*{\section}{0pt}{7pt}{3pt}
\titleformat{\section}{\normalfont\large\bfseries\color{nv}}{}{0pt}{}
\renewcommand{\arraystretch}{1.12}
\fvset{fontsize=\footnotesize,frame=single,framesep=4pt,rulecolor=\color{cmdrule},xleftmargin=2pt,xrightmargin=2pt}
\DefineVerbatimEnvironment{cmd}{Verbatim}{}
\setlength{\tabcolsep}{4pt}
\sloppy\setlength{\emergencystretch}{3em}
\begin{document}
"""

def title_block(title, subtitle, prov):
    return (r"\begin{center}" + "\n" +
            r"{\LARGE\bfseries\color{nv} " + title + r"}\\[3pt]" + "\n" +
            r"{\normalsize " + subtitle + r"}\\[1pt]" + "\n" +
            r"{\small " + prov + r"}" + "\n" +
            r"\end{center}" + "\n" + r"\vspace{2pt}\hrule\vspace{4pt}" + "\n")

DEFAULT_TITLE = ("DCTwin --- Code Handoff Guide",
                 "A 5-page quickstart for taking over the codebase.",
                 r"Condensed from \texttt{docs/DCTwin\_User\_Guide.md} (the full 16-page reference). Digital-twin dual-loop optimizer for weekly data-center cooling setpoints.")

FOOTER = "\n\\end{document}\n"

def main():
    sections = json.load(open(sys.argv[1]))
    if isinstance(sections, dict):
        sections = sections.get("sections", sections)
    # preferred order by title keyword
    order = ["what dctwin", "repository", "setup", "running", "architecture",
             "invariant", "deeper"]
    def rank(s):
        tl = s.get("title", "").lower()
        for i, k in enumerate(order):
            if k in tl:
                return i
        return len(order)
    sections = sorted(sections, key=rank)
    title = sys.argv[3] if len(sys.argv) > 3 else DEFAULT_TITLE[0]
    subtitle = sys.argv[4] if len(sys.argv) > 4 else DEFAULT_TITLE[1]
    prov = sys.argv[5] if len(sys.argv) > 5 else DEFAULT_TITLE[2]
    body = "\n\n".join(render_section(s) for s in sections)
    tex = PREAMBLE + title_block(title, subtitle, prov) + body + FOOTER
    open(sys.argv[2], "w").write(tex)
    print("wrote", sys.argv[2], len(tex), "bytes;", len(sections), "sections")

if __name__ == "__main__":
    main()
