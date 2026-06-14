@echo off
REM ── 고문서 OCR 복원: 설치 스크립트 (Windows) ──
REM 가상환경(.venv) 생성 → 코어 의존성 + PaddleOCR 설치까지 한 번에 수행합니다.
chcp 65001 >nul
setlocal
cd /d "%~dp0"

REM 1) paddlepaddle 휠과 호환되는 Python(3.9~3.13) 찾기
set "PYEXE="
for %%V in (3.12 3.11 3.10 3.13 3.9) do (
  if not defined PYEXE (
    py -%%V -c "import sys" >nul 2>&1 && set "PYEXE=py -%%V"
  )
)
if not defined PYEXE (
  py -3 -c "import sys; exit(0 if (3,9)<=sys.version_info[:2]<=(3,13) else 1)" >nul 2>&1 && set "PYEXE=py -3"
)
if not defined PYEXE (
  echo [오류] paddlepaddle와 호환되는 Python(3.9~3.13)을 찾지 못했습니다.
  echo        https://www.python.org/downloads/ 에서 Python 3.12 설치를 권장합니다.
  exit /b 1
)
echo ▶ 사용할 Python: %PYEXE%

REM 2) 가상환경 생성
if not exist ".venv" (
  %PYEXE% -m venv .venv
)
call .venv\Scripts\activate.bat

REM 3) 패키징 도구 최신화
python -m pip install --upgrade pip setuptools wheel

REM 4) 코어 의존성
python -m pip install -r requirements.txt

REM 5) PaddleOCR (CPU). 용량이 큽니다.
python -m pip install "paddlepaddle>=3.0" "paddleocr>=3.0"

echo.
echo ✓ 설치 완료. 서버 실행:  start.bat
echo   브라우저에서 http://localhost:8000/app/ 가 열립니다.
endlocal
