"""전처리 미세조정 실시간 미리보기 지원.

흐름:
  1) /api/preview/load : 파일을 올리면 첫 페이지를 원본 ndarray로 캐시(토큰 발급).
  2) /api/preview/apply: 토큰 + 파라미터로 전처리해 PNG 반환(파일 재업로드 없음 → 빠름).
  3) /api/preview/measure: 토큰 + 파라미터로 중앙 일부만 OCR해 신뢰도 측정(몇 초).

캐시는 메모리에 최근 몇 개만 보관(LRU). 사용자가 슬라이더를 움직일 때마다 apply만
호출하므로 가볍다.
"""
from __future__ import annotations

import threading
import uuid
from collections import OrderedDict

import cv2
import numpy as np

_LOCK = threading.Lock()
_CACHE: "OrderedDict[str, np.ndarray]" = OrderedDict()
_MAX_ITEMS = 8


def store(arr: np.ndarray) -> str:
    token = uuid.uuid4().hex
    with _LOCK:
        _CACHE[token] = arr
        _CACHE.move_to_end(token)
        while len(_CACHE) > _MAX_ITEMS:
            _CACHE.popitem(last=False)
    return token


def get(token: str) -> "np.ndarray | None":
    with _LOCK:
        arr = _CACHE.get(token)
        if arr is not None:
            _CACHE.move_to_end(token)
        return arr


def load_first_page(data: bytes, filename: str) -> np.ndarray:
    """업로드 바이트에서 첫 페이지를 BGR ndarray로. PDF는 첫 장을 렌더링."""
    ext = (filename or "").lower().rsplit(".", 1)[-1] if "." in (filename or "") else ""
    if ext == "pdf":
        import pypdfium2 as pdfium
        pdf = pdfium.PdfDocument(data)
        try:
            bitmap = pdf[0].render(scale=2.0)
            pil = bitmap.to_pil().convert("RGB")
            return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)
        finally:
            pdf.close()
    img = cv2.imdecode(np.frombuffer(data, dtype=np.uint8), cv2.IMREAD_COLOR)
    if img is None:
        raise ValueError("이미지를 읽을 수 없습니다 (손상되었거나 지원하지 않는 형식).")
    return img


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
