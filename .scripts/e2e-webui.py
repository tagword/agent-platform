"""End-to-end browser smoke test for the WebUI.

Run with services already up:
  - TaskAgent at 127.0.0.1:18772
  - Gateway     at 127.0.0.1:18773
  - WebUI       at 127.0.0.1:18774

Verifies the complete user flow:
  1. Open login page → register
  2. Land on home → see agent card
  3. Select agent → upload CSV → fill instructions → run
  4. Wait for sync /tasks/run (real LLM) → land on task detail
  5. Render Markdown report
  6. Visit tasks list
"""

import asyncio
import os
import tempfile
from pathlib import Path

from playwright.async_api import async_playwright

WEBUI_URL = os.environ.get("E2E_WEBUI_URL", "http://127.0.0.1:18774/index.html")
GW_URL = os.environ.get("E2E_GW_URL", "http://127.0.0.1:18773")


SAMPLE_CSV = """date,channel,new_users,retained_d7,revenue
2026-04-01,organic,1200,420,5400
2026-04-01,paid,800,180,12000
2026-04-02,organic,1350,475,6100
2026-04-02,paid,820,175,11800
2026-04-03,organic,1100,390,5000
2026-04-03,paid,950,210,14000
"""


async def main() -> int:
    # Write a sample CSV to /tmp
    csv_path = Path(tempfile.gettempdir()) / "e2e-p4-sample.csv"
    csv_path.write_text(SAMPLE_CSV, encoding="utf-8")
    # Random email so re-runs work
    import random, string
    suffix = "".join(random.choices(string.ascii_lowercase, k=6))
    email = f"e2e-p4-{suffix}@test.com"
    password = "test1234"
    name = "E2E P4"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=True)
        ctx = await browser.new_context(viewport={"width": 1280, "height": 800})
        page = await ctx.new_page()
        page.on("console", lambda msg: print(f"  [browser-{msg.type}] {msg.text}"))
        page.on("pageerror", lambda exc: print(f"  [browser-ERROR] {exc}"))
        # Inject window.AGENT_PLATFORM_API_BASE BEFORE any script runs
        await page.add_init_script(f"window.AGENT_PLATFORM_API_BASE = '{GW_URL}';")

        # Step 0: open webui
        print(f"[0] opening {WEBUI_URL}")
        await page.goto(WEBUI_URL)
        await page.wait_for_selector("#auth-form", timeout=5000)
        await page.screenshot(path="/tmp/e2e-p4-1-login.png", full_page=True)
        print("[1] login page rendered")

        # Step 1: switch to register tab
        await page.click('.auth-tab[data-tab="register"]')
        await page.fill('input[name="email"]', email)
        await page.fill('input[name="password"]', password)
        await page.fill('input[name="name"]', name)
        await page.screenshot(path="/tmp/e2e-p4-2-register.png", full_page=True)
        await page.click('button[type="submit"]')
        await page.wait_for_selector(".agent-card", timeout=10000)
        await page.screenshot(path="/tmp/e2e-p4-3-home.png", full_page=True)
        print("[2] registered, on home page, agent card visible")

        # Step 2: select agent
        await page.click(".agent-card")
        await page.wait_for_selector("#upload-zone", state="visible", timeout=3000)
        print("[3] agent selected, upload zone visible")

        # Step 3: upload file
        async with page.expect_file_chooser() as fc_info:
            await page.click("#upload-zone")
        fc = await fc_info.value
        await fc.set_files(str(csv_path))
        await page.wait_for_selector("#upload-zone.has-file", timeout=3000)
        print(f"[4] file uploaded: {csv_path}")

        # Step 4: fill instructions and run
        await page.fill("#user-instructions", "重点关注付费渠道的留存率")
        await page.fill("#dataset-name", "E2E 测试数据")
        await page.screenshot(path="/tmp/e2e-p4-4-before-run.png", full_page=True)
        await page.click("#run-btn")
        print("[5] run clicked, waiting for sync /tasks/run (real LLM)...")

        # Step 5: wait for navigation to task detail
        await page.wait_for_url("**#/tasks/**", timeout=180_000)
        await page.wait_for_selector("#report-md", timeout=30_000)
        await page.screenshot(path="/tmp/e2e-p4-5-report.png", full_page=True)
        print("[6] task detail page rendered with report")

        # Step 6: check report has Chinese content
        report_html = await page.inner_html("#report-md")
        has_chinese = any(ord(c) > 0x4e00 for c in report_html)
        assert has_chinese, "Report should contain Chinese characters"
        has_table = "<table" in report_html
        assert has_table, "Report should contain a table"
        print("[7] report contains Chinese + table ✓")

        # Step 7: navigate to tasks list
        await page.click('nav a[href="#/tasks"]')
        await page.wait_for_selector(".task-row", timeout=5000)
        rows = await page.query_selector_all(".task-row")
        assert len(rows) >= 1, "tasks list should have at least 1 row"
        await page.screenshot(path="/tmp/e2e-p4-6-tasks.png", full_page=True)
        print(f"[8] tasks list rendered with {len(rows)} task(s)")

        # Step 8: mobile viewport check
        await page.set_viewport_size({"width": 375, "height": 667})
        await page.click('nav a[href="#/home"]')
        await page.wait_for_selector(".agent-card", timeout=5000)
        await page.screenshot(path="/tmp/e2e-p4-7-mobile.png", full_page=True)
        print("[9] mobile viewport (375x667) renders")

        await browser.close()
    print("\n✅ ALL E2E STEPS PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
