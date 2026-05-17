import unittest

from app.services.answer_service import AnswerService


class AnswerServiceTests(unittest.TestCase):
    def test_compose_returns_extractive_summary_for_summary_query(self):
        results = [
            {
                "text": "00:00:01.000 Speaker: The product tracks market moves. It flags suspicious transactions immediately. It also predicts stock opportunities.",
            }
        ]

        answer = AnswerService.compose("summarize the video", results)

        self.assertIsNotNone(answer)
        self.assertEqual(answer["mode"], "extractive_summary")
        self.assertIn("The product tracks market moves.", answer["text"])

    def test_compose_returns_retrieval_brief_for_non_summary_query(self):
        results = [
            {
                "text": "00:00:01.000 Speaker: The agent scans market feeds in real time.",
            },
            {
                "text": "00:00:05.000 Speaker: It also alerts the user before a suspicious transfer completes.",
            },
        ]

        answer = AnswerService.compose("what does it do", results)

        self.assertIsNotNone(answer)
        self.assertEqual(answer["mode"], "retrieval_brief")
        self.assertIn("The agent scans market feeds in real time.", answer["text"])


if __name__ == "__main__":
    unittest.main()
