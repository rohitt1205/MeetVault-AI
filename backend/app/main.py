import os
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.graph_routes import router as graph_router
from app.api.mcp_routes import router as mcp_router
from app.rag.router import router as rag_router
from app.workers.poller import WorkspaceSyncPoller

load_dotenv(Path(__file__).resolve().parents[2] / ".env")
load_dotenv()

app = FastAPI()

frontend_origin = os.getenv("FRONTEND_ORIGIN", "http://127.0.0.1:5173")
additional_origins = {
    origin.strip()
    for origin in os.getenv("FRONTEND_ORIGINS", "").split(",")
    if origin.strip()
}
allowed_origins = {
    frontend_origin,
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:4173",
    "http://127.0.0.1:4173",
    *additional_origins,
}

app.add_middleware(
    CORSMiddleware,
    allow_origins=sorted(allowed_origins),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/")
def home():
    return {"message": "MeetVault AI Backend Running"}


@app.on_event("startup")
def start_background_workers():
    WorkspaceSyncPoller.start()


@app.on_event("shutdown")
def stop_background_workers():
    WorkspaceSyncPoller.stop()


app.include_router(graph_router)
app.include_router(rag_router)
app.include_router(mcp_router)
