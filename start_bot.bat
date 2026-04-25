@echo off
echo Stopping existing LzyDownloader Discord Bridge instances...

:: Safely target only python processes executing 'bot.py'
wmic process where "name like 'python%%.exe' and commandline like '%%bot.py%%'" call terminate >nul 2>&1

echo Starting new instance...
start "" pythonw bot.py