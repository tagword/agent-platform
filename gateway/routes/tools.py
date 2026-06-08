"""Available tools listing — from seed-tools registration.

GET /api/available-tools  →  list of tools with name & description.
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends

from gateway.auth.deps import get_current_user

router = APIRouter(prefix="/api", tags=["tools"])


@router.get("/available-tools")
async def list_available_tools(user: dict = Depends(get_current_user)) -> dict[str, Any]:
    """Return all tools available in seed-tools (no auth filter yet)."""
    try:
        from seed_tools._registration import setup_builtin_tools
        reg, _ = setup_builtin_tools()
    except Exception as e:
        return {"tools": [], "total": 0, "error": str(e)}

    tools = []
    for name, tool_def in sorted(reg.tools.items(), key=lambda x: x[0].lower()):
        # Build category from tool description or name
        cat = _categorize(name, tool_def.description or "")
        tools.append({
            "name": name,
            "description": tool_def.description or "",
            "category": cat,
        })

    # Group by category
    grouped: dict[str, list[dict]] = {}
    for t in tools:
        grouped.setdefault(t["category"], []).append({"name": t["name"], "description": t["description"]})

    return {
        "tools": tools,
        "grouped": grouped,
        "total": len(tools),
    }


def _categorize(name: str, desc: str) -> str:
    """Simple category heuristic based on name prefix / keyword."""
    if name.startswith("browser_"):
        return "浏览器"
    if name.startswith("file_") or name in ("glob_tool", "grep_tool", "artifact_read"):
        return "文件操作"
    if name.startswith("web_") or name == "web_search_tool":
        return "网络"
    if name.startswith("seed_cron") or name.startswith("codeagent_cron"):
        return "系统"
    if name in ("bash_tool", "bash_exec"):
        return "命令行"
    if name.startswith("mcp_"):
        return "MCP"
    if name in ("code_check", "code_analyze", "test_gen", "test_run", "lsp_definition", "lsp_diagnostics"):
        return "开发"
    if name in ("symbol_search", "symbol_index_refresh", "refactor", "diagram"):
        return "开发"
    if name in ("project", "scaffold", "api_docs", "deps_check", "deploy", "apply_patch", "pipeline"):
        return "开发"
    if name in ("image_generate", "music_generate", "video_generate"):
        return "创作"
    if name in ("vision_analyze", "vision_analyze_directory", "audio_transcribe", "video_analyze"):
        return "媒体分析"
    if name in ("db",):
        return "数据"
    if name in ("git",):
        return "Git"
    if name in ("memory_search", "self_reflect"):
        return "记忆"
    if name in ("hub_send",):
        return "通信"
    if name in ("todo_tool", "tool_search_tool", "workspace_verify", "whoami", "echo", "calculate", "counter", "wbs_draft"):
        return "通用"
    if name in ("notebook_edit_tool",):
        return "笔记本"
    if name in ("instruction_read",):
        return "指令"
    return "其他"
