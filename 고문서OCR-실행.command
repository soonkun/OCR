#!/usr/bin/env bash
# ── 고문서 OCR 복원: 더블클릭 실행 (macOS) ──
# 이 파일을 Finder에서 더블클릭하면:
#   1) (최초 1회) 자동으로 설치 → 2) 서버 시작 → 3) 브라우저가 자동으로 열립니다.
cd "$(dirname "$0")"

PORT="${PORT:-8000}"

echo "════════════════════════════════════════════"
echo "   고문서 OCR 복원 — 시작합니다"
echo "════════════════════════════════════════════"

# 최초 실행 시 자동 설치
if [ ! -d ".venv" ]; then
  echo "▶ 최초 실행: 필요한 프로그램을 설치합니다 (몇 분 걸릴 수 있어요)..."
  bash ./setup.sh || { echo "✗ 설치 실패. 위 메시지를 확인하세요."; read -r -p "엔터를 누르면 닫힙니다..."; exit 1; }
fi

# 서버가 뜨면 브라우저를 자동으로 열어주는 백그라운드 대기
( for _ in $(seq 1 60); do
    if curl -s -o /dev/null "http://localhost:${PORT}/api/health"; then
      open "http://localhost:${PORT}/app/"; break
    fi
    sleep 1
  done ) &

echo "▶ 브라우저가 곧 자동으로 열립니다: http://localhost:${PORT}/app/"
echo "  (이 창을 닫으면 서버가 종료됩니다)"
echo ""

# 서버 실행 (이 창에서 동작 — 닫으면 종료)
exec ./run.sh
