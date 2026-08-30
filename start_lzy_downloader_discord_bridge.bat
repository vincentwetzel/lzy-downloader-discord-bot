@echo off
set "SCRIPT_DIR=%~dp0"
cd /d "%SCRIPT_DIR%"

:: Stop older supervisors and the current bridge before starting one supervisor.
powershell -NoProfile -Command "try { $supervisors = @(Get-CimInstance Win32_Process -Filter \"name = 'cmd.exe'\" -ErrorAction Stop | Where-Object { $_.CommandLine -like '*start_lzy_downloader_discord_bridge.bat*' -and $_.CommandLine -like '*__supervise*' }); $supervisors | Invoke-CimMethod -MethodName Terminate -ErrorAction Stop | Out-Null } catch {}" >nul 2>&1
>"%SCRIPT_DIR%lzy_downloader_discord_bridge.stop" echo restart
powershell -NoProfile -Command "$line = netstat -ano -p udp | Select-String '127.0.0.1:48765'; if ($line) { $owner = [regex]::Match($line.ToString(), '\s(\d+)\s*$').Groups[1].Value; if ($owner) { Stop-Process -Id ([int]$owner) -Force -ErrorAction SilentlyContinue } }" >nul 2>&1
powershell -NoProfile -Command "Start-Sleep -Seconds 11" >nul 2>&1
if exist "%SCRIPT_DIR%lzy_downloader_discord_bridge.stop" del /q "%SCRIPT_DIR%lzy_downloader_discord_bridge.stop" >nul 2>&1

powershell -NoProfile -Command "$supervisor = Join-Path '%SCRIPT_DIR%' 'supervise_lzy_downloader_discord_bridge.ps1'; Start-Process -FilePath 'powershell.exe' -ArgumentList @('-NoProfile','-ExecutionPolicy','Bypass','-WindowStyle','Hidden','-File',$supervisor) -WorkingDirectory '%SCRIPT_DIR%' -WindowStyle Hidden" >nul 2>&1
exit /b 0
