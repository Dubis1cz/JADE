@echo off
title JARVIS App Builder
echo.
echo  =============================================
echo   J.A.R.V.I.S. - App Builder
echo  =============================================
echo.

:: Check Node
node --version >nul 2>&1
if errorlevel 1 (
    echo  [ERROR] Node.js not found. Install from https://nodejs.org
    pause & exit
)
echo  [OK] Node.js found

:: Copy jarvis.html and server.py into app folder
echo  [..] Copying files...
copy /Y ..\jarvis.html jarvis.html >nul 2>&1
copy /Y ..\server.py server.py >nul 2>&1
if not exist jarvis.html (
    :: Try same directory
    copy /Y jarvis.html jarvis.html >nul 2>&1
)
echo  [OK] Files ready

:: Install dependencies
echo  [..] Installing Electron (this may take a few minutes)...
call npm install
if errorlevel 1 (
    echo  [ERROR] npm install failed
    pause & exit
)
echo  [OK] Dependencies installed

:: Run the app directly (no build needed for testing)
echo.
echo  =============================================
echo   Launching JARVIS...
echo   Press Ctrl+Shift+J to toggle the window
echo   Right-click the tray icon to quit
echo  =============================================
echo.
call npm start
pause
