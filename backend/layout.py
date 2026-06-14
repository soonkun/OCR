"""다단(多段) 레이아웃 감지 — 2단 세로조판 페이지를 좌/우 칸으로 분리.

옛 학술지·신문은 2단 조판이 흔하다. 페이지 전체를 한 번에 OCR하면 같은 높이의
좌·우 줄이 뒤섞여 읽기 순서가 엉킨다. 가운데 '거터(빈 세로 띠)'를 찾아 칸을 나눠
각각 OCR한 뒤 왼쪽→오른쪽 순으로 이으면 본래 읽기 순서가 복원된다.

거터가 뚜렷하지 않으면(표지·단단 페이지) 분리하지 않고 통째로 둔다.
"""
from __future__ import annotations

import cv2
import numpy as np


def _body_ink_profile(gray: np.ndarray) -> np.ndarray:
    """본문 영역(세로 20~92%)의 열별 잉크량 프로파일.

    상단 전폭 제목·삽화와 하단 쪽번호를 제외하고 본문만 본다. 그래야 가운데
    거터가 제목 잉크에 가려지지 않는다.
    """
    h, w = gray.shape[:2]
    band = gray[int(h * 0.20):int(h * 0.92), :]
    _, bw = cv2.threshold(band, 0, 1, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    prof = bw.sum(axis=0).astype(np.float32)
    k = max(3, (w // 200) | 1)  # 폭의 ~0.5% 평활화
    return cv2.blur(prof.reshape(1, -1), (k, 1)).ravel()


def find_gutter(gray: np.ndarray) -> int | None:
    """중앙부에서 좌·우 본문보다 훨씬 비어 있는 세로 거터의 x좌표. 없으면 None."""
    h, w = gray.shape[:2]
    if w < 400:
        return None
    prof = _body_ink_profile(gray)
    lo, hi = int(w * 0.30), int(w * 0.70)      # 거터를 찾을 중앙 영역
    region = prof[lo:hi]
    if region.size == 0:
        return None
    gmin = float(region.min())
    split_x = lo + int(np.argmin(region))
    # 좌·우 본문 칸의 평균 잉크량.
    side = float((prof[int(w * 0.10):int(w * 0.30)].mean()
                  + prof[int(w * 0.70):int(w * 0.90)].mean()) / 2.0)
    if side <= 0:
        return None
    # 표지·속표지처럼 글자가 적은 페이지는 빈 영역을 거터로 오인하기 쉽다.
    # 좌·우 칸에 본문이라 할 만한 잉크가 충분할 때만 2단으로 본다.
    band_h = int(h * 0.92) - int(h * 0.20)
    if side < 0.05 * band_h:
        return None
    # 거터 잉크량이 본문 칸의 20% 미만이면 진짜 빈 띠(2단)로 본다.
    if gmin > side * 0.20:
        return None
    if split_x < w * 0.2 or split_x > w * 0.8:
        return None
    return split_x


def split_columns(img: np.ndarray) -> list[np.ndarray]:
    """2단이면 [왼쪽칸, 오른쪽칸], 아니면 [원본]. 읽기 순서(좌→우) 보장."""
    gray = img if img.ndim == 2 else cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    x = find_gutter(gray)
    if x is None:
        return [img]
    return [img[:, :x], img[:, x:]]
