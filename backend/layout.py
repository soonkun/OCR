"""다단(多段) 레이아웃 복원 — 검출된 '텍스트 줄 박스'로 단을 추정해 읽기 순서를
바로잡는다.

옛 학술지·책자는 2단·3단 세로조판이 흔하다. 페이지 전체를 한 번에 OCR하면 같은
높이의 여러 칸 줄이 뒤섞여 읽기 순서가 엉킨다. 이를 바로잡으려면 각 줄이 어느 칸에
속하는지 알아야 한다.

이전에는 '열별 잉크량'으로 칸 사이 빈 띠(거터)를 찾았으나, 이 책처럼 **사진·삽화가
많은 페이지**에서는 그림 잉크가 거터를 메우거나 그림 사이 흰 틈을 거터로 오인해
검출이 흔들렸다. 그래서 잉크가 아니라 **OCR이 찾은 텍스트 줄 박스의 x분포**로 단을
추정한다. 사진·삽화는 텍스트 박스를 만들지 않으므로 단 구조를 망치지 않는다.

핵심: 줄 박스들을 x축에 투영해 '글자 줄이 덮는 세로 띠(=칸)'와 '아무 줄도 덮지 않는
세로 띠(=거터)'를 구분한다. 칸이 2개 이상이면 각 줄을 칸에 배정하고, 칸은 좌→우,
칸 안에서는 위→아래 순으로 이어 본래 읽기 순서를 복원한다.
"""
from __future__ import annotations

import numpy as np

# 이 비율(페이지 폭 대비)보다 넓은 줄은 '여러 칸을 가로지르는 제목/머리글'로 보고
# 단 경계 추정(투영)에서 제외한다(거터를 메워 단을 가리지 않도록).
_CROSS_COL_W = 0.55
# 칸으로 인정할 최소 폭(페이지 폭 대비)
_MIN_COL_W = 0.07
# 줄 커버리지가 최대치의 이 비율 이상인 x를 '칸 영역'으로 본다(낮으면 거터).
_COV_RATIO = 0.12
# 단 추정에 필요한 최소 줄 수(너무 적으면 그냥 위→아래 정렬)
_MIN_LINES = 4
# 진짜 본문 칸으로 인정할 칸당 최소 줄 수. 사진 속에서 흩어져 인식된 몇 줄이
# 가짜 칸을 만드는 것을 막는다(이만한 칸이 2개 미만이면 단단으로 처리).
_MIN_COL_LINES = 3


def _center(box) -> tuple[float, float]:
    if not box:
        return (0.0, 0.0)
    x1, y1, x2, y2 = box[:4]
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def _detect_column_bounds(lines: list[dict], w: int) -> list[tuple[int, int]]:
    """줄 박스의 x-커버리지로 칸 영역 [(x시작, x끝), ...]을 좌→우로 반환.

    각 줄 박스의 x구간을 1로 더한 커버리지 배열에서, 일정 수준 이상 덮인 연속 구간을
    '칸'으로 본다. 여러 칸을 가로지르는 넓은 줄(제목)은 제외해 거터가 메워지지 않게
    한다. 칸을 못 찾으면 [(0, w)] (단단).
    """
    cov = np.zeros(w, dtype=np.float32)
    for ln in lines:
        box = ln.get("box")
        if not box:
            continue
        x1 = max(0, int(box[0]))
        x2 = min(w, int(box[2]))
        if x2 - x1 <= 0 or (x2 - x1) > _CROSS_COL_W * w:
            continue
        cov[x1:x2] += 1.0

    maxc = float(cov.max()) if cov.size else 0.0
    if maxc <= 0:
        return [(0, w)]

    covered = cov >= max(1.0, _COV_RATIO * maxc)
    # 덮인 연속 구간(=칸 후보)을 모은다.
    runs: list[tuple[int, int]] = []
    start: int | None = None
    for i in range(w):
        if covered[i]:
            if start is None:
                start = i
        elif start is not None:
            runs.append((start, i))
            start = None
    if start is not None:
        runs.append((start, w))

    min_col = _MIN_COL_W * w
    cols = [(s, e) for s, e in runs if (e - s) >= min_col]
    return cols if cols else [(0, w)]


def order_lines_by_column(lines: list[dict], page_w: int) -> list[dict]:
    """줄 목록을 본래 읽기 순서(칸 좌→우, 칸 안에서 위→아래)로 정렬해 반환.

    각 줄은 {"box": [x1,y1,x2,y2], ...}. 박스 정보가 충분하면 텍스트 박스 x분포로
    단을 추정해 칸별로 묶고, 그렇지 않으면 단순히 위→아래로 정렬한다.
    """
    boxed = [l for l in lines if l.get("box")]
    if len(boxed) < _MIN_LINES:
        return sorted(lines, key=lambda l: _center(l.get("box"))[1])

    cols = _detect_column_bounds(boxed, page_w)
    if len(cols) <= 1:
        # 단단: 위→아래, 같은 높이는 좌→우.
        return sorted(lines, key=lambda l: (round(_center(l.get("box"))[1] / 12.0),
                                            _center(l.get("box"))[0]))

    centers = [(s + e) / 2.0 for s, e in cols]
    buckets: list[list[dict]] = [[] for _ in cols]
    for ln in lines:
        cx = _center(ln.get("box"))[0]
        idx = None
        for i, (s, e) in enumerate(cols):
            if s <= cx <= e:
                idx = i
                break
        if idx is None:  # 어느 칸에도 안 들면 가장 가까운 칸으로
            idx = int(np.argmin([abs(cx - c) for c in centers]))
        buckets[idx].append(ln)

    # 본문이라 할 만큼 줄이 있는 칸이 2개 미만이면(사진 위주·표지 등) 단단 처리.
    if sum(1 for b in buckets if len(b) >= _MIN_COL_LINES) < 2:
        return sorted(lines, key=lambda l: (round(_center(l.get("box"))[1] / 12.0),
                                            _center(l.get("box"))[0]))

    ordered: list[dict] = []
    for b in buckets:
        b.sort(key=lambda l: _center(l.get("box"))[1])  # 칸 안 위→아래
        ordered.extend(b)
    return ordered
