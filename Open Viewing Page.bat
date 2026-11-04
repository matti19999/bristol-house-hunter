@echo off
title House Hunter viewing page - close this window to stop
cd /d "%~dp0"
python viewing_page.py
if errorlevel 1 pause
