@echo off
rem ASCII-only batch. Waits and retries once: CODESYS is single-instance and the previous
rem run may not have released its mutex yet, which shows up as an empty log + exit 1.
setlocal
set "EXE=C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe"
set "SCR=%~dp0probe_devices.py"
set "OUT=%~dp0probe_devices_stdout.txt"
echo SCR=[%SCR%] > "%OUT%"
"%EXE%" --profile="CODESYS V3.5 SP17 Patch 3" --runscript="%SCR%" --noUI >> "%OUT%" 2>&1
echo [exit=%ERRORLEVEL%] >> "%OUT%"
