"""FastAPI 애플리케이션: 업로드, 진행상황 조회, 결과 제공, 정적 프론트 서빙."""
from __future__ import annotations

import uuid
from pathlib import Path
from typing import Any

import json

from fastapi import Body, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import (
    FileResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
    Response,
)
from fastapi.staticfiles import StaticFiles

from . import config, db, llm_correct, ocr_engine, pipeline, preview
from .preprocess import PreprocessOptions, preprocess_image

app = FastAPI(title="고문서 OCR 복원", version="1.0.0")


@app.middleware("http")
async def _no_cache_frontend(request, call_next):
    """프론트엔드(/app)·정적 자산을 브라우저가 캐시하지 않게 한다.

    업데이트한 뒤에도 브라우저가 옛 JS/HTML을 붙들어 새 화면이 안 보이는 문제를
    막는다(일반 새로고침만으로 항상 최신 화면이 뜨도록). 로컬 앱이라 캐시 끄는
    비용은 무시할 수 있다.
    """
    response = await call_next(request)
    if request.url.path.startswith("/app"):
        response.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
    return response


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
        "llm_available": llm_correct.available(),
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
    options: str = Form("{}"),
) -> JSONResponse:
    # options: 전처리 옵션 JSON 문자열(토글 + 미세조정 파라미터)
    try:
        opt_data = json.loads(options) if options else {}
    except (ValueError, TypeError):
        opt_data = {}
    opt = PreprocessOptions.from_dict(opt_data)

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
    # 페이지별 미리보기({doc_id}_p*.png)와 단일 미리보기를 모두 정리
    try:
        for f in config.PREVIEW_DIR.glob(f"{doc_id}*.png"):
            f.unlink(missing_ok=True)
    except Exception:
        pass
    return {"id": doc_id, "deleted": True}


@app.get("/api/documents/{doc_id}/preview")
def get_preview(doc_id: str, page: int | None = None):
    """전처리 미리보기 PNG. page(0-기반)를 주면 그 페이지를, 없으면 현재
    preview_path(처리 중이면 진행 페이지, 완료면 마지막 페이지)를 반환한다."""
    doc = db.get_document(doc_id)
    if doc is None:
        raise HTTPException(status_code=404, detail="문서를 찾을 수 없습니다.")
    if page is not None:
        path = config.PREVIEW_DIR / f"{doc_id}_p{int(page)}.png"
        if not path.exists() and doc.get("preview_path"):
            # 구버전에서 처리돼 페이지별 미리보기가 없으면 단일 미리보기로 폴백
            path = config.PREVIEW_DIR / doc["preview_path"]
    elif doc.get("preview_path"):
        path = config.PREVIEW_DIR / doc["preview_path"]
    else:
        raise HTTPException(status_code=404, detail="미리보기가 없습니다.")
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
# 전처리 미세조정 미리보기
# ---------------------------------------------------------------------------

@app.post("/api/preview/load")
async def preview_load(file: UploadFile = File(...)) -> dict[str, Any]:
    """파일을 캐시하고 토큰·총 페이지 수를 발급(이후 재업로드 없이 페이지별 조정)."""
    data = await file.read()
    if len(data) > config.MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="파일이 너무 큽니다.")
    try:
        token, pages, arr = preview.store_source(data, file.filename or "")
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"미리보기 로드 실패: {exc}")
    h, w = arr.shape[:2]
    return {"token": token, "width": w, "height": h, "pages": pages}


def _preview_page(payload: dict[str, Any]):
    """payload 의 token·page 로 캐시된 페이지 ndarray를 가져온다(없으면 404)."""
    try:
        page = int(payload.get("page", 0) or 0)
    except (TypeError, ValueError):
        page = 0
    arr = preview.get_page(str(payload.get("token", "")), page)
    if arr is None:
        raise HTTPException(status_code=404, detail="미리보기가 만료되었습니다. 다시 선택하세요.")
    return arr


@app.post("/api/preview/render")
def preview_render(payload: dict[str, Any] = Body(...)):
    """토큰 + 페이지 + 전처리 파라미터로 처리한 이미지를 PNG로 반환. raw=true면 원본."""
    arr = _preview_page(payload)
    if payload.get("raw"):
        png = preview.encode_png(arr)
    else:
        opt = PreprocessOptions.from_dict(payload)
        png = preview.encode_png(preprocess_image(arr, opt))
    return Response(content=png, media_type="image/png")


@app.post("/api/preview/measure")
def preview_measure(payload: dict[str, Any] = Body(...)) -> dict[str, Any]:
    """중앙 일부만 OCR해 전처리 설정의 OCR 적합도(신뢰도)를 빠르게 측정."""
    arr = _preview_page(payload)
    if not ocr_engine.paddle_available():
        raise HTTPException(status_code=400, detail="OCR 엔진이 설치되어 있지 않습니다.")
    opt = PreprocessOptions.from_dict(payload)
    proc = preprocess_image(arr, opt)
    crop = preview.center_crop(proc)
    lines = ocr_engine.run_ocr_lines(crop, config.HANGUL_LANG)
    scores = [l["score"] for l in lines if l.get("score")]
    mean = sum(scores) / len(scores) if scores else 0.0
    hi = sum(1 for s in scores if s >= 0.85)
    sample = " ".join(l["text"] for l in lines[:6] if l.get("text"))
    return {
        "mean_score": round(mean, 3),
        "lines": len(lines),
        "high_conf": hi,
        "sample": sample[:120],
    }


# ---------------------------------------------------------------------------
# 정적 프론트엔드 서빙
# ---------------------------------------------------------------------------

@app.get("/")
def index() -> RedirectResponse:
    return RedirectResponse(url="/app/")


# /app/ 경로로 SPA 정적 파일 제공 (index.html 자동)
app.mount("/app", StaticFiles(directory=str(config.FRONTEND_DIR), html=True),
          name="frontend")
