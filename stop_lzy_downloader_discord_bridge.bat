@echo off
echo Stopping LzyDownloader Discord Bridge...

:: Tell the start-script supervisor not to relaunch the bridge.
set "STOP_MARKER=%~dp0lzy_downloader_discord_bridge.stop"
>"%STOP_MARKER%" echo stop

:: Find and terminate the specific Python process running this bridge
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name like 'python%%.exe' and CommandLine like '%%lzy_downloader_discord_bridge.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

:: Also terminate any orphaned headless LzyDownloader server processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name = 'LzyDownloader.exe' and CommandLine like '%%--server%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo Bot stopped successfully!
