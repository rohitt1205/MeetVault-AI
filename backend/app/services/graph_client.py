import os
from urllib.parse import quote

import requests
from dotenv import load_dotenv
from fastapi import HTTPException

load_dotenv()

GRAPH_BASE_URL = os.getenv("GRAPH_BASE_URL", "https://graph.microsoft.com/v1.0")
GRAPH_TIMEOUT_SECONDS = int(os.getenv("GRAPH_TIMEOUT_SECONDS", "30"))


class GraphClient:
    """Small Microsoft Graph REST client using the user's delegated token."""

    @staticmethod
    def _headers(access_token: str, extra_headers: dict | None = None) -> dict:
        headers = {
            "Authorization": f"Bearer {access_token}",
            "Accept": "application/json",
        }

        if extra_headers:
            headers.update(extra_headers)

        return headers

    @staticmethod
    def _url(endpoint: str) -> str:
        if endpoint.startswith("https://"):
            return endpoint

        return f"{GRAPH_BASE_URL}{endpoint}"

    @staticmethod
    def _request(
        method: str,
        endpoint: str,
        access_token: str,
        *,
        params: dict | None = None,
        json: dict | None = None,
        extra_headers: dict | None = None,
    ) -> requests.Response:
        try:
            response = requests.request(
                method=method,
                url=GraphClient._url(endpoint),
                headers=GraphClient._headers(access_token, extra_headers),
                params=params,
                json=json,
                timeout=GRAPH_TIMEOUT_SECONDS,
            )
        except requests.exceptions.RequestException as exc:
            raise HTTPException(status_code=502, detail=f"Graph request failed: {exc}") from exc

        if response.status_code >= 400:
            raise HTTPException(
                status_code=response.status_code,
                detail={
                    "message": "Microsoft Graph returned an error",
                    "endpoint": endpoint,
                    "response": response.text,
                },
            )

        return response

    @staticmethod
    def get(endpoint: str, access_token: str, params: dict | None = None) -> dict:
        response = GraphClient._request(
            "GET",
            endpoint,
            access_token,
            params=params,
        )

        if not response.content:
            return {}

        return response.json()

    @staticmethod
    def get_text(
        endpoint: str,
        access_token: str,
        params: dict | None = None,
        accept: str = "text/plain",
    ) -> str:
        response = GraphClient._request(
            "GET",
            endpoint,
            access_token,
            params=params,
            extra_headers={"Accept": accept},
        )

        return response.text

    @staticmethod
    def get_bytes(
        endpoint: str,
        access_token: str,
        params: dict | None = None,
        accept: str = "application/octet-stream",
    ) -> bytes:
        response = GraphClient._request(
            "GET",
            endpoint,
            access_token,
            params=params,
            extra_headers={"Accept": accept},
        )

        return response.content

    @staticmethod
    def post(endpoint: str, access_token: str, payload: dict) -> dict:
        response = GraphClient._request(
            "POST",
            endpoint,
            access_token,
            json=payload,
            extra_headers={"Content-Type": "application/json"},
        )

        if not response.content:
            return {}

        return response.json()

    @staticmethod
    def get_collection(endpoint: str, access_token: str, params: dict | None = None) -> list:
        items = []
        next_endpoint = endpoint
        next_params = params

        while next_endpoint:
            response = GraphClient.get(
                endpoint=next_endpoint,
                access_token=access_token,
                params=next_params,
            )
            items.extend(response.get("value", []))
            next_endpoint = response.get("@odata.nextLink")
            next_params = None

        return items

    @staticmethod
    def quote(value: str) -> str:
        return quote(value, safe="")
