"""애플리케이션 설정 및 경로 정의."""
from __future__ import annotations

import os
from pathlib import Path

# 프로젝트 루트 (이 파일 기준 한 단계 위)
ROOT_DIR = Path(__file__).resolve().parent.parent

DATA_DIR = Path(os.environ.get("OCR_DATA_DIR", ROOT_DIR / "data"))
UPLOAD_DIR = DATA_DIR / "uploads"      # 원본 업로드
PREVIEW_DIR = DATA_DIR / "previews"    # 전처리 미리보기 이미지
DB_PATH = DATA_DIR / "ocr.db"

FRONTEND_DIR = ROOT_DIR / "frontend"

# 동시에 처리할 문서 수 (CPU 환경 기준 보수적으로 1~2 권장)
MAX_WORKERS = int(os.environ.get("OCR_MAX_WORKERS", "1"))

# 기본 OCR 언어. 한국어+한자 혼용 고문서가 주 대상이므로 혼용 모드를 기본값으로.
# (PaddleOCR 언어 코드: korean / chinese_cht / ch / japan / en, 또는 'korean+han')
DEFAULT_LANG = os.environ.get("OCR_DEFAULT_LANG", "korean+han")

# PP-OCRv5 버전 지정 (설치된 paddleocr 버전이 지원하지 않으면 자동 무시)
OCR_VERSION = os.environ.get("OCR_VERSION", "PP-OCRv5")

# 한국어+한자 혼용 모드. 단일 PaddleOCR 모델은 한글·한자를 동시에 인식하지
# 못하므로(korean=한글전용, chinese_cht=한자전용), 이 언어 코드가 선택되면
# 두 모델을 같이 돌려(듀얼패스) LLM으로 합치고 한글 병기 형식으로 보정한다.
MIXED_LANG = "korean+han"
# 듀얼패스에서 한자 인식에 사용할 PaddleOCR 언어 코드.
HANJA_LANG = os.environ.get("OCR_HANJA_LANG", "chinese_cht")
# 한글 인식에 사용할 언어 코드.
HANGUL_LANG = os.environ.get("OCR_HANGUL_LANG", "korean")

# ── LLM 보정 설정 (한국어+한자 → 한글 병기) ──────────────────
# ANTHROPIC_API_KEY 환경변수가 있으면 LLM 보정이 활성화된다(없으면 폴백).
LLM_MODEL = os.environ.get("OCR_LLM_MODEL", "claude-opus-4-8")
# 1=LLM 보정 사용, 0=끄기(키가 있어도 강제로 끔)
LLM_ENABLED = os.environ.get("OCR_LLM_ENABLED", "1").strip().lower() in (
    "1", "true", "on", "yes",
)
# 토큰 절약 + 문맥 활용: 줄 단위가 아니라 여러 페이지를 한 번에 묶어 보정한다.
# 한 번의 LLM 호출에 담을 OCR 후보 글자수 상한(이 값을 넘으면 배치를 끊는다).
LLM_BATCH_CHARS = int(os.environ.get("OCR_LLM_BATCH_CHARS", "6000"))
# 한 번의 호출에 담을 최대 페이지 수.
LLM_BATCH_MAX_PAGES = int(os.environ.get("OCR_LLM_BATCH_MAX_PAGES", "8"))

# 업로드 허용 확장자
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}

# 업로드 최대 크기 (바이트). 기본 50MB
MAX_UPLOAD_BYTES = int(os.environ.get("OCR_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


def ensure_dirs() -> None:
    """필요한 데이터 디렉터리를 생성."""
    for d in (DATA_DIR, UPLOAD_DIR, PREVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)
