@echo off
REM One-click launcher for the 京剧 visualization system.
REM Double-click this file. It calls start.ps1 which boots backend + frontend
REM and opens the browser automatically.
powershell -NoProfile -ExecutionPolicy Bypass -File "%~dp0start.ps1"
