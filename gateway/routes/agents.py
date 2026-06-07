"""Agent template routes: GET /api/agents, GET /api/agents/{id}.

Phase 3: read-only listing. Editing / publishing is via the seed_templates/
package files + the `scripts/seed_agents.py` bootstrapper.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from gateway.auth.deps import get_current_user
from gateway.db import repo

router = APIRouter(prefix="/api/agents", tags=["agents"])


@router.get("")
async def list_agents(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = repo.list_agent_templates(enabled_only=True)
    return {
        "agents": [
            {
                "id": r["id"],
                "name": r["name"],
                "description": r["description"],
                "version": r["version"],
                "bundle": r["bundle"],
                "job_id": r["job_id"],
            }
            for r in rows
        ]
    }


@router.get("/{agent_id}")
async def get_agent(agent_id: str, user: dict = Depends(get_current_user)) -> dict[str, Any]:
    row = repo.get_agent_template(agent_id)
    if not row or not row.get("enabled"):
        raise HTTPException(status_code=404, detail=f"Agent not found: {agent_id}")
    return {
        "id": row["id"],
        "name": row["name"],
        "description": row["description"],
        "version": row["version"],
        "bundle": row["bundle"],
        "job_id": row["job_id"],
    }
