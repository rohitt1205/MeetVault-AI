from app.mcp.github import github_oauth
from app.mcp.jira import jira_connector

github_connections = {}
jira_connections = {}

class MCPManager:
    @staticmethod
    def get_all_connections(user_key: str):
        github = MCPManager.get_github_connection(user_key)
        jira = MCPManager.get_jira_connection(user_key)

        outlook = {
            "connected": True,
            "provider": "microsoft"
        }

        return {
            "github": github,
            "jira": jira,
            "outlook": outlook
        }

    @staticmethod
    def connect_github(code: str, user_key: str):
        session = github_oauth.process_github_callback(code, user_key)
        github_connections[user_key] = session
        return session

    @staticmethod
    def get_github_connection(user_key: str):
        return github_connections.get(
            user_key,
            {
                "connected": False,
                "username": None
            }
        )

    @staticmethod
    def connect_jira(
        email: str,
        domain: str,
        api_token: str,
        user_key: str
    ):
        session = jira_connector.verify_and_connect(
            email=email,
            domain=domain,
            api_token=api_token,
            user_key=user_key
        )

        if session:
            jira_connections[user_key] = session

        return session

    @staticmethod
    def get_jira_connection(user_key: str):
        return jira_connections.get(
            user_key,
            {
                "connected": False,
                "email": None,
                "domain": None
            }
        )

    @staticmethod
    def get_github_login_url(user_key: str):
        return github_oauth.get_github_login_url(user_key)

    @staticmethod
    def get_jira_tickets(user_key: str):
        session = MCPManager.get_jira_connection(user_key)

        if not session or not session.get("connected"):
            return []

        return jira_connector.fetch_tickets(
            email=session["email"],
            domain=session["domain"],
            token=session["token"]
        )
