"""SQLite 기반 문서 메타데이터 저장소.

문서 목록/진행상황/결과 텍스트를 관리한다. 처리 자체는 백그라운드
스레드에서 수행되고, 이 모듈을 통해 상태를 갱신한다.
스레드 안전성을 위해 매 호출마다 짧게 커넥션을 열고 닫는다.
"""
from __future__ import annotations

import json
import sqlite3
import threading
from datetime import datetime, timezone
from typing import Any, Optional

from . import config

_LOCK = threading.Lock()

_SCHEMA = """
CREATE TABLE IF NOT EXISTS documents (
    id          TEXT PRIMARY KEY,
    filename    TEXT NOT NULL,
    orig_path   TEXT NOT NULL,
    preview_path TEXT,
    status      TEXT NOT NULL DEFAULT 'queued',  -- queued|processing|done|error
    stage       TEXT NOT NULL DEFAULT '대기 중',
    progress    REAL NOT NULL DEFAULT 0,
    pages       INTEGER NOT NULL DEFAULT 1,
    lang        TEXT NOT NULL DEFAULT 'korean',
    options     TEXT NOT NULL DEFAULT '{}',
    text        TEXT NOT NULL DEFAULT '',
    error       TEXT,
    created_at  TEXT NOT NULL,
    updated_at  TEXT NOT NULL
);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(config.DB_PATH, timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db() -> None:
    config.ensure_dirs()
    with _LOCK, _connect() as conn:
        conn.executescript(_SCHEMA)


def _row_to_dict(row: sqlite3.Row, *, include_text: bool = True) -> dict[str, Any]:
    d = dict(row)
    try:
        d["options"] = json.loads(d.get("options") or "{}")
    except json.JSONDecodeError:
        d["options"] = {}
    if not include_text:
        d.pop("text", None)
    return d


def create_document(
    doc_id: str,
    filename: str,
    orig_path: str,
    lang: str,
    options: dict[str, Any],
    pages: int = 1,
) -> None:
    ts = _now()
    with _LOCK, _connect() as conn:
        conn.execute(
            """INSERT INTO documents
               (id, filename, orig_path, status, stage, progress, pages, lang,
                options, created_at, updated_at)
               VALUES (?, ?, ?, 'queued', '대기 중', 0, ?, ?, ?, ?, ?)""",
            (doc_id, filename, orig_path, pages, lang, json.dumps(options), ts, ts),
        )


def update_progress(doc_id: str, *, stage: str, progress: float,
                    status: str = "processing") -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE documents SET stage=?, progress=?, status=?, updated_at=? WHERE id=?",
            (stage, round(progress, 1), status, _now(), doc_id),
        )


def set_preview(doc_id: str, preview_path: str) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE documents SET preview_path=?, updated_at=? WHERE id=?",
            (preview_path, _now(), doc_id),
        )


def set_pages(doc_id: str, pages: int) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE documents SET pages=?, updated_at=? WHERE id=?",
            (pages, _now(), doc_id),
        )


def finish_document(doc_id: str, text: str) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """UPDATE documents SET status='done', stage='완료', progress=100,
               text=?, error=NULL, updated_at=? WHERE id=?""",
            (text, _now(), doc_id),
        )


def fail_document(doc_id: str, error: str) -> None:
    with _LOCK, _connect() as conn:
        conn.execute(
            """UPDATE documents SET status='error', stage='오류', error=?,
               updated_at=? WHERE id=?""",
            (error, _now(), doc_id),
        )


def update_text(doc_id: str, text: str) -> None:
    """사용자가 결과 텍스트를 편집해 저장할 때 사용."""
    with _LOCK, _connect() as conn:
        conn.execute(
            "UPDATE documents SET text=?, updated_at=? WHERE id=?",
            (text, _now(), doc_id),
        )


def get_document(doc_id: str) -> Optional[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        row = conn.execute("SELECT * FROM documents WHERE id=?", (doc_id,)).fetchone()
    return _row_to_dict(row) if row else None


def list_documents() -> list[dict[str, Any]]:
    with _LOCK, _connect() as conn:
        rows = conn.execute(
            "SELECT * FROM documents ORDER BY created_at DESC"
        ).fetchall()
    # 목록에는 본문 텍스트를 제외해 응답을 가볍게 유지
    return [_row_to_dict(r, include_text=False) for r in rows]


def delete_document(doc_id: str) -> Optional[dict[str, Any]]:
    doc = get_document(doc_id)
    if doc is None:
        return None
    with _LOCK, _connect() as conn:
        conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
    return doc


def reset_stuck_documents() -> None:
    """서버 재시작 시, 처리 중이던(processing) 문서를 오류로 표시.

    백그라운드 스레드는 재시작과 함께 사라지므로 좀비 상태를 정리한다.
    """
    with _LOCK, _connect() as conn:
        conn.execute(
            """UPDATE documents SET status='error', stage='중단됨',
               error='서버 재시작으로 처리가 중단되었습니다. 다시 시도해 주세요.',
               updated_at=? WHERE status IN ('processing','queued')""",
            (_now(),),
        )
