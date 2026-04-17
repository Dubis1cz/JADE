@echo off
title JARVIS App Builder
echo.
echo  =============================================
echo   J.A.R.V.I.S. - Building App
echo  =============================================
echo.

taskkill /F /IM electron.exe /T >nul 2>&1
taskkill /F /IM JARVIS.exe /T >nul 2>&1
timeout /t 2 /nobreak >nul

echo  [..] Cleaning old build...
if exist dist rd /s /q dist
mkdir dist

echo  [..] Copying latest files...
copy /Y ..\jarvis.html jarvis.html >nul 2>&1
copy /Y ..\login.html  login.html  >nul 2>&1
copy /Y ..\server.py   server.py   >nul 2>&1
echo  [OK] Files copied

if not exist node_modules (
    echo  [..] Installing dependencies...
    call npm install
)

echo.
echo  [..] Building JARVIS app... (2-5 minutes)
call npx electron-packager . JARVIS --platform=win32 --arch=x64 --icon=src/icon.ico --out=dist --overwrite --asar --prune=true

if errorlevel 1 ( echo [ERROR] Build failed & pause & exit )

echo  [..] Adding resources to app...
if exist "dist\JARVIS-win32-x64\resources" (
    copy /Y jarvis.html "dist\JARVIS-win32-x64\resources\" >nul
    copy /Y login.html  "dist\JARVIS-win32-x64\resources\" >nul
    copy /Y server.py   "dist\JARVIS-win32-x64\resources\" >nul
    if exist python-embed (
        xcopy /E /I /Y python-embed "dist\JARVIS-win32-x64\resources\python-embed" >nul
        echo  [OK] Bundled Python included
    )
)

echo.
echo  =============================================
echo   SUCCESS! Zip and send:
echo   dist\JARVIS-win32-x64\
echo  =============================================
pause
