# Сборка 8080 в условиях, когда параллельно работает чужой прогон CODESYS
# (проект Z80): его обёртки делают taskkill /IM CODESYS.exe /F и убивают нашу
# сборку. Здесь ждём, пока чужие прогоны закончатся, и только тогда собираем.
param(
    [int]$Tries = 5,
    [int]$WaitMin = 8
)
$ErrorActionPreference = 'Continue'
$logPath = 'C:\dsh8080\work\emu_s4\log\gen_stage4.log'
$gen = 'C:\Users\Ольга\OneDrive\Рабочий стол\CODESYS\8080_CODESYS_3.5\generator'

function Test-Foreign {
    $busy = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -match 'run_probe_fb|audit-all|make_z80|gen_z80|run_bisect|run_quick|Z80_EMU') })
    return ($busy.Count -gt 0)
}

for ($i = 1; $i -le $Tries; $i++) {
    Write-Host ("=== попытка $i из $Tries ===")
    $dl = (Get-Date).AddMinutes($WaitMin)
    while ((Get-Date) -lt $dl) {
        if (-not (Test-Foreign)) { break }
        Write-Host ("  чужой прогон идёт, ждём... " + (Get-Date -Format 'HH:mm:ss'))
        Start-Sleep -Seconds 6
    }
    if (Test-Foreign) { Write-Host '  чужой прогон так и не закончился за отведённое время' }
    else { Write-Host '  тихое окно есть, собираем' }

    & taskkill /F /T /IM CODESYS.exe 2>&1 | Out-Null
    Start-Sleep -Seconds 5
    Push-Location $gen
    try {
        & '.\tools\run_stage4.ps1' -Script '.\gen_stage4.py' -MaxAttempts 2 -RunTimeoutSec 1800 -QuietSec 6 -NoSrcCopy 2>&1 | Select-Object -Last 6
    } finally {
        Pop-Location
    }
    if (Select-String -Path $logPath -Pattern '=== DONE ===' -Quiet -ErrorAction SilentlyContinue) {
        Write-Host ("СБОРКА ЗАВЕРШЕНА на попытке $i")
        break
    }
    Write-Host '  сборка не дошла до конца, повторяем'
}
Write-Host '=== КОНЕЦ ЦИКЛА ==='
