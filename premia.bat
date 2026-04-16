@echo off
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
cd "C:\Users\sadiq\Documents\Claude\Projects\PREMIA"
echo Running pre-flight connection test...
python test_connection.py
echo.
echo Starting PREMIA Bot...
REM Use --paper for paper mode (default)
REM Remove --paper to run via 1LY webhook (set ONELY enabled=True in config.py first)
python main.py
pause
