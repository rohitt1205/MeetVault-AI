# Outlook connector linked to active user context
def get_outlook_status(user_key: str = "demo"):
    is_connected = user_key != "demo"
    return {
        "connected": True,
        "provider": "microsoft",
        "email": user_key if is_connected else "demo@microsoft.com"
    }
