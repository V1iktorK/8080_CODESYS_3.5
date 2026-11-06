# Онлайн-прогон 8080 в условиях, когда параллельно работает чужой прогон CODESYS
# (проект Z80): его обёртки делают taskkill /IM CODESYS.exe /F.
# Пересборка не нужна - проект уже собран и сохранён; нужен только прогон.
param(
    [string]$Script = '.\gen_probe_run.py',
    [int]$Tries = 25,
    [int]$WaitMin = 6
)
$ErrorActionPreference = 'Continue'
$gen = 'C:\Users\Ольга\OneDrive\Рабочий стол\CODESYS\8080_CODESYS_3.5\generator'
$name = [System.IO.Path]::GetFileNameWithoutExtension($Script)
$logPath = "C:\dsh8080\work\emu_s4\log\$name.log"

function Test-Foreign {
    $busy = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_probe_fb|audit-all|make_z80|gen_z80|run_bisect|run_quick|Z80_EMU') })
    return ($busy.Count -gt 0)
}

for ($i = 1; $i -le $Tries; $i++) {
    $dl = (Get-Date).AddMinutes($WaitMin)
    while ((Get-Date) -lt $dl) {
        if (-not (Test-Foreign)) { break }
        Start-Sleep -Seconds 4
    }
    $quiet = -not (Test-Foreign)
    Write-Host ("=== попытка $i/$Tries : тихое окно = $quiet : " + (Get-Date -Format 'HH:mm:ss') + " ===")
    & taskkill /F /T /IM CODESYS.exe 2>&1 | Out-Null
    Start-Sleep -Seconds 4
    Push-Location $gen
    try {
        & '.\tools\run_stage4.ps1' -Script $Script -MaxAttempts 1 -RunTimeoutSec 600 -QuietSec 4 -NoSrcCopy 2>&1 | Select-Object -Last 3
    } finally {
        Pop-Location
    }
    if (Select-String -Path $logPath -Pattern '=== DONE ===' -Quiet -ErrorAction SilentlyContinue) {
        Write-Host ("ПРОГОН ЗАВЕРШЁН на попытке $i")
        break
    }
}
Write-Host '=== КОНЕЦ ЦИКЛА ==='
