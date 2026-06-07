"""Task routes: POST /api/tasks/run, GET /api/tasks, GET /api/tasks/{id}.

Flow for run:
1. Validate upload_id belongs to user
2. Create user_task row (status=queued)
3. Update to status=running
4. Call TaskAgent /tasks/run
5. Update row with status/reply/error/duration
6. Return task record to client
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field

from gateway.auth.deps import get_current_user
from gateway.db import repo
from gateway.taskagent_client import TaskAgentError, run_task

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/tasks", tags=["tasks"])


# --- Request models ---------------------------------------------------------

class RunTaskRequest(BaseModel):
    upload_id: str
    agent_id: str = Field(..., description="Agent template id, e.g. 'data-analysis-report'")
    user_instructions: str = Field(default="", max_length=2000)
    dataset_name: Optional[str] = None  # overrides filename


# --- Helpers ----------------------------------------------------------------

def _resolve_parsed_data(upload: dict) -> dict:
    """Extract the parsed payload from a uploads row.

    Returns a dict with at least `format`; either `rows` (table) or `data` (object).
    """
    raw = upload.get("parsed_json")
    if not raw:
        raise HTTPException(status_code=400, detail="Upload has no parsed data; re-upload a CSV/Excel/JSON file")
    try:
        parsed = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Stored parse data is corrupt")
    if parsed.get("format") is None:
        raise HTTPException(status_code=400, detail="Upload has no recognized data format")
    return parsed


# --- Routes -----------------------------------------------------------------

@router.post("/run")
async def run_user_task(
    body: RunTaskRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Trigger a task synchronously. Returns the report when done."""
    # 1. Validate agent
    agent = repo.get_agent_template(body.agent_id)
    if not agent or not agent.get("enabled"):
        raise HTTPException(status_code=404, detail=f"Agent not found or disabled: {body.agent_id}")

    # 2. Validate upload ownership
    upload = repo.get_upload(user_id=user["id"], upload_id=body.upload_id)
    if not upload:
        raise HTTPException(status_code=404, detail=f"Upload not found: {body.upload_id}")
    if upload.get("parse_status") != "ok":
        raise HTTPException(
            status_code=400,
            detail=f"Upload is not parseable: {upload.get('parse_error') or 'unknown error'}",
        )

    parsed = _resolve_parsed_data(upload)
    dataset_name = body.dataset_name or upload["filename"]

    # 3. Create user_task row
    task_id = repo.create_user_task(
        user_id=user["id"],
        agent_template_id=body.agent_id,
        agent_version=agent["version"],
        upload_id=body.upload_id,
    )
    repo.update_user_task(task_id, status="running")

    file_meta = {
        "filename": upload["filename"],
        "size_bytes": upload["size_bytes"],
        "content_type": upload.get("content_type"),
        "dataset_name": dataset_name,
        "upload_id": upload["id"],
    }

    # 4. Call TaskAgent
    try:
        result = await run_task(
            job_id=agent["job_id"],
            raw_data=parsed,
            user_instructions=body.user_instructions,
            file_meta=file_meta,
        )
    except TaskAgentError as e:
        logger.warning("TaskAgent error for task %s: %s", task_id, e)
        repo.update_user_task(
            task_id, status="failed", error=str(e), completed=True,
        )
        raise HTTPException(status_code=502, detail=f"TaskAgent error: {e}")

    # 5. Persist result
    status_out = result.get("status", "ok")
    if status_out not in ("ok", "failed", "timeout", "cancelled"):
        status_out = "ok"
    report_md = result.get("reply") or ""
    error_msg = result.get("error")
    duration_ms = result.get("duration_ms")

    repo.update_user_task(
        task_id,
        status=status_out,
        taskagent_task_id=result.get("task_id"),
        report_md=report_md,
        error=error_msg,
        duration_ms=duration_ms,
        completed=True,
    )

    return {
        "task_id": task_id,
        "status": status_out,
        "report": report_md,
        "error": error_msg,
        "duration_ms": duration_ms,
        "usage": result.get("usage"),
    }


@router.get("")
async def list_tasks(
    limit: int = 50,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    rows = repo.list_user_tasks(user_id=user["id"], limit=min(max(limit, 1), 200))
    return {
        "tasks": [
            {
                "id": r["id"],
                "upload_id": r["upload_id"],
                "agent_template_id": r["agent_template_id"],
                "agent_version": r["agent_version"],
                "status": r["status"],
                "error": r["error"],
                "duration_ms": r["duration_ms"],
                "created_at": r["created_at"],
                "completed_at": r["completed_at"],
            }
            for r in rows
        ]
    }


@router.get("/{task_id}")
async def get_task(
    task_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    row = repo.get_user_task(user_id=user["id"], task_id=task_id)
    if not row:
        raise HTTPException(status_code=404, detail="Task not found")
    return {
        "id": row["id"],
        "upload_id": row["upload_id"],
        "agent_template_id": row["agent_template_id"],
        "agent_version": row["agent_version"],
        "taskagent_task_id": row["taskagent_task_id"],
        "status": row["status"],
        "report": row["report_md"],
        "error": row["error"],
        "duration_ms": row["duration_ms"],
        "created_at": row["created_at"],
        "completed_at": row["completed_at"],
    }
