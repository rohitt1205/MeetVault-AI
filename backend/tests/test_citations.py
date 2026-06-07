import unittest

from app.rag.citations import build_citations


class CitationBuilderTests(unittest.TestCase):
    def test_build_citations_includes_speaker_time_and_excerpt(self):
        citations = build_citations([
            {
                "chunk_id": "meeting-1:2",
                "text": (
                    "00:12:34.500 Puneeth Kamath: Japan assignment rules need review.\n"
                    "00:13:01.000 Puneeth Kamath: Nathan will close UAT after dashboard review."
                ),
                "metadata": {
                    "speaker_start": "Puneeth Kamath",
                    "speaker_end": "Puneeth Kamath",
                    "start_timestamp": "00:12:34.500",
                    "end_timestamp": "00:13:01.000",
                    "meeting_title": "Following: CRMA",
                    "source_type": "onedrive_transcript",
                },
            }
        ])

        self.assertEqual(len(citations), 1)
        self.assertEqual(citations[0]["speaker"], "Puneeth Kamath")
        self.assertEqual(citations[0]["time_label"], "00:12:34.500 – 00:13:01.000")
        self.assertEqual(citations[0]["meeting_title"], "Following: CRMA")
        self.assertIn("Japan assignment rules", citations[0]["excerpt"])

    def test_build_citations_skips_jira_sources(self):
        citations = build_citations([
            {
                "chunk_id": "mcp-jira-live",
                "text": "Found 2 live Jira ticket(s).",
                "metadata": {"source_type": "mcp_jira"},
            }
        ])
        self.assertEqual(citations, [])

    def test_build_citations_sorts_by_start_time(self):
        citations = build_citations([
            {
                "chunk_id": "b",
                "text": "00:20:00 Speaker: later point",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": "00:20:00",
                    "source_type": "graph_transcript",
                },
            },
            {
                "chunk_id": "a",
                "text": "00:05:00 Speaker: earlier point",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": "00:05:00",
                    "source_type": "graph_transcript",
                },
            },
        ])

        self.assertEqual([item["id"] for item in citations], ["a", "b"])

    def test_build_citations_respects_limit(self):
        sources = [
            {
                "chunk_id": f"chunk-{index}",
                "text": f"00:0{index}:00 Speaker: point {index}",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": f"00:0{index}:00",
                    "source_type": "graph_transcript",
                },
            }
            for index in range(1, 6)
        ]

        citations = build_citations(sources, limit=1)

        self.assertEqual(len(citations), 1)

    def test_build_citations_picks_one_proof_per_topic(self):
        sources = [
            {
                "chunk_id": "recipe-chunk",
                "text": "00:10:00 Speaker: The recipe workflow needs approval.",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": "00:10:00",
                    "source_type": "graph_transcript",
                },
            },
            {
                "chunk_id": "lenses-chunk",
                "text": "00:05:00 Speaker: Lenses are configured in the dashboard.",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": "00:05:00",
                    "source_type": "graph_transcript",
                },
            },
            {
                "chunk_id": "other-chunk",
                "text": "00:01:00 Speaker: Unrelated intro.",
                "metadata": {
                    "speaker_start": "Speaker",
                    "start_timestamp": "00:01:00",
                    "source_type": "graph_transcript",
                },
            },
        ]

        citations = build_citations(
            sources,
            limit=2,
            query="explain lenses and recipe",
        )

        self.assertEqual(len(citations), 2)
        excerpts = " ".join(item["excerpt"].lower() for item in citations)
        self.assertIn("lens", excerpts)
        self.assertIn("recipe", excerpts)

    def test_build_citations_handles_typo_and_shared_chunk(self):
        shared_text = (
            "00:16:36.481 Madduri Lakshmi Ambika: recipes will be the more focused area.\n"
            "00:17:10.000 Madduri Lakshmi Ambika: we analyze data using lenses in explore data."
        )
        sources = [
            {
                "chunk_id": "shared-chunk",
                "text": shared_text,
                "metadata": {
                    "speaker_start": "Madduri Lakshmi Ambika",
                    "speaker_end": "Madduri Lakshmi Ambika",
                    "start_timestamp": "00:16:36.481",
                    "end_timestamp": "00:17:36.081",
                    "meeting_title": "Following: CRMA",
                    "source_type": "onedrive_transcript",
                },
            }
        ]

        citations = build_citations(
            sources,
            limit=2,
            query="explain reciepe and lenses",
        )

        self.assertEqual(len(citations), 2)
        topics = {item["topic"] for item in citations}
        self.assertEqual(topics, {"reciepe", "lenses"})
        recipe_excerpt = next(item["excerpt"].lower() for item in citations if item["topic"] == "reciepe")
        lens_excerpt = next(item["excerpt"].lower() for item in citations if item["topic"] == "lenses")
        self.assertIn("recipe", recipe_excerpt)
        self.assertIn("lens", lens_excerpt)

    def test_single_topic_proof_uses_focused_excerpt(self):
        shared_text = (
            "00:16:36.481 Madduri Lakshmi Ambika: recipes will be the more focused area.\n"
            "00:17:10.000 Madduri Lakshmi Ambika: we analyze data using lenses in explore data."
        )
        sources = [
            {
                "chunk_id": "shared-chunk",
                "text": shared_text,
                "metadata": {
                    "speaker_start": "Madduri Lakshmi Ambika",
                    "start_timestamp": "00:16:36.481",
                    "end_timestamp": "00:17:36.081",
                    "source_type": "onedrive_transcript",
                },
            }
        ]

        citations = build_citations(sources, limit=1, query="explain lenses")

        self.assertEqual(len(citations), 1)
        excerpt = citations[0]["excerpt"].lower()
        self.assertIn("lens", excerpt)
        self.assertNotIn("recipes will be the more focused", excerpt)


if __name__ == "__main__":
    unittest.main()
