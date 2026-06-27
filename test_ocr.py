"""테스트 문서로 OCR 파이프라인을 직접 검증하는 러너.

웹 서버 없이 backend 모듈을 그대로 호출해, 지정한 페이지 범위를 처리하고
- 전처리 미리보기 PNG (data/_test/preN_pre.png)
- 원본 렌더 PNG (data/_test/preN_raw.png)
- 듀얼패스 폴백 병합 텍스트
를 출력한다.

사용:  python test_ocr.py [시작페이지] [끝페이지]   (1-기반, 기본 1 1)
"""
from __future__ import annotations

import sys
import time
from pathlib import Path

import cv2
import numpy as np
import pypdfium2 as pdfium

from backend import config, dual_ocr, ocr_engine
from backend.preprocess import PreprocessOptions, preprocess_image

PDF = Path("document/000000039871_01.PDF")
OUT = Path("data/_test")
OUT.mkdir(parents=True, exist_ok=True)


def render_page(pdf, i: int, scale: float = 3.0) -> np.ndarray:
    page = pdf[i]
    pil = page.render(scale=scale).to_pil().convert("RGB")
    return cv2.cvtColor(np.asarray(pil), cv2.COLOR_RGB2BGR)


def main() -> None:
    start = int(sys.argv[1]) if len(sys.argv) > 1 else 1
    end = int(sys.argv[2]) if len(sys.argv) > 2 else start

    print(f"paddle_available = {ocr_engine.paddle_available()}")
    print(f"HANGUL_LANG={config.HANGUL_LANG}  HANJA_LANG={config.HANJA_LANG}")
    opt = PreprocessOptions()  # 기본 전처리

    all_pages: list[tuple[int, str]] = []
    pdf = pdfium.PdfDocument(str(PDF))
    t_all = time.time()
    try:
        for n in range(start, end + 1):
            i = n - 1
            t0 = time.time()
            raw = render_page(pdf, i)
            cv2.imwrite(str(OUT / f"p{n}_raw.png"), raw)
            proc = preprocess_image(raw, opt)
            cv2.imwrite(str(OUT / f"p{n}_pre.png"), proc)

            lines = dual_ocr.run_dual_lines(proc)
            text = dual_ocr.merge_fallback(lines)
            dt = time.time() - t0

            # 콘솔은 cp949라 한글이 깨질 수 있어 진행상황만 ASCII로 찍는다.
            print(f"[page {n}/{end}] lines={len(lines)} {dt:.1f}s "
                  f"(elapsed {time.time()-t_all:.0f}s)", flush=True)
            (OUT / f"p{n}.txt").write_text(text, encoding="utf-8")
            all_pages.append((n, text))
    finally:
        pdf.close()

    # 합본 텍스트 저장 (페이지 구분선 포함)
    joined = "\n\n".join(f"──── {n}페이지 ────\n{t}" for n, t in all_pages)
    (OUT / "full.txt").write_text(joined, encoding="utf-8")
    print(f"DONE {len(all_pages)} pages -> data/_test/full.txt "
          f"({time.time()-t_all:.0f}s total)", flush=True)


if __name__ == "__main__":
    main()
