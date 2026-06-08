"""User Agent CRUD: POST/GET/PUT/DELETE /api/user-agents.

On create/update, also write:
  {agent_home}/{agent_id}/tools.json       — tool whitelist for seed
  {agent_home}/{agent_id}/persona/system.md — system prompt
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gateway.auth.deps import get_current_user
from gateway.db import repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/user-agents", tags=["user_agents"])


# ── Pydantic schemas ──


class CreateAgentRequest(BaseModel):
    name: str
    description: str = ""
    system_prompt: str = ""
    tools: list[str] = []
    model: str = ""


class UpdateAgentRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    system_prompt: Optional[str] = None
    tools: Optional[list[str]] = None
    model: Optional[str] = None


# ── Seed integration helpers ──


def _write_agent_tools(agent_id: str, tools: list[str]) -> None:
    """Write tools.json so seed's get_tools_for_agent() picks it up.

    Format: { "acquired": { "allow": [...] } }
    """
    try:
        from seed.core.paths import agent_home, ensure_agent_dirs

        home = ensure_agent_dirs(agent_id)
        tools_path = home / "tools.json"
        data = {"acquired": {"allow": list(tools)}}
        tools_path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        logger.info("Wrote tools.json for agent %s (%d tools)", agent_id, len(tools))
    except Exception as e:
        logger.warning("Failed to write tools.json for agent %s: %s", agent_id, e)


def _write_agent_persona(agent_id: str, system_prompt: str) -> None:
    """Write system.md so seed loads it as the agent's system prompt.

    seed loads: {agent_home}/{agent_id}/persona/system.md
    """
    try:
        from seed.core.paths import ensure_agent_dirs

        home = ensure_agent_dirs(agent_id)
        persona_dir = home / "persona"
        persona_dir.mkdir(parents=True, exist_ok=True)
        system_path = persona_dir / "system.md"
        system_path.write_text(system_prompt.strip(), encoding="utf-8")
        logger.info("Wrote persona/system.md for agent %s (%d chars)", agent_id, len(system_prompt))
    except Exception as e:
        logger.warning("Failed to write persona for agent %s: %s", agent_id, e)


def _remove_agent_dirs(agent_id: str) -> None:
    """Clean up agent home directory on delete."""
    try:
        from seed.core.paths import agent_home
        import shutil

        home = agent_home(agent_id)
        if home.exists():
            shutil.rmtree(str(home))
            logger.info("Removed agent home for %s", agent_id)
    except Exception as e:
        logger.warning("Failed to remove agent home for %s: %s", agent_id, e)


# ── Routes ──


@router.get("")
async def list_user_agents(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = repo.list_user_agents(user["id"])
    return {"agents": rows, "total": len(rows)}


@router.post("", status_code=201)
async def create_user_agent(
    body: CreateAgentRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Agent name is required")
    if len(name) > 64:
        raise HTTPException(status_code=422, detail="Agent name too long (max 64)")

    agent = repo.create_user_agent(
        user_id=user["id"],
        name=name,
        description=body.description.strip(),
        system_prompt=body.system_prompt.strip(),
        tools=body.tools,
        model=body.model.strip(),
    )

    # Write to seed agent home
    _write_agent_tools(agent["id"], body.tools)
    _write_agent_persona(agent["id"], body.system_prompt)

    # Invalidate seed tool cache so subsequent runs pick up new tools
    _reset_tool_cache()

    return agent


@router.get("/{agent_id}")
async def get_user_agent(
    agent_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    agent = repo.get_user_agent(user["id"], agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")
    return agent


@router.put("/{agent_id}")
async def update_user_agent(
    agent_id: str,
    body: UpdateAgentRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    agent = repo.get_user_agent(user["id"], agent_id)
    if not agent:
        raise HTTPException(status_code=404, detail="Agent not found")

    updated = repo.update_user_agent(
        user["id"], agent_id,
        name=body.name,
        description=body.description,
        system_prompt=body.system_prompt,
        tools=body.tools,
        model=body.model,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Agent not found")

    # Sync seed agent home
    final_tools = body.tools if body.tools is not None else agent["tools"]
    final_prompt = body.system_prompt if body.system_prompt is not None else agent["system_prompt"]
    _write_agent_tools(agent_id, final_tools)
    _write_agent_persona(agent_id, final_prompt)
    _reset_tool_cache()

    return updated


@router.delete("/{agent_id}")
async def delete_user_agent(
    agent_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    deleted = repo.delete_user_agent(user["id"], agent_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Agent not found")
    _remove_agent_dirs(agent_id)
    _reset_tool_cache()
    return {"deleted": True}


def _reset_tool_cache() -> None:
    try:
        from seed.integrations.agent_tools import reset_agent_tools_cache
        reset_agent_tools_cache()
    except Exception:
        pass
