@echo off
rem Builds dist\AwesomeHouse.exe from the files in this folder, then puts it in
rem share_package\Awesome House\ (with README, LICENSE and the About PDF) and
rem zips that folder as AwesomeHouse-Beta-0.16.1.zip, ready to send.
setlocal
set APPNAME=AwesomeHouse
set VERSION=Beta-0.16.1
set PKG=share_package\Awesome House
cd /d "%~dp0"
findstr /c:"YOUR_PAYPAL_NAME" wow_price_gui.pyw >nul && (
  echo Your PayPal link isn't set yet. Edit DONATE_URL near the top of wow_price_gui.pyw first.
  pause
  exit /b 1
)
set PY=python
where py >nul 2>nul && set PY=py
%PY% -m pip install --upgrade pyinstaller
%PY% -m PyInstaller --noconfirm --clean --onefile --windowed --name %APPNAME% --icon ah_coin_icon.ico --add-data "ah_coin_icon.ico;." --add-data "dungeon_travel.json;." wow_price_gui.pyw
echo.
if not exist dist\%APPNAME%.exe (
  echo Build failed - see the messages above.
  pause
  exit /b 1
)
echo Done: dist\%APPNAME%.exe

rem ---- share package: exe + README + LICENSE + About PDF, no personal files
if not exist "%PKG%" mkdir "%PKG%"
if exist package\README.txt copy /y package\*.* "%PKG%\" >nul
copy /y dist\%APPNAME%.exe "%PKG%\%APPNAME%.exe" >nul
rem Python's own LICENSE.txt holds the licenses of Python, OpenSSL, Tcl/Tk etc. built into the exe
set PYLIC=
for /f "usebackq delims=" %%P in (`%PY% -c "import sys,os;print(os.path.join(sys.base_prefix,'LICENSE.txt'))"`) do set PYLIC=%%P
if exist "%PYLIC%" (copy /y "%PYLIC%" "%PKG%\PYTHON-LICENSE.txt" >nul) else (echo Warning: Python's LICENSE.txt was not found - the package needs PYTHON-LICENSE.txt.)
for %%F in ("README.txt" "LICENSE.txt" "THIRD-PARTY-NOTICES.txt" "PYTHON-LICENSE.txt" "About Awesome House.pdf") do (
  if not exist "%PKG%\%%~F" echo Warning: %PKG%\%%~F is missing.
)
if exist "%APPNAME%-%VERSION%.zip" del "%APPNAME%-%VERSION%.zip"
powershell -NoProfile -Command "Compress-Archive -Path '%PKG%' -DestinationPath '%APPNAME%-%VERSION%.zip' -Force"
if exist "%APPNAME%-%VERSION%.zip" (echo Share package: %APPNAME%-%VERSION%.zip) else (echo Couldn't make the zip - the folder %PKG% is ready to zip by hand.)
pause
