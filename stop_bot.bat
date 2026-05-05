@echo off
echo Stopping LzyDownloader Discord Bridge...

:: Find and terminate the specific Python process running bot.py
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name like 'python%%.exe' and CommandLine like '%%bot.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

:: Also terminate any orphaned headless LzyDownloader server processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name = 'LzyDownloader.exe' and CommandLine like '%%--server%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo Bot stopped successfully!
pause