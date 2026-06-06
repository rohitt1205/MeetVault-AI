import requests
from fastapi import HTTPException


def verify_and_connect(access_token: str, instance_url: str) -> dict:
    """Verifies Salesforce access token by fetching user info."""
    clean_url = instance_url.strip().rstrip("/")

    url = f"{clean_url}/services/oauth2/userinfo"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    try:
        response = requests.get(url, headers=headers, timeout=15)
        if not response.ok:
            raise HTTPException(
                status_code=401,
                detail=f"Salesforce verification failed: {response.text}",
            )
        data = response.json()
        name = data.get("name") or "Salesforce User"
        email = data.get("email") or data.get("preferred_username")
        if not email:
            raise HTTPException(
                status_code=502,
                detail="Salesforce verification response missing user email.",
            )
        return {
            "connected": True,
            "display_name": name,
            "email": email,
            "instance_url": clean_url,
            "access_token": access_token,
            "refresh_token": clean_url,
            "provider_user_id": email or data.get("sub"),
        }
    except requests.RequestException as exc:
        raise HTTPException(
            status_code=502,
            detail=f"Salesforce authentication failed: {exc}",
        ) from exc


def fetch_opportunities(access_token: str, instance_url: str, limit: int = 5) -> list[dict]:
    """Queries open opportunities from Salesforce via SOQL."""
    clean_url = instance_url.strip().rstrip("/")
    soql = (
        "SELECT Name, Amount, StageName, CloseDate "
        "FROM Opportunity "
        "WHERE IsClosed = false "
        "ORDER BY LastModifiedDate DESC "
        f"LIMIT {limit}"
    )
    url = f"{clean_url}/services/data/v58.0/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    params = {"q": soql}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if not response.ok:
            return []
        data = response.json()
        records = data.get("records", [])
        return [
            {
                "name": rec.get("Name"),
                "amount": rec.get("Amount"),
                "stage": rec.get("StageName"),
                "close_date": rec.get("CloseDate"),
            }
            for rec in records
        ]
    except Exception as e:
        print(f"Error fetching Salesforce opportunities: {e}")
        return []


def fetch_leads(access_token: str, instance_url: str, limit: int = 5) -> list[dict]:
    """Queries open/recent leads from Salesforce via SOQL."""
    clean_url = instance_url.strip().rstrip("/")
    soql = (
        "SELECT Name, Company, Status "
        "FROM Lead "
        "WHERE IsConverted = false "
        "ORDER BY LastModifiedDate DESC "
        f"LIMIT {limit}"
    )
    url = f"{clean_url}/services/data/v58.0/query"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json",
    }
    params = {"q": soql}
    try:
        response = requests.get(url, headers=headers, params=params, timeout=15)
        if not response.ok:
            return []
        data = response.json()
        records = data.get("records", [])
        return [
            {
                "name": rec.get("Name"),
                "company": rec.get("Company"),
                "status": rec.get("Status"),
            }
            for rec in records
        ]
    except Exception as e:
        print(f"Error fetching Salesforce leads: {e}")
        return []
