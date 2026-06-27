@echo off
echo Stopping existing LzyDownloader Discord Bridge instances...

:: Safely target only python processes executing 'bot.py'
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name like 'python%%.exe' and CommandLine like '%%bot.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

:: Also kill any lingering headless LzyDownloader server processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name = 'LzyDownloader.exe' and CommandLine like '%%--server%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo Starting new instance...
start "" pythonw bot.py