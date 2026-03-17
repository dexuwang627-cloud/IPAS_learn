"""
FastAPI 主應用
"""
from dotenv import load_dotenv
load_dotenv()

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from contextlib import asynccontextmanager
import os

from database import init_db, migrate_add_explanation, migrate_add_multichoice_scenario
from services.embedding_service import init_chroma
from routers import questions, quiz, generate


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_add_explanation()
    migrate_add_multichoice_scenario()
    init_chroma()
    yield


app = FastAPI(title="iPAS 題庫系統", version="1.0.0", lifespan=lifespan)

app.include_router(questions.router, prefix="/api")
app.include_router(quiz.router, prefix="/api")
app.include_router(generate.router, prefix="/api")

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))
