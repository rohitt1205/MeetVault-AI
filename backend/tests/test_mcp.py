import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.mcp import connection_store
from app.mcp.github import github_oauth
from app.mcp.jira import jira_connector
from app.mcp.mcp_manager import MCPManager


class MCPTests(unittest.TestCase):
    def test_connections_persist_without_exposing_tokens(self):
        original_path = connection_store.MCP_CONNECTION_STORE_PATH
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                connection_store.MCP_CONNECTION_STORE_PATH = Path(tmp_dir) / "mcp.json"

                with patch(
                    "app.mcp.mcp_manager.jira_connector.verify_and_connect",
                    return_value={
                        "connected": True,
                        "email": "dev@example.com",
                        "domain": "team",
                        "token": "jira-secret",
                    },
                ):
                    MCPManager.connect_jira(
                        email="dev@example.com",
                        domain="team.atlassian.net",
                        api_token="jira-secret",
                        user_key="Dev@Example.com",
                    )

                public_connection = MCPManager.get_jira_connection("dev@example.com")
                private_session = MCPManager.get_jira_session("dev@example.com")
            finally:
                connection_store.MCP_CONNECTION_STORE_PATH = original_path

        self.assertTrue(public_connection["connected"])
        self.assertNotIn("token", public_connection)
        self.assertEqual(private_session["token"], "jira-secret")

    def test_github_login_reports_missing_oauth_config(self):
        with patch.dict("os.environ", {}, clear=True):
            with self.assertRaises(HTTPException) as context:
                github_oauth.get_github_login_url("dev@example.com")

        self.assertEqual(context.exception.status_code, 503)
        self.assertIn("GITHUB_CLIENT_ID", context.exception.detail)

    def test_jira_fetch_uses_current_user_jql(self):
        response = Mock()
        response.ok = True
        response.json.return_value = {"issues": []}

        with patch("app.mcp.jira.jira_connector.requests.get", return_value=response) as mock_get:
            jira_connector.fetch_tickets(
                email="dev@example.com",
                domain="team",
                token="secret",
            )

        params = mock_get.call_args.kwargs["params"]
        self.assertIn("assignee = currentUser()", params["jql"])


if __name__ == "__main__":
    unittest.main()
