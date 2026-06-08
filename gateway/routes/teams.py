"""Team CRUD + run workflow.

GET    /api/teams          — list user's teams
POST   /api/teams          — create team
GET    /api/teams/{id}     — team detail
PUT    /api/teams/{id}     — update team
DELETE /api/teams/{id}     — delete team
POST   /api/teams/{id}/run — run workflow (sequential or manager)

WORKFLOW_RUNS tracked in-process (ephemeral dict — DB in B3.1).
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from gateway.auth.deps import get_current_user
from gateway.db import repo

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/teams", tags=["teams"])


# ── Schemas ──

class TeamMember(BaseModel):
    agent_id: str
    role_name: str = ""
    step_order: int = 1


class CreateTeamRequest(BaseModel):
    name: str
    description: str = ""
    workflow_mode: str = "sequential"
    members: list[TeamMember] = []


class UpdateTeamRequest(BaseModel):
    name: Optional[str] = None
    description: Optional[str] = None
    workflow_mode: Optional[str] = None
    members: Optional[list[TeamMember]] = None


class RunWorkflowRequest(BaseModel):
    prompt: str
    context: str = ""


# ── Workflow run tracking ──

# ── Routes ──

@router.get("")
async def list_teams(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    rows = repo.list_teams(user["id"])
    return {"teams": rows, "total": len(rows)}


@router.post("", status_code=201)
async def create_team(
    body: CreateTeamRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Team name is required")
    if body.workflow_mode not in ("sequential", "manager"):
        raise HTTPException(status_code=422, detail="workflow_mode must be 'sequential' or 'manager'")

    members = [m.model_dump() for m in body.members]

    team = repo.create_team(
        user_id=user["id"],
        name=name,
        description=body.description.strip(),
        workflow_mode=body.workflow_mode,
        members=members,
    )
    return team


@router.get("/{team_id}")
async def get_team(
    team_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    team = repo.get_team(user["id"], team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


@router.put("/{team_id}")
async def update_team(
    team_id: str,
    body: UpdateTeamRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    team = repo.get_team(user["id"], team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    members = [m.model_dump() for m in body.members] if body.members is not None else None

    updated = repo.update_team(
        user["id"], team_id,
        name=body.name,
        description=body.description,
        workflow_mode=body.workflow_mode,
        members=members,
    )
    if not updated:
        raise HTTPException(status_code=404, detail="Team not found")
    return updated


@router.delete("/{team_id}")
async def delete_team(
    team_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    deleted = repo.delete_team(user["id"], team_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Team not found")
    return {"deleted": True}


# ── Workflow run ──

@router.post("/{team_id}/run", status_code=202)
async def run_workflow(
    team_id: str,
    body: RunWorkflowRequest,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    team = repo.get_team(user["id"], team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    if not team["members"]:
        raise HTTPException(status_code=400, detail="Team has no members")

    run_id = repo.create_workflow_run(
        team_id=team_id,
        user_id=user["id"],
        prompt=body.prompt,
        workflow_mode=team["workflow_mode"],
    )

    # Launch background execution
    import asyncio
    asyncio.create_task(_execute_workflow(run_id, team, body.prompt, body.context))

    return {
        "run_id": run_id,
        "status": "queued",
        "team_name": team["name"],
        "workflow_mode": team["workflow_mode"],
        "members_count": len(team["members"]),
    }


@router.get("/{team_id}/runs")
async def list_team_runs(
    team_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List recent workflow runs for a team."""
    rows = repo.list_workflow_runs_by_team(team_id, user["id"])
    return {"runs": rows, "total": len(rows)}


@router.get("/runs/{run_id}")
async def get_workflow_run(
    run_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    run = repo.get_workflow_run(run_id)
    if not run or run["user_id"] != user["id"]:
        raise HTTPException(status_code=404, detail="Run not found")
    return run


# ── Workflow engine ──

async def _execute_workflow(
    run_id: str,
    team: dict,
    prompt: str,
    context: str,
) -> None:
    repo.update_workflow_run(run_id, status="running")

    try:
        if team["workflow_mode"] == "sequential":
            await _run_sequential(run_id, team, prompt, context)
        elif team["workflow_mode"] == "manager":
            await _run_manager(run_id, team, prompt, context)
        else:
            repo.update_workflow_run(run_id, status="failed", error=f"Unknown workflow mode: {team['workflow_mode']}", completed=True)
    except Exception as e:
        logger.exception("Workflow %s failed", run_id)
        repo.update_workflow_run(run_id, status="failed", error=str(e), completed=True)


async def _run_sequential(
    run_id: str,
    team: dict,
    prompt: str,
    context: str,
) -> None:
    """Run agents in order: A → B → C, passing context forward."""
    members = sorted(team["members"], key=lambda m: m.get("step_order", 0))
    current_input = prompt
    accumulated_context = context

    for i, member in enumerate(members):
        step = {
            "step": i + 1,
            "agent_id": member["agent_id"],
            "role_name": member.get("role_name", ""),
            "status": "running",
            "input": current_input,
            "output": None,
            "error": None,
        }
        repo.update_workflow_run(run_id, steps=None)  # ensure row exists
        current_steps = _get_steps(run_id) + [step]
        repo.update_workflow_run(run_id, status="running", steps=current_steps)

        try:
            output = await _call_agent(member["agent_id"], current_input, accumulated_context)
            step["status"] = "ok"
            step["output"] = output
            # Pass output as input to next agent
            current_input = output
            accumulated_context = f"{accumulated_context}\n\n--- 上一步输出 ---\n{output}"
            current_steps[-1] = step
            repo.update_workflow_run(run_id, steps=current_steps)
        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            current_steps[-1] = step
            repo.update_workflow_run(run_id, status="failed", steps=current_steps, error=f"Step {i + 1} ({member.get('role_name', '')}) failed: {e}", completed=True)
            return

    repo.update_workflow_run(run_id, status="ok", steps=_get_steps(run_id), result=current_input, completed=True)


async def _run_manager(
    run_id: str,
    team: dict,
    prompt: str,
    context: str,
) -> None:
    """Manager mode: first member = PM, rest = specialists."""
    members = team["members"]
    if len(members) < 2:
        await _run_sequential(run_id, team, prompt, context)
        return

    pm = members[0]
    specialists = members[1:]

    # Step 1: PM analyzes request and creates plan
    step_plan = {
        "step": 1,
        "agent_id": pm["agent_id"],
        "role_name": pm.get("role_name", "PM"),
        "status": "running",
        "input": prompt,
        "output": None,
        "error": None,
    }
    repo.update_workflow_run(run_id, steps=[step_plan], status="running")

    try:
        plan_prompt = (
            f"你是一个项目经理。请分析以下需求，拆分成最多 {len(specialists)} 个子任务，"
            f"每个子任务分配给一个专家（角色列表见下）。\n\n"
            f"需求: {prompt}\n\n"
            f"可用专家: {', '.join(s.get('role_name', '') or s['agent_id'] for s in specialists)}\n\n"
            f"请输出一个 JSON 数组，每个元素包含: task_name, assigned_role, instructions\n"
        )
        plan_result = await _call_agent(pm["agent_id"], plan_prompt, context)
        step_plan["status"] = "ok"
        step_plan["output"] = plan_result
        repo.update_workflow_run(run_id, steps=[step_plan])

        subtasks = _parse_subtasks(plan_result, specialists)
        if not subtasks:
            subtasks = [
                {"task_name": f"分析任务", "assigned_role": s.get("role_name", ""), "agent_id": s["agent_id"], "instructions": prompt}
                for s in specialists
            ]
    except Exception as e:
        step_plan["status"] = "failed"
        step_plan["error"] = str(e)
        repo.update_workflow_run(run_id, status="failed", steps=[step_plan], error=f"PM planning failed: {e}", completed=True)
        return

    # Steps 2+: Specialists execute subtasks
    all_steps = [step_plan]
    specialist_outputs = {}
    for i, subtask in enumerate(subtasks):
        agent_id = subtask.get("agent_id", "")
        role_name = subtask.get("assigned_role", f"专家{i+1}")
        step = {
            "step": i + 2,
            "agent_id": agent_id,
            "role_name": role_name,
            "status": "running",
            "input": subtask.get("instructions", prompt),
            "output": None,
            "error": None,
        }
        all_steps.append(step)
        repo.update_workflow_run(run_id, steps=all_steps)

        try:
            output = await _call_agent(agent_id, step["input"], context)
            step["status"] = "ok"
            step["output"] = output
            specialist_outputs[role_name] = output
            all_steps[-1] = step
            repo.update_workflow_run(run_id, steps=all_steps)
        except Exception as e:
            step["status"] = "failed"
            step["error"] = str(e)
            all_steps[-1] = step
            specialist_outputs[role_name] = f"[Error: {e}]"
            repo.update_workflow_run(run_id, steps=all_steps)

    # Final step: PM merges results
    merge_input = (
        f"原始需求: {prompt}\n\n"
        f"各专家输出:\n\n"
        + "\n\n".join(f"### {role}\n{output}" for role, output in specialist_outputs.items())
        + "\n\n请整合以上所有专家的输出，生成最终的综合报告。"
    )

    step_merge = {
        "step": len(subtasks) + 2,
        "agent_id": pm["agent_id"],
        "role_name": pm.get("role_name", "PM"),
        "status": "running",
        "input": merge_input,
        "output": None,
        "error": None,
    }
    all_steps.append(step_merge)
    repo.update_workflow_run(run_id, steps=all_steps)

    try:
        final = await _call_agent(pm["agent_id"], merge_input, context)
        step_merge["status"] = "ok"
        step_merge["output"] = final
        all_steps[-1] = step_merge
        repo.update_workflow_run(run_id, status="ok", steps=all_steps, result=final, completed=True)
    except Exception as e:
        step_merge["status"] = "failed"
        step_merge["error"] = str(e)
        all_steps[-1] = step_merge
        repo.update_workflow_run(run_id, status="failed", steps=all_steps, error=f"PM merge failed: {e}", completed=True)


def _get_steps(run_id: str) -> list[dict]:
    run = repo.get_workflow_run(run_id)
    return run["steps"] if run else []


def _parse_subtasks(plan_result: str, specialists: list[dict]) -> list[dict]:
    """Best-effort parse JSON subtasks from PM's plan output."""
    import re
    # Try to extract JSON array
    match = re.search(r'\[[\s\S]*?\]', plan_result)
    if match:
        try:
            tasks = json.loads(match.group())
            # Map to specialists
            for t in tasks:
                role = t.get("assigned_role", "")
                for s in specialists:
                    if s.get("role_name", "") == role:
                        t["agent_id"] = s["agent_id"]
                        break
                if "agent_id" not in t:
                    t["agent_id"] = specialists[0]["agent_id"] if specialists else ""
            return tasks
        except (json.JSONDecodeError, KeyError):
            pass
    return []


async def _call_agent(agent_id: str, prompt: str, context: str = "") -> str:
    """Call a single agent via TaskAgent's synchronous API.

    Falls back to a local seed agent call if taskagent is unavailable.
    """
    from gateway import config

    combined = f"{context}\n\n{prompt}" if context else prompt

    # Try calling TaskAgent first
    taskagent_url = config.TASKAGENT_URL
    if taskagent_url:
        try:
            import httpx
            async with httpx.AsyncClient(timeout=120) as client:
                resp = await client.post(
                    f"{taskagent_url}/tasks/run",
                    json={
                        "agent_id": agent_id,
                        "message": combined,
                        "ephemeral": True,
                    },
                )
                if resp.is_success:
                    data = resp.json()
                    return data.get("reply") or data.get("result", "")
                logger.warning("TaskAgent returned %s, falling back to local", resp.status_code)
        except Exception as e:
            logger.warning("TaskAgent call failed: %s, falling back to local", e)

    # Fallback: direct seed call
    return await _call_agent_local(agent_id, combined)


async def _call_agent_local(agent_id: str, message: str) -> str:
    """Run agent locally via seed's task runner."""
    try:
        from seed.integrations.task_runner import RunContext, run_agent_task

        ctx = RunContext(
            agent_id=agent_id,
            user_message=message,
            session_id=f"wf-{uuid.uuid4().hex[:12]}",
            ephemeral=True,
            max_tool_rounds=16,
            timeout_sec=120,
        )
        result = await run_agent_task(ctx)
        if result.status == "ok":
            return result.reply
        raise Exception(result.error or f"Agent returned status: {result.status}")
    except Exception as e:
        logger.error("Local agent call failed for %s: %s", agent_id, e)
        raise
