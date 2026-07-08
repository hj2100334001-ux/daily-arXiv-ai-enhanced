import os
import sys
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
AI_DIR = PROJECT_ROOT / "ai"
sys.path.insert(0, str(AI_DIR))


class AiEnhanceTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.previous_cwd = Path.cwd()
        os.chdir(AI_DIR)
        import enhance  # noqa: PLC0415

        cls.enhance = enhance

    @classmethod
    def tearDownClass(cls):
        os.chdir(cls.previous_cwd)

    def test_parse_ai_json_response(self):
        parsed = self.enhance.parse_ai_json_response(
            '{"tldr":"摘要","motivation":"动机","method":"方法","result":"结果","conclusion":"结论"}'
        )

        self.assertEqual(parsed["tldr"], "摘要")
        self.assertEqual(parsed["conclusion"], "结论")

    def test_parse_ai_json_response_from_markdown_fence(self):
        parsed = self.enhance.parse_ai_json_response(
            '```json\n{"tldr":"摘要","motivation":"动机","method":"方法","result":"结果","conclusion":"结论"}\n```'
        )

        self.assertEqual(parsed["method"], "方法")


if __name__ == "__main__":
    unittest.main()