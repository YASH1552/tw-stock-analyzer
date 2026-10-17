@echo off
cd /d "%~dp0"
title Taiwan Stock Analyzer
python --version >nul 2>nul
if errorlevel 1 (py -3 launch.py) else (python launch.py)
if errorlevel 1 pause
