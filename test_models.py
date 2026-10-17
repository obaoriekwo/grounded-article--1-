"""Unit tests for the Pydantic models and APA formatting. Run: python -m unittest -v"""
import unittest
from pydantic import ValidationError
from models import Reference, Report
from apa import in_text, reference_entry, author_apa

REFS = [Reference(id=f"S{i}", authors=a, year=y, title=t, doi=d) for i, (a, y, t, d) in enumerate([
    (["Ashish Vaswani", "Noam Shazeer", "Niki Parmar"], 2017, "Attention is all you need", "10.48550/arxiv.1706.03762"),
    (["Jacob Devlin", "Ming-Wei Chang"], 2019, "BERT", None),
    (["Thomas Wolf"], 2020, "Transformers", "https://doi.org/10.18653/v1/2020.emnlp-demos.6")], start=1)]
ABSTRACT = " ".join(["word"] * 60) + " [S1]"

def report(**overrides):
    data = dict(title="A test article", abstract=ABSTRACT, introduction=["Intro [S2]."],
                sections=[{"heading": "First part", "paragraphs": ["Text [S3]."]},
                          {"heading": "Second part", "paragraphs": ["More [S1, S2]."]}],
                conclusion=["End."], references=REFS)
    data.update(overrides)
    return Report.model_validate(data)

class TestReport(unittest.TestCase):
    def test_valid(self):
        self.assertEqual(len(report().references), 3)
    def test_unknown_citation(self):
        with self.assertRaises(ValidationError):
            report(conclusion=["End [S9]."])
    def test_uncited_reference(self):
        extra = REFS + [Reference(id="S4", authors=["X Y"], year=2020, title="Never cited")]
        with self.assertRaises(ValidationError):
            report(references=extra)
    def test_needs_two_sections_and_abstract_length(self):
        with self.assertRaises(ValidationError):
            report(sections=[{"heading": "Only one", "paragraphs": ["[S1] [S2] [S3]"]}])
        with self.assertRaises(ValidationError):
            report(abstract="Too short [S1].")
    def test_bad_doi_and_year(self):
        with self.assertRaises(ValidationError):
            Reference(id="R1", authors=["A B"], year=2020, title="Title", doi="not-a-doi")
        with self.assertRaises(ValidationError):
            Reference(id="R1", authors=["A B"], year=2099, title="Title")
    def test_doi_cleaned(self):
        self.assertEqual(REFS[2].doi, "10.18653/v1/2020.emnlp-demos.6")

class TestAPA(unittest.TestCase):
    def test_in_text(self):
        self.assertEqual(in_text(REFS[0]), "Vaswani et al., 2017")
        self.assertEqual(in_text(REFS[1]), "Devlin & Chang, 2019")
        self.assertEqual(in_text(REFS[2]), "Wolf, 2020")
    def test_author_names(self):
        self.assertEqual(author_apa("Ming-Wei Chang"), "Chang, M.-W.")
        self.assertEqual(author_apa("Jean-Paul Sartre"), "Sartre, J.-P.")
        self.assertEqual(author_apa("Vincent van Gogh"), "van Gogh, V.")
    def test_reference_entry(self):
        self.assertIn("Vaswani, A., Shazeer, N., &amp; Parmar, N. (2017). Attention is all you need.", reference_entry(REFS[0]))
        self.assertIn("https://doi.org/10.48550/arxiv.1706.03762", reference_entry(REFS[0]))



class TestGroundedReport(unittest.TestCase):
    def test_same_source_cited_twice_in_one_paragraph(self):
        from generate import grounded_report
        from models import ArticleDraft, Source
        sources = {f"S{i}": Source(id=f"S{i}", title=f"Paper {i}", authors=["Ann Author"], year=2020) for i in range(1, 5)}
        draft = ArticleDraft(title="A test article", abstract=" ".join(["word"] * 60),
                             introduction=["First [S4] and again [S4], then [S1]."],
                             sections=[{"heading": "Part one", "paragraphs": ["[S2] [S2] [S3]"]},
                                       {"heading": "Part two", "paragraphs": ["[S1, S4]"]}],
                             conclusion=["Done."])
        report = grounded_report(draft, sources)
        self.assertEqual([r.id for r in report.references], ["S4", "S1", "S2", "S3"])


if __name__ == "__main__":
    unittest.main()
