#!/usr/bin/env bash
# 개발 서버 실행 스크립트
set -e

HOST="${HOST:-0.0.0.0}"
PORT="${PORT:-8000}"

cd "$(dirname "$0")"

# (선택) 가상환경 자동 활성화
if [ -d ".venv" ]; then
  # shellcheck disable=SC1091
  source .venv/bin/activate
fi

echo "▶ http://localhost:${PORT}/app/  에서 접속하세요"
exec uvicorn backend.main:app --host "$HOST" --port "$PORT" --reload
