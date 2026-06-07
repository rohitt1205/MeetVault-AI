from app.mcp.github import github_oauth, github_connector
from app.mcp.jira import jira_connector
from app.mcp.outlook import outlook_connector
from app.mcp.calendar import calendar_connector
from app.mcp.slack import slack_connector
from app.mcp.salesforce import salesforce_connector
from app.mcp.connection_store import MCPConnectionStore
from app.mcp.tool_registry import MCPToolRegistry
from app.mcp import custom_mcp_connector
from app.mcp import oauth_providers


class MCPManager:
    @staticmethod
    def register_provider_tools(provider: str, user_key: str, supabase_jwt: str | None = None):
        """Auto-registers predefined tools for standard providers in the ToolRegistry."""
        tools_map = {
            "github": [
                {"name": "get_github_issues", "description": "Fetches open GitHub issues assigned to the authenticated user.", "parameters": {"type": "object", "properties": {}}},
                {"name": "get_github_prs", "description": "Fetches open GitHub pull requests created by the user.", "parameters": {"type": "object", "properties": {}}},
                {"name": "get_github_reviews", "description": "Fetches pull requests awaiting review by the user.", "parameters": {"type": "object", "properties": {}}},
                {"name": "get_github_repositories", "description": "Fetches repositories the authenticated user can access.", "parameters": {"type": "object", "properties": {}}},
            ],
            "jira": [
                {"name": "get_jira_tickets", "description": "Fetches Jira issues and tasks assigned to the authenticated user.", "parameters": {"type": "object", "properties": {}}},
            ],
            "slack": [
                {"name": "get_slack_mentions", "description": "Fetches recent user mentions and messages from Slack.", "parameters": {"type": "object", "properties": {}}},
            ],
            "salesforce": [
                {"name": "get_salesforce_opportunities", "description": "Fetches sales leads and pipeline opportunities from Salesforce.", "parameters": {"type": "object", "properties": {}}},
            ],
            "outlook": [
                {"name": "get_outlook_emails", "description": "Fetches unread important or flagged emails from Microsoft Outlook.", "parameters": {"type": "object", "properties": {}}},
            ],
            "calendar": [
                {"name": "get_calendar_events", "description": "Fetches upcoming meetings and calendar schedule from Microsoft Calendar.", "parameters": {"type": "object", "properties": {}}},
            ],
            "notion": [
                {"name": "get_notion_pages", "description": "Fetches recent workspaces and pages from Notion.", "parameters": {"type": "object", "properties": {}}},
            ],
            "gmail": [
                {"name": "get_gmail_messages", "description": "Fetches unread messages and inbox summaries from Gmail.", "parameters": {"type": "object", "properties": {}}},
            ]
        }
        
        if provider in tools_map:
            MCPToolRegistry.register_tools(provider, user_key, tools_map[provider], supabase_jwt)

    @staticmethod
    def get_all_connections(
        user_key: str,
        graph_jwt: str | None = None,
        supabase_jwt: str | None = None,
    ):
        github = MCPManager.get_github_connection(user_key, supabase_jwt)
        jira = MCPManager.get_jira_connection(user_key, supabase_jwt)
        outlook = outlook_connector.get_outlook_status(
            user_key, graph_jwt, supabase_jwt
        )
        calendar = calendar_connector.get_calendar_status(
            user_key, graph_jwt, supabase_jwt
        )
        slack = MCPManager.get_slack_connection(user_key, supabase_jwt)
        salesforce = MCPManager.get_salesforce_connection(user_key, supabase_jwt)

        # Get extra connections (Notion, Gmail, Custom MCP)
        conns = MCPConnectionStore.get_all_user_connections(user_key, supabase_jwt)
        active_providers = {c.get("provider"): c for c in conns}

        notion_conn = active_providers.get("notion")
        notion = {
            "connected": notion_conn is not None and notion_conn.get("connected", True),
            "email": notion_conn.get("provider_user_id") if notion_conn else None,
        }

        gmail_conn = active_providers.get("gmail")
        gmail = {
            "connected": gmail_conn is not None and gmail_conn.get("connected", True),
            "email": gmail_conn.get("provider_user_id") if gmail_conn else None,
        }

        custom_mcp_servers = []
        for p, c in active_providers.items():
            if p.startswith("mcp:"):
                custom_mcp_servers.append({
                    "url": p.replace("mcp:", "", 1),
                    "connected": c.get("connected", True),
                })

        return {
            "github": github,
            "jira": jira,
            "outlook": outlook,
            "calendar": calendar,
            "slack": slack,
            "salesforce": salesforce,
            "notion": notion,
            "gmail": gmail,
            "custom_mcp_servers": custom_mcp_servers,
        }

    @staticmethod
    def connect_github(
        code: str, user_key: str, supabase_jwt: str | None = None
    ):
        session = github_oauth.process_github_callback(code, user_key)
        res = MCPConnectionStore.set("github", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("github", user_key, supabase_jwt)
        return res

    @staticmethod
    def get_oauth_login_url(provider: str, state: str):
        if provider == "github":
            return github_oauth.get_github_login_url(state)
        return oauth_providers.build_login_url(provider, state)

    @staticmethod
    def connect_oauth_provider(
        provider: str, code: str, user_key: str, supabase_jwt: str | None = None
    ):
        if provider == "github":
            return MCPManager.connect_github(code, user_key, supabase_jwt)

        session = oauth_providers.exchange_callback(provider, code)
        res = MCPConnectionStore.set(provider, user_key, session, supabase_jwt)
        MCPManager.register_provider_tools(provider, user_key, supabase_jwt)
        return res

    @staticmethod
    def get_github_connection(user_key: str, supabase_jwt: str | None = None):
        session = MCPConnectionStore.get("github", user_key, supabase_jwt)
        if not session or not session.get("connected", False):
            return {
                "connected": False,
                "username": None,
            }

        return {
            "connected": True,
            "username": session.get("username") or session.get("provider_user_id"),
        }

    @staticmethod
    def get_github_session(user_key: str, supabase_jwt: str | None = None):
        return MCPConnectionStore.get("github", user_key, supabase_jwt) or {
            "connected": False,
            "username": None,
        }

    @staticmethod
    def get_jira_session(user_key: str, supabase_jwt: str | None = None):
        return MCPConnectionStore.get("jira", user_key, supabase_jwt) or {
            "connected": False,
            "email": None,
            "domain": None,
        }

    @staticmethod
    def get_jira_connection(user_key: str, supabase_jwt: str | None = None):
        session = MCPManager.get_jira_session(user_key, supabase_jwt)
        if not session.get("connected"):
            return {
                "connected": False,
                "email": None,
                "domain": None,
            }

        return {
            "connected": True,
            "email": session.get("email"),
            "domain": session.get("domain"),
        }

    @staticmethod
    def connect_jira(
        email: str,
        domain: str,
        api_token: str,
        user_key: str,
        supabase_jwt: str | None = None,
    ):
        session = jira_connector.verify_and_connect(
            email=email,
            domain=domain,
            api_token=api_token,
            user_key=user_key,
        )

        res = MCPConnectionStore.set("jira", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("jira", user_key, supabase_jwt)
        return res

    @staticmethod
    def get_github_login_url(user_key: str):
        return github_oauth.get_github_login_url(user_key)

    @staticmethod
    def get_jira_tickets(user_key: str, supabase_jwt: str | None = None):
        session = MCPManager.get_jira_session(user_key, supabase_jwt)

        if not session or not session.get("connected"):
            return []

        return jira_connector.fetch_tickets(
            email=session["email"],
            domain=session["domain"],
            token=session["token"],
            account_id=session.get("account_id"),
            display_name=session.get("display_name"),
        )

    # Slack connection methods
    @staticmethod
    def get_slack_session(user_key: str, supabase_jwt: str | None = None):
        return MCPConnectionStore.get("slack", user_key, supabase_jwt) or {
            "connected": False,
            "email": None,
        }

    @staticmethod
    def get_slack_connection(user_key: str, supabase_jwt: str | None = None):
        session = MCPManager.get_slack_session(user_key, supabase_jwt)
        if not session.get("connected"):
            return {
                "connected": False,
                "email": None,
            }
        return {
            "connected": True,
            "email": session.get("email") or session.get("provider_user_id"),
        }

    @staticmethod
    def connect_slack(
        token: str, user_key: str, supabase_jwt: str | None = None
    ):
        session = slack_connector.verify_and_connect(token)
        res = MCPConnectionStore.set("slack", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("slack", user_key, supabase_jwt)
        return res

    # Salesforce connection methods
    @staticmethod
    def get_salesforce_session(user_key: str, supabase_jwt: str | None = None):
        return MCPConnectionStore.get("salesforce", user_key, supabase_jwt) or {
            "connected": False,
            "email": None,
            "instance_url": None,
        }

    @staticmethod
    def get_salesforce_connection(user_key: str, supabase_jwt: str | None = None):
        session = MCPManager.get_salesforce_session(user_key, supabase_jwt)
        if not session.get("connected"):
            return {
                "connected": False,
                "email": None,
                "instance_url": None,
            }
        return {
            "connected": True,
            "email": session.get("email"),
            "instance_url": session.get("instance_url"),
        }

    @staticmethod
    def connect_salesforce(
        access_token: str,
        instance_url: str,
        user_key: str,
        supabase_jwt: str | None = None,
    ):
        session = salesforce_connector.verify_and_connect(access_token, instance_url)
        res = MCPConnectionStore.set("salesforce", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("salesforce", user_key, supabase_jwt)
        return res

    # Notion token connection
    @staticmethod
    def connect_notion(
        email: str,
        token: str,
        user_key: str,
        supabase_jwt: str | None = None,
    ):
        from app.mcp import notion_connector
        notion_connector.fetch_recent_pages(token, limit=1)
        session = {
            "connected": True,
            "email": email,
            "access_token": token,
            "provider_user_id": email,
        }
        res = MCPConnectionStore.set("notion", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("notion", user_key, supabase_jwt)
        return res

    # Gmail token connection
    @staticmethod
    def connect_gmail(
        email: str,
        token: str,
        user_key: str,
        supabase_jwt: str | None = None,
    ):
        from app.mcp import gmail_connector
        gmail_connector.fetch_unread_messages(token, limit=1)
        session = {
            "connected": True,
            "email": email,
            "access_token": token,
            "provider_user_id": email,
        }
        res = MCPConnectionStore.set("gmail", user_key, session, supabase_jwt)
        MCPManager.register_provider_tools("gmail", user_key, supabase_jwt)
        return res

    # Custom MCP Server connection
    @staticmethod
    def connect_custom_mcp(
        url: str,
        token: str | None,
        user_key: str,
        supabase_jwt: str | None = None,
    ):
        # 1. Discover tools (validates endpoint compatibility)
        tools = custom_mcp_connector.discover_tools(url, token)

        # 2. Save connection in store under unique provider name
        provider_name = f"mcp:{url}"
        session = {
            "connected": True,
            "access_token": url,
            "refresh_token": token,
            "provider_user_id": url,
        }
        MCPConnectionStore.set(provider_name, user_key, session, supabase_jwt)

        # 3. Register discovered tools
        MCPToolRegistry.register_tools(provider_name, user_key, tools, supabase_jwt)

        return {
            "connected": True,
            "tools": tools,
        }

    @staticmethod
    def disconnect_provider(
        provider: str, user_key: str, supabase_jwt: str | None = None
    ) -> bool:
        # Clear tools in Tool Registry as well
        MCPToolRegistry.clear_tools(provider, user_key, supabase_jwt)

        db_success = False
        if supabase_jwt:
            db_success = MCPConnectionStore.disconnect_in_db(provider, supabase_jwt)
            if db_success:
                return True
            else:
                print(f"Database disconnect failed for provider {provider}. Falling back to local store.")

        # Fallback local store disconnect: set connected=False
        session = MCPConnectionStore.get(provider, user_key) or {}
        session["connected"] = False
        session["access_token"] = None
        session["token"] = None
        MCPConnectionStore.set(provider, user_key, session)
        return True

    @staticmethod
    def _execute_tool_inner(
        provider: str,
        tool_name: str,
        arguments: dict,
        user_key: str,
        graph_jwt: str | None = None,
        supabase_jwt: str | None = None,
    ):
        # 1. Custom MCP execution
        if provider.startswith("mcp:"):
            url = provider.replace("mcp:", "", 1)
            conn = MCPConnectionStore.get(provider, user_key, supabase_jwt)
            token = conn.get("refresh_token") if conn else None
            from app.mcp import custom_mcp_connector
            return custom_mcp_connector.execute_tool(url, tool_name, arguments, token)

        # 2. Built-in execution
        # Jira
        if provider == "jira" and tool_name == "get_jira_tickets":
            return MCPManager.get_jira_tickets(user_key, supabase_jwt)

        # GitHub
        if provider == "github":
            session = MCPConnectionStore.get("github", user_key, supabase_jwt)
            token = session.get("access_token") if session else None
            if not token:
                raise Exception("GitHub not connected")
            if tool_name == "get_github_issues":
                from app.mcp.github import github_connector
                return github_connector.fetch_assigned_issues(token)
            elif tool_name == "get_github_prs":
                from app.mcp.github import github_connector
                return github_connector.fetch_pull_requests(token)
            elif tool_name == "get_github_reviews":
                from app.mcp.github import github_connector
                return github_connector.fetch_pending_reviews(token)
            elif tool_name == "get_github_repositories":
                from app.mcp.github import github_connector
                return github_connector.fetch_repositories(token)

        # Slack
        if provider == "slack" and tool_name == "get_slack_mentions":
            session = MCPConnectionStore.get("slack", user_key, supabase_jwt)
            token = session.get("access_token") if session else None
            if not token:
                raise Exception("Slack not connected")
            from app.mcp.slack import slack_connector
            return slack_connector.fetch_mentions(token)

        # Salesforce
        if provider == "salesforce" and tool_name == "get_salesforce_opportunities":
            session = MCPConnectionStore.get("salesforce", user_key, supabase_jwt)
            token = session.get("access_token") if session else None
            instance = session.get("refresh_token") if session else None
            if not token or not instance:
                raise Exception("Salesforce not connected")
            from app.mcp.salesforce import salesforce_connector
            opps = salesforce_connector.fetch_opportunities(token, instance)
            leads = salesforce_connector.fetch_leads(token, instance)
            return {"opportunities": opps, "leads": leads}

        # Outlook
        if provider == "outlook" and tool_name == "get_outlook_emails":
            if not graph_jwt:
                raise Exception("Graph JWT missing for Outlook")
            from app.mcp.outlook import outlook_connector
            unread = outlook_connector.fetch_unread_important_emails(graph_jwt)
            flagged = outlook_connector.fetch_flagged_emails(graph_jwt)
            action = outlook_connector.fetch_action_required_emails(graph_jwt)
            return {"unread_important": unread, "flagged": flagged, "action_required": action}

        # Calendar
        if provider == "calendar" and tool_name == "get_calendar_events":
            if not graph_jwt:
                raise Exception("Graph JWT missing for Calendar")
            from app.mcp.calendar import calendar_connector
            upcoming = calendar_connector.fetch_upcoming_meetings(graph_jwt)
            deadlines = calendar_connector.fetch_deadlines(graph_jwt)
            return {"upcoming_meetings": upcoming, "deadlines": deadlines}

        # Notion
        if provider == "notion":
            session = MCPConnectionStore.get("notion", user_key, supabase_jwt)
            token = session.get("access_token") if session else None
            if not token:
                raise Exception("Notion not connected")
            from app.mcp import notion_connector
            return notion_connector.fetch_recent_pages(token)

        # Gmail
        if provider == "gmail":
            session = MCPConnectionStore.get("gmail", user_key, supabase_jwt)
            token = session.get("access_token") if session else None
            if not token:
                raise Exception("Gmail not connected")
            from app.mcp import gmail_connector
            return gmail_connector.fetch_unread_messages(token)

        raise Exception(f"Tool {tool_name} for provider {provider} not found.")

    @staticmethod
    def execute_tool(
        provider: str,
        tool_name: str,
        arguments: dict,
        user_key: str,
        graph_jwt: str | None = None,
        supabase_jwt: str | None = None,
    ):
        import json
        print(f"\n--- [DEBUG] MCPManager.execute_tool START ---")
        print(f"Provider: {provider} | Tool: {tool_name}")
        print(f"Arguments: {arguments}")
        try:
            res = MCPManager._execute_tool_inner(provider, tool_name, arguments, user_key, graph_jwt, supabase_jwt)
            try:
                res_str = json.dumps(res)[:1000]
            except Exception:
                res_str = str(res)[:1000]
            print(f"Result (truncated): {res_str}")
            print(f"--- [DEBUG] MCPManager.execute_tool END ---\n")
            return res
        except Exception as e:
            print(f"ERROR in execute_tool: {e}")
            print(f"--- [DEBUG] MCPManager.execute_tool END ---\n")
            raise
