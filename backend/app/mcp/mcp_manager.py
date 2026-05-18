from app.mcp.github import github_oauth
from app.mcp.jira import jira_connector
from app.mcp.outlook import outlook_connector
from app.mcp.connection_store import MCPConnectionStore


class MCPManager:
    @staticmethod
    def get_all_connections(user_key: str, access_token: str | None = None):
        github = MCPManager.get_github_connection(user_key)
        jira = MCPManager.get_jira_connection(user_key)
        outlook = outlook_connector.get_outlook_status(user_key, access_token)

        return {
            "github": github,
            "jira": jira,
            "outlook": outlook,
        }

    @staticmethod
    def connect_github(code: str, user_key: str):
        session = github_oauth.process_github_callback(code, user_key)
        return MCPConnectionStore.set("github", user_key, session)

    @staticmethod
    def get_github_connection(user_key: str):
        session = MCPConnectionStore.get("github", user_key)
        if not session:
            return {
                "connected": False,
                "username": None,
            }

        return {
            key: value
            for key, value in session.items()
            if key != "access_token"
        } | {
            "connected": True,
        }

    @staticmethod
    def get_github_session(user_key: str):
        return MCPConnectionStore.get("github", user_key) or {
            "connected": False,
            "username": None,
        }

    @staticmethod
    def get_jira_session(user_key: str):
        return MCPConnectionStore.get("jira", user_key) or {
            "connected": False,
            "email": None,
            "domain": None,
        }

    @staticmethod
    def get_jira_connection(user_key: str):
        session = MCPManager.get_jira_session(user_key)
        if not session.get("connected"):
            return session

        return {
            key: value
            for key, value in session.items()
            if key != "token"
        }

    @staticmethod
    def get_disconnected_jira():
        return (
            {
                "connected": False,
                "email": None,
                "domain": None,
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
            user_key=user_key,
        )

        return MCPConnectionStore.set("jira", user_key, session)

    @staticmethod
    def get_github_login_url(user_key: str):
        return github_oauth.get_github_login_url(user_key)

    @staticmethod
    def get_jira_tickets(user_key: str):
        session = MCPManager.get_jira_session(user_key)

        if not session or not session.get("connected"):
            return []

        return jira_connector.fetch_tickets(
            email=session["email"],
            domain=session["domain"],
            token=session["token"]
        )
