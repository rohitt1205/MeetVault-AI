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
            mock_collection.query.return_value = fake_response

            result = ChromaService.query_embeddings([0.1, 0.2], n_results=5)

        self.assertEqual(result["documents"][0], ["live text 1", "live text 2"])
        self.assertEqual(result["ids"][0], ["upload-1:1", "upload-2:1"])

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
