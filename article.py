#!/usr/bin/env python3
"""
Grounded article generator.

    Topic -> web search (OpenAlex) -> sources -> LLM writes structured Report -> Pydantic validation
          -> reference verification (Crossref / OpenAlex) -> HTML -> article.pdf

Usage:
    python article.py "large language models in healthcare"          grounded (with web search)
    python article.py "large language models in healthcare" --no-search    comparison: model memory only
    python article.py "large language models in healthcare" --compare      run both and compare references
    python article.py                                                   asks for the topic

Output goes to output/<topic>/ : article.pdf, article.html, report.json, sources.json, verification.md
"""

import argparse
import json
import re
import sys
import time
from pathlib import Path

from pydantic import ValidationError

from generate import generate_grounded, generate_ungrounded, save_json
from llm import LLM, PROVIDERS, LLMError
from render import to_html, write_pdf
from search import SearchError, search_sources
from verify import checks_markdown, summary, verify_report


def slugify(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:60] or "article"


def run(topic: str, grounded: bool, args, out_dir: Path) -> dict:
    mode = "grounded" if grounded else "no-search"
    folder = out_dir / mode
    folder.mkdir(parents=True, exist_ok=True)
    print(f"\n=== {mode.upper()} ===")
    llm = LLM(args.provider, args.model)
    start = time.perf_counter()

    if grounded:
        print(f"1. Searching OpenAlex for '{topic}'...")
        sources = search_sources(topic, args.sources, args.since)
        save_json(sources, folder / "sources.json")
        for s in sources:
            print(f"   [{s.id}] {s.authors[0]} et al. ({s.year}) {s.title[:70]}")
        print(f"2. Generating the structured report with {llm.provider} / {llm.model}...")
        report = generate_grounded(llm, topic, sources)
        note = f"{len(report.references)} sources from OpenAlex web search"
    else:
        print(f"1. No web search: generating from the model's memory ({llm.provider} / {llm.model})...")
        report = generate_ungrounded(llm, topic)
        note = "no web search (references written by the model)"
    print("3. Pydantic validation passed: "
          f"{len(report.sections)} sections, {len(report.references)} references, all citations resolve.")
    save_json(report, folder / "report.json")

    html = to_html(report, topic, note)
    (folder / "article.html").write_text(html, encoding="utf-8")
    write_pdf(html, folder / "article.pdf")
    print(f"4. PDF written: {folder / 'article.pdf'}")

    result = {"mode": mode, "folder": str(folder), "references": len(report.references),
              "seconds": round(time.perf_counter() - start, 1)}
    if not args.no_verify:
        print("5. Verifying every reference against Crossref / OpenAlex...")
        checks = verify_report(report.references, check_urls=not args.skip_url_check)
        md = checks_markdown(checks, report.references, f"Reference check — {mode}")
        (folder / "verification.md").write_text(f"# {report.title}\n\n" + md, encoding="utf-8")
        (folder / "verification.json").write_text(json.dumps([c.__dict__ for c in checks], ensure_ascii=False,
                                                             indent=2), encoding="utf-8")
        result.update(summary(checks))
        print(f"   {result['verified']} verified, {result['partially correct']} partially correct, "
              f"{result['not found']} not found → {folder / 'verification.md'}")
    return result


def comparison_table(results: list[dict]) -> str:
    rows = ["| Mode | References | Verified | Partially correct | Not found (hallucinated) | Time (s) |",
            "|---|---|---|---|---|---|"]
    for r in results:
        rows.append(f"| {r['mode']} | {r['references']} | {r.get('verified', '-')} | "
                    f"{r.get('partially correct', '-')} | {r.get('not found', '-')} | {r['seconds']} |")
    return "\n".join(rows)


def main() -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except AttributeError:
            pass
    p = argparse.ArgumentParser(description="Generate a short, source-grounded scientific article as a PDF.")
    p.add_argument("topic", nargs="?", help="article topic (asked interactively if omitted)")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--no-search", action="store_true", help="comparison mode: no web search, model memory only")
    mode.add_argument("--compare", action="store_true", help="run with and without search and compare references")
    p.add_argument("-p", "--provider", default="gemini", choices=list(PROVIDERS), help="LLM provider (default gemini)")
    p.add_argument("-m", "--model", help="model name (default depends on the provider)")
    p.add_argument("-n", "--sources", type=int, default=8, help="number of search results to use (default 8)")
    p.add_argument("--since", type=int, help="only sources published from this year on")
    p.add_argument("-o", "--output", default="output", help="output folder (default: output)")
    p.add_argument("--no-verify", action="store_true", help="skip the reference check")
    p.add_argument("--skip-url-check", action="store_true", help="do not open reference URLs during the check")
    args = p.parse_args()

    topic = args.topic or input("Article topic: ").strip()
    if len(topic) < 3:
        print("Error: please give a topic of at least 3 characters.", file=sys.stderr)
        return 2
    if not 3 <= args.sources <= 20:
        print("Error: --sources must be between 3 and 20.", file=sys.stderr)
        return 2
    out_dir = Path(args.output) / slugify(topic)

    try:
        if args.compare:
            results = [run(topic, True, args, out_dir), run(topic, False, args, out_dir)]
            table = comparison_table(results)
            (out_dir / "comparison.md").write_text(f"# Reference comparison: {topic}\n\n{table}\n", encoding="utf-8")
            print("\n" + table + f"\n\nSaved: {out_dir / 'comparison.md'}")
        else:
            run(topic, not args.no_search, args, out_dir)
    except SearchError as e:
        print(f"Search error: {e}", file=sys.stderr)
        return 1
    except LLMError as e:
        print(f"LLM error: {e}", file=sys.stderr)
        return 1
    except ValidationError as e:
        print(f"Validation error: {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
