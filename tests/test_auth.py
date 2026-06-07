"""End-to-end auth tests."""

from __future__ import annotations


def test_health(client):
    r = client.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True
    assert body["service"] == "agent-platform"


def test_register_login_me_flow(client):
    # Register
    r = client.post("/api/auth/register", json={
        "email": "alice@example.com",
        "password": "secret123",
        "name": "Alice",
    })
    assert r.status_code == 201, r.text
    body = r.json()
    assert "token" in body
    assert body["user"]["email"] == "alice@example.com"
    assert body["user"]["name"] == "Alice"
    assert body["user"]["id"].startswith("usr_")
    token = body["token"]

    # Me with token
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert r.status_code == 200
    assert r.json()["email"] == "alice@example.com"

    # Login again — same token if same second; just verify it works
    r = client.post("/api/auth/login", json={
        "email": "alice@example.com",
        "password": "secret123",
    })
    assert r.status_code == 200
    new_token = r.json()["token"]
    # The new token should be usable (re-auth path works)
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {new_token}"})
    assert r.status_code == 200

    # Login with wrong password
    r = client.post("/api/auth/login", json={
        "email": "alice@example.com",
        "password": "wrong",
    })
    assert r.status_code == 401


def test_register_duplicate_email(client):
    payload = {"email": "bob@example.com", "password": "secret123", "name": "Bob"}
    r1 = client.post("/api/auth/register", json=payload)
    assert r1.status_code == 201
    r2 = client.post("/api/auth/register", json=payload)
    assert r2.status_code == 409
    assert "already" in r2.json()["detail"].lower()


def test_register_validation(client):
    # Bad email — custom regex validator returns 400
    r = client.post("/api/auth/register", json={
        "email": "totally bogus", "password": "secret123", "name": "X"
    })
    assert r.status_code == 400
    assert "email" in r.json()["detail"].lower()

    # Short password — pydantic Field(min_length=6) returns 422
    r = client.post("/api/auth/register", json={
        "email": "ok@example.com", "password": "123", "name": "X"
    })
    assert r.status_code == 422

    # Missing field — pydantic returns 422
    r = client.post("/api/auth/register", json={
        "email": "ok@example.com", "password": "secret123",
    })
    assert r.status_code == 422


def test_me_requires_token(client):
    r = client.get("/api/auth/me")
    assert r.status_code == 401

    r = client.get("/api/auth/me", headers={"Authorization": "Bearer not-a-real-token"})
    assert r.status_code == 401

    r = client.get("/api/auth/me", headers={"Authorization": "Basic xxx"})
    assert r.status_code == 401


def test_user_isolation(client):
    """Two users can register; each sees only their own data via /me."""
    # Alice
    r1 = client.post("/api/auth/register", json={
        "email": "alice@example.com", "password": "secret123", "name": "Alice"
    })
    token_alice = r1.json()["token"]
    user_alice = r1.json()["user"]

    # Bob
    r2 = client.post("/api/auth/register", json={
        "email": "bob@example.com", "password": "secret123", "name": "Bob"
    })
    token_bob = r2.json()["token"]
    user_bob = r2.json()["user"]

    assert user_alice["id"] != user_bob["id"]

    # Each sees their own profile
    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_alice}"})
    assert r.json()["id"] == user_alice["id"]

    r = client.get("/api/auth/me", headers={"Authorization": f"Bearer {token_bob}"})
    assert r.json()["id"] == user_bob["id"]
