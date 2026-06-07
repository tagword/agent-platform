"""Agent template listing tests."""

from __future__ import annotations


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_list_agents_default_seeded(client):
    """The default seed template 'data-analysis-report' should be listed."""
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "secret123", "name": "Alice",
    })
    token = r.json()["token"]

    r = client.get("/api/agents", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    ids = [a["id"] for a in body["agents"]]
    assert "data-analysis-report" in ids
    agent = next(a for a in body["agents"] if a["id"] == "data-analysis-report")
    assert agent["name"] == "数据分析报告"
    assert agent["version"] == "v1"
    assert agent["job_id"] == "data-analysis-report"


def test_list_agents_requires_auth(client):
    r = client.get("/api/agents")
    assert r.status_code == 401


def test_get_agent(client):
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "secret123", "name": "Alice",
    })
    token = r.json()["token"]
    r = client.get("/api/agents/data-analysis-report", headers=_auth(token))
    assert r.status_code == 200
    assert r.json()["id"] == "data-analysis-report"


def test_get_agent_404(client):
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "secret123", "name": "Alice",
    })
    token = r.json()["token"]
    r = client.get("/api/agents/nonexistent-agent", headers=_auth(token))
    assert r.status_code == 404
