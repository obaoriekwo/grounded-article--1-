"""
Reference checker. Every reference in a Report is compared with the record of the real publication.

Finding the record:
  1. If the reference has a DOI, look it up in Crossref; if Crossref does not hold it (arXiv and
     other DataCite DOIs), look it up in OpenAlex. A DOI found in neither does not exist.
  2. If there is no DOI, the DOI does not exist, or it belongs to a different title, search the title
     in OpenAlex. Candidates are ranked by title similarity, matching first author and year, and a
     candidate is accepted only if the title is nearly identical (>= 0.90), or similar (>= 0.75)
     with the same first author. This prevents matching a different paper with a similar title.

Comparing the fields (title, authors, year, DOI/URL):
  verified           - a matching publication exists and all fields agree
                       (a year that differs by one is accepted: preprint and published versions)
  partially correct  - the publication exists, but some fields are wrong
  not found          - no matching publication: the reference is hallucinated
"""

import os
import re
import unicodedata
from dataclasses import dataclass, field
from difflib import SequenceMatcher

import requests

from apa import split_name
from models import Reference, clean_doi
from search import search_title, work_by_doi

CROSSREF_URL = os.getenv("CROSSREF_URL", "https://api.crossref.org")
TIMEOUT = 30
HEADERS = {"User-Agent": "grounded-article/1.0 (course assignment; mailto:%s)" % os.getenv("OPENALEX_MAILTO", "none")}
SAME_TITLE, SIMILAR_TITLE = 0.90, 0.75


@dataclass
class Check:
    ref_id: str
    title: str
    status: str = "not found"
    matched_title: str = ""
    matched_doi: str = ""
    fields: dict = field(default_factory=dict)   # field -> "ok" | "ok (...)" | "wrong: ..." | "missing"
    note: str = ""


# ---- text helpers -----------------------------------------------------------------------------

def ascii_lower(s: str) -> str:
    return unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode().lower()


def title_similarity(a: str, b: str) -> float:
    a = " ".join(re.sub(r"[^a-z0-9 ]", " ", ascii_lower(a)).split())
    b = " ".join(re.sub(r"[^a-z0-9 ]", " ", ascii_lower(b)).split())
    return SequenceMatcher(None, a, b).ratio() if a and b else 0.0


def name_tokens(name: str) -> set[str]:
    """All word tokens of a name longer than one letter (initials are ignored)."""
    return {t for t in re.split(r"[^a-z]+", ascii_lower(name)) if len(t) > 1}


def same_person(claimed: str, real: str) -> bool:
    """'J. Jayasudha' = 'Jayasudha J'; 'Jared Kaplan' = 'Jared Kaplan A'; 'Vaswani, A.' = 'Ashish Vaswani'."""
    claimed_surname = re.sub(r"[^a-z]", "", ascii_lower(split_name(claimed)[0]))
    real_surname = re.sub(r"[^a-z]", "", ascii_lower(split_name(real)[0]))
    if claimed_surname and claimed_surname == real_surname:
        return True
    return (claimed_surname in name_tokens(real)) or (real_surname in name_tokens(claimed) and len(real_surname) > 1)


def first_author_matches(claimed: list[str], real: list[str]) -> bool:
    return bool(claimed and real) and any(same_person(claimed[0], r) for r in real[:3])


# ---- record lookups (all normalised to {title, authors, year, doi, url}) -------------------------

def openalex_record(w: dict) -> dict:
    return {"title": w.get("title") or w.get("display_name") or "",
            "authors": [a["author"]["display_name"] for a in w.get("authorships", []) if a.get("author")],
            "year": w.get("publication_year"), "doi": clean_doi(w.get("doi")),
            "url": (w.get("primary_location") or {}).get("landing_page_url")}


def crossref_by_doi(doi: str) -> dict | None:
    r = requests.get(f"{CROSSREF_URL}/works/{doi}", timeout=TIMEOUT, headers=HEADERS)
    if r.status_code == 404:
        return None
    r.raise_for_status()
    m = r.json()["message"]
    year = None
    for key in ("issued", "published", "published-online", "published-print", "created"):  # earliest first
        parts = (m.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = parts[0][0]
            break
    authors = [f"{a.get('given', '')} {a.get('family', '')}".strip() or a.get("name", "")
               for a in m.get("author", [])]
    return {"title": (m.get("title") or [""])[0], "authors": authors, "year": year,
            "doi": clean_doi(m.get("DOI")), "url": m.get("URL")}


def record_by_doi(doi: str) -> tuple[dict | None, str]:
    record = crossref_by_doi(doi)
    if record:
        return record, "Crossref DOI"
    work = work_by_doi(doi)
    if work:
        return openalex_record(work), "OpenAlex DOI"
    return None, ""


def record_by_title(ref: Reference) -> dict | None:
    best, best_score = None, -1.0
    for w in search_title(ref.title):
        rec = openalex_record(w)
        sim = title_similarity(ref.title, rec["title"])
        author_ok = first_author_matches(ref.authors, rec["authors"])
        if sim < SAME_TITLE and not (sim >= SIMILAR_TITLE and author_ok):
            continue                                   # a different paper with a similar title
        year_gap = abs((ref.year or 0) - (rec["year"] or 0)) if ref.year and rec["year"] else 5
        score = sim + (0.5 if author_ok else 0) - 0.05 * min(year_gap, 5)
        if score > best_score:
            best, best_score = rec, score
    return best


def url_alive(url: str) -> bool | None:
    try:
        r = requests.get(url, timeout=15, headers=HEADERS, allow_redirects=True, stream=True)
        return r.status_code < 400
    except requests.RequestException:
        return None


# ---- comparison ------------------------------------------------------------------------------

def compare(ref: Reference, record: dict, c: Check) -> None:
    c.matched_title, c.matched_doi = record["title"], record.get("doi") or ""

    sim = title_similarity(ref.title, record["title"])
    c.fields["title"] = "ok" if sim >= SAME_TITLE else f"wrong: real title is '{record['title']}'"

    real = record["authors"]
    if not real:
        c.fields["authors"] = "missing in record"
    elif first_author_matches(ref.authors, real) and \
            all(any(same_person(a, r) for r in real) for a in ref.authors[:3]):
        c.fields["authors"] = "ok"
    else:
        c.fields["authors"] = "wrong: real authors are " + ", ".join(real[:4]) + (" et al." if len(real) > 4 else "")

    if record.get("year") is None:
        c.fields["year"] = "missing in record"
    elif ref.year == record["year"]:
        c.fields["year"] = "ok"
    elif ref.year and abs(ref.year - record["year"]) == 1:
        c.fields["year"] = f"ok ({record['year']} in record; preprint and published versions differ)"
    else:
        c.fields["year"] = f"wrong: real year is {record['year']}"

    if "doi" not in c.fields:
        if ref.doi and record.get("doi"):
            c.fields["doi"] = "ok" if ref.doi.lower() == record["doi"].lower() else f"wrong: real DOI is {record['doi']}"
        elif ref.doi:
            c.fields["doi"] = "ok"
        else:
            c.fields["doi"] = "missing" + (f" (real DOI is {record['doi']})" if record.get("doi") else "")


def check_reference(ref: Reference, check_urls: bool = True) -> Check:
    c = Check(ref.id, ref.title)
    record, via = None, ""
    try:
        if ref.doi:
            record, via = record_by_doi(ref.doi)
            if record is None:
                c.fields["doi"] = "wrong: DOI does not exist"
            elif title_similarity(ref.title, record["title"]) < SIMILAR_TITLE:
                by_title = record_by_title(ref)
                if by_title:
                    c.fields["doi"] = f"wrong: DOI belongs to '{record['title'][:80]}'"
                    record, via = by_title, "OpenAlex title search"
        if record is None:
            record = record_by_title(ref)
            via = "OpenAlex title search" if record else ""
    except requests.RequestException as e:
        c.status, c.note = "unchecked", f"lookup failed ({e.__class__.__name__})"
        return c

    if record is None:
        c.note = "no publication with this DOI or title was found"
        return c

    compare(ref, record, c)
    if check_urls and ref.url and not ref.doi:
        alive = url_alive(ref.url)
        c.fields["url"] = {True: "ok", False: "wrong: URL does not open", None: "could not check"}[alive]

    wrong = [k for k, v in c.fields.items() if v.startswith("wrong")]
    c.status = "verified" if not wrong else "partially correct"
    c.note = f"matched via {via}"
    return c


def verify_report(refs: list[Reference], check_urls: bool = True) -> list[Check]:
    results = []
    for ref in refs:
        result = check_reference(ref, check_urls)
        print(f"  {ref.id}: {result.status}")
        results.append(result)
    return results


def summary(checks: list[Check]) -> dict:
    out = {"total": len(checks)}
    for status in ("verified", "partially correct", "not found", "unchecked"):
        out[status] = sum(c.status == status for c in checks)
    return out


def checks_markdown(checks: list[Check], refs: list[Reference], heading: str) -> str:
    by_id = {r.id: r for r in refs}
    s = summary(checks)
    lines = [f"## {heading}", "",
             f"{s['verified']} verified · {s['partially correct']} partially correct · "
             f"{s['not found']} not found (hallucinated) · {s['unchecked']} unchecked — of {s['total']} references", "",
             "| Ref | Claimed reference | Status | Title | Authors | Year | DOI/URL | Notes |",
             "|---|---|---|---|---|---|---|---|"]
    for c in checks:
        r = by_id[c.ref_id]
        claimed = f"{', '.join(r.authors[:2])}{' et al.' if len(r.authors) > 2 else ''} ({r.year}). {r.title}"
        f = c.fields
        doi_url = f.get("doi") or f.get("url") or "-"
        lines.append(" | ".join(["", c.ref_id, claimed.replace("|", "/"), f"**{c.status}**",
                                 f.get("title", "-"), f.get("authors", "-"), f.get("year", "-"),
                                 doi_url, c.note, ""]).strip())
    return "\n".join(lines) + "\n"
