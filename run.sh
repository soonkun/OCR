#!/usr/bin/env bash
# 개발 서버 실행 스크립트
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

# PaddleOCR 모델 다운로드 소스 (필요 시 ModelScope / BOS 로 변경)
export PADDLE_PDX_MODEL_SOURCE="${PADDLE_PDX_MODEL_SOURCE:-HuggingFace}"

cd "$(dirname "$0")"

# (선택) 가상환경 자동 활성화
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "▶ http://localhost:${PORT}/app/  에서 접속하세요"

# (macOS) 서버가 뜨면 브라우저를 자동으로 연다. OCR_NO_BROWSER=1 이면 생략.
if [ -z "${OCR_NO_BROWSER:-}" ] && command -v open >/dev/null 2>&1; then
  ( for _ in $(seq 1 60); do
      if curl -s -o /dev/null "http://localhost:${PORT}/api/health"; then
        open "http://localhost:${PORT}/app/"; break
      fi
      sleep 1
    done ) &
fi

exec uvicorn backend.main:app --host "$HOST" --port "$PORT" --reload
