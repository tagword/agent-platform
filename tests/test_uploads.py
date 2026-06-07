"""Upload route tests: CSV, Excel, JSON, auth, size limit, isolation."""

from __future__ import annotations

import io
import json


def _register_and_get_token(client, email="alice@example.com") -> str:
    r = client.post("/api/auth/register", json={
        "email": email, "password": "secret123", "name": "Alice",
    })
    return r.json()["token"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# --- Auth gate --------------------------------------------------------------

def test_upload_requires_auth(client):
    r = client.post("/api/uploads", files={"file": ("a.csv", b"x,y\n1,2\n", "text/csv")})
    assert r.status_code == 401


def test_list_uploads_requires_auth(client):
    r = client.get("/api/uploads")
    assert r.status_code == 401


# --- CSV upload -------------------------------------------------------------

def test_upload_csv_success(client):
    token = _register_and_get_token(client)
    csv_bytes = "name,age,city\nAlice,30,Beijing\nBob,25,Shanghai\n".encode("utf-8")
    r = client.post(
        "/api/uploads",
        files={"file": ("users.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["filename"] == "users.csv"
    assert body["size_bytes"] == len(csv_bytes)
    assert body["parse_status"] == "ok"
    assert body["parse_error"] is None
    assert body["summary"]["row_count"] == 2
    assert set(body["summary"]["columns"]) == {"name", "age", "city"}

    # Fetch the upload and verify parsed rows are present
    r = client.get(f"/api/uploads/{body['id']}", headers=_auth(token))
    assert r.status_code == 200
    detail = r.json()
    assert detail["rows"] is not None
    assert len(detail["rows"]) == 2
    assert detail["rows"][0]["name"] == "Alice"


def test_upload_csv_with_bom(client):
    """Excel-style BOM should be stripped."""
    token = _register_and_get_token(client)
    csv_bytes = "\ufeffname,age\nAlice,30\n".encode("utf-8")
    r = client.post(
        "/api/uploads",
        files={"file": ("users.csv", io.BytesIO(csv_bytes), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 201
    assert r.json()["summary"]["columns"] == ["name", "age"]  # not "\ufeffname"


# --- JSON upload ------------------------------------------------------------

def test_upload_json_array(client):
    token = _register_and_get_token(client)
    data = [{"name": "Alice", "age": 30}, {"name": "Bob", "age": 25}]
    r = client.post(
        "/api/uploads",
        files={"file": ("users.json", io.BytesIO(json.dumps(data).encode("utf-8")), "application/json")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["parse_status"] == "ok"
    assert body["summary"]["row_count"] == 2

    r = client.get(f"/api/uploads/{body['id']}", headers=_auth(token))
    detail = r.json()
    assert len(detail["rows"]) == 2


def test_upload_json_object(client):
    token = _register_and_get_token(client)
    data = {"summary_stats": {"mean": 100, "median": 99}, "metrics": ["a", "b"]}
    r = client.post(
        "/api/uploads",
        files={"file": ("analysis.json", io.BytesIO(json.dumps(data).encode("utf-8")), "application/json")},
        headers=_auth(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["summary"]["shape"] == "object"
    assert "summary_stats" in body["summary"]["top_level_keys"]

    r = client.get(f"/api/uploads/{body['id']}", headers=_auth(token))
    detail = r.json()
    assert detail["rows"] is None  # object form has no rows
    assert detail["data"]["summary_stats"]["mean"] == 100


def test_upload_invalid_json(client):
    token = _register_and_get_token(client)
    r = client.post(
        "/api/uploads",
        files={"file": ("bad.json", io.BytesIO(b"{not valid json"), "application/json")},
        headers=_auth(token),
    )
    assert r.status_code == 201
    body = r.json()
    assert body["parse_status"] == "failed"
    assert "JSON" in body["parse_error"] or "json" in body["parse_error"]


# --- Excel upload -----------------------------------------------------------

def test_upload_excel_success(client):
    from openpyxl import Workbook
    wb = Workbook()
    ws = wb.active
    ws.title = "Data"
    ws.append(["name", "age", "city"])
    ws.append(["Alice", 30, "Beijing"])
    ws.append(["Bob", 25, "Shanghai"])
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)

    token = _register_and_get_token(client)
    r = client.post(
        "/api/uploads",
        files={"file": ("data.xlsx", buf, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        headers=_auth(token),
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["parse_status"] == "ok"
    assert body["summary"]["row_count"] == 2
    assert body["summary"]["active_sheet"] == "Data"
    assert "Data" in body["summary"]["sheets"]


# --- Bad extensions / size --------------------------------------------------

def test_upload_unsupported_extension(client):
    token = _register_and_get_token(client)
    r = client.post(
        "/api/uploads",
        files={"file": ("photo.png", io.BytesIO(b"\x89PNG"), "image/png")},
        headers=_auth(token),
    )
    assert r.status_code == 400
    assert "Unsupported" in r.json()["detail"]


def test_upload_size_limit(client, monkeypatch):
    from gateway import config
    # Override the limit for this test only
    monkeypatch.setattr(config, "MAX_UPLOAD_MB", 1)
    token = _register_and_get_token(client)
    big = b"x" * (2 * 1024 * 1024)  # 2 MB
    r = client.post(
        "/api/uploads",
        files={"file": ("big.csv", io.BytesIO(big), "text/csv")},
        headers=_auth(token),
    )
    assert r.status_code == 413
    assert "too large" in r.json()["detail"].lower()


# --- List + isolation --------------------------------------------------------

def test_list_uploads_pagination_and_order(client):
    import time
    token = _register_and_get_token(client)
    for i in range(3):
        csv = f"name,age\nAlice{i},{20 + i}\n".encode()
        r = client.post(
            "/api/uploads",
            files={"file": (f"u{i}.csv", io.BytesIO(csv), "text/csv")},
            headers=_auth(token),
        )
        assert r.status_code == 201
        time.sleep(1.05)  # cross a unix-second boundary for stable ordering

    r = client.get("/api/uploads", headers=_auth(token))
    assert r.status_code == 200
    body = r.json()
    assert len(body["uploads"]) == 3
    # Most recent first
    assert body["uploads"][0]["filename"] == "u2.csv"
    assert body["uploads"][2]["filename"] == "u0.csv"


def test_user_isolation_uploads(client):
    """User A cannot see User B's uploads."""
    token_a = _register_and_get_token(client, email="a@example.com")
    csv = b"name\nAlice\n"
    r = client.post(
        "/api/uploads",
        files={"file": ("a.csv", io.BytesIO(csv), "text/csv")},
        headers=_auth(token_a),
    )
    upload_id = r.json()["id"]

    # User B
    token_b = _register_and_get_token(client, email="b@example.com")
    # B's list is empty
    r = client.get("/api/uploads", headers=_auth(token_b))
    assert r.json()["uploads"] == []
    # B cannot fetch A's upload
    r = client.get(f"/api/uploads/{upload_id}", headers=_auth(token_b))
    assert r.status_code == 404


def test_get_upload_404(client):
    token = _register_and_get_token(client)
    r = client.get("/api/uploads/upl_nonexistent", headers=_auth(token))
    assert r.status_code == 404
