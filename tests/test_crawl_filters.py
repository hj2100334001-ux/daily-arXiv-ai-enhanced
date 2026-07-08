import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT / "daily_arxiv"))

from daily_arxiv.filters import (  # noqa: E402
    build_submitted_date_query,
    build_title_keyword_query,
    matches_title_keywords,
    parse_csv,
    parse_positive_int,
)


class CrawlFilterTests(unittest.TestCase):
    def test_keywords_match_title_only(self):
        keywords = parse_csv("gui agent, grounding")

        self.assertTrue(matches_title_keywords("GUI Agent Benchmark", keywords, "any"))
        self.assertFalse(matches_title_keywords("Generic Benchmark", keywords, "any"))

    def test_keyword_mode_all_requires_every_keyword_in_title(self):
        keywords = parse_csv("gui agent, grounding")

        self.assertTrue(matches_title_keywords("GUI Agent Grounding Benchmark", keywords, "all"))
        self.assertFalse(matches_title_keywords("GUI Agent Benchmark", keywords, "all"))

    def test_build_submitted_date_query_for_range(self):
        query = build_submitted_date_query(["cs.CV", "cs.CL"], "2026-07-01", "2026-07-08")

        self.assertEqual(
            query,
            "(cat:cs.CV OR cat:cs.CL) AND submittedDate:[202607010000 TO 202607082359]",
        )

    def test_build_title_keyword_query_uses_title_terms(self):
        keywords = parse_csv("gui agent, grounding")

        self.assertEqual(
            build_title_keyword_query(keywords, "any"),
            "((ti:gui AND ti:agent) OR ti:grounding)",
        )

    def test_build_title_keyword_query_supports_all_mode(self):
        keywords = parse_csv("gui agent, grounding")

        self.assertEqual(
            build_title_keyword_query(keywords, "all"),
            "((ti:gui AND ti:agent) AND ti:grounding)",
        )

    def test_parse_positive_int_uses_default_for_empty_or_invalid_values(self):
        self.assertEqual(parse_positive_int("", default=20), 20)
        self.assertEqual(parse_positive_int("0", default=20), 20)
        self.assertEqual(parse_positive_int("abc", default=20), 20)
        self.assertEqual(parse_positive_int("5", default=20), 5)


if __name__ == "__main__":
    unittest.main()