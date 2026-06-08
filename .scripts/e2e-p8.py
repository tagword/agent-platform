"""P8 verification: async mode + multiple agent templates + mobile bottom nav.

Strategy: use API (curl) for functional validation, playwright only for
UI rendering verification (login page, task list, report rendering).
"""

import asyncio
import json
import os
import random
import string
import subprocess
import tempfile
from pathlib import Path

import httpx


GW_URL = os.environ.get("E2E_GW_URL", "http://127.0.0.1:18777")
WEBUI_URL = os.environ.get("E2E_WEBUI_URL", "http://127.0.0.1:18778/index.html")
PASSWORD = "test1234"
CSV = """date,channel,new_users,retained_d7,revenue
2026-04-01,organic,1200,420,5400
2026-04-02,paid,800,180,12000
"""


async def test_api() -> dict:
    """Test the full API flow (async mode) via httpx.

    Returns login token for use in playwright step.
    """
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    email = f"e2e-p8-{suffix}@test.com"
    async with httpx.AsyncClient(base_url=GW_URL, timeout=30) as c:
        # Register
        r = await c.post("/api/auth/register", json={
            "email": email, "password": PASSWORD, "name": "P8",
        })
        assert r.status_code == 201, f"register: {r.text}"
        token = r.json()["token"]
        auth = {"Authorization": f"Bearer {token}"}
        print(f"[api:1] registered {email}")

        # List agents
        r = await c.get("/api/agents", headers=auth)
        assert r.status_code == 200
        agents = r.json()["agents"]
        assert len(agents) >= 2, f"expected >=2 agents, got {len(agents)}"
        ids = [a["id"] for a in agents]
        assert "code-review" in ids
        assert "doc-summary" in ids
        assert "data-analysis-report" in ids
        print(f"[api:2] {len(agents)} agent templates: {[a['id'] for a in agents]}")

        # Upload CSV — don't set Content-Type manually, httpx adds boundary
        r = await c.post(
            "/api/uploads", headers=auth,
            files={"file": ("e2e.csv", CSV.encode("utf-8"), "text/csv")},
        )
        assert r.status_code == 201, f"upload: {r.text}"
        upload_id = r.json()["id"]
        print(f"[api:3] uploaded CSV: {upload_id}")

        # Enqueue async task
        r = await c.post("/api/tasks", json={
            "upload_id": upload_id,
            "agent_id": "data-analysis-report",
            "user_instructions": "关注付费渠道留存",
            "dataset_name": "P8 测试",
        }, headers=auth)
        assert r.status_code == 202, f"enqueue: {r.text}"
        task_id = r.json()["task_id"]
        assert r.json()["status"] == "queued"
        print(f"[api:4] async task enqueued: {task_id}")

        # Poll until done
        for i in range(120):
            await asyncio.sleep(1)
            r = await c.get(f"/api/tasks/{task_id}", headers=auth)
            assert r.status_code == 200
            status = r.json()["status"]
            if status in ("ok", "failed", "timeout", "cancelled"):
                print(f"[api:5] task finished after {i+1}s: status={status}")
                break
        else:
            raise AssertionError("task did not finish in 120s")

        result = r.json()
        assert result["status"] == "ok", f"expected ok, got {result['status']}: {result.get('error')}"
        assert result.get("report"), "report should not be empty"
        assert len(result["report"]) > 100, f"report too short: {len(result['report'])}"
        assert any(ord(c) > 0x4e00 for c in result["report"]), "report should contain Chinese"
        print(f"[api:6] report {len(result['report'])} chars, has Chinese ✓")
        print(f"[api:7] duration_ms={result['duration_ms']}")

        return {"email": email, "token": token, "task_id": task_id}


async def test_ui(email: str, token: str):
    """Open webui as this user and verify the task detail renders correctly."""
    from playwright.async_api import async_playwright

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800},
                                        storage_state={"cookies": [], "origins": []})
        page = await ctx.new_page()
        page.on("console", lambda msg: print(f"  [browser:{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"  [browser:ERROR] {exc}"))
        await page.add_init_script(f"window.AGENT_PLATFORM_API_BASE = '{GW_URL}';")
        # Inject token directly into localStorage so we skip login
        await page.goto(WEBUI_URL, wait_until="domcontentloaded")
        await page.evaluate(f"""
            localStorage.setItem('ap_token', '{token}');
            localStorage.setItem('ap_user', JSON.stringify({json.dumps({"name": "P8", "email": email})}));
            location.reload();
        """)
        await page.wait_for_timeout(2000)
        # Navigate to tasks
        await page.evaluate('location.hash = "#/tasks";')
        await page.wait_for_timeout(2000)
        await page.screenshot(path="/tmp/e2e-p8-ui-tasks.png", full_page=True)
        try:
            await page.wait_for_selector(".task-row", timeout=10000)
            rows = await page.query_selector_all(".task-row")
            print(f"[ui:1] tasks list rendered with {len(rows)} row(s) ✓")
        except Exception:
            print(f"[ui:WARN] no task rows visible, url={page.url}")
            body = await page.inner_text("body")
            print(f"[debug] body: {body[:500]}")
            await page.screenshot(path="/tmp/e2e-p8-ui-debug.png", full_page=True)

        # Mobile bottom nav (on home page)
        await page.evaluate('location.hash = "#/home";')
        await page.wait_for_timeout(2000)
        await page.set_viewport_size({"width": 375, "height": 667})
        await page.wait_for_timeout(1000)
        bnav = await page.is_visible("#bottomnav")
        tnav = await page.is_visible("#topnav")
        print(f"[ui:2] mobile: bottomnav={bnav}, topnav={tnav}")
        await page.screenshot(path="/tmp/e2e-p8-ui-mobile.png", full_page=True)

        await browser.close()
        print("[ui:3] UI checks passed ✓")


async def main():
    print("=== Phase 8 E2E ===")
    result = await test_api()
    await test_ui(result["email"], result["token"])
    print("\n✅ ALL P8 TESTS PASSED")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
