"""한국어+한자 혼용 문서를 위한 듀얼패스 OCR.

단일 PaddleOCR 모델은 한글(11,172자)과 한자(15,565자)를 동시에 인식하지 못한다:
  - korean 모델  : 한글 전용 (한자 0자)
  - chinese_cht 등: 한자 전용 (한글 0자)

따라서 두 모델을 같은 이미지에 돌려 줄(텍스트 박스) 단위로 짝지어,
각 줄마다 '한글 모델 후보'와 '한자 모델 후보'를 함께 모은다. 두 패스는 동일한
검출(det) 모델을 쓰므로 박스가 거의 일치한다 → 박스 중심 최근접으로 정렬한다.

이 후보쌍 목록을 llm_correct가 받아 원문을 복원하고 한글 병기로 보정한다.
LLM이 없으면 pipeline이 신뢰도 높은 후보를 택해 합치는 폴백을 쓴다.
"""
from __future__ import annotations

import numpy as np

from . import config, layout, ocr_engine


def _center(box) -> tuple[float, float]:
    if not box:
        return (0.0, 0.0)
    x1, y1, x2, y2 = box[:4]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _reading_order_key(line: dict):
    """위→아래, 좌→우 읽기 순서. 같은 줄로 볼 y 허용오차 12px."""
    cx, cy = _center(line.get("box"))
    return (round(cy / 12.0), cx)


def run_dual_lines(img: np.ndarray) -> list[dict]:
    """듀얼패스 + 2단 컬럼 분리. [{ko, han, ko_score, han_score, box}] 목록 반환.

    2단 조판이면 좌/우 칸을 따로 OCR해 왼쪽→오른쪽 순서로 이어 읽기 순서를
    바로잡는다. 단단 페이지면 통째로 처리한다.
    """
    columns = layout.split_columns(img)
    merged: list[dict] = []
    for col in columns:
        merged.extend(_dual_lines_single(col))
    return merged


def _dual_lines_single(img: np.ndarray) -> list[dict]:
    """단일 이미지(한 칸)에 대한 듀얼패스 정렬 결과."""
    ko_lines = ocr_engine.run_ocr_lines(img, config.HANGUL_LANG)
    han_lines = ocr_engine.run_ocr_lines(img, config.HANJA_LANG)

    # 한자 패스 줄을 박스 중심으로 매칭 풀에 넣는다.
    han_pool = [dict(l, _used=False) for l in han_lines]

    merged: list[dict] = []
    for ko in ko_lines:
        kc = _center(ko.get("box"))
        best, best_d = None, None
        for h in han_pool:
            if h["_used"]:
                continue
            hc = _center(h.get("box"))
            d = (kc[0] - hc[0]) ** 2 + (kc[1] - hc[1]) ** 2
            if best_d is None or d < best_d:
                best, best_d = h, d
        # 박스 높이의 ~1.5배 안이면 같은 줄로 본다(좌표 단위 px²).
        thresh = 60.0 ** 2
        if best is not None and (best_d is None or best_d <= thresh):
            best["_used"] = True
            merged.append({
                "ko": ko["text"], "han": best["text"],
                "ko_score": ko["score"], "han_score": best["score"],
                "box": ko.get("box"),
            })
        else:
            merged.append({
                "ko": ko["text"], "han": "",
                "ko_score": ko["score"], "han_score": 0.0,
                "box": ko.get("box"),
            })

    # 한자 패스에만 있던 줄(예: 한자만 있는 행)을 추가한다.
    for h in han_pool:
        if not h["_used"]:
            merged.append({
                "ko": "", "han": h["text"],
                "ko_score": 0.0, "han_score": h["score"],
                "box": h.get("box"),
            })

    merged.sort(key=_reading_order_key)
    return merged


def merge_fallback(lines: list[dict]) -> str:
    """LLM이 없을 때: 줄마다 신뢰도 높은 후보를 택해 합친다(병기 없음)."""
    out: list[str] = []
    for ln in lines:
        ko, han = ln.get("ko", ""), ln.get("han", "")
        if ko and han:
            out.append(ko if ln.get("ko_score", 0) >= ln.get("han_score", 0) else han)
        else:
            out.append(ko or han)
    return "\n".join(s for s in out if s)
