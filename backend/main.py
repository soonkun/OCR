"""FastAPI 애플리케이션: 업로드, 진행상황 조회, 결과 제공, 정적 프론트 서빙."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles

from . import config, db, ocr_engine, pipeline
from .preprocess import PreprocessOptions

app = FastAPI(title="고문서 OCR 복원", version="1.0.0")


@app.on_event("startup")
def _startup() -> None:
    config.ensure_dirs()
    db.init_db()
    db.reset_stuck_documents()


@app.on_event("shutdown")
def _shutdown() -> None:
    pipeline.shutdown()


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/api/health")
def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "paddle_available": ocr_engine.paddle_available(),
        "default_lang": config.DEFAULT_LANG,
    }


@app.get("/api/documents")
def get_documents() -> list[dict[str, Any]]:
    return db.list_documents()


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str) -> dict[str, Any]:
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    return doc


def _parse_bool(value: str | None, default: bool) -> bool:
    if value is None:
        return default
    return value.strip().lower() in ("1", "true", "on", "yes")


@app.post("/api/documents")
async def upload_documents(
    files: list[UploadFile] = File(...),
    lang: str = Form(config.DEFAULT_LANG),
    grayscale: str | None = Form(None),
    denoise: str | None = Form(None),
    upscale: str | None = Form(None),
    deskew: str | None = Form(None),
    binarize: str | None = Form(None),
) -> JSONResponse:
    opt = PreprocessOptions(
        grayscale=_parse_bool(grayscale, True),
        denoise=_parse_bool(denoise, True),
        upscale=_parse_bool(upscale, True),
        deskew=_parse_bool(deskew, True),
        binarize=_parse_bool(binarize, True),
    )

    created: list[dict[str, Any]] = []
    for upload in files:
        ext = Path(upload.filename or "").suffix.lower()
        if ext not in config.ALLOWED_EXTS:
            raise HTTPException(
                status_code=400,
                detail=f"지원하지 않는 형식입니다: {upload.filename}",
            )
        data = await upload.read()
        if len(data) > config.MAX_UPLOAD_BYTES:
            raise HTTPException(
                status_code=413,
                detail=f"파일이 너무 큽니다: {upload.filename}",
            )

        doc_id = uuid.uuid4().hex
        dest = config.UPLOAD_DIR / f"{doc_id}{ext}"
        dest.write_bytes(data)

        db.create_document(
            doc_id=doc_id,
            filename=upload.filename or f"document{ext}",
            orig_path=str(dest),
            lang=lang,
            options=opt.to_dict(),
        )
        pipeline.submit(doc_id)
        created.append({"id": doc_id, "filename": upload.filename})

    return JSONResponse(status_code=201, content={"created": created})


@app.post("/api/documents/{doc_id}/retry")
def retry_document(doc_id: str) -> dict[str, Any]:
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    db.update_progress(doc_id, stage="대기 중", progress=0, status="queued")
    pipeline.submit(doc_id)
    return {"id": doc_id, "status": "queued"}


@app.put("/api/documents/{doc_id}/text")
async def save_text(doc_id: str, payload: dict[str, Any]) -> dict[str, Any]:
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    text = str(payload.get("text", ""))
    db.update_text(doc_id, text)
    return {"id": doc_id, "saved": True}


@app.delete("/api/documents/{doc_id}")
def remove_document(doc_id: str) -> dict[str, Any]:
    doc = db.delete_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    # 관련 파일 정리
    for key in ("orig_path",):
        try:
            Path(doc[key]).unlink(missing_ok=True)
        except Exception:
            pass
    if doc.get("preview_path"):
        try:
            (config.PREVIEW_DIR / doc["preview_path"]).unlink(missing_ok=True)
        except Exception:
            pass
    return {"id": doc_id, "deleted": True}


@app.get("/api/documents/{doc_id}/preview")
def get_preview(doc_id: str):
    doc = db.get_document(doc_id)
    if doc is None or not doc.get("preview_path"):
        raise HTTPException(status_code=404, detail="미리보기가 없습니다.")
    path = config.PREVIEW_DIR / doc["preview_path"]
    if not path.exists():
        raise HTTPException(status_code=404, detail="미리보기가 없습니다.")
    return FileResponse(path, media_type="image/png")


@app.get("/api/documents/{doc_id}/download")
def download_text(doc_id: str):
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    base = Path(doc["filename"]).stem or doc_id
    # 한글 등 비ASCII 파일명은 RFC5987(filename*)로 인코딩, ASCII 폴백도 제공
    from urllib.parse import quote

    ascii_name = base.encode("ascii", "ignore").decode("ascii") or doc_id
    disposition = (
        f"attachment; filename=\"{ascii_name}.txt\"; "
        f"filename*=UTF-8''{quote(base + '.txt')}"
    )
    headers = {"Content-Disposition": disposition}
    return PlainTextResponse(
        content=doc.get("text", ""),
        headers=headers,
        media_type="text/plain; charset=utf-8",
    )


# ---------------------------------------------------------------------------
# 정적 프론트엔드 서빙
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/app/")


# /app/ 경로로 SPA 정적 파일 제공 (index.html 자동)
app.mount("/app", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
          name="frontend")
