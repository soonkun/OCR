"""LLM(OpenAI) 기반 한국어+한자 후보정 → 문단 재구성 + 한글 병기 + 주석.

듀얼패스 OCR가 만든 두 후보(한글 모델 / 한자 모델 인식 결과)를 받아:
  1) 두 후보를 종합해 원문(한글+한자 혼용)을 복원한다.
  2) 줄 단위가 아니라 **문단 단위**로 자연스럽게 재구성한다(OCR가 쪼갠 줄을 잇는다).
  3) 흐리거나 깨진 글자는 앞뒤 문맥으로 유추해 채운다 —
     단, **원문(1962년 당시의 옛 표기·옛 표현)을 최대한 존중**하고 현대어로
     함부로 바꾸지 않는다.
  4) 한자어는 '한글독음(漢字)' 형식으로 병기한다(문맥에 맞는 독음).
  5) 요즘 안 쓰는 옛 표현·사어나, 흐려서 추정해 넣은 부분은 **주석**으로 단다.

토큰 절약 + 문맥 활용을 위해 **여러 페이지를 한 번의 호출로 묶어** 처리한다
(config.LLM_BATCH_CHARS / LLM_BATCH_MAX_PAGES).

OPENAI_API_KEY 가 없거나 openai 미설치면 available()=False → 호출부가
신뢰도 기반 폴백을 쓴다(앱은 키 없이도 정상 동작).
"""
from __future__ import annotations

import os
import re
from typing import Callable, Optional

from . import config

_CLIENT = None
_AVAILABLE: Optional[bool] = None

_SYSTEM = """\
너는 한국 고문서(한국어+한자 혼용, 1960년대 인쇄물) OCR **전사(轉寫)** 도우미다.
입력은 같은 지면을 두 OCR 모델로 읽은 결과다. 각 페이지마다 두 덩어리가 온다:
  - [한글모델]: 한글은 비교적 정확하나 한자는 누락/깨짐
  - [한자모델]: 한자는 비교적 정확하나 한글은 누락/깨짐
두 결과는 서로를 보완한다. 종합해서 그 페이지에 **실제로 적혀 있던 글자**를 복원하라.

★ 최우선 원칙 — 지어내지 마라(충실성):
1. 오직 위 두 OCR 후보에 **실제로 나타난 글자**만 근거로 삼아라.
   - 이 글의 주제·사건·인물을 네가 알고 있더라도 **모르는 척하라**. 너의 배경지식으로
     날짜·숫자·금액·이름·사실·문장을 **절대 추가하지 마라.** 그럴듯하게 부풀리지 마라.
   - 후보에 없는 내용을 한 글자라도 새로 만들어내면 실패다. 매끄러운 문장보다
     **불완전하더라도 원문에 충실한 것**이 낫다.
2. 후보가 조각나 있으면 **조각난 대로** 둔다. 빠진 부분을 상상으로 잇지 마라.
   한 구절이 통째로 판독 불가면 그 자리에 `□□□` 를 두고 넘어간다.
3. 유추는 **글자 수준의 최소한만** 허용한다. 두 후보에 또렷이 없으나 문맥상
   거의 확실한 한두 글자를 채울 때는 반드시 `〔 〕` 로 감싼다. 예: 發〔達〕.
   〔 〕 는 꼭 필요한 곳에만, 아껴 쓴다. 확신이 없으면 채우지 말고 `□` 로 둔다.

★ 원문 표기 보존:
4. 1962년 당시의 옛 철자·옛 표기·옛 표현·옛 문법을 **그대로 둔다.**
   '하야/하여', '되엿다/되었다', '함니다/합니다', '읍니다', '-노라', 옛 띄어쓰기 등을
   현대 맞춤법으로 **고치지 마라.** 어휘를 현대어로 바꾸지 마라. 문장을 다듬지 마라.

★ 한글 병기:
5. 한자(어)는 '한글독음(漢字)' 형식으로 적는다. 한자 앞에 문맥에 맞는 독음을, 한자는
   괄호 안에. 예: 農業 → 농업(農業), 影響 → 영향(影響). 독음은 문맥에 맞는 음으로
   (樂→락/악/요, 不→불/부, 度→도/탁). 한글·숫자·문장부호는 그대로.

★ 주석:
6. 본문 아래에 '― 주석 ―' 절을 둔다(없으면 생략). 본문은 원문대로 두고 설명은 여기서만:
   - 요즘 안 쓰는 옛 표현·사어·어려운 한자어 풀이.
   - 〔 〕로 추정한 부분, `□`로 비워 둔 판독 불가 부분을 짧게 명시.

출력 형식(엄수):
- 입력의 '===== 페이지 N =====' 구분선을 출력에도 페이지마다 똑같이 넣는다(번호 유지).
- 각 페이지: 본문(병기) → 빈 줄 → (필요시) '― 주석 ―' 절.
- 보정 결과 텍스트만 출력한다. 머리말·해설·코드블록을 붙이지 마라."""

_PAGE_RE = re.compile(r"=+\s*페이지\s*(\d+)\s*=+")


def available() -> bool:
    """LLM 보정 사용 가능 여부 (설정 on + 키 존재 + SDK 설치)."""
    global _AVAILABLE
    if not config.LLM_ENABLED:
        return False
    if not os.environ.get("OPENAI_API_KEY"):
        return False
    if _AVAILABLE is None:
        try:
            import openai  # noqa: F401
            _AVAILABLE = True
        except Exception:
            _AVAILABLE = False
    return _AVAILABLE


def _client():
    global _CLIENT
    if _CLIENT is None:
        from openai import OpenAI
        _CLIENT = OpenAI()
    return _CLIENT


def _page_texts(lines: list[dict]) -> tuple[str, str]:
    """정렬된 줄 후보에서 (한글모델 전체텍스트, 한자모델 전체텍스트)."""
    ko = "\n".join(l["ko"] for l in lines if l.get("ko"))
    han = "\n".join(l["han"] for l in lines if l.get("han"))
    return ko, han


def _batch_pages(pages: list[list[dict]]) -> list[list[int]]:
    """페이지를 글자수/페이지수 예산에 맞춰 배치 묶음(전역 인덱스 리스트)으로 나눈다."""
    batches: list[list[int]] = []
    cur: list[int] = []
    cur_chars = 0
    for idx, lines in enumerate(pages):
        ko, han = _page_texts(lines)
        size = len(ko) + len(han)
        if not size:
            continue  # 후보 없는 페이지는 LLM 대상에서 제외(빈 결과 처리)
        if cur and (cur_chars + size > config.LLM_BATCH_CHARS
                    or len(cur) >= config.LLM_BATCH_MAX_PAGES):
            batches.append(cur)
            cur, cur_chars = [], 0
        cur.append(idx)
        cur_chars += size
    if cur:
        batches.append(cur)
    return batches


def _build_user_message(pages: list[list[dict]], indices: list[int]) -> str:
    parts = ["다음 페이지들을 복원해 한글 병기로 보정하라. "
             "각 '===== 페이지 N =====' 구분선을 출력에도 유지하라.\n"]
    for idx in indices:
        ko, han = _page_texts(pages[idx])
        parts.append(f"===== 페이지 {idx + 1} =====")
        parts.append("[한글모델]\n" + (ko or "(없음)"))
        parts.append("[한자모델]\n" + (han or "(없음)"))
        parts.append("")
    return "\n".join(parts)


def _split_pages(text: str) -> dict[int, str]:
    """LLM 출력에서 '===== 페이지 N =====' 구분선 기준으로 페이지별 텍스트 추출."""
    out: dict[int, str] = {}
    matches = list(_PAGE_RE.finditer(text))
    for i, m in enumerate(matches):
        num = int(m.group(1)) - 1  # 0-기반 인덱스로
        start = m.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        out[num] = text[start:end].strip("\n")
    return out


def _call(user_msg: str) -> Optional[str]:
    try:
        # 출력이 길 수 있어 스트리밍으로 받아 취합한다.
        stream = _client().chat.completions.create(
            model=config.LLM_MODEL,
            max_tokens=8000,
            temperature=0,  # 충실성 우선: 창의적 보충(지어내기) 억제
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": user_msg},
            ],
            stream=True,
        )
        parts = []
        for chunk in stream:
            if not chunk.choices:
                continue
            delta = chunk.choices[0].delta
            if delta and delta.content:
                parts.append(delta.content)
    except Exception:
        return None
    return "".join(parts) or None


def correct_document(
    pages: list[list[dict]],
    progress: Optional[Callable[[int, int], None]] = None,
) -> Optional[list[str]]:
    """문서 전체(페이지별 줄 후보 목록)를 배치로 보정.

    반환: 페이지별 보정 텍스트 리스트(길이 = len(pages)). 후보 없거나 실패한
    페이지는 빈 문자열. 사용 불가 시 None.
    """
    if not available() or not pages:
        return None
    results = [""] * len(pages)
    batches = _batch_pages(pages)
    for b, indices in enumerate(batches):
        if progress:
            progress(b, len(batches))
        out = _call(_build_user_message(pages, indices))
        if not out:
            continue
        per_page = _split_pages(out)
        for idx in indices:
            txt = per_page.get(idx)
            if txt:
                results[idx] = txt
    return results
