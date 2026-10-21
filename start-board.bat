@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul
set "PYTHONUTF8=1"
set "BOARD_EXEC_FLAGS="
cd /d "%~dp0"
if defined BOARD_PYTHON goto check_custom
:check_venv
if not exist ".venv\Scripts\python.exe" goto check_py
".venv\Scripts\python.exe" -I -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto check_py
set "BOARD_EXEC=%~dp0.venv\Scripts\python.exe"
goto run
:check_custom
"%BOARD_PYTHON%" -I -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto check_venv
set "BOARD_EXEC=%BOARD_PYTHON%"
goto run
:check_py
py -3 -I -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto check_python
set "BOARD_EXEC=py"
set "BOARD_EXEC_FLAGS=-3"
goto run
:check_python
python -I -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto check_python3
set "BOARD_EXEC=python"
goto run
:check_python3
python3 -I -c "import sys; raise SystemExit(sys.version_info < (3, 10))" >nul 2>&1
if errorlevel 1 goto missing
set "BOARD_EXEC=python3"
goto run
:missing
echo Python 3.10+ is required: https://www.python.org/downloads/windows/
if not defined CI pause
exit /b 1
:run
"%BOARD_EXEC%" %BOARD_EXEC_FLAGS% "%~dp0launcher.py" %*
set "BOARD_RESULT=%errorlevel%"
if not "%BOARD_RESULT%"=="0" if not defined CI pause
exit /b %BOARD_RESULT%
