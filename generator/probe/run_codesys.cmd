@echo off
rem ASCII-only runner. Usage: run_codesys.cmd <script.py>
rem Waits for any previous CODESYS instance to exit, then runs the script headless.
setlocal
set "EXE=C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe"
set "SCR=%~1"
set "OUT=%~dp1%~n1_stdout.txt"
"%EXE%" --profile="CODESYS V3.5 SP17 Patch 3" --runscript="%SCR%" --noUI > "%OUT%" 2>&1
echo [exit=%ERRORLEVEL%] >> "%OUT%"
