@echo off
REM Gomunseo OCR - double-click launcher (Windows). Logic lives in start.bat.
REM ASCII-only content on purpose (Korean inside a .bat breaks CP949 consoles).
cd /d "%~dp0"
call "%~dp0start.bat"
