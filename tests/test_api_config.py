"""API endpoint tests for config router."""


def test_get_config(client):
    res = client.get("/api/v1/config")
    assert res.status_code == 200
    data = res.json()
    assert "supabase_url" in data
    assert "supabase_key" in data
    assert data["api_version"] == "v1"


def test_config_no_auth_required(client):
    """Config endpoint should work without any auth header."""
    res = client.get("/api/v1/config")
    assert res.status_code == 200


def test_config_no_service_role_key(client):
    """Config must NOT expose the service role key."""
    res = client.get("/api/v1/config")
    data = res.json()
    # The service role key should not appear anywhere in the response
    response_str = str(data)
    assert "service_role" not in response_str.lower()
