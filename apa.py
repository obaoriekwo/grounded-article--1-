"""APA 7 formatting: in-text citations (Author, Year) and reference-list entries."""

import re

from models import CITATION, Reference


def split_name(name: str) -> tuple[str, str]:
    """Return (surname, given names) for 'Ashish Vaswani', 'Vaswani, Ashish' or 'Vaswani, A.'."""
    name = " ".join(name.split())
    if "," in name:
        surname, given = [p.strip() for p in name.split(",", 1)]
        return surname, given
    parts = name.split(" ")
    if len(parts) == 1:
        return parts[0], ""
    # keep particles such as 'van', 'de', 'von' with the surname
    i = len(parts) - 1
    while i > 1 and parts[i - 1].lower() in {"van", "von", "de", "der", "den", "da", "di", "le", "la", "du"}:
        i -= 1
    return " ".join(parts[i:]), " ".join(parts[:i])


def initials(given: str) -> str:
    out = []
    for part in re.split(r"[\s.]+", given):
        if not part:
            continue
        out.append("-".join(p[0].upper() + "." for p in part.split("-") if p))
    return " ".join(out)


def author_apa(name: str) -> str:
    surname, given = split_name(name)
    return f"{surname}, {initials(given)}".rstrip(", ") if given else surname


def year_text(year: int | None) -> str:
    return str(year) if year else "n.d."


def in_text(ref: Reference) -> str:
    surnames = [split_name(a)[0] for a in ref.authors]
    if len(surnames) == 1:
        who = surnames[0]
    elif len(surnames) == 2:
        who = f"{surnames[0]} & {surnames[1]}"
    else:
        who = f"{surnames[0]} et al."
    return f"{who}, {year_text(ref.year)}"


def reference_entry(ref: Reference) -> str:
    """APA 7 reference as HTML (venue in italics)."""
    names = [author_apa(a) for a in ref.authors]
    if len(names) > 20:
        names = names[:19] + ["..."] + names[-1:]
        authors = ", ".join(names[:-1]) + " " + names[-1]
    elif len(names) == 1:
        authors = names[0]
    else:
        authors = ", ".join(names[:-1]) + ", & " + names[-1]
    title = ref.title.rstrip(".")
    parts = [f"{esc(authors)} ({year_text(ref.year)}). {esc(title)}."]
    if ref.venue:
        parts.append(f"<i>{esc(ref.venue)}</i>.")
    link = f"https://doi.org/{ref.doi}" if ref.doi else ref.url
    if link:
        parts.append(f'<a href="{esc(link)}">{esc(link)}</a>')
    return " ".join(parts)


def sort_key(ref: Reference) -> tuple:
    return (split_name(ref.authors[0])[0].lower(), ref.year or 0)


def replace_citations(text: str, refs: dict[str, Reference]) -> str:
    """[S1, S3] -> (Vaswani et al., 2017; Devlin et al., 2019). Text is HTML-escaped first."""
    def repl(match):
        ids = [x.strip() for x in re.split(r"[,;]", match.group(1))]
        return "(" + "; ".join(esc(in_text(refs[i])) for i in ids if i in refs) + ")"
    return CITATION.sub(repl, esc(text))


def esc(s: str) -> str:
    return s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;").replace('"', "&quot;")
