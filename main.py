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

from database import (
    init_db, migrate_add_explanation, migrate_add_multichoice_scenario,
    migrate_add_bank_id, migrate_add_quiz_history, migrate_add_exam_sessions,
)
from middleware import SecurityHeadersMiddleware, RateLimitMiddleware
from config import IS_PRODUCTION
from routers import questions, quiz
from routers.config_routes import router as config_router
from routers.history import router as history_router
from routers.exam import router as exam_router
from routers.search import router as search_router
from routers.notebook import router as notebook_router
from routers.dashboard import router as dashboard_router
from routers.admin_invite import router as admin_invite_router
from routers.user_invite import router as user_invite_router


@asynccontextmanager
async def lifespan(app: FastAPI):
    init_db()
    migrate_add_explanation()
    migrate_add_multichoice_scenario()
    migrate_add_bank_id()
    migrate_add_quiz_history()
    migrate_add_exam_sessions()
    from database_notebook import migrate_add_wrong_notebook
    migrate_add_wrong_notebook()
    from database_invite import migrate_add_invite_tables
    migrate_add_invite_tables()
    try:
        from services.embedding_service import init_chroma
        init_chroma()
    except Exception as e:
        import logging
        logging.getLogger(__name__).warning("Chroma init skipped: %s", e)
    yield


app = FastAPI(
    title="iPAS 題庫系統",
    version="1.1.0",
    lifespan=lifespan,
    docs_url=None if IS_PRODUCTION else "/docs",
    redoc_url=None if IS_PRODUCTION else "/redoc",
    openapi_url=None if IS_PRODUCTION else "/openapi.json",
)

# Security middleware
app.add_middleware(SecurityHeadersMiddleware)
app.add_middleware(
    RateLimitMiddleware,
    default_rpm=60,
    strict_paths={
        "/api/quiz/pdf": 5,
        "/api/quiz/check": 30,
        "/api/quiz": 20,
        "/api/questions": 30,
        "/api/exam": 10,
        "/api/history": 30,
        "/api/questions/search": 30,
        "/api/notebook": 30,
        "/api/dashboard": 30,
        "/api/invite": 20,
        "/api/me/pro/redeem": 5,
        "/api/me/pro": 30,
    },
)

# v1 routes (primary)
app.include_router(config_router, prefix="/api/v1")
app.include_router(questions.router, prefix="/api/v1")
app.include_router(quiz.router, prefix="/api/v1")
app.include_router(history_router, prefix="/api/v1")
app.include_router(exam_router, prefix="/api/v1")
app.include_router(search_router, prefix="/api/v1")
app.include_router(notebook_router, prefix="/api/v1")
app.include_router(dashboard_router, prefix="/api/v1")
app.include_router(admin_invite_router, prefix="/api/v1")
app.include_router(user_invite_router, prefix="/api/v1")

# Deprecated: mount on /api for backward compat
app.include_router(questions.router, prefix="/api", deprecated=True)
app.include_router(quiz.router, prefix="/api", deprecated=True)

# Optional: generate router (needs google-genai, chromadb)
try:
    from routers import generate
    app.include_router(generate.router, prefix="/api/v1")
    app.include_router(generate.router, prefix="/api", deprecated=True)
except ImportError:
    pass

static_dir = os.path.join(os.path.dirname(__file__), "static")
os.makedirs(static_dir, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.get("/")
async def root():
    return FileResponse(os.path.join(static_dir, "index.html"))


@app.get("/admin")
async def admin_page():
    return FileResponse(os.path.join(static_dir, "admin.html"))
