@echo off
echo Stopping existing LzyDownloader Discord Bridge instances...

:: Safely target only Python processes executing this bridge
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name like 'python%%.exe' and CommandLine like '%%lzy_downloader_discord_bridge.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

:: Also kill any lingering headless LzyDownloader server processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name = 'LzyDownloader.exe' and CommandLine like '%%--server%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo Starting new instance...
start "" pythonw lzy_downloader_discord_bridge.py
