import unittest
from unittest.mock import patch

from app.workers.poller import WorkspaceSyncPoller


class WorkspaceSyncPollerTests(unittest.TestCase):
    def test_register_token_does_not_sync_when_disabled(self):
        previous_enabled = WorkspaceSyncPoller.enabled
        WorkspaceSyncPoller.enabled = False
        try:
            with patch(
                "app.workers.poller.IngestionService.start_workspace_sync"
            ) as sync_mock:
                status = WorkspaceSyncPoller.register_token("not-a-real-token")

            self.assertFalse(status["enabled"])
            self.assertEqual(status["last_result"]["status"], "DISABLED")
            sync_mock.assert_not_called()
        finally:
            WorkspaceSyncPoller.enabled = previous_enabled


if __name__ == "__main__":
    unittest.main()
