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


def run_dual_lines(img: np.ndarray) -> list[dict]:
    """듀얼패스 + 다단 읽기순서 복원. [{ko, han, ko_score, han_score, box}] 반환.

    페이지 전체를 ko·han 모델로 한 번씩 OCR해 줄 박스를 모으고, 줄 박스의 x분포로
    단(칸)을 추정해 칸 좌→우·칸 안 위→아래 순으로 정렬한다(backend/layout.py).
    사진·삽화가 많은 페이지에서도 텍스트 박스 기준이라 단 구조가 흔들리지 않는다.
    """
    merged = _match_ko_han(img)
    page_w = img.shape[1]
    return layout.order_lines_by_column(merged, page_w)


def _match_ko_han(img: np.ndarray) -> list[dict]:
    """페이지 전체 ko·han 듀얼패스를 줄 박스 중심으로 짝지어 병합(정렬 전)."""
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
