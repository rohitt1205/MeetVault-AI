from fastapi import FastAPI
from app.api.graph_routes import router as graph_router

app = FastAPI()


@app.get("/")
def home():
    return {"message": "MeetVault AI Backend Running"}


app.include_router(graph_router)