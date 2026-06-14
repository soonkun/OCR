#!/usr/bin/env bash
# ── 고문서 OCR 복원: 설치 스크립트 (macOS / Linux) ──
# 가상환경(.venv) 생성 → 코어 의존성 + PaddleOCR 설치까지 한 번에 수행합니다.
set -e

cd "$(dirname "$0")"

# 1) Python 인터프리터 선택 (paddlepaddle 휠은 cp39~cp313 지원)
PY=""
for c in python3.13 python3.12 python3.11 python3.10 python3.9 python3; do
  if command -v "$c" >/dev/null 2>&1; then
    ver="$("$c" -c 'import sys; print("%d.%d" % sys.version_info[:2])' 2>/dev/null || echo "")"
    case "$ver" in
      3.9|3.10|3.11|3.12|3.13) PY="$c"; break ;;
    esac
  fi
done

if [ -z "$PY" ]; then
  echo "✗ paddlepaddle와 호환되는 Python(3.9~3.13)을 찾지 못했습니다." >&2
  echo "  Homebrew 예시:  brew install python@3.12" >&2
  exit 1
fi
echo "▶ 사용할 Python: $PY ($($PY --version 2>&1))"

# 2) 가상환경 생성
if [ ! -d ".venv" ]; then
  "$PY" -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

# 3) 패키징 도구 최신화
python -m pip install --upgrade pip setuptools wheel

# 4) 코어 의존성
python -m pip install -r requirements.txt

# 5) PaddleOCR (CPU). 용량이 큽니다.
python -m pip install "paddlepaddle>=3.0" "paddleocr>=3.0"

echo ""
echo "✓ 설치 완료. 서버 실행:  ./run.sh"
echo "  브라우저에서 http://localhost:8000/app/ 로 접속하세요."
