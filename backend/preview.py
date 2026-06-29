"""전처리 미세조정 실시간 미리보기 지원 (다중 페이지).

흐름:
  1) /api/preview/load   : 파일을 올리면 캐시(토큰 발급)하고 총 페이지 수를 알려준다.
  2) /api/preview/render : 토큰 + 페이지번호 + 파라미터로 전처리해 PNG 반환(재업로드 없음).
  3) /api/preview/measure: 토큰 + 페이지번호 + 파라미터로 중앙 일부만 OCR해 신뢰도 측정.

PDF는 모든 페이지를 미리 메모리에 올리지 않고, 요청된 페이지만 그때그때 렌더링한다
(원본 바이트만 캐시 + 최근 렌더 몇 장 캐시). 사용자가 페이지를 넘길 때만 렌더되므로
가볍다. 캐시는 토큰 단위 LRU.
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict
from typing import Any

import cv2
import numpy as np

_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, dict[str, Any]]" = OrderedDict()
_MAX_ITEMS = 8           # 동시에 캐시할 문서(토큰) 수
_MAX_PAGE_CACHE = 4      # 토큰당 렌더된 페이지 캐시 수
_PDF_SCALE = 2.0         # 미리보기 렌더 배율(파이프라인은 3.0, 미리보기는 가볍게)


def _ext(filename: str) -> str:
    name = filename or ""
    return name.lower().rsplit(".", 1)[-1] if "." in name else ""


def store_source(data: bytes, filename: str) -> tuple[str, int, np.ndarray]:
    """업로드 파일을 캐시하고 (토큰, 총 페이지 수, 첫 페이지 BGR) 반환."""
    if _ext(filename) == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            pages = len(pdf)
        finally:
            pdf.close()
        if pages <= 0:
            raise ValueError("PDF에서 페이지를 찾을 수 없습니다.")
        src: dict[str, Any] = {"kind": "pdf", "bytes": data, "pages": pages,
                               "page_cache": OrderedDict()}
    else:
        img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
        if img is None:
            raise ValueError("이미지를 읽을 수 없습니다 (손상되었거나 지원하지 않는 형식).")
        src = {"kind": "img", "img": img, "pages": 1, "page_cache": OrderedDict()}

    token = uuid.uuid4().hex
    with _LOCK:
        _CACHE[token] = src
        _CACHE.move_to_end(token)
        while len(_CACHE) > _MAX_ITEMS:
            _CACHE.popitem(last=False)

    first = get_page(token, 0)
    if first is None:  # 방금 넣었으므로 정상 경로에선 발생하지 않음
        raise ValueError("미리보기 로드에 실패했습니다.")
    return token, int(src["pages"]), first


def get_page(token: str, index: int) -> "np.ndarray | None":
    """토큰의 index 페이지(0-기반) BGR ndarray. 없으면 None.

    PDF는 요청 페이지를 그때 렌더링하고 토큰별로 최근 몇 장만 캐시한다.
    """
    with _LOCK:
        src = _CACHE.get(token)
        if src is None:
            return None
        _CACHE.move_to_end(token)
        kind = src["kind"]

    if kind == "img":
        return src["img"]

    # PDF: 범위 보정 후 캐시 확인 → 없으면 렌더
    pages = int(src["pages"])
    index = max(0, min(int(index), pages - 1))
    cache: "OrderedDict[int, np.ndarray]" = src["page_cache"]
    with _LOCK:
        if index in cache:
            cache.move_to_end(index)
            return cache[index]

    import pypdfium2 as pdfium
    pdf = pdfium.PdfDocument(src["bytes"])
    try:
        pil = pdf[index].render(scale=_PDF_SCALE).to_pil().convert("RGB")
        arr = cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
    finally:
        pdf.close()

    with _LOCK:
        cache[index] = arr
        cache.move_to_end(index)
        while len(cache) > _MAX_PAGE_CACHE:
            cache.popitem(last=False)
    return arr


def encode_png(img: np.ndarray, max_w: int = 1000) -> bytes:
    """미리보기 전송용 PNG 바이트. 너무 크면 폭을 줄여 전송 속도를 확보."""
    h, w = img.shape[:2]
    if w > max_w:
        scale = max_w / w
        img = cv2.resize(img, (max_w, int(h * scale)), interpolation=cv2.INTER_AREA)
    ok, buf = cv2.imencode(".png", img)
    if not ok:
        raise RuntimeError("PNG 인코딩 실패")
    return buf.tobytes()


def center_crop(img: np.ndarray, frac_w: float = 0.6, frac_h: float = 0.35) -> np.ndarray:
    """OCR 신뢰도 빠른 측정을 위해 중앙 일부만 잘라낸다."""
    h, w = img.shape[:2]
    cw, ch = int(w * frac_w), int(h * frac_h)
    x0, y0 = (w - cw) // 2, (h - ch) // 2
    return img[y0:y0 + ch, x0:x0 + cw]
