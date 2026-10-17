"""Tests for the reference checker, replaying real cases. Network calls are replaced by fixtures.
Run: python -m unittest -v"""
import unittest
from unittest import mock

import verify
from models import Reference


def work(title, authors, year, doi=None):
    return {"id": f"W-{title}-{year}", "title": title, "publication_year": year, "doi": doi and f"https://doi.org/{doi}",
            "authorships": [{"author": {"display_name": a}} for a in authors], "primary_location": {}}


CANDIDATES = {
    "Attention Is All You Need": [work("Attention is all you need", ["Unknown Reprinter"], 2025, "10.65215/2q58a426"),
                                  work("Attention Is All You Need", ["Ashish Vaswani", "Noam Shazeer"], 2017)],
    "LoRA: Low-Rank Adaptation of Large Language Models": [
        work("QA-LoRA: Quantization-Aware Low-Rank Adaptation of Large Language Models", ["Yuhui Xu", "Lingxi Xie"], 2023)],
    "Scaling Laws for Neural Language Models": [work("Scaling Laws for Neural Language Models",
                                                     ["Jared Kaplan A", "Sam McCandlish", "Tom Henighan"], 2020)],
    "Long Range Arena: A Benchmark for Efficient Transformers": [work("Long Range Arena: A Benchmark for Efficient Transformers",
                                                                      ["Yi Tay", "Mostafa Dehghani"], 2020)],
}
DOI_OPENALEX = {  # DOIs that Crossref does not hold, but OpenAlex does (arXiv / DataCite)
    "10.48550/arxiv.2108.05542": work("AMMUS : A Survey of Transformer-based Pretrained Models in Natural Language Processing",
                                      ["Katikapalli Subramanyam Kalyan", "Ajit Rajasekharan"], 2021, "10.48550/arxiv.2108.05542"),
}
CROSSREF = {
    "10.1234/jayasudha": {"title": "A Review of Transformer-Based Models for Natural Language Processing (NLP)",
                          "authors": ["Jayasudha J"], "year": 2025, "doi": "10.1234/jayasudha", "url": None},
}


def check(ref):
    with mock.patch.object(verify, "search_title", lambda t, rows=10: CANDIDATES.get(t, [])), \
         mock.patch.object(verify, "work_by_doi", lambda d: DOI_OPENALEX.get(d)), \
         mock.patch.object(verify, "crossref_by_doi", lambda d: CROSSREF.get(d)):
        return verify.check_reference(ref, check_urls=False)


class TestVerify(unittest.TestCase):
    def test_picks_original_not_duplicate(self):
        c = check(Reference(id="R1", authors=["Ashish Vaswani", "Noam Shazeer"], year=2017, title="Attention Is All You Need"))
        self.assertEqual(c.status, "verified")
        self.assertEqual(c.fields["year"], "ok")

    def test_similar_title_by_other_authors_is_not_a_match(self):
        c = check(Reference(id="R8", authors=["Edward J. Hu", "Yelong Shen"], year=2022,
                            title="LoRA: Low-Rank Adaptation of Large Language Models"))
        self.assertEqual(c.status, "not found")

    def test_messy_author_names(self):
        c = check(Reference(id="R5", authors=["Jared Kaplan", "Sam McCandlish"], year=2020,
                            title="Scaling Laws for Neural Language Models"))
        self.assertEqual(c.fields["authors"], "ok")
        c = check(Reference(id="S8", authors=["J. Jayasudha"], year=2025, doi="10.1234/jayasudha",
                            title="A Review of Transformer-Based Models for Natural Language Processing (NLP)"))
        self.assertEqual(c.status, "verified")

    def test_arxiv_doi_not_in_crossref(self):
        c = check(Reference(id="S4", authors=["Katikapalli Subramanyam Kalyan", "Ajit Rajasekharan"], year=2021,
                            doi="10.48550/arxiv.2108.05542",
                            title="AMMUS : A Survey of Transformer-based Pretrained Models in Natural Language Processing"))
        self.assertEqual(c.status, "verified")
        self.assertEqual(c.fields["doi"], "ok")

    def test_real_wrong_year_is_still_caught(self):
        c = check(Reference(id="R7", authors=["Yi Tay", "Mostafa Dehghani"], year=2022,
                            title="Long Range Arena: A Benchmark for Efficient Transformers"))
        self.assertEqual(c.status, "partially correct")
        self.assertTrue(c.fields["year"].startswith("wrong"))

    def test_one_year_difference_accepted(self):
        c = check(Reference(id="R9", authors=["Yi Tay"], year=2021,
                            title="Long Range Arena: A Benchmark for Efficient Transformers"))
        self.assertEqual(c.status, "verified")

    def test_fabricated_reference(self):
        c = check(Reference(id="R3", authors=["Laura Martinez"], year=2021, doi="10.5555/fake.123",
                            title="Hierarchical Sparse Attention for Long-Context Language Understanding"))
        self.assertEqual(c.status, "not found")
        self.assertEqual(c.fields["doi"], "wrong: DOI does not exist")


if __name__ == "__main__":
    unittest.main()
