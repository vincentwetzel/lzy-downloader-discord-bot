@echo off

:: Run the supervisor in a detached child so this launcher returns immediately.
if /i not "%~1"=="__supervise" (
    :: Do not create a second supervisor for this launcher, and remove a
    :: supervisor left behind by an older copy of this bot directory.
    powershell -NoProfile -Command "$current = [IO.Path]::GetFullPath('%~f0'); $supervisors = Get-CimInstance Win32_Process -Filter \"name = 'cmd.exe'\" | Where-Object { $_.CommandLine -like '*start_lzy_downloader_discord_bridge.bat*' -and $_.CommandLine -like '*__supervise*' }; $same = $supervisors | Where-Object { $_.CommandLine -like ('*' + $current + '*') }; if ($same) { exit 1 }; $supervisors | Where-Object { $_.CommandLine -notlike ('*' + $current + '*') } | Invoke-CimMethod -MethodName Terminate | Out-Null; exit 0"
    if errorlevel 1 exit /b 0
    powershell -NoProfile -Command "Start-Process -FilePath '%ComSpec%' -ArgumentList @('/d','/c','call','%~f0','__supervise') -WindowStyle Hidden"
    exit /b 0
)

echo Stopping existing LzyDownloader Discord Bridge instances...

:: Safely target only Python processes executing this bridge
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name like 'python%%.exe' and CommandLine like '%%lzy_downloader_discord_bridge.py%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

:: Also kill any lingering headless LzyDownloader server processes
powershell -NoProfile -Command "Get-CimInstance Win32_Process -Filter \"name = 'LzyDownloader.exe' and CommandLine like '%%--server%%'\" | Invoke-CimMethod -MethodName Terminate" >nul 2>&1

echo Starting new instance...
set "STOP_MARKER=%~dp0lzy_downloader_discord_bridge.stop"
if exist "%STOP_MARKER%" del /q "%STOP_MARKER%" >nul 2>&1

:: Keep the supervisor alive so a sleep/wake-related process or gateway failure is recovered.
:supervise
if exist "%STOP_MARKER%" exit /b 0
pythonw "%~dp0lzy_downloader_discord_bridge.py"
if exist "%STOP_MARKER%" exit /b 0
echo Bridge exited unexpectedly. Restarting in 10 seconds...
timeout /t 10 /nobreak >nul
goto supervise
