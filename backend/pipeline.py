"""문서 처리 파이프라인: 로드 → 전처리 → OCR → 결과 저장.

백그라운드 스레드풀에서 실행되며, 진행상황을 db 모듈을 통해 갱신한다.
이미지/PDF(여러 페이지)를 지원한다.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

import cv2
import numpy as np

from . import config, db, dual_ocr, llm_correct, ocr_engine
from .preprocess import PreprocessOptions, preprocess_image

_EXECUTOR = ThreadPoolExecutor(max_workers=config.MAX_WORKERS)


def submit(doc_id: str) -> None:
    """문서를 백그라운드 처리 큐에 등록."""
    _EXECUTOR.submit(_safe_process, doc_id)


def shutdown() -> None:
    _EXECUTOR.shutdown(wait=False, cancel_futures=True)


def _safe_process(doc_id: str) -> None:
    try:
        _process(doc_id)
    except Exception as exc:  # 어떤 예외든 문서를 오류 상태로
        db.fail_document(doc_id, f"{type(exc).__name__}: {exc}")


def _load_pages(path: Path) -> list[np.ndarray]:
    """파일 경로에서 BGR 이미지 페이지 리스트를 만든다 (PDF는 다중 페이지)."""
    if path.suffix.lower() == ".pdf":
        return _load_pdf_pages(path)
    img = cv2.imdecode(np.fromfile(str(path), dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다 (손상되었거나 지원하지 않는 형식).")
    return [img]


def _load_pdf_pages(path: Path) -> list[np.ndarray]:
    try:
        import pypdfium2 as pdfium
    except Exception as exc:  # pragma: no cover
        raise RuntimeError(
            "PDF 처리를 위해 pypdfium2가 필요합니다: pip install pypdfium2"
        ) from exc

    pages: list[np.ndarray] = []
    pdf = pdfium.PdfDocument(str(path))
    try:
        for i in range(len(pdf)):
            page = pdf[i]
            # scale=3 ≈ 216 DPI 정도로 렌더링 (저화질 보완)
            bitmap = page.render(scale=3.0)
            pil_img = bitmap.to_pil().convert("RGB")
            arr = cv2.cvtColor(np.asarray(pil_img), cv2.COLOR_RGB2BGR)
            pages.append(arr)
    finally:
        pdf.close()
    if not pages:
        raise ValueError("PDF에서 페이지를 찾을 수 없습니다.")
    return pages


def _save_preview(doc_id: str, processed: np.ndarray) -> None:
    """전처리된 첫 페이지를 미리보기 PNG로 저장."""
    preview_path = config.PREVIEW_DIR / f"{doc_id}.png"
    # 미리보기는 폭을 적당히 제한해 용량 절약
    h, w = processed.shape[:2]
    max_w = 1000
    if w > max_w:
        scale = max_w / w
        processed = cv2.resize(processed, (max_w, int(h * scale)),
                               interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(preview_path), processed)
    db.set_preview(doc_id, preview_path.name)


def _process(doc_id: str) -> None:
    doc = db.get_document(doc_id)
    if doc is None:
        return

    opt = PreprocessOptions.from_dict(doc.get("options"))
    lang = doc.get("lang") or config.DEFAULT_LANG
    path = Path(doc["orig_path"])
    is_mixed = (lang == config.MIXED_LANG) and ocr_engine.paddle_available()

    db.update_progress(doc_id, stage="문서 불러오는 중", progress=3)
    pages = _load_pages(path)
    db.set_pages(doc_id, len(pages))

    total = len(pages)
    page_texts: list[str] = []
    # 혼용 모드: 페이지별 듀얼패스 줄 후보를 모아 두었다가 배치로 LLM 보정한다.
    page_candidates: list[list[dict]] = []

    # OCR 구간은 5~85%, 혼용 LLM 보정 구간은 85~97%로 분배.
    ocr_end = 85.0 if is_mixed else 95.0
    for idx, page in enumerate(pages):
        base = 5 + (idx / total) * (ocr_end - 5)
        span = (ocr_end - 5) / total

        db.update_progress(
            doc_id,
            stage=f"전처리 중 ({idx + 1}/{total}페이지)",
            progress=base + span * 0.1,
        )
        processed = preprocess_image(page, opt)

        if idx == 0:
            _save_preview(doc_id, processed)

        db.update_progress(
            doc_id,
            stage=f"문자 인식 중 ({idx + 1}/{total}페이지)",
            progress=base + span * 0.4,
        )
        if is_mixed:
            lines = dual_ocr.run_dual_lines(processed)
            page_candidates.append(lines)
            # 우선 폴백(신뢰도 병합) 텍스트를 채워둔다. LLM이 있으면 뒤에서 덮어쓴다.
            text = dual_ocr.merge_fallback(lines)
        else:
            text = ocr_engine.run_ocr(processed, lang)
        page_texts.append(text)

        db.update_progress(
            doc_id,
            stage=f"인식 완료 ({idx + 1}/{total}페이지)",
            progress=base + span,
        )

    # === LLM 한글 병기 보정 (혼용 모드, 여러 페이지를 배치로) =================
    # 토큰 절약 + 문맥 활용을 위해 페이지를 묶어 호출한다(backend/llm_correct.py).
    # 키가 없거나 실패하면 위에서 채운 폴백 텍스트가 그대로 유지된다.
    if is_mixed and llm_correct.available() and any(page_candidates):
        def _cb(done: int, total_batches: int) -> None:
            frac = done / max(total_batches, 1)
            db.update_progress(
                doc_id,
                stage=f"한글 병기 보정 중 ({done + 1}/{total_batches}묶음)",
                progress=85 + frac * 12,
            )
        corrected = llm_correct.correct_document(page_candidates, _cb)
        if corrected:
            for i, c in enumerate(corrected):
                if c:
                    page_texts[i] = c

    # 여러 페이지는 구분선으로 합친다.
    if total > 1:
        joined = "\n\n".join(
            f"──── {i + 1}페이지 ────\n{t}" for i, t in enumerate(page_texts)
        )
    else:
        joined = page_texts[0] if page_texts else ""

    db.update_progress(doc_id, stage="결과 저장 중", progress=98)
    db.finish_document(doc_id, joined)
