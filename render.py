"""Render a validated Report to HTML and PDF (xhtml2pdf, pure Python, works on Windows)."""

import os
from datetime import date
from pathlib import Path

from apa import esc, reference_entry, replace_citations, sort_key
from models import Report

# Built-in PDF fonts only cover basic Latin, so letters such as Ł, ő or č would show as boxes.
# Use a real TrueType serif font from the system when one is available.
FONT_CANDIDATES = [
    ("C:/Windows/Fonts/times.ttf", "C:/Windows/Fonts/timesbd.ttf", "C:/Windows/Fonts/timesi.ttf"),
    ("/System/Library/Fonts/Supplemental/Times New Roman.ttf",
     "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
     "/System/Library/Fonts/Supplemental/Times New Roman Italic.ttf"),
    ("/usr/share/fonts/truetype/liberation/LiberationSerif-Regular.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf",
     "/usr/share/fonts/truetype/liberation/LiberationSerif-Italic.ttf"),
    ("/usr/share/fonts/truetype/dejavu/DejaVuSerif.ttf", "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf",
     "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Italic.ttf"),
]


def find_font() -> tuple[str, str, str] | None:
    for files in FONT_CANDIDATES:
        if all(os.path.exists(f) for f in files):
            return files
    return None


def font_css() -> tuple[str, str]:
    """Return (@font-face rules, font-family) for the first complete serif font found."""
    found = find_font()
    if found:
        regular, bold, italic = found
        faces = (f"@font-face {{ font-family: ArticleSerif; src: url('{regular}'); }}\n"
                 f"@font-face {{ font-family: ArticleSerif; src: url('{bold}'); font-weight: bold; }}\n"
                 f"@font-face {{ font-family: ArticleSerif; src: url('{italic}'); font-style: italic; }}\n")
        return faces, "ArticleSerif"
    return "", "Times-Roman"


CSS = """
@page { size: A4; margin: 2.2cm 2.3cm 2.2cm 2.3cm;
        @frame footer { -pdf-frame-content: footer; bottom: 1cm; margin-left: 2.3cm; margin-right: 2.3cm; height: 1cm; } }
body { font-family: FONTNAME; font-size: 11pt; line-height: 1.45; color: #111; }
h1 { font-size: 19pt; text-align: center; margin: 0 0 4pt 0; color: #1F3B5C; }
.meta { text-align: center; font-size: 9.5pt; color: #555; margin-bottom: 14pt; }
.abstract { margin: 0 1.2cm 14pt 1.2cm; font-size: 10pt; }
.abstract-title { font-weight: bold; text-align: center; font-size: 10.5pt; margin-bottom: 3pt; }
h2 { font-size: 13pt; color: #1F3B5C; margin: 14pt 0 4pt 0; border-bottom: 0.5pt solid #9AA9BC; padding-bottom: 2pt; }
p { margin: 0 0 7pt 0; text-align: justify; }
.ref { margin: 0 0 6pt 0; padding-left: 1.2cm; text-indent: -1.2cm; font-size: 10pt; text-align: left; }
a { color: #1F4E8C; text-decoration: none; }
#footer { font-size: 8.5pt; color: #777; text-align: center; }
"""


def to_html(report: Report, topic: str, mode_note: str) -> str:
    refs = {r.id: r for r in report.references}
    cite = lambda text: replace_citations(text, refs)
    faces, family = font_css()
    css = faces + CSS.replace("FONTNAME", family)
    parts = [f"<html><head><meta charset='utf-8'><title>{esc(report.title)}</title><style>{css}</style></head><body>",
             f"<h1>{esc(report.title)}</h1>",
             f"<div class='meta'>Topic: {esc(topic)} · {date.today():%d %B %Y} · {esc(mode_note)}</div>",
             f"<div class='abstract'><div class='abstract-title'>Abstract</div><p>{cite(report.abstract)}</p></div>",
             "<h2>1. Introduction</h2>"]
    parts += [f"<p>{cite(p)}</p>" for p in report.introduction]
    for n, section in enumerate(report.sections, start=2):
        parts.append(f"<h2>{n}. {esc(section.heading)}</h2>")
        parts += [f"<p>{cite(p)}</p>" for p in section.paragraphs]
    parts.append(f"<h2>{len(report.sections) + 2}. Conclusion</h2>")
    parts += [f"<p>{cite(p)}</p>" for p in report.conclusion]
    parts.append("<h2>References</h2>")
    parts += [f"<p class='ref'>{reference_entry(r)}</p>" for r in sorted(report.references, key=sort_key)]
    parts.append("<div id='footer'>Generated with an LLM · page <pdf:pagenumber/></div></body></html>")
    return "\n".join(parts)


def write_pdf(html: str, path: Path) -> None:
    from xhtml2pdf import pisa
    options = {}
    try:  # newer xhtml2pdf versions confine file access; allow only the font folder, and no network
        from xhtml2pdf.config.resources import ResourceAccessPolicy
        font = find_font()
        extra = tuple({Path(f).parent for f in font}) if font else ()
        options["resource_policy"] = ResourceAccessPolicy(allow_remote=False, base_dir=Path.cwd(), extra_roots=extra)
    except ImportError:
        pass
    with open(path, "wb") as f:
        result = pisa.CreatePDF(html, dest=f, encoding="utf-8", **options)
    if result.err:
        raise RuntimeError(f"PDF rendering failed with {result.err} error(s)")
