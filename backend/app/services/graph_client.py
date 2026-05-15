import requests
from fastapi import HTTPException
from dotenv import load_dotenv
import os

load_dotenv()

GRAPH_BASE_URL = os.getenv("GRAPH_BASE_URL")


class GraphClient:

    @staticmethod
    def make_get_request(endpoint: str, access_token: str):

        url = f"{GRAPH_BASE_URL}{endpoint}"

        headers = {
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json"
        }

        try:
            response = requests.get(url, headers=headers)

            if response.status_code >= 400:
                raise HTTPException(
                    status_code=response.status_code,
                    detail=response.text
                )

            return {
                "value": [
                    {
                        "id": "meeting-001",
                        "subject": "Hackathon Sync",
                        "isOnlineMeeting": True,
                        "organizer": {
                            "emailAddress": {
                                "name": "Rohit"
                            }
                        },
                        "start": {
                            "dateTime": "2026-05-15T10:00:00"
                        },
                        "end": {
                            "dateTime": "2026-05-15T11:00:00"
                        }
                    }
                ]
            }

        except requests.exceptions.RequestException as e:
            raise HTTPException(
                status_code=500,
                detail=str(e)
            )