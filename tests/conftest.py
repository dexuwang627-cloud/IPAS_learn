"""
Shared test fixtures for iPAS Quiz system.
"""
import os

# Set env vars BEFORE any app imports (needed at collection time for
# modules that read os.environ at import, e.g. services/question_generator.py)
os.environ.setdefault("GEMINI_API_KEY", "test-dummy-key")
os.environ.setdefault("SUPABASE_URL", "")
os.environ.setdefault("SUPABASE_SERVICE_ROLE_KEY", "")
os.environ.setdefault("SUPABASE_JWT_SECRET", "test-jwt-secret-for-testing-only-32chars!")
os.environ.setdefault("SUPABASE_ANON_KEY", "test-anon-key")
os.environ.setdefault("ADMIN_EMAILS", "admin@example.com")
os.environ.setdefault("ENV", "testing")

import time
import tempfile
from unittest.mock import patch

import jwt
import pytest
from fastapi.testclient import TestClient


@pytest.fixture(autouse=True)
def _env_setup(tmp_path):
    """Set up test environment variables and SQLite DB."""
    db_path = str(tmp_path / "test.db")
    patches = {
        "database.SUPABASE_URL": "",
        "database.SUPABASE_KEY": "",
        "database._SQLITE_DB": db_path,
        "database.REST_URL": "",
    }
    env_vars = {
        "SUPABASE_URL": "",
        "SUPABASE_SERVICE_ROLE_KEY": "",
        "SUPABASE_JWT_SECRET": "test-jwt-secret-for-testing-only-32chars!",
        "ADMIN_EMAILS": "admin@example.com",
        "ENV": "testing",
        "SUPABASE_ANON_KEY": "test-anon-key",
        "GEMINI_API_KEY": "test-dummy-key",
    }
    with patch.dict(os.environ, env_vars):
        patchers = [patch(k, v) for k, v in patches.items()]
        for p in patchers:
            p.start()

        # Also patch auth module
        with patch("auth.SUPABASE_JWT_SECRET", "test-jwt-secret-for-testing-only-32chars!"), \
             patch("auth._ADMIN_EMAILS", {"admin@example.com"}):

            import database
            database.init_db()

            yield

        for p in patchers:
            p.stop()


@pytest.fixture
def client():
    """FastAPI TestClient with rate limiter reset."""
    from main import app
    # Walk middleware stack to find and clear rate limiter buckets
    obj = getattr(app, 'middleware_stack', None)
    while obj is not None:
        if hasattr(obj, '_buckets'):
            obj._buckets.clear()
            break
        obj = getattr(obj, 'app', None)
    return TestClient(app)


def _make_token(payload_overrides=None):
    """Create a valid JWT for testing."""
    now = int(time.time())
    payload = {
        "sub": "test-user-00000000-0000-0000-0000-000000000001",
        "email": "test@example.com",
        "aud": "authenticated",
        "role": "authenticated",
        "exp": now + 3600,
        "iat": now,
        "app_metadata": {},
        "user_metadata": {},
    }
    if payload_overrides:
        payload.update(payload_overrides)
    return jwt.encode(payload, "test-jwt-secret-for-testing-only-32chars!", algorithm="HS256")


@pytest.fixture
def auth_headers():
    """Headers with a valid non-admin JWT."""
    token = _make_token()
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


@pytest.fixture
def admin_headers():
    """Headers with a valid admin JWT."""
    token = _make_token({
        "email": "admin@example.com",
        "app_metadata": {"role": "admin"},
    })
    return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


SAMPLE_QUESTIONS = [
    {
        "chapter": "Climate Change",
        "chapter_group": "Climate",
        "source_file": "01.pdf",
        "type": "choice",
        "content": "Which is a greenhouse gas?",
        "option_a": "CO2", "option_b": "N2", "option_c": "O2", "option_d": "Ar",
        "answer": "A", "difficulty": 1,
        "explanation": "CO2 is a major greenhouse gas.",
    },
    {
        "chapter": "Carbon Footprint",
        "chapter_group": "Carbon",
        "source_file": "02.pdf",
        "type": "truefalse",
        "content": "CO2 is a greenhouse gas",
        "option_a": None, "option_b": None, "option_c": None, "option_d": None,
        "answer": "T", "difficulty": 1,
        "explanation": "True, CO2 is indeed a greenhouse gas.",
    },
    {
        "chapter": "Carbon Footprint",
        "chapter_group": "Carbon",
        "source_file": "02.pdf",
        "type": "multichoice",
        "content": "Which are greenhouse gases? (select all)",
        "option_a": "CO2", "option_b": "CH4", "option_c": "N2", "option_d": "O3",
        "answer": "AB", "difficulty": 2,
        "explanation": "CO2 and CH4 are greenhouse gases.",
    },
    {
        "chapter": "Scenario",
        "chapter_group": "Scenario",
        "source_file": "03.pdf",
        "type": "scenario_choice",
        "content": "In this scenario, what should be done?",
        "option_a": "Reduce", "option_b": "Offset", "option_c": "Ignore", "option_d": "Increase",
        "answer": "A", "difficulty": 2,
        "scenario_id": "sc1", "scenario_text": "A factory emits 100 tons CO2 per year.",
        "explanation": "Reduction is the primary strategy.",
    },
    {
        "chapter": "Scenario",
        "chapter_group": "Scenario",
        "source_file": "03.pdf",
        "type": "scenario_multichoice",
        "content": "Which actions help? (select all)",
        "option_a": "Solar", "option_b": "Coal", "option_c": "Wind", "option_d": "Oil",
        "answer": "AC", "difficulty": 3,
        "scenario_id": "sc1", "scenario_text": "A factory emits 100 tons CO2 per year.",
        "explanation": "Solar and wind are renewable.",
    },
]


@pytest.fixture
def sample_questions():
    """Return list of sample question dicts."""
    return SAMPLE_QUESTIONS


@pytest.fixture
def populated_db(sample_questions):
    """Insert sample questions into SQLite and return their IDs."""
    from database import insert_question
    ids = []
    for q in sample_questions:
        qid = insert_question(q)
        ids.append(qid)
    return ids
