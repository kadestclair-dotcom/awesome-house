@echo off
rem Runs the Awesome House test suite. Double-click it, or run it from a terminal in this folder.
rem   run_tests.bat            everything (the window tests flash a few windows on screen)
rem   run_tests.bat fast       everything except the window tests (a couple of seconds)
rem   run_tests.bat gui        only the window tests
rem Your real key, watchlist and price history are never touched: every test uses a temporary folder,
rem and the network is blocked so nothing talks to Blizzard or GitHub.
cd /d "%~dp0"

python -c "import pytest" 2>nul || (
    echo Installing pytest...
    python -m pip install --quiet pytest || goto :nopython
)

if /i "%~1"=="fast" (
    python -m pytest -m "not gui"
) else if /i "%~1"=="gui" (
    python -m pytest tests\test_gui.py
) else (
    python -m pytest
)
set RESULT=%ERRORLEVEL%
echo.
if %RESULT%==0 (echo All tests passed.) else (echo Some tests FAILED - see the list above.)
if "%~1"=="" pause
exit /b %RESULT%

:nopython
echo Couldn't run Python. Install Python 3 from python.org (tick "Add python.exe to PATH") and try again.
pause
exit /b 1
