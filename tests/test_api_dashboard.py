"""API endpoint tests for learning dashboard."""
import pytest


@pytest.fixture(autouse=True)
def _make_test_user_pro():
    """Dashboard chart endpoints require Pro tier, so add test user via invite."""
    import database_invite
    database_invite.migrate_add_invite_tables()
    inv = database_invite.create_invite(duration_days=30, max_uses=10, created_by="admin")
    database_invite.redeem_invite(inv["code"], "test-user-00000000-0000-0000-0000-000000000001")


def _build_history(client, auth_headers):
    """Do a quiz to generate history data."""
    res = client.post("/api/v1/quiz", json={
        "num_choice": 2, "num_tf": 1, "num_multichoice": 0,
        "num_scenario": 0,
    }, headers=auth_headers)
    data = res.json()
    answers = {}
    for i, q in enumerate(data["questions"]):
        # Alternate right/wrong to get mixed accuracy
        answers[str(q["id"])] = q.get("answer", "A") if i % 2 == 0 else "Z"
    client.post("/api/v1/quiz/check", json={
        "session_id": data["session_id"],
        "answers": answers,
    }, headers=auth_headers)


def test_accuracy_trend_empty(client, populated_db, auth_headers):
    res = client.get("/api/v1/dashboard/accuracy-trend", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["granularity"] == "day"
    assert data["data"] == []


def test_accuracy_trend_with_history(client, populated_db, auth_headers):
    _build_history(client, auth_headers)
    res = client.get("/api/v1/dashboard/accuracy-trend", headers=auth_headers)
    data = res.json()
    assert len(data["data"]) >= 1
    point = data["data"][0]
    assert "date" in point
    assert "total" in point
    assert "correct" in point
    assert "accuracy" in point


def test_accuracy_trend_weekly(client, populated_db, auth_headers):
    _build_history(client, auth_headers)
    res = client.get(
        "/api/v1/dashboard/accuracy-trend?granularity=week",
        headers=auth_headers,
    )
    data = res.json()
    assert data["granularity"] == "week"
    if data["data"]:
        assert "W" in data["data"][0]["date"]


def test_volume_endpoint(client, populated_db, auth_headers):
    _build_history(client, auth_headers)
    res = client.get("/api/v1/dashboard/volume", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["data"]) >= 1
    assert "date" in data["data"][0]
    assert "count" in data["data"][0]


def test_chapter_accuracy(client, populated_db, auth_headers):
    _build_history(client, auth_headers)
    res = client.get("/api/v1/dashboard/chapter-accuracy", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert len(data["data"]) >= 1
    ch = data["data"][0]
    assert "chapter" in ch
    assert "total" in ch
    assert "accuracy" in ch


def test_summary_endpoint(client, populated_db, auth_headers):
    _build_history(client, auth_headers)
    res = client.get("/api/v1/dashboard/summary", headers=auth_headers)
    assert res.status_code == 200
    data = res.json()
    assert data["total_answered"] >= 1
    assert "overall_accuracy" in data
    assert "current_streak" in data
    assert "best_streak" in data
    assert "total_days_active" in data
    assert "wrong_notebook_count" in data
    assert "bookmarked_count" in data


def test_dashboard_requires_auth(client):
    res = client.get("/api/v1/dashboard/summary")
    assert res.status_code in (401, 422)


def test_granularity_validation(client, auth_headers):
    res = client.get(
        "/api/v1/dashboard/accuracy-trend?granularity=invalid",
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_days_validation(client, auth_headers):
    res = client.get(
        "/api/v1/dashboard/volume?days=999",
        headers=auth_headers,
    )
    assert res.status_code == 422
