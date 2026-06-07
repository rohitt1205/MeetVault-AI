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

    def test_compose_ignores_repeated_low_signal_transcripts(self):
        results = [
            {
                "text": "Unknown: You You You You You You You You You You You You You You You You You",
            }
        ]

        answer = AnswerService.compose("summarize LWC Training", results)

        self.assertIsNone(answer)

    def test_citation_limit_is_one_for_targeted_question(self):
        self.assertEqual(AnswerService.citation_limit_for_query("explain lenses"), 1)

    def test_citation_limit_matches_multi_topic_question(self):
        self.assertEqual(
            AnswerService.citation_limit_for_query("explain lenses and recipe"),
            2,
        )

    def test_extract_query_topics_splits_on_and(self):
        self.assertEqual(
            AnswerService.extract_query_topics("explain lenses and recipe"),
            ["lenses", "recipe"],
        )

    def test_extract_primary_topic_for_single_focus(self):
        self.assertEqual(AnswerService.extract_primary_topic("explain lenses"), "lenses")

    def test_citation_limit_is_higher_for_summary(self):
        self.assertEqual(
            AnswerService.citation_limit_for_query("give summary of this meeting"),
            5,
        )


if __name__ == "__main__":
    unittest.main()
