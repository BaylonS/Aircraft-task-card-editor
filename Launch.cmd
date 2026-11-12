@echo off
cd /d "%~dp0"
if exist "tcl\tcl8.6\init.tcl" set "TCL_LIBRARY=%~dp0tcl\tcl8.6"
if exist "tcl\tk8.6\tk.tcl" set "TK_LIBRARY=%~dp0tcl\tk8.6"
if not exist ".venv\Scripts\python.exe" (
  echo Please run Install.ps1 first. See README.md.
  pause
  exit /b 1
)
".venv\Scripts\python.exe" editor.py
if errorlevel 1 pause
