import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from verify_and_dedupe import verify_and_dedupe


class DedupeTests(unittest.TestCase):
    def test_same_url_is_duplicate(self):
        events = [
            {
                "id": "a",
                "title": "OpenAI releases API update",
                "summary": "",
                "company": "OpenAI",
                "source_url": "https://openai.com/news/test?utm_source=x",
                "credibility": "official",
                "importance": "High",
                "tags": ["API 更新"],
                "secondary_sources": [],
                "is_manual_input": False,
            },
            {
                "id": "b",
                "title": "OpenAI API update",
                "summary": "",
                "company": "OpenAI",
                "source_url": "https://openai.com/news/test",
                "credibility": "unverified",
                "importance": "Medium",
                "tags": ["待核实"],
                "secondary_sources": [],
                "is_manual_input": True,
            },
        ]
        merged, duplicates = verify_and_dedupe(events)
        self.assertEqual(len(merged), 1)
        self.assertEqual(len(duplicates), 1)
        self.assertTrue(merged[0]["multi_source"])
        self.assertEqual(merged[0]["credibility"], "official")


if __name__ == "__main__":
    unittest.main()
