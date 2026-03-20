"""API endpoint tests for question search."""


def test_search_basic(client, populated_db, auth_headers):
    res = client.get(
        "/api/v1/questions/search?q=greenhouse",
        headers=auth_headers,
    )
    assert res.status_code == 200
    data = res.json()
    assert "questions" in data
    assert "total" in data
    assert data["total"] >= 1
    assert data["query"] == "greenhouse"


def test_search_no_answers_for_regular_user(client, populated_db, auth_headers):
    """Regular users should not see answers or explanations."""
    res = client.get(
        "/api/v1/questions/search?q=CO2",
        headers=auth_headers,
    )
    data = res.json()
    for q in data["questions"]:
        assert "answer" not in q
        assert "explanation" not in q


def test_search_admin_sees_answers(client, populated_db, admin_headers):
    """Admin users should see answers and explanations."""
    res = client.get(
        "/api/v1/questions/search?q=CO2",
        headers=admin_headers,
    )
    data = res.json()
    assert data["total"] >= 1
    # Admin should see full question data
    has_answer = any("answer" in q for q in data["questions"])
    assert has_answer


def test_search_no_results(client, populated_db, auth_headers):
    res = client.get(
        "/api/v1/questions/search?q=xyznonexistent",
        headers=auth_headers,
    )
    data = res.json()
    assert data["total"] == 0
    assert data["questions"] == []


def test_search_pagination(client, populated_db, auth_headers):
    res = client.get(
        "/api/v1/questions/search?q=CO2&limit=1&offset=0",
        headers=auth_headers,
    )
    data = res.json()
    assert len(data["questions"]) <= 1


def test_search_requires_query(client, auth_headers):
    """Missing query param should fail validation."""
    res = client.get("/api/v1/questions/search", headers=auth_headers)
    assert res.status_code == 422


def test_search_min_length(client, auth_headers):
    """Query too short should fail validation."""
    res = client.get(
        "/api/v1/questions/search?q=x",
        headers=auth_headers,
    )
    assert res.status_code == 422


def test_search_no_auth(client, populated_db):
    """Search should work without auth but strip answers."""
    res = client.get("/api/v1/questions/search?q=greenhouse")
    assert res.status_code == 200
    data = res.json()
    for q in data["questions"]:
        assert "answer" not in q
        assert "explanation" not in q
