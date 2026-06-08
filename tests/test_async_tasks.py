"""Async task route tests — POST /api/tasks queues, GET polls.

Mocks TaskAgent via the same monkeypatch trick as test_tasks.py.
"""

from __future__ import annotations

import asyncio
import io
import time
from typing import Any

import pytest


class FakeAsyncTaskAgent:
    def __init__(self, delay: float = 0.1, status: str = "ok", error: str | None = None):
        self.delay = delay
        self.status = status
        self.error = error
        self.calls: list[dict] = []

    async def __call__(self, *, job_id, raw_data, user_instructions="", file_meta=None):
        self.calls.append({
            "job_id": job_id, "raw_data": raw_data,
            "user_instructions": user_instructions, "file_meta": file_meta,
        })
        await asyncio.sleep(self.delay)
        reply = "" if self.status != "ok" else "# Async Report\n\nGenerated asynchronously."
        return {
            "status": self.status,
            "reply": reply,
            "tools_used": [],
            "error": self.error,
            "duration_ms": int(self.delay * 1000),
            "usage": {"prompt_tokens": 10, "completion_tokens": 5, "total_tokens": 15},
            "session_id": "task-async",
            "task_id": "tsk_async_1234",
        }


@pytest.fixture
def fake_taskagent(monkeypatch):
    fake = FakeAsyncTaskAgent()
    # async_runner.run_task is what the background worker calls
    monkeypatch.setattr("gateway.async_runner.run_task", fake)
    return fake


@pytest.fixture
def fake_taskagent_slow(monkeypatch):
    fake = FakeAsyncTaskAgent(delay=0.3)
    monkeypatch.setattr("gateway.async_runner.run_task", fake)
    return fake


def _register(client, email: str = "alice@example.com", name: str = "Alice") -> str:
    r = client.post("/api/auth/register", json={
        "email": email, "password": "secret123", "name": name,
    })
    assert r.status_code in (201, 409), r.text
    if r.status_code == 409:
        # already registered, log in
        r = client.post("/api/auth/login", json={
            "email": email, "password": "secret123",
        })
        assert r.status_code == 200, r.text
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload_csv(client, token: str) -> str:
    r = client.post(
        "/api/uploads",
        files={"file": ("data.csv", io.BytesIO(b"name,age\nAlice,30\n"), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- Async enqueue + poll ---------------------------------------------------

def test_enqueue_returns_202_with_task_id(client, fake_taskagent):
    token = _register(client)
    upload_id = _upload_csv(client, token)

    r = client.post(
        "/api/tasks",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 202, r.text
    body = r.json()
    assert body["status"] == "queued"
    assert body["task_id"].startswith("utk_")
    assert "queue_depth" in body


def test_enqueue_validates_upload(client, fake_taskagent):
    token = _register(client)
    r = client.post(
        "/api/tasks",
        json={"upload_id": "upl_x", "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_enqueue_validates_agent(client, fake_taskagent):
    token = _register(client)
    upload_id = _upload_csv(client, token)
    r = client.post(
        "/api/tasks",
        json={"upload_id": upload_id, "agent_id": "nonexistent"},
        headers=_auth(token),
    )
    assert r.status_code == 404


def test_enqueue_requires_auth(client, fake_taskagent):
    r = client.post("/api/tasks", json={
        "upload_id": "upl_x", "agent_id": "data-analysis-report",
    })
    assert r.status_code == 401


def test_poll_until_done(client, fake_taskagent_slow):
    """Enqueue then poll the task detail endpoint until status leaves queued/running."""
    token = _register(client)
    upload_id = _upload_csv(client, token)

    r = client.post(
        "/api/tasks",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    task_id = r.json()["task_id"]

    # Poll up to 5 seconds
    deadline = time.time() + 5
    final = None
    while time.time() < deadline:
        r = client.get(f"/api/tasks/{task_id}", headers=_auth(token))
        assert r.status_code == 200
        body = r.json()
        if body["status"] in ("ok", "failed", "timeout", "cancelled"):
            final = body
            break
        time.sleep(0.1)
    assert final is not None, "task did not finish in 5s"
    assert final["status"] == "ok"
    assert "Async Report" in final["report"]
    assert final["duration_ms"] >= 100  # fake slept 0.3s
    assert final["taskagent_task_id"] == "tsk_async_1234"
    assert final["completed_at"] is not None


def test_enqueue_with_instructions(client, fake_taskagent):
    token = _register(client)
    upload_id = _upload_csv(client, token)
    client.post(
        "/api/tasks",
        json={
            "upload_id": upload_id,
            "agent_id": "data-analysis-report",
            "user_instructions": "异步测试",
            "dataset_name": "AsyncTest",
        },
        headers=_auth(token),
    )
    # Wait briefly for worker to pick it up
    time.sleep(0.3)
    assert len(fake_taskagent.calls) == 1
    call = fake_taskagent.calls[0]
    assert call["user_instructions"] == "异步测试"
    assert call["file_meta"]["dataset_name"] == "AsyncTest"
    assert call["job_id"] == "data-analysis-report"


def test_async_task_user_isolation(client, fake_taskagent_slow):
    token_a = _register(client, email="a@example.com")
    upload_a = _upload_csv(client, token_a)
    r = client.post(
        "/api/tasks",
        json={"upload_id": upload_a, "agent_id": "data-analysis-report"},
        headers=_auth(token_a),
    )
    task_id_a = r.json()["task_id"]

    token_b = _register(client, email="b@example.com")
    # B cannot see A's task
    r = client.get(f"/api/tasks/{task_id_a}", headers=_auth(token_b))
    assert r.status_code == 404
    r = client.get("/api/tasks", headers=_auth(token_b))
    assert r.json()["tasks"] == []


def test_async_task_failure_persisted(client, monkeypatch):
    """If the agent returns failed, the task row reflects it after worker runs."""
    fake = FakeAsyncTaskAgent(status="failed", error="LLM blew up")
    monkeypatch.setattr("gateway.async_runner.run_task", fake)

    token = _register(client)
    upload_id = _upload_csv(client, token)
    r = client.post(
        "/api/tasks",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    task_id = r.json()["task_id"]

    time.sleep(0.3)
    r = client.get(f"/api/tasks/{task_id}", headers=_auth(token))
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "LLM blew up"
    assert body["report"] == ""  # no report on failure
