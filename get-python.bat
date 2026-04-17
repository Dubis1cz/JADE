@echo off
title Downloading Portable Python for JARVIS
echo.
echo  =============================================
echo   Downloading Portable Python 3.12
echo   This is needed to bundle Python with JARVIS
echo  =============================================
echo.

if exist python-embed\python.exe (
    echo  [OK] Portable Python already downloaded!
    goto done
)

echo  [..] Creating python-embed folder...
mkdir python-embed 2>nul

echo  [..] Downloading Python 3.12 embeddable package...
echo       (about 10MB, please wait)

:: Use PowerShell to download
powershell -Command "& {[Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri 'https://www.python.org/ftp/python/3.12.8/python-3.12.8-embed-amd64.zip' -OutFile 'python-embed.zip' -UseBasicParsing}"

if not exist python-embed.zip (
    echo  [ERROR] Download failed. Check your internet connection.
    pause & exit
)

echo  [..] Extracting...
powershell -Command "Expand-Archive -Path 'python-embed.zip' -DestinationPath 'python-embed' -Force"
del python-embed.zip

:: Enable pip and site-packages in embedded Python
echo  [..] Configuring embedded Python...
:: The ._pth file needs to include Lib/site-packages
if exist python-embed\python312._pth (
    powershell -Command "(Get-Content 'python-embed\python312._pth') -replace '#import site', 'import site' | Set-Content 'python-embed\python312._pth'"
)

:: Download get-pip.py and install pip
powershell -Command "Invoke-WebRequest -Uri 'https://bootstrap.pypa.io/get-pip.py' -OutFile 'python-embed\get-pip.py' -UseBasicParsing"
python-embed\python.exe python-embed\get-pip.py --no-warn-script-location 2>nul

echo  [OK] Portable Python ready!

:done
echo.
echo  =============================================
echo   Python is ready. Now run build.bat to
echo   create the JARVIS installer.
echo  =============================================
echo.
pause
