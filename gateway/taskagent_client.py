"""HTTP client for the TaskAgent /tasks/run endpoint (sync mode).

Why sync mode (Phase 3): users uploading a file expect a report in seconds.
We treat long-running tasks as a Phase 4+ concern (async + WebSocket).
"""

from __future__ import annotations

import logging
from typing import Any, Optional

import httpx

from gateway import config

logger = logging.getLogger(__name__)


class TaskAgentError(Exception):
    """Raised when TaskAgent returns an error or is unreachable."""


def _build_message(user_instructions: str, raw_data: Any, file_meta: dict[str, Any]) -> str:
    """Build the user_message string that the agent will see.

    The agent is a stateful LLM receiving natural-language user_message,
    not raw JSON. We embed the data as a fenced JSON block for parseability.
    """
    import json as _json
    dataset = file_meta.get("dataset_name", "未命名")
    notes = (user_instructions or "").strip()
    payload = {
        "dataset_name": dataset,
        "raw_data": raw_data,
        "file_meta": {k: v for k, v in file_meta.items() if k != "dataset_name"},
    }
    blocks = [
        f"请为数据集「{dataset}」生成分析报告。",
    ]
    if notes:
        blocks.append(f"\n补充说明：{notes}\n")
    blocks.append("\n以下是数据（JSON 格式）：\n")
    blocks.append("```json\n" + _json.dumps(payload, ensure_ascii=False, default=str) + "\n```")
    return "\n".join(blocks)


async def run_task(
    *,
    job_id: str,
    raw_data: Any,
    user_instructions: str = "",
    file_meta: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """Call TaskAgent /tasks/run synchronously and return the full result.

    Returns dict with keys: status, reply, tools_used, error, duration_ms,
    usage, session_id, task_id.
    Raises TaskAgentError on transport failure or 4xx/5xx.
    """
    file_meta = file_meta or {}
    user_message = _build_message(user_instructions, raw_data, file_meta)
    payload = {
        "message": user_message,
        "user_instructions": user_instructions,
        "file_meta": file_meta,
        "raw_data": raw_data,
    }
    body = {"job_id": job_id, "payload": payload}
    url = f"{config.TASKAGENT_URL.rstrip('/')}/tasks/run"
    logger.info("Calling TaskAgent: %s job=%s", url, job_id)
    try:
        async with httpx.AsyncClient(timeout=config.TASKAGENT_TIMEOUT_SEC) as client:
            r = await client.post(url, json=body)
    except httpx.TimeoutException as e:
        raise TaskAgentError(f"TaskAgent timed out after {config.TASKAGENT_TIMEOUT_SEC}s") from e
    except httpx.HTTPError as e:
        raise TaskAgentError(f"TaskAgent unreachable: {e}") from e

    if r.status_code == 403:
        raise TaskAgentError(
            "TaskAgent has sync /tasks/run disabled. "
            "Set TASKAGENT_SYNC_RUN_ENABLED=1 in TaskAgent's env."
        )
    if r.status_code == 404:
        raise TaskAgentError(f"Unknown job_id: {job_id} (TaskAgent has no such job configured)")
    if r.status_code >= 400:
        # Try to surface TaskAgent's error message
        try:
            detail = r.json().get("detail") or r.text
        except Exception:
            detail = r.text
        raise TaskAgentError(f"TaskAgent {r.status_code}: {detail}")

    try:
        return r.json()
    except Exception as e:
        raise TaskAgentError(f"TaskAgent returned non-JSON response: {r.text[:200]}") from e


async def check_health() -> bool:
    """Return True if TaskAgent is reachable and healthy."""
    url = f"{config.TASKAGENT_URL.rstrip('/')}/health"
    try:
        async with httpx.AsyncClient(timeout=5) as client:
            r = await client.get(url)
            return r.status_code == 200
    except Exception:
        return False
