"""
Wraps Supabase Storage (object storage, separate from the Postgres
database) for the extracted .txt files. Postgres only ever holds a
pointer (storage_path) plus small metadata — never the full text —
which keeps the 500 MB free-tier database quota untouched no matter
how much material a subject accumulates.
"""

from __future__ import annotations
import uuid
from db import get_client
from config import MATERIALS_BUCKET


def _safe_path(subject_id: str, material_type: str, filename: str) -> str:
    unique = uuid.uuid4().hex[:12]
    safe_name = "".join(c for c in filename if c.isalnum() or c in "._-") or "file"
    return f"{subject_id}/{material_type}/{unique}_{safe_name}.txt"


def upload_text(subject_id: str, material_type: str, filename: str, text: str) -> str:
    """Uploads extracted text as a .txt object and returns its storage path."""
    sb = get_client()
    path = _safe_path(subject_id, material_type, filename)
    sb.storage.from_(MATERIALS_BUCKET).upload(
        path,
        text.encode("utf-8"),
        {"content-type": "text/plain; charset=utf-8"},
    )
    return path


def download_text(storage_path: str) -> str:
    sb = get_client()
    data = sb.storage.from_(MATERIALS_BUCKET).download(storage_path)
    return data.decode("utf-8", errors="ignore")


def delete_objects(storage_paths: list[str]) -> None:
    if not storage_paths:
        return
    sb = get_client()
    sb.storage.from_(MATERIALS_BUCKET).remove(storage_paths)
