# Grounded Article Generator

Asks for a topic and generates a short scientific/technical article as a PDF, with title, abstract, introduction, main sections, conclusion and an APA reference list. The references come from **real web search results**, not from the model's memory. A built-in checker verifies every reference, and a comparison mode shows what happens without search.

```
Topic → web search (OpenAlex) → sources → LLM writes structured Report → Pydantic validation
      → HTML → article.pdf → reference check (Crossref / OpenAlex)
```

## Quick start (Windows, VS Code + PowerShell)

```
python -m pip install -r requirements.txt
$env:GEMINI_API_KEY="your-key"
python article.py "transformer models in natural language processing"
```

The result is in `output/<topic>/grounded/article.pdf`.

## Usage

```
python article.py "topic"                 grounded article (with web search)
python article.py "topic" --no-search     comparison: the model writes references from memory
python article.py "topic" --compare       run both and compare the references
python article.py                         asks for the topic
```

| Option | Description |
|---|---|
| `-p`, `--provider` | `gemini` (default, `GEMINI_API_KEY`) or `openai` (`OPENAI_API_KEY`) |
| `-m`, `--model` | Model name |
| `-n`, `--sources` | Number of search results to give the model (default 8) |
| `--since YEAR` | Only use sources published from this year on |
| `-o`, `--output` | Output folder (default `output`) |
| `--no-verify` | Skip the reference check |
| `--skip-url-check` | Do not open reference URLs during the check |

Each run writes `article.pdf`, `article.html`, `report.json` (the validated structure), `sources.json` (grounded mode), `verification.md` and `verification.json`. `--compare` also writes `comparison.md`.

## How it works

1. **Web search** (`search.py`): the topic is searched in [OpenAlex](https://openalex.org), a free search API covering 250+ million scholarly works. No key is needed. OpenAlex returns real metadata (authors, year, title, venue, DOI) and abstracts. A general web search engine returns only page titles and snippets, which are not enough for APA references.
2. **Generation** (`generate.py`): the model gets the numbered search results and writes the article as JSON, citing sources only as `[S1]`, `[S2]`. It is told to use only these sources and to treat them as untrusted data.
3. **Grounded references**: the program builds the reference list itself from the search metadata of the cited sources. The model never types an author, year or DOI, so it cannot invent one. Citing an id that isn't in the search results fails validation, and the model is asked to correct it.
4. **Pydantic validation** (`models.py`): the `Report` model requires a title, a 40–300-word abstract, an introduction, 2–6 sections, a conclusion and at least 3 references. It also checks DOI and URL formats and years, that every citation in the text exists in the reference list, and that every reference is cited. Invalid output is sent back to the model with the errors, up to 3 attempts.
5. **Rendering** (`apa.py`, `render.py`): `[S1, S3]` becomes APA in-text citations such as `(Vaswani et al., 2017; Wolf, 2020)`, and the reference list is formatted in APA 7 and sorted alphabetically. HTML is converted to PDF with xhtml2pdf.
6. **Reference check** (`verify.py`): each reference's DOI is looked up in Crossref, or its title is searched in OpenAlex. Then **title, authors, year and DOI/URL** are compared with the real record. Each reference is marked **verified**, **partially correct** (it exists, but some details are wrong) or **not found** (hallucinated).

## Files

```
article.py        command-line entry point and pipeline
search.py         OpenAlex web search
generate.py       prompts and Report construction (grounded / no-search)
llm.py            LLM providers, JSON output, validation retries
models.py         Pydantic models: Source, Reference, Section, Report
apa.py            APA 7 in-text citations and reference entries
render.py         HTML and PDF rendering
verify.py         reference verification against Crossref and OpenAlex
test_models.py    unit tests (python -m unittest -v)
```
