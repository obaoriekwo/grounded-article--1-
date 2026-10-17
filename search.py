"""
Web search for sources: OpenAlex (https://openalex.org), a free search API over 250+ million
scholarly works. No API key is needed. Every result comes with real metadata (authors, year,
title, venue, DOI, landing page), which is what APA references and their verification need.
"""

import os
import re

import requests

from models import Source, clean_doi

OPENALEX_URL = os.getenv("OPENALEX_URL", "https://api.openalex.org")
TIMEOUT = 30


class SearchError(Exception):
    pass


def _params(extra: dict) -> dict:
    mailto = os.getenv("OPENALEX_MAILTO")  # optional: puts requests in OpenAlex's faster "polite pool"
    return {**extra, **({"mailto": mailto} if mailto else {})}


def _abstract(inverted_index: dict | None) -> str:
    """OpenAlex stores abstracts as {word: [positions]}; rebuild the text."""
    if not inverted_index:
        return ""
    positions = [(pos, word) for word, places in inverted_index.items() for pos in places]
    return " ".join(word for _, word in sorted(positions))


def work_to_source(work: dict, source_id: str) -> Source:
    location = work.get("primary_location") or {}
    venue = (location.get("source") or {}).get("display_name")
    doi = clean_doi(work.get("doi"))
    url = (f"https://doi.org/{doi}" if doi else None) or location.get("landing_page_url") or work.get("id")
    return Source(
        id=source_id,
        title=(work.get("title") or work.get("display_name") or "").strip(),
        authors=[a["author"]["display_name"] for a in work.get("authorships", [])
                 if a.get("author", {}).get("display_name")],
        year=work.get("publication_year"),
        venue=venue,
        doi=doi,
        url=url,
        abstract=_abstract(work.get("abstract_inverted_index")),
        origin="openalex",
    )


def search_sources(topic: str, count: int = 8, since_year: int | None = None) -> list[Source]:
    filters = ["has_abstract:true", "type:article|review|preprint|book-chapter"]
    if since_year:
        filters.append(f"from_publication_date:{since_year}-01-01")
    try:
        r = requests.get(f"{OPENALEX_URL}/works", timeout=TIMEOUT, params=_params({
            "search": topic, "filter": ",".join(filters), "per_page": min(50, count * 3),
            "select": "id,doi,title,display_name,publication_year,authorships,primary_location,abstract_inverted_index",
        }))
    except requests.RequestException as e:
        raise SearchError(f"could not reach OpenAlex: {e.__class__.__name__}")
    if r.status_code != 200:
        raise SearchError(f"OpenAlex returned HTTP {r.status_code}")
    sources = []
    for work in r.json().get("results", []):
        src = work_to_source(work, f"S{len(sources) + 1}")
        if src.title and src.authors and src.year and len(src.abstract.split()) >= 30:
            sources.append(src)
        if len(sources) == count:
            break
    if len(sources) < 3:
        raise SearchError(f"only {len(sources)} usable sources found for '{topic}'; try a broader topic")
    return sources


SELECT = "id,doi,title,display_name,publication_year,authorships,primary_location"


def search_title(title: str, rows: int = 10) -> list[dict]:
    """Used by the verifier: candidate works for a title (relevance search + exact title search)."""
    results, seen = [], set()
    clean = re.sub(r"[^\w\s-]", " ", title)          # commas etc. would break the filter syntax
    for params in ({"search": title}, {"filter": f"title.search:{clean}"}):
        r = requests.get(f"{OPENALEX_URL}/works", timeout=TIMEOUT,
                         params=_params({**params, "per_page": rows, "select": SELECT}))
        if r.status_code != 200:
            continue
        for w in r.json().get("results", []):
            if w.get("id") not in seen:
                seen.add(w.get("id"))
                results.append(w)
    return results


def work_by_doi(doi: str) -> dict | None:
    """OpenAlex also knows DOIs that Crossref does not hold (e.g. arXiv and Zenodo DOIs from DataCite)."""
    r = requests.get(f"{OPENALEX_URL}/works/doi:{doi}", timeout=TIMEOUT, params=_params({"select": SELECT}))
    if r.status_code == 404:
        return None
    r.raise_for_status()
    return r.json()
