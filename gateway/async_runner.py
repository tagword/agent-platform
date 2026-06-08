"""In-process background task runner.

Spawns a single asyncio task at app startup; tasks are queued in-memory and
executed serially per-user (no global concurrency limit needed for v1).

For multi-process / multi-host scale-out, replace the queue with Redis
(KEEP-API-COMPATIBLE: same enqueue/execute signatures).
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass
from typing import Any, Optional

from gateway import config
from gateway.db import repo
from gateway.taskagent_client import TaskAgentError, run_task

logger = logging.getLogger(__name__)


@dataclass
class _QueueItem:
    user_task_id: str
    user_id: str
    upload_id: str
    agent_id: str
    user_instructions: str
    dataset_name: Optional[str]


class TaskQueue:
    """Simple asyncio queue. Singleton owned by the app process."""

    def __init__(self) -> None:
        self._q: asyncio.Queue[_QueueItem] = asyncio.Queue()
        self._worker_task: Optional[asyncio.Task] = None
        self._stop_event: Optional[asyncio.Event] = None

    async def enqueue(self, item: _QueueItem) -> None:
        await self._q.put(item)
        # Lazy-start: if not yet started (e.g. in tests with sync TestClient),
        # kick the worker once.
        if self._worker_task is None:
            await self.start()

    def qsize(self) -> int:
        return self._q.qsize()

    async def start(self) -> None:
        if self._worker_task is not None:
            return
        self._stop_event = asyncio.Event()
        self._worker_task = asyncio.create_task(self._worker_loop())
        logger.info("AsyncTaskQueue worker started")

    async def stop(self) -> None:
        if self._stop_event is not None:
            self._stop_event.set()
        if self._worker_task is not None:
            self._worker_task.cancel()
            try:
                await self._worker_task
            except asyncio.CancelledError:
                pass
        self._worker_task = None
        self._stop_event = None
        logger.info("AsyncTaskQueue worker stopped")

    async def _worker_loop(self) -> None:
        while True:
            if self._stop_event and self._stop_event.is_set() and self._q.empty():
                logger.info("Worker exiting: stop event set + queue empty")
                return
            try:
                item = await asyncio.wait_for(self._q.get(), timeout=0.5)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                # Drain remaining items? For v1, just drop them.
                return
            try:
                await self._execute(item)
            except Exception:
                logger.exception("Async task %s crashed in worker", item.user_task_id)

    async def _execute(self, item: _QueueItem) -> None:
        # 1. Load upload
        upload = repo.get_upload(user_id=item.user_id, upload_id=item.upload_id)
        if not upload:
            repo.update_user_task(
                item.user_task_id, status="failed",
                error=f"upload disappeared: {item.upload_id}", completed=True,
            )
            return
        if upload.get("parse_status") != "ok":
            repo.update_user_task(
                item.user_task_id, status="failed",
                error=f"upload no longer parseable: {upload.get('parse_error')}", completed=True,
            )
            return

        # 2. Load agent
        agent = repo.get_agent_template(item.agent_id)
        if not agent or not agent.get("enabled"):
            repo.update_user_task(
                item.user_task_id, status="failed",
                error=f"agent no longer available: {item.agent_id}", completed=True,
            )
            return

        # 3. Parse
        try:
            parsed = json.loads(upload["parsed_json"])
        except (json.JSONDecodeError, TypeError):
            repo.update_user_task(
                item.user_task_id, status="failed",
                error="stored parse data is corrupt", completed=True,
            )
            return

        # 4. Mark running
        repo.update_user_task(item.user_task_id, status="running")

        # 5. Call TaskAgent
        file_meta = {
            "filename": upload["filename"],
            "size_bytes": upload["size_bytes"],
            "content_type": upload.get("content_type"),
            "dataset_name": item.dataset_name or upload["filename"],
            "upload_id": upload["id"],
        }
        try:
            result = await run_task(
                job_id=agent["job_id"],
                raw_data=parsed,
                user_instructions=item.user_instructions,
                file_meta=file_meta,
            )
        except TaskAgentError as e:
            logger.warning("Async task %s: TaskAgent error: %s", item.user_task_id, e)
            repo.update_user_task(
                item.user_task_id, status="failed", error=str(e), completed=True,
            )
            return

        # 6. Persist result
        status_out = result.get("status", "ok")
        if status_out not in ("ok", "failed", "timeout", "cancelled"):
            status_out = "ok"
        repo.update_user_task(
            item.user_task_id,
            status=status_out,
            taskagent_task_id=result.get("task_id"),
            report_md=result.get("reply") or "",
            error=result.get("error"),
            duration_ms=result.get("duration_ms"),
            completed=True,
        )
        logger.info("Async task %s completed: %s", item.user_task_id, status_out)


# Module-level singleton
_queue: Optional[TaskQueue] = None


def get_queue() -> TaskQueue:
    global _queue
    if _queue is None:
        _queue = TaskQueue()
    return _queue


def reset_queue() -> None:
    """Test helper: drop the singleton (worker is cancelled via stop())."""
    global _queue
    _queue = None
