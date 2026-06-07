"""Task route tests — uses a fake TaskAgent injected via monkeypatch.

We never depend on a real TaskAgent in unit tests; we replace the network
client with a stub that returns canned responses. This isolates the gateway
logic (auth, validation, persistence) from TaskAgent/seed internals.
"""

from __future__ import annotations

import io
import json

import pytest


# --- Fakes ------------------------------------------------------------------

class FakeTaskAgentSuccess:
    """Stand-in for gateway.taskagent_client.run_task."""

    def __init__(self):
        self.calls = []

    async def __call__(self, *, job_id, raw_data, user_instructions="", file_meta=None):
        self.calls.append({
            "job_id": job_id,
            "raw_data": raw_data,
            "user_instructions": user_instructions,
            "file_meta": file_meta,
        })
        return {
            "status": "ok",
            "reply": "# 摘要\n这是一份测试报告。\n\n## 关键指标\n- DAU: 1000",
            "tools_used": ["bash", "file_read"],
            "error": None,
            "duration_ms": 1234,
            "usage": {"prompt_tokens": 100, "completion_tokens": 200, "total_tokens": 300},
            "session_id": "task-fake-session",
            "task_id": "tsk_fake_id_1234",
        }


class FakeTaskAgentFailed:
    async def __call__(self, *, job_id, raw_data, user_instructions="", file_meta=None):
        return {
            "status": "failed",
            "reply": "",
            "tools_used": [],
            "error": "LLM quota exceeded",
            "duration_ms": 500,
            "usage": None,
            "session_id": "task-fake-fail",
            "task_id": "tsk_fake_fail",
        }


class FakeTaskAgentUnreachable:
    async def __call__(self, **kwargs):
        from gateway.taskagent_client import TaskAgentError
        raise TaskAgentError("TaskAgent unreachable: connection refused")


# --- Fixtures ----------------------------------------------------------------

@pytest.fixture
def fake_taskagent_success(monkeypatch):
    fake = FakeTaskAgentSuccess()
    monkeypatch.setattr("gateway.routes.tasks.run_task", fake)
    return fake


@pytest.fixture
def fake_taskagent_failed(monkeypatch):
    fake = FakeTaskAgentFailed()
    monkeypatch.setattr("gateway.routes.tasks.run_task", fake)
    return fake


@pytest.fixture
def fake_taskagent_unreachable(monkeypatch):
    fake = FakeTaskAgentUnreachable()
    monkeypatch.setattr("gateway.routes.tasks.run_task", fake)
    return fake


# --- Helpers -----------------------------------------------------------------

def _register(client, email="alice@example.com") -> str:
    r = client.post("/api/auth/register", json={
        "email": email, "password": "secret123", "name": "Alice",
    })
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _upload_csv(client, token: str, csv_text: str = "name,age\nAlice,30\nBob,25\n") -> str:
    r = client.post(
        "/api/uploads",
        files={"file": ("data.csv", io.BytesIO(csv_text.encode("utf-8")), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    return r.json()["id"]


# --- Auth / validation -------------------------------------------------------

def test_run_task_requires_auth(client):
    r = client.post("/api/tasks/run", json={"upload_id": "upl_x", "agent_id": "data-analysis-report"})
    assert r.status_code == 401


def test_run_task_unknown_agent(client, fake_taskagent_success):
    token = _register(client)
    upload_id = _upload_csv(client, token)
    r = client.post(
        "/api/tasks/run",
        json={"upload_id": upload_id, "agent_id": "nonexistent-agent"},
        headers=_auth(token),
    )
    assert r.status_code == 404
    assert "not found" in r.json()["detail"].lower()


def test_run_task_unknown_upload(client, fake_taskagent_success):
    token = _register(client)
    r = client.post(
        "/api/tasks/run",
        json={"upload_id": "upl_nonexistent", "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 404
    assert "upload" in r.json()["detail"].lower()


# --- Happy path -------------------------------------------------------------

def test_run_task_success_persists_report(client, fake_taskagent_success):
    token = _register(client)
    upload_id = _upload_csv(client, token)

    r = client.post(
        "/api/tasks/run",
        json={
            "upload_id": upload_id,
            "agent_id": "data-analysis-report",
            "user_instructions": "重点关注 age 维度",
            "dataset_name": "用户增长数据",
        },
        headers=_auth(token),
    )
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["status"] == "ok"
    assert "测试报告" in body["report"]
    assert body["error"] is None
    assert body["duration_ms"] == 1234
    assert body["usage"]["total_tokens"] == 300

    # Verify TaskAgent was called with right job + payload
    call = fake_taskagent_success.calls[0]
    assert call["job_id"] == "data-analysis-report"
    assert call["user_instructions"] == "重点关注 age 维度"
    assert call["file_meta"]["dataset_name"] == "用户增长数据"
    assert call["file_meta"]["filename"] == "data.csv"
    assert call["raw_data"]["format"] == "csv"
    assert call["raw_data"]["summary"]["row_count"] == 2

    # Verify task persisted
    task_id = body["task_id"]
    r = client.get(f"/api/tasks/{task_id}", headers=_auth(token))
    assert r.status_code == 200
    detail = r.json()
    assert detail["status"] == "ok"
    assert "测试报告" in detail["report"]
    assert detail["taskagent_task_id"] == "tsk_fake_id_1234"
    assert detail["completed_at"] is not None


def test_run_task_failed_agent_response(client, fake_taskagent_failed):
    token = _register(client)
    upload_id = _upload_csv(client, token)
    r = client.post(
        "/api/tasks/run",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 200  # task ran, agent returned failed
    body = r.json()
    assert body["status"] == "failed"
    assert body["error"] == "LLM quota exceeded"
    assert body["report"] == ""


def test_run_task_unreachable_taskagent(client, fake_taskagent_unreachable):
    token = _register(client)
    upload_id = _upload_csv(client, token)
    r = client.post(
        "/api/tasks/run",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 502
    assert "unreachable" in r.json()["detail"].lower()

    # Task should be marked failed with the error
    r = client.get("/api/tasks", headers=_auth(token))
    assert r.json()["tasks"][0]["status"] == "failed"
    assert "unreachable" in r.json()["tasks"][0]["error"].lower()


# --- User isolation ----------------------------------------------------------

def test_task_isolation(client, fake_taskagent_success):
    """User A's task is not visible to user B."""
    token_a = _register(client, email="a@example.com")
    upload_a = _upload_csv(client, token_a)

    r = client.post(
        "/api/tasks/run",
        json={"upload_id": upload_a, "agent_id": "data-analysis-report"},
        headers=_auth(token_a),
    )
    task_id_a = r.json()["task_id"]

    # User B
    token_b = _register(client, email="b@example.com")
    r = client.get("/api/tasks", headers=_auth(token_b))
    assert r.json()["tasks"] == []
    r = client.get(f"/api/tasks/{task_id_a}", headers=_auth(token_b))
    assert r.status_code == 404


# --- List ordering -----------------------------------------------------------

def test_list_tasks_recent_first(client, fake_taskagent_success):
    import time
    token = _register(client)
    upload_id = _upload_csv(client, token)
    task_ids = []
    for _ in range(3):
        r = client.post(
            "/api/tasks/run",
            json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
            headers=_auth(token),
        )
        assert r.status_code == 200
        task_ids.append(r.json()["task_id"])
        time.sleep(1.05)  # cross a unix-second boundary

    r = client.get("/api/tasks", headers=_auth(token))
    listed = [t["id"] for t in r.json()["tasks"]]
    assert listed == list(reversed(task_ids))  # most recent first


# --- Unparseable upload ------------------------------------------------------

def test_run_task_rejects_unparseable_upload(client, fake_taskagent_success):
    token = _register(client)
    # Upload a corrupt JSON — parse_status will be 'failed'
    r = client.post(
        "/api/uploads",
        files={"file": ("bad.json", io.BytesIO(b"{not valid"), "application/json")},
        headers=_auth(token),
    )
    upload_id = r.json()["id"]
    assert r.json()["parse_status"] == "failed"

    r = client.post(
        "/api/tasks/run",
        json={"upload_id": upload_id, "agent_id": "data-analysis-report"},
        headers=_auth(token),
    )
    assert r.status_code == 400
    assert "parseable" in r.json()["detail"].lower()
    # And TaskAgent should NOT have been called
    assert len(fake_taskagent_success.calls) == 0
