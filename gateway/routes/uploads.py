"""Upload routes: POST /api/uploads, GET /api/uploads, GET /api/uploads/{id}.

Flow:
1. Receive multipart file (FastAPI UploadFile)
2. Validate size + extension
3. Stream to disk under uploads/<user_id>/<upload_id>.<ext>
4. Parse via gateway.parsers
5. Store parsed JSON + metadata in DB
6. Return upload record (without the raw bytes)

Phase 2 limits: sync parse (small files only, <= MAX_UPLOAD_MB).
"""

from __future__ import annotations

import json
import logging
import shutil
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from gateway import config
from gateway.auth.deps import get_current_user
from gateway.db import repo
from gateway.parsers import ParserError, parse_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/uploads", tags=["uploads"])


def _max_bytes() -> int:
    """Computed at call time so tests can monkeypatch MAX_UPLOAD_MB."""
    return config.MAX_UPLOAD_MB * 1024 * 1024


def _validate_extension(filename: str) -> str:
    """Return the lowercased extension if allowed, else raise 400."""
    ext = Path(filename).suffix.lower()
    if ext not in config.ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Allowed: {sorted(config.ALLOWED_EXTENSIONS)}",
        )
    return ext


@router.post("", status_code=201)
async def upload_file(
    file: UploadFile = File(...),
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Upload + parse a single file. Returns upload record (with parsed summary)."""
    if not file.filename:
        raise HTTPException(status_code=400, detail="Missing filename")

    ext = _validate_extension(file.filename)
    size_bytes = 0
    target_dir = config.UPLOADS_DIR / user["id"]
    target_dir.mkdir(parents=True, exist_ok=True)

    # Create upload record FIRST to get an ID (for storage path)
    # We do this by buffering to a temp file, then committing.
    # Simpler: reserve an ID, write directly, then insert DB row.
    upload_id = repo.new_upload_id()
    target_path = target_dir / f"{upload_id}{ext}"

    parse_status = "ok"
    parse_error: Optional[str] = None
    parsed: Optional[dict] = None

    try:
        with target_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 64)  # 64 KiB
                if not chunk:
                    break
                size_bytes += len(chunk)
                if size_bytes > _max_bytes():
                    out.close()
                    target_path.unlink(missing_ok=True)
                    raise HTTPException(
                        status_code=413,
                        detail=f"File too large (> {config.MAX_UPLOAD_MB} MB)",
                    )
                out.write(chunk)
    except HTTPException:
        raise
    except Exception as e:
        target_path.unlink(missing_ok=True)
        logger.exception("upload write failed")
        raise HTTPException(status_code=500, detail=f"Failed to save upload: {e}")

    # Parse
    try:
        parsed = parse_file(target_path)
    except ParserError as e:
        parse_status = "failed"
        parse_error = str(e)
        logger.warning("Parse failed for %s: %s", file.filename, e)
    except Exception as e:
        parse_status = "failed"
        parse_error = f"unexpected: {e}"
        logger.exception("Parse crashed for %s", file.filename)
    finally:
        await file.close()

    # Serialize parsed JSON to a string for storage
    parsed_json_str: Optional[str] = None
    if parsed is not None:
        try:
            parsed_json_str = json.dumps(parsed, ensure_ascii=False, default=str)
        except (TypeError, ValueError) as e:
            parse_status = "failed"
            parse_error = f"parsed content not JSON-serializable: {e}"
            parsed_json_str = None

    record = repo.create_upload(
        user_id=user["id"],
        filename=file.filename,
        content_type=file.content_type,
        size_bytes=size_bytes,
        storage_path=str(target_path),
        parsed_json=parsed_json_str,
        parse_status=parse_status,
        parse_error=parse_error,
        upload_id=upload_id,  # use the pre-allocated ID so DB row matches on-disk path
    )
    return {
        "id": record["id"],
        "filename": record["filename"],
        "size_bytes": record["size_bytes"],
        "content_type": record["content_type"],
        "parse_status": record["parse_status"],
        "parse_error": record["parse_error"],
        "summary": (parsed or {}).get("summary") if parsed else None,
        "created_at": record["created_at"],
    }


@router.get("")
async def list_uploads(
    limit: int = 50,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """List current user's uploads (most recent first)."""
    rows = repo.list_uploads(user_id=user["id"], limit=min(max(limit, 1), 200))
    return {
        "uploads": [
            {
                "id": r["id"],
                "filename": r["filename"],
                "size_bytes": r["size_bytes"],
                "parse_status": r["parse_status"],
                "parse_error": r["parse_error"],
                "created_at": r["created_at"],
            }
            for r in rows
        ]
    }


@router.get("/{upload_id}")
async def get_upload(
    upload_id: str,
    user: dict = Depends(get_current_user),
) -> dict[str, Any]:
    """Get a single upload record (including parsed JSON)."""
    row = repo.get_upload(user_id=user["id"], upload_id=upload_id)
    if not row:
        raise HTTPException(status_code=404, detail="Upload not found")
    parsed = None
    if row.get("parsed_json"):
        try:
            parsed = json.loads(row["parsed_json"])
        except json.JSONDecodeError:
            parsed = None
    return {
        "id": row["id"],
        "filename": row["filename"],
        "size_bytes": row["size_bytes"],
        "content_type": row["content_type"],
        "parse_status": row["parse_status"],
        "parse_error": row["parse_error"],
        "summary": (parsed or {}).get("summary"),
        "rows": (parsed or {}).get("rows"),
        "data": (parsed or {}).get("data"),
        "created_at": row["created_at"],
    }
