from app.services.token_diagnostics_service import TokenDiagnosticsService


def get_outlook_status(user_key: str = "demo", access_token: str | None = None):
    diagnostics = TokenDiagnosticsService.inspect(access_token or "") if access_token else {}
    is_connected = bool(diagnostics.get("is_graph_token"))
    email = (
        diagnostics.get("user_principal_name")
        or (user_key if user_key != "demo" else None)
    )

    return {
        "connected": is_connected,
        "provider": "microsoft",
        "email": email,
        "scopes": diagnostics.get("scopes", []),
    }
