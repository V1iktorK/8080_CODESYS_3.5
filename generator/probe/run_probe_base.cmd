@echo off
rem ASCII-only batch with diagnostics.
setlocal
set "EXE=C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe"
set "SCR=%~dp0probe_base.py"
set "OUT=%~dp0probe_base_stdout.txt"
echo SCR=[%SCR%] > "%OUT%"
if exist "%SCR%" (echo SCRIPT EXISTS >> "%OUT%") else (echo SCRIPT MISSING >> "%OUT%")
"%EXE%" --profile="CODESYS V3.5 SP17 Patch 3" --runscript="%SCR%" --noUI >> "%OUT%" 2>&1
echo [exit=%ERRORLEVEL%] >> "%OUT%"
