import base64
import json
import os
from typing import Any


REQUIRED_GRAPH_SCOPES = (
    "Calendars.Read",
    "Files.Read",
    "OnlineMeetings.Read",
    "OnlineMeetingTranscript.Read.All",
)
GRAPH_AUDIENCES = {
    "00000003-0000-0000-c000-000000000000",
    "https://graph.microsoft.com",
}


class TokenDiagnosticsService:
    @staticmethod
    def _decode_segment(segment: str) -> dict[str, Any]:
        padding = "=" * (-len(segment) % 4)
        decoded = base64.urlsafe_b64decode(f"{segment}{padding}")
        return json.loads(decoded.decode("utf-8"))

    @staticmethod
    def inspect(access_token: str) -> dict[str, Any]:
        parts = access_token.split(".")
        if len(parts) < 2:
            return {
                "valid_jwt": False,
                "scopes": [],
                "missing_scopes": list(REQUIRED_GRAPH_SCOPES),
            }

        try:
            claims = TokenDiagnosticsService._decode_segment(parts[1])
        except (ValueError, json.JSONDecodeError):
            return {
                "valid_jwt": False,
                "scopes": [],
                "missing_scopes": list(REQUIRED_GRAPH_SCOPES),
            }

        scope_claim = claims.get("scp") or ""
        scopes = sorted({scope for scope in scope_claim.split() if scope})
        missing_scopes = [
            scope
            for scope in REQUIRED_GRAPH_SCOPES
            if scope not in scopes
        ]
        backend_app_configured = all(
            os.getenv(key)
            for key in ("MS_CLIENT_ID", "MS_CLIENT_SECRET", "MS_TENANT_ID")
        )
        audience = claims.get("aud")
        is_graph_token = audience in GRAPH_AUDIENCES

        return {
            "valid_jwt": True,
            "audience": audience,
            "tenant_id": claims.get("tid"),
            "user_principal_name": claims.get("upn") or claims.get("unique_name"),
            "scopes": scopes,
            "missing_scopes": missing_scopes,
            "is_graph_token": is_graph_token,
            "can_fetch_meetings": is_graph_token and "Calendars.Read" in scopes,
            "can_fetch_files": is_graph_token and "Files.Read" in scopes,
            "can_fetch_online_meetings": is_graph_token and "OnlineMeetings.Read" in scopes,
            "can_auto_sync": (
                is_graph_token
                and
                "Calendars.Read" in scopes
                and "Files.Read" in scopes
            ),
            "backend_app_configured": backend_app_configured,
        }
