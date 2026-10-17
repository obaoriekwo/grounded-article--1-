"""
Structured, validated representation of the article (Pydantic).

The LLM never produces the PDF directly. It produces JSON that must pass these models first:
  Source     - one search result with its real metadata (from the search API)
  Reference  - one entry in the reference list
  Section    - a heading with paragraphs
  Report     - the whole article; its validator checks that every citation [S1] / [R1] in the
               text points to a reference and that every reference is actually cited.
"""

import re
from datetime import date

from pydantic import BaseModel, Field, field_validator, model_validator

CITATION = re.compile(r"\[((?:[SR]\d+)(?:\s*[,;]\s*[SR]\d+)*)\]")
DOI_PATTERN = re.compile(r"^10\.\d{4,9}/\S+$")
CURRENT_YEAR = date.today().year


def citation_ids(text: str) -> list[str]:
    ids = []
    for group in CITATION.findall(text):
        ids += [x.strip() for x in re.split(r"[,;]", group)]
    return ids


def clean_doi(value: str | None) -> str | None:
    if not value:
        return None
    value = value.strip()
    value = re.sub(r"^(https?://)?(dx\.)?doi\.org/", "", value, flags=re.I)
    value = re.sub(r"^doi:\s*", "", value, flags=re.I)
    return value or None


class Source(BaseModel):
    id: str
    title: str
    authors: list[str] = []
    year: int | None = None
    venue: str | None = None
    doi: str | None = None
    url: str | None = None
    abstract: str = ""
    origin: str = "openalex"


class Reference(BaseModel):
    id: str = Field(pattern=r"^[SR]\d+$")
    authors: list[str] = Field(min_length=1, description="Author names, e.g. 'Ashish Vaswani'")
    year: int | None = Field(default=None, ge=1800, le=CURRENT_YEAR + 1)
    title: str = Field(min_length=3, max_length=400)
    venue: str | None = None
    doi: str | None = None
    url: str | None = None

    @field_validator("authors")
    @classmethod
    def authors_not_blank(cls, v):
        v = [" ".join(a.split()) for a in v if a and a.strip()]
        if not v:
            raise ValueError("at least one non-empty author is required")
        return v

    @field_validator("doi", mode="before")
    @classmethod
    def doi_format(cls, v):
        v = clean_doi(v)
        if v is not None and not DOI_PATTERN.match(v):
            raise ValueError(f"'{v}' is not a valid DOI (expected 10.xxxx/...)")
        return v

    @field_validator("url")
    @classmethod
    def url_format(cls, v):
        if v is not None and not re.match(r"^https?://\S+$", v.strip()):
            raise ValueError(f"'{v}' is not an http(s) URL")
        return v.strip() if v else v


class Section(BaseModel):
    heading: str = Field(min_length=3, max_length=150)
    paragraphs: list[str] = Field(min_length=1, max_length=8)


class Report(BaseModel):
    title: str = Field(min_length=5, max_length=200)
    abstract: str
    introduction: list[str] = Field(min_length=1, max_length=5)
    sections: list[Section] = Field(min_length=2, max_length=6)
    conclusion: list[str] = Field(min_length=1, max_length=4)
    references: list[Reference] = Field(min_length=3, max_length=25)

    @field_validator("abstract")
    @classmethod
    def abstract_length(cls, v):
        words = len(v.split())
        if not 40 <= words <= 300:
            raise ValueError(f"abstract must be 40-300 words, got {words}")
        return v

    @field_validator("introduction", "conclusion")
    @classmethod
    def no_blank_paragraphs(cls, v):
        if any(not p.strip() for p in v):
            raise ValueError("paragraphs must not be empty")
        return v

    def body_texts(self) -> list[str]:
        texts = [self.abstract, *self.introduction, *self.conclusion]
        for s in self.sections:
            texts += s.paragraphs
        return texts

    @model_validator(mode="after")
    def citations_match_references(self):
        ref_ids = [r.id for r in self.references]
        duplicates = {i for i in ref_ids if ref_ids.count(i) > 1}
        if duplicates:
            raise ValueError(f"duplicate reference ids: {sorted(duplicates)}")
        cited = []
        for text in self.body_texts():
            cited += citation_ids(text)
        unknown = sorted(set(cited) - set(ref_ids))
        if unknown:
            raise ValueError(f"the text cites {unknown}, which are not in the reference list")
        uncited = sorted(set(ref_ids) - set(cited))
        if uncited:
            raise ValueError(f"references {uncited} are never cited in the text")
        if len(set(cited)) < 3:
            raise ValueError("the article must cite at least 3 different references")
        return self


# ----- what the LLM is asked to return ---------------------------------------------------------

class ArticleDraft(BaseModel):
    """LLM output in grounded mode: text only. References are added by the program from the sources."""
    title: str
    abstract: str
    introduction: list[str]
    sections: list[Section]
    conclusion: list[str]


class UngroundedDraft(ArticleDraft):
    """LLM output without web search: the model must also write the references itself."""
    references: list[Reference]
