"""PaddleOCR(PP-OCRv5) 래퍼.

PaddleOCR / paddlepaddle 설치 여부에 따라:
  - 설치돼 있으면 실제 OCR 수행
  - 미설치면 폴백 엔진이 안내 메시지를 반환 (서버는 정상 동작)

paddleocr는 버전별로 호출 규약이 달라서, 결과 파싱을 방어적으로 처리한다.
언어별로 엔진 인스턴스를 캐시한다(초기화 비용이 크기 때문).
"""
from __future__ import annotations

import threading
from typing import Optional

import numpy as np


def _ensure_bgr(img: np.ndarray) -> np.ndarray:
    """PaddleOCR은 3채널(H,W,3)을 요구한다. 이진화·흑백 전처리로 들어온
    1채널(H,W) 또는 (H,W,1)/(H,W,4) 이미지를 3채널 BGR로 정규화한다."""
    import cv2

    if img.ndim == 2:
        return cv2.cvtColor(img, cv2.COLOR_GRAY2BGR)
    if img.ndim == 3:
        ch = img.shape[2]
        if ch == 1:
            return cv2.cvtColor(img[:, :, 0], cv2.COLOR_GRAY2BGR)
        if ch == 4:
            return cv2.cvtColor(img, cv2.COLOR_BGRA2BGR)
    return img

_LOCK = threading.Lock()
_ENGINES: dict[str, "object"] = {}
_PADDLE_AVAILABLE: Optional[bool] = None


def paddle_available() -> bool:
    global _PADDLE_AVAILABLE
    if _PADDLE_AVAILABLE is None:
        try:
            import paddleocr  # noqa: F401

            _PADDLE_AVAILABLE = True
        except Exception:
            _PADDLE_AVAILABLE = False
    return _PADDLE_AVAILABLE


def _build_engine(lang: str):
    from paddleocr import PaddleOCR

    from . import config

    # 버전/인자 호환성: 신버전은 ocr_version·use_angle_cls 인자를
    # 받아들이지 않을 수 있어 단계적으로 시도한다.
    # PP-OCRv5(3.x)에서는 문서 방향분류·왜곡보정·텍스트라인 방향 모델을 꺼서
    # 다운로드해야 할 모델 수를 줄인다(오프라인 환경에 유리, 속도도 빠름).
    #
    # ※ MKLDNN(oneDNN)은 기본값(켜짐) 그대로 둔다. paddlepaddle 3.1.0 + CPU에서는
    #   MKLDNN을 끄면(enable_mkldnn=False) 큰 이미지 추론이 Segmentation fault로
    #   죽는다(실측). 반대로 켜 두면 정상 동작한다. 따라서 mkldnn 인자를 강제로
    #   넘기지 않는다(이전 3.0.0용 enable_mkldnn=False 우회는 제거).
    attempts = [
        dict(lang=lang, ocr_version=config.OCR_VERSION,
             use_doc_orientation_classify=False, use_doc_unwarping=False,
             use_textline_orientation=False),
        dict(lang=lang,
             use_doc_orientation_classify=False, use_doc_unwarping=False,
             use_textline_orientation=False),
        dict(lang=lang, ocr_version=config.OCR_VERSION, use_angle_cls=True,
             show_log=False),
        dict(lang=lang, ocr_version=config.OCR_VERSION),
        dict(lang=lang, use_angle_cls=True, show_log=False),
        dict(lang=lang),
    ]
    last_err: Optional[Exception] = None
    for kwargs in attempts:
        try:
            return PaddleOCR(**kwargs)
        except Exception as exc:  # 인자 미지원 등
            last_err = exc
            continue
    raise RuntimeError(f"PaddleOCR 초기화 실패: {last_err}")


def _get_engine(lang: str):
    with _LOCK:
        engine = _ENGINES.get(lang)
        if engine is None:
            engine = _build_engine(lang)
            _ENGINES[lang] = engine
        return engine


def _parse_result(result) -> list[str]:
    """다양한 paddleocr 결과 포맷에서 텍스트 라인을 추출."""
    lines: list[str] = []
    if not result:
        return lines

    # 신버전 .predict()/.ocr() 는 dict(예: {'rec_texts': [...]})를 담은 리스트 반환
    for page in result:
        if isinstance(page, dict):
            texts = page.get("rec_texts") or page.get("rec_text")
            if texts:
                lines.extend(t for t in texts if t)
            continue
        # 구버전: page = [ [box, (text, conf)], ... ]
        if isinstance(page, (list, tuple)):
            for item in page:
                try:
                    info = item[1]
                    text = info[0] if isinstance(info, (list, tuple)) else info
                    if text:
                        lines.append(str(text))
                except (IndexError, TypeError):
                    continue
    return lines


def run_ocr(img: np.ndarray, lang: str) -> str:
    """전처리된 이미지에서 텍스트를 추출. 실패 시 예외를 올린다."""
    if not paddle_available():
        return _fallback_text()

    img = _ensure_bgr(img)
    engine = _get_engine(lang)
    # paddleocr 버전에 따라 predict 또는 ocr 사용
    if hasattr(engine, "predict"):
        try:
            result = engine.predict(img)
            lines = _parse_result(result)
            if lines:
                return "\n".join(lines)
        except Exception:
            pass  # ocr() 로 폴백 시도
    result = engine.ocr(img)
    return "\n".join(_parse_result(result))


def _parse_lines(result) -> list[dict]:
    """결과에서 줄 단위로 (text, score, box[x1,y1,x2,y2])를 추출.

    듀얼패스 정렬을 위해 박스를 함께 반환한다. 신버전(predict) 결과 우선,
    구버전 포맷도 방어적으로 처리한다.
    """
    lines: list[dict] = []
    if not result:
        return lines
    for page in result:
        # 신버전: dict(rec_texts/rec_scores/rec_boxes 또는 rec_polys)
        if isinstance(page, dict):
            texts = page.get("rec_texts") or []
            scores = page.get("rec_scores") or []
            boxes = page.get("rec_boxes")
            polys = page.get("rec_polys") or page.get("dt_polys")
            for i, text in enumerate(texts):
                if not text:
                    continue
                score = float(scores[i]) if i < len(scores) else 0.0
                box = None
                if boxes is not None and i < len(boxes):
                    box = _to_xyxy(boxes[i])
                elif polys is not None and i < len(polys):
                    box = _poly_to_xyxy(polys[i])
                lines.append({"text": str(text), "score": score, "box": box})
            continue
        # 구버전: page = [ [box, (text, conf)], ... ]
        if isinstance(page, (list, tuple)):
            for item in page:
                try:
                    poly, info = item[0], item[1]
                    text = info[0] if isinstance(info, (list, tuple)) else info
                    score = float(info[1]) if isinstance(info, (list, tuple)) and len(info) > 1 else 0.0
                    if text:
                        lines.append({"text": str(text), "score": score,
                                      "box": _poly_to_xyxy(poly)})
                except (IndexError, TypeError):
                    continue
    return lines


def _to_xyxy(box) -> Optional[list]:
    """[x1,y1,x2,y2] 형태 박스를 float 리스트로 정규화."""
    try:
        arr = [float(v) for v in (box.tolist() if hasattr(box, "tolist") else box)]
        if len(arr) >= 4:
            return arr[:4]
    except (TypeError, ValueError):
        pass
    return None


def _poly_to_xyxy(poly) -> Optional[list]:
    """다각형 꼭짓점 목록을 [minx,miny,maxx,maxy]로 변환."""
    try:
        pts = poly.tolist() if hasattr(poly, "tolist") else poly
        xs = [float(p[0]) for p in pts]
        ys = [float(p[1]) for p in pts]
        return [min(xs), min(ys), max(xs), max(ys)]
    except (TypeError, ValueError, IndexError):
        return None


def run_ocr_lines(img: np.ndarray, lang: str) -> list[dict]:
    """전처리된 이미지에서 줄 단위 결과 목록을 반환.

    각 원소: {"text": str, "score": float, "box": [x1,y1,x2,y2]|None}
    PaddleOCR 미설치 시 빈 목록.
    """
    if not paddle_available():
        return []
    img = _ensure_bgr(img)
    engine = _get_engine(lang)
    if hasattr(engine, "predict"):
        try:
            return _parse_lines(engine.predict(img))
        except Exception:
            pass
    return _parse_lines(engine.ocr(img))


def _fallback_text() -> str:
    return (
        "[OCR 엔진 미설치]\n"
        "PaddleOCR(paddlepaddle)이 설치되어 있지 않아 텍스트 인식을 건너뛰었습니다.\n"
        "전처리(업스케일·이진화·deskew)는 정상 수행되었으며, 미리보기에서 결과를 확인할 수 있습니다.\n"
        "실제 인식을 사용하려면 다음을 설치하세요:\n"
        "    pip install paddlepaddle paddleocr"
    )
