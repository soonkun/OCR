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

# 기본 OCR 언어. PaddleOCR 언어 코드 (korean / ch / en / japan ...)
# 한국어+한자 혼용 고문서는 'korean'을 기본으로 두고 UI에서 변경 가능.
DEFAULT_LANG = os.environ.get("OCR_DEFAULT_LANG", "korean")

# PP-OCRv5 버전 지정 (설치된 paddleocr 버전이 지원하지 않으면 자동 무시)
OCR_VERSION = os.environ.get("OCR_VERSION", "PP-OCRv5")

# 업로드 허용 확장자
ALLOWED_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".tif", ".tiff", ".webp", ".pdf"}

# 업로드 최대 크기 (바이트). 기본 50MB
MAX_UPLOAD_BYTES = int(os.environ.get("OCR_MAX_UPLOAD_BYTES", str(50 * 1024 * 1024)))


def ensure_dirs() -> None:
    """필요한 데이터 디렉터리를 생성."""
    for d in (DATA_DIR, UPLOAD_DIR, PREVIEW_DIR):
        d.mkdir(parents=True, exist_ok=True)
