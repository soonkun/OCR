@echo off
REM ── 고문서 OCR 복원: 더블클릭 실행 (Windows) ──
chcp 65001 >nul
cd /d "%~dp0"

REM 모델 다운로드 서버 지정 (필요 시 ModelScope / BOS 로 변경)
set PADDLE_PDX_MODEL_SOURCE=HuggingFace

REM 최초 실행 시: 가상환경(.venv)이 없으면 자동으로 설치
if not exist ".venv\Scripts\python.exe" (
  echo  최초 실행: 필요한 프로그램을 설치합니다 (몇 분 걸릴 수 있어요)...
  call setup.bat
)

REM 실행에 사용할 Python 결정
if exist ".venv\Scripts\python.exe" (
  set "RUNPY=.venv\Scripts\python.exe"
) else (
  echo  [오류] 설치에 실패했습니다. 위 메시지를 확인하세요.
  pause
  exit /b 1
)

echo.
echo  고문서 OCR 복원 서버를 시작합니다...
echo  잠시 후 브라우저에서 http://localhost:8000/app/ 가 열립니다.
echo  (이 창을 닫으면 서버가 종료됩니다)
echo.

REM 서버를 별도 창에서 실행
start "OCR 서버" cmd /k %RUNPY% -m uvicorn backend.main:app --host 127.0.0.1 --port 8000

REM 서버가 뜰 시간을 잠깐 준 뒤 브라우저 열기
timeout /t 5 >nul
start "" http://localhost:8000/app/
