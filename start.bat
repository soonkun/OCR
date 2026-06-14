@echo off
REM ── 고문서 OCR 복원: 더블클릭 실행 (Windows) ──
chcp 65001 >nul
cd /d "%~dp0"

REM 모델 다운로드 서버 지정 (필요 시 ModelScope / BOS 로 변경)
set PADDLE_PDX_MODEL_SOURCE=HuggingFace

echo.
echo  고문서 OCR 복원 서버를 시작합니다...
echo  잠시 후 브라우저에서 http://localhost:8000/app/ 가 열립니다.
echo  (이 창을 닫으면 서버가 종료됩니다)
echo.

REM 서버를 별도 창에서 실행
start "OCR 서버" cmd /k py -3.12 -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

REM 서버가 뜰 시간을 잠깐 준 뒤 브라우저 열기
timeout /t 5 >nul
start "" http://localhost:8000/app/
