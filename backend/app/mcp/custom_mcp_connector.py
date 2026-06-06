import requests
from urllib.parse import urljoin
from fastapi import HTTPException

def _headers(token: str | None = None) -> dict:
    h = {"Content-Type": "application/json"}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return h

def _normalize_tools(raw_tools: list) -> list[dict]:
    normalized = []
    for tool in raw_tools:
        if isinstance(tool, dict) and "name" in tool:
            normalized.append({
                "name": tool["name"],
                "description": tool.get("description", ""),
                "parameters": tool.get("inputSchema") or tool.get("parameters") or {
                    "type": "object",
                    "properties": {}
                }
            })
    return normalized

def _find_sse_endpoint(url: str, token: str | None = None) -> str | None:
    """Checks the base URL or /sse endpoint for a Model Context Protocol endpoint redirect."""
    headers = {"Accept": "text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    
    for candidate in [url, url.rstrip("/") + "/sse"]:
        try:
            res = requests.get(candidate, headers=headers, stream=True, timeout=5)
            if res.ok:
                for line in res.iter_lines(decode_unicode=True):
                    if line and line.startswith("event: endpoint"):
                        # Next line should be data:
                        continue
                    if line and line.startswith("data:"):
                        data_val = line.replace("data:", "").strip()
                        if data_val:
                            return urljoin(candidate, data_val)
        except Exception:
            pass
    return None

def discover_tools(url: str, token: str | None = None) -> list[dict]:
    """
    Connects to the Custom MCP Server URL and queries available tools.
    Supports official SSE handshake and fallback direct JSON-RPC HTTP POST.
    """
    headers = _headers(token)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/list",
        "params": {}
    }

    # 1. Try direct HTTP POST JSON-RPC first (simplest)
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=10)
        if res.ok:
            data = res.json()
            if "result" in data and "tools" in data["result"]:
                return _normalize_tools(data["result"]["tools"])
    except Exception:
        pass

    # 2. Try official MCP SSE handshake
    endpoint_url = _find_sse_endpoint(url, token)
    if endpoint_url:
        try:
            res = requests.post(endpoint_url, json=payload, headers=headers, timeout=10)
            if res.ok:
                data = res.json()
                if "result" in data and "tools" in data["result"]:
                    return _normalize_tools(data["result"]["tools"])
        except Exception:
            pass

    # If it fails, raise a helpful connection error
    raise HTTPException(
        status_code=502,
        detail="Could not reach Custom MCP Server or verify compatibility."
    )

def execute_tool(url: str, tool_name: str, arguments: dict, token: str | None = None) -> dict:
    """
    Invokes a tool on the Custom MCP server.
    """
    headers = _headers(token)
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "tools/call",
        "params": {
            "name": tool_name,
            "arguments": arguments or {}
        }
    }

    # 1. Try direct HTTP POST JSON-RPC
    try:
        res = requests.post(url, json=payload, headers=headers, timeout=15)
        if res.ok:
            data = res.json()
            if "result" in data:
                return data["result"]
    except Exception:
        pass

    # 2. Try official MCP SSE execution
    endpoint_url = _find_sse_endpoint(url, token)
    if endpoint_url:
        try:
            res = requests.post(endpoint_url, json=payload, headers=headers, timeout=15)
            if res.ok:
                data = res.json()
                if "result" in data:
                    return data["result"]
        except Exception:
            pass

    raise HTTPException(
        status_code=502,
        detail=f"Failed to execute tool '{tool_name}' on the Custom MCP Server."
    )
