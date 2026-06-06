import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

from fastapi import HTTPException

from app.mcp import tool_registry, custom_mcp_connector
from app.mcp import oauth_state_store
from app.rag import retrieve


class MCPV2Tests(unittest.TestCase):
    def setUp(self):
        self.original_tools_path = tool_registry.MCP_TOOL_REGISTRY_PATH
        self.tmp_dir = tempfile.TemporaryDirectory()
        tool_registry.MCP_TOOL_REGISTRY_PATH = Path(self.tmp_dir.name) / "mcp_tools.json"

    def tearDown(self):
        self.tmp_dir.cleanup()
        tool_registry.MCP_TOOL_REGISTRY_PATH = self.original_tools_path

    def test_tool_registry_registration_and_retrieval(self):
        """Validates that tools can be registered and retrieved locally."""
        tools = [
            {"name": "fetch_data", "description": "Fetches raw data", "parameters": {}},
            {"name": "send_alert", "description": "Sends alarm", "parameters": {"msg": "str"}}
        ]
        
        # Register tools
        ok = tool_registry.MCPToolRegistry.register_tools("custom_mcp_1", "user-1", tools)
        self.assertTrue(ok)

        # Retrieve tools
        active = tool_registry.MCPToolRegistry.get_active_tools("user-1")
        self.assertEqual(len(active), 2)
        
        names = [t["name"] for t in active]
        self.assertIn("fetch_data", names)
        self.assertIn("send_alert", names)
        self.assertEqual(active[0]["provider"], "custom_mcp_1")

        # Clear tools
        clear_ok = tool_registry.MCPToolRegistry.clear_tools("custom_mcp_1", "user-1")
        self.assertTrue(clear_ok)
        
        active_cleared = tool_registry.MCPToolRegistry.get_active_tools("user-1")
        self.assertEqual(len(active_cleared), 0)

    def test_oauth_state_round_trip(self):
        """Validates that OAuth login context can be stored and consumed once."""
        original_path = oauth_state_store.MCP_OAUTH_STATE_STORE_PATH
        with tempfile.TemporaryDirectory() as tmp_dir:
            try:
                oauth_state_store.MCP_OAUTH_STATE_STORE_PATH = Path(tmp_dir) / "oauth_state.json"
                state = oauth_state_store.MCPOAuthStateStore.create(
                    "dev@example.com",
                    "supabase-jwt-token",
                )
                ctx = oauth_state_store.MCPOAuthStateStore.consume(state)
                self.assertEqual(ctx["user_key"], "dev@example.com")
                self.assertEqual(ctx["supabase_jwt"], "supabase-jwt-token")
                self.assertIsNone(oauth_state_store.MCPOAuthStateStore.consume(state))
            finally:
                oauth_state_store.MCP_OAUTH_STATE_STORE_PATH = original_path

    @patch("app.mcp.custom_mcp_connector.requests.post")
    def test_custom_mcp_discovery_direct_post(self, mock_post):
        """Validates tool discovery via direct JSON-RPC POST."""
        mock_res = Mock()
        mock_res.ok = True
        mock_res.json.return_value = {
            "result": {
                "tools": [
                    {
                        "name": "get_weather",
                        "description": "Get current weather",
                        "inputSchema": {"type": "object", "properties": {}}
                    }
                ]
            }
        }
        mock_post.return_value = mock_res

        tools = custom_mcp_connector.discover_tools("http://localhost:9000")
        self.assertEqual(len(tools), 1)
        self.assertEqual(tools[0]["name"], "get_weather")
        self.assertEqual(tools[0]["description"], "Get current weather")

    @patch("app.mcp.custom_mcp_connector.requests.post")
    def test_custom_mcp_execute_direct_post(self, mock_post):
        """Validates tool execution via direct JSON-RPC POST."""
        mock_res = Mock()
        mock_res.ok = True
        mock_res.json.return_value = {
            "result": {"status": "success", "data": "rainy"}
        }
        mock_post.return_value = mock_res

        res = custom_mcp_connector.execute_tool("http://localhost:9000", "get_weather", {})
        self.assertEqual(res["data"], "rainy")

    def test_fallback_keyword_matching_router(self):
        """Checks keyword-based routing matching behavior."""
        active_tools = [
            {
                "provider": "jira",
                "name": "get_jira_tickets",
                "description": "Fetch tickets",
                "parameters": {}
            },
            {
                "provider": "github",
                "name": "get_github_issues",
                "description": "Fetch issues",
                "parameters": {}
            }
        ]
        
        # Query that should match Jira keyword
        jira_calls = retrieve._detect_tool_calls_fallback("Do I have any open tickets assigned in Jira?", active_tools)
        self.assertEqual(len(jira_calls), 1)
        self.assertEqual(jira_calls[0]["provider"], "jira")
        self.assertEqual(jira_calls[0]["tool_name"], "get_jira_tickets")

        # Query that should match GitHub keyword
        github_calls = retrieve._detect_tool_calls_fallback("Show me my pr reviews on github", active_tools)
        self.assertEqual(len(github_calls), 1)
        self.assertEqual(github_calls[0]["provider"], "github")
        self.assertEqual(github_calls[0]["tool_name"], "get_github_issues")

    @patch("app.mcp.slack.slack_connector.requests.post")
    def test_slack_invalid_token_fails(self, mock_post):
        """Verifies that Slack does not create a fake connection for invalid tokens."""
        from app.mcp.slack import slack_connector

        mock_response = Mock()
        mock_response.ok = True
        mock_response.json.return_value = {"ok": False, "error": "invalid_auth"}
        mock_post.return_value = mock_response

        with self.assertRaises(HTTPException):
            slack_connector.verify_and_connect("invalid-token")

    @patch("app.mcp.salesforce.salesforce_connector.requests.get")
    def test_salesforce_invalid_token_fails(self, mock_get):
        """Verifies that Salesforce does not create a fake connection for invalid tokens."""
        from app.mcp.salesforce import salesforce_connector

        mock_response = Mock()
        mock_response.ok = False
        mock_response.text = "invalid session"
        mock_get.return_value = mock_response

        with self.assertRaises(HTTPException):
            salesforce_connector.verify_and_connect("invalid-token", "https://example.salesforce.com")

    @patch("app.mcp.jira.jira_connector.requests.get")
    def test_jira_invalid_token_fails(self, mock_get):
        """Verifies that Jira does not create a fake connection for invalid tokens."""
        from app.mcp.jira import jira_connector

        mock_response = Mock()
        mock_response.ok = False
        mock_response.text = "invalid api token"
        mock_get.return_value = mock_response

        with self.assertRaises(HTTPException):
            jira_connector.verify_and_connect("user@example.com", "team", "invalid-token", "demo")

    @patch("app.mcp.connection_store.MCPConnectionStore.disconnect_in_db")
    def test_mcp_manager_disconnect_fallback(self, mock_disconnect_db):
        """Verifies that disconnect_provider falls back to local storage if DB call fails."""
        from app.mcp.mcp_manager import MCPManager
        from app.mcp.connection_store import MCPConnectionStore
        mock_disconnect_db.return_value = False

        # Clear existing tool registries / state if any
        # Disconnect mock provider
        res = MCPManager.disconnect_provider("jira", "demo", "supabase-jwt.with.dot")
        self.assertTrue(res)  # Should return True due to local fallback


if __name__ == "__main__":
    unittest.main()
