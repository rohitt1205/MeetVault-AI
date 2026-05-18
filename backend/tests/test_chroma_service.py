import unittest
from unittest.mock import MagicMock, patch

from app.services.chroma_service import ChromaService


class ChromaServiceTests(unittest.TestCase):
    def test_query_embeddings_filters_legacy_results_without_meeting_id(self):
        fake_response = {
            "documents": [[
                "legacy text",
                "live text 1",
                "live text 2",
            ]],
            "metadatas": [[
                {"source": "meeting_transcript"},
                {"meeting_id": "upload-1", "meeting_title": "One"},
                {"meeting_id": "upload-2", "meeting_title": "Two"},
            ]],
            "distances": [[1.0, 1.1, 1.2]],
            "ids": [["1", "upload-1:1", "upload-2:1"]],
        }

        with patch.object(ChromaService, "collection", MagicMock()) as mock_collection:
            mock_collection.count.return_value = 3
            mock_collection.query.return_value = fake_response

            result = ChromaService.query_embeddings([0.1, 0.2], n_results=5)

        self.assertEqual(result["documents"][0], ["live text 1", "live text 2"])
        self.assertEqual(result["ids"][0], ["upload-1:1", "upload-2:1"])

    def test_query_embeddings_uses_wide_candidate_pool_for_reranking(self):
        fake_response = {
            "documents": [["live text"]],
            "metadatas": [[{"meeting_id": "upload-1", "meeting_title": "One"}]],
            "distances": [[1.0]],
            "ids": [["upload-1:1"]],
        }

        with patch.object(ChromaService, "collection", MagicMock()) as mock_collection:
            mock_collection.count.return_value = 100
            mock_collection.query.return_value = fake_response

            ChromaService.query_embeddings([0.1, 0.2], n_results=5, candidate_pool_size=80)

        mock_collection.query.assert_called_once()
        self.assertEqual(mock_collection.query.call_args.kwargs["n_results"], 80)

    def test_query_embeddings_uses_candidate_pool_when_meeting_id_scoped(self):
        fake_response = {
            "documents": [["scoped text"]],
            "metadatas": [[{"meeting_id": "teams-1", "meeting_title": "Standup"}]],
            "distances": [[0.5]],
            "ids": [["teams-1:1"]],
        }

        with patch.object(ChromaService, "collection", MagicMock()) as mock_collection:
            mock_collection.count.return_value = 100
            mock_collection.query.return_value = fake_response

            ChromaService.query_embeddings(
                [0.1, 0.2],
                meeting_id="teams-1",
                n_results=5,
                candidate_pool_size=80,
            )

        self.assertEqual(mock_collection.query.call_args.kwargs["n_results"], 80)

    def test_query_embeddings_filters_disallowed_source_types_before_limiting(self):
        fake_response = {
            "documents": [[
                "old local chunk",
                "sharepoint chunk",
            ]],
            "metadatas": [[
                {
                    "meeting_id": "upload-1",
                    "meeting_title": "Asynchronous apex",
                    "source_type": "uploaded_transcript",
                },
                {
                    "meeting_id": "sharepoint-1",
                    "meeting_title": "LWC Training",
                    "source_type": "sharepoint_recording_transcription",
                },
            ]],
            "distances": [[0.01, 1.20]],
            "ids": [["upload-1:1", "sharepoint-1:1"]],
        }

        with patch.object(ChromaService, "collection", MagicMock()) as mock_collection:
            mock_collection.count.return_value = 2
            mock_collection.query.return_value = fake_response

            result = ChromaService.query_embeddings(
                [0.1, 0.2],
                n_results=1,
                allowed_source_types={"sharepoint_recording_transcription"},
            )

        self.assertEqual(result["documents"][0], ["sharepoint chunk"])
        self.assertEqual(result["ids"][0], ["sharepoint-1:1"])

    def test_delete_meeting_embeddings_removes_matching_chunks(self):
        fake_collection = MagicMock()
        fake_collection.get.return_value = {
            "ids": ["teams-1:1", "teams-1:2"],
            "metadatas": [
                {"meeting_id": "teams-1"},
                {"meeting_id": "teams-1"},
            ],
        }

        with patch.object(ChromaService, "collection", fake_collection):
            result = ChromaService.delete_meeting_embeddings("teams-1")

        fake_collection.delete.assert_called_once_with(ids=["teams-1:1", "teams-1:2"])
        self.assertEqual(result["deleted_chunks"], 2)

    def test_remove_legacy_documents_deletes_only_legacy_ids(self):
        fake_collection = MagicMock()
        fake_collection.get.return_value = {
            "ids": ["1", "upload-1:1", "2"],
            "metadatas": [
                {"source": "meeting_transcript"},
                {"meeting_id": "upload-1", "meeting_title": "One"},
                {"source": "meeting_transcript"},
            ],
        }

        with patch.object(ChromaService, "collection", fake_collection):
            result = ChromaService.remove_legacy_documents()

        fake_collection.delete.assert_called_once_with(ids=["1", "2"])
        self.assertEqual(result["removed"], 2)


if __name__ == "__main__":
    unittest.main()
