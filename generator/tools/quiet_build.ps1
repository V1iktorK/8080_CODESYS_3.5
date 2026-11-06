# Сборка+прогон 8080 с ВРЕМЕННОЙ ЗАМОРОЗКОЙ чужих прогонов CODESYS.
#
# Причина: CODESYS однопроцессный (общий мьютекс), а соседний проект (Z80)
# держит его непрерывной серией проб, причём его обёртки перед каждым запуском
# делают taskkill /F /T /IM CODESYS.exe - то есть убивают и нашу сборку.
# Ожидание "тихого окна" не помогает: окна короче сборки.
#
# Здесь чужие обёртки ЗАМОРАЖИВАЮТСЯ (NtSuspendProcess), а в конце
# РАЗМОРАЖИВАЮТСЯ (NtResumeProcess) в блоке finally. Это обратимо: процессы
# продолжают работу с того места, где остановились.
param(
    [string]$Script = '.\gen_stage4.py',
    [int]$Attempts = 3,
    [switch]$NoOnline
)
$ErrorActionPreference = 'Continue'

Add-Type -Namespace Win32 -Name Nt -MemberDefinition @'
[DllImport("ntdll.dll")] public static extern int NtSuspendProcess(IntPtr h);
[DllImport("ntdll.dll")] public static extern int NtResumeProcess(IntPtr h);
'@

$gen = 'C:\Users\Ольга\OneDrive\Рабочий стол\CODESYS\8080_CODESYS_3.5\generator'
$frozen = @()
try {
    # Замораживаем ВСЕ оболочки, кроме относящихся к нашему проекту (8080_CODESYS_3.5).
    # Узкий фильтр по Z80 не работает: чужой цикл порождает НОВЫЕ обёртки уже
    # после заморозки, и каждая из них делает taskkill /IM CODESYS.exe /F.
    # Наши собственные команды всегда содержат путь ...\8080_CODESYS_3.5\..., поэтому
    # они под правило не попадают.
    $foreign = @(Get-CimInstance Win32_Process -Filter "Name='powershell.exe' OR Name='pwsh.exe' OR Name='cmd.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -and ($_.CommandLine -notmatch '8080_CODESYS_3.5') -and
                       ($_.CommandLine -match 'CODESYS|Z80|run_probe|audit|make_z80|gen_z80|bisect|run_quick|taskkill') })
    Write-Host ("чужих оболочек найдено: " + $foreign.Count)
    foreach ($p in $foreign) {
        try {
            $pr = Get-Process -Id $p.ProcessId -ErrorAction Stop
            [Win32.Nt]::NtSuspendProcess($pr.Handle) | Out-Null
            $frozen += $pr
            Write-Host ("  заморожен " + $p.ProcessId)
        } catch {
            Write-Host ("  НЕ удалось заморозить " + $p.ProcessId + ": " + $_.Exception.Message)
        }
    }
    & taskkill /F /T /IM CODESYS.exe 2>&1 | Out-Null
    Start-Sleep -Seconds 6

    if ($NoOnline) { $env:DSH_S4_NO_ONLINE = '1' } else { Remove-Item Env:\DSH_S4_NO_ONLINE -ErrorAction SilentlyContinue }
    Push-Location $gen
    try {
        & '.\tools\run_stage4.ps1' -Script $Script -MaxAttempts $Attempts -RunTimeoutSec 1800 -QuietSec 5 2>&1 | Select-Object -Last 12
    } finally {
        Pop-Location
    }
} finally {
    foreach ($pr in $frozen) {
        try { [Win32.Nt]::NtResumeProcess($pr.Handle) | Out-Null; Write-Host ("  разморожен " + $pr.Id) } catch { }
    }
    Write-Host '=== ЗАМОРОЗКА СНЯТА ==='
}
