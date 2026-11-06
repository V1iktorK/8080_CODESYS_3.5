# run_stage4.ps1 - ИЗОЛИРОВАННЫЙ раннер скриптов CODESYS для ЭТАПА 4 (прогон + тесты).
#
# ЗАЧЕМ ЕЩЁ ОДИН РАННЕР. Соседний проект Z80_EMU использует ту же сцену
# C:\dsh8080\work\stage и тот же рабочий корень C:\dsh8080\work\emu, а перед
# каждым запуском делает taskkill /F /T /IM CODESYS.exe (docs/03, п. 12.6).
# Поэтому у этапа 4 - СВОИ папки:
#     сцена   C:\dsh8080\work\stage_s4
#     работа  C:\dsh8080\work\emu_s4   (src/, build/, log/)
# и ожидание «тихого окна»: запуск начинается только когда процессов
# CODESYS.exe нет QuietSec секунд подряд.
#
# Отличия от run_ccp_build.ps1:
#   * прогон ДОЛГИЙ (сборка + онлайн-сессия + прогон сканов), поэтому
#     RunTimeoutSec надо держать не меньше 1800 с;
#   * ключ -NoSrcCopy: не копировать рабочий src обратно в проект. Онлайн-прогон
#     и проба пишут только build/log, а src проекта этапа 3 трогать не нужно.
#
# Признак успеха - строка `=== DONE ===` в логе И непустой лог.

param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$ProjectRoot,
    [int]$MaxAttempts = 20,
    [int]$RunTimeoutSec = 1800,
    [int]$QuietSec = 5,
    [string]$Stage = 'C:\dsh8080\work\stage_s4',
    [string]$WorkRoot = 'C:\dsh8080\work\emu_s4',
    [switch]$NoSrcCopy
)

$ErrorActionPreference = 'Stop'
$codesysExe = 'C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe'
$profile    = 'CODESYS V3.5 SP17 Patch 3'

if (-not (Test-Path $Script)) { throw "script not found: $Script" }
$Script = (Resolve-Path $Script).Path
$srcDir = Split-Path -Parent $Script
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $srcDir }

$logName = [System.IO.Path]::GetFileNameWithoutExtension($Script) + '.log'
$projLog = Join-Path (Join-Path $ProjectRoot 'log') $logName
$workLog = Join-Path (Join-Path $WorkRoot 'log') $logName
$liveLog = Join-Path (Join-Path $ProjectRoot 'log') $logName

New-Item -ItemType Directory -Force -Path $Stage, $WorkRoot, (Join-Path $WorkRoot 'src'),
    (Join-Path $WorkRoot 'build'), (Join-Path $WorkRoot 'log'),
    (Join-Path $ProjectRoot 'log') | Out-Null

function Stop-CodesysLeftovers {
    for ($i = 0; $i -lt 10; $i++) {
        if (-not (Get-Process -Name CODESYS -ErrorAction SilentlyContinue)) { break }
        & taskkill /F /T /IM CODESYS.exe 2>&1 | Out-Null
        Start-Sleep -Seconds 2
    }
}

function Wait-QuietWindow {
    param([int]$Seconds = 15, [int]$MaxWaitSec = 900)
    $quietFrom = $null
    $deadline = (Get-Date).AddSeconds($MaxWaitSec)
    while ((Get-Date) -lt $deadline) {
        if (Get-Process -Name CODESYS -ErrorAction SilentlyContinue) {
            $quietFrom = $null
            Start-Sleep -Seconds 2
        } else {
            if (-not $quietFrom) { $quietFrom = Get-Date }
            if (((Get-Date) - $quietFrom).TotalSeconds -ge $Seconds) { return $true }
            Start-Sleep -Seconds 1
        }
    }
    return $false
}

# CODESYS - ОДНОПРОЦЕССНОЕ приложение (общий мьютекс). Если соседний проект уже
# держит его, наш запуск молча завершается, не выполнив скрипт (пустой лог).
# Поэтому попытка считается неудачной и повторяется - см. цикл ниже.
function Test-CodesysBusy {
    return [bool](Get-Process -Name CODESYS -ErrorAction SilentlyContinue)
}

function Wait-CodesysExit {
    param([int]$TimeoutSec = 1800)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name CODESYS -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Seconds 3
    }
    return $false
}

# --- сцена: исходники .py -> своя локальная папка ---
Get-ChildItem $srcDir -Filter '*.py' -File | ForEach-Object { Copy-Item $_.FullName -Destination $Stage -Force }
$staged = Join-Path $Stage ([System.IO.Path]::GetFileName($Script))
$stdout = Join-Path $Stage ([System.IO.Path]::GetFileNameWithoutExtension($Script) + '.stdout.txt')

# --- зависимости ядра: из отдельной папки dep_ccp (снимок src проекта 8080_EMU) ---
$depDir = 'C:\dsh8080\work\dep_ccp'
if (Test-Path $depDir) {
    Get-ChildItem $depDir -Filter '*.plcopenxml' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item $_.FullName -Destination (Join-Path $WorkRoot 'src') -Force }
}

$env:DSH_EMU_ROOT = $WorkRoot.Replace('\', '/')
Write-Host "project : $ProjectRoot"
Write-Host "work    : $WorkRoot"
Write-Host "stage   : $Stage"
Write-Host "deps    : $depDir"

# лог прошлого запуска удаляем ДО цикла (иначе «лог непустой = успех» сработает
# на старом файле - docs/03, п. 11.3)
if (Test-Path $workLog) { Remove-Item $workLog -Force -ErrorAction SilentlyContinue }

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-Host "--- attempt $attempt : ждём тихое окно ($QuietSec с) ---"
    [void](Wait-QuietWindow -Seconds $QuietSec -MaxWaitSec 1800)
    Stop-CodesysLeftovers
    Start-Sleep -Seconds 2
    Get-ChildItem (Join-Path $WorkRoot 'build') -Filter '*.~*' -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem $WorkRoot -Filter '*.~*' -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $argLine = '--profile="' + $profile + '" --runscript="' + $staged + '" --noUI'
    $p = Start-Process -FilePath $codesysExe -ArgumentList $argLine -PassThru -NoNewWindow `
                       -RedirectStandardOutput $stdout -RedirectStandardError "$stdout.err"
    $finished = Wait-CodesysExit -TimeoutSec $RunTimeoutSec
    Start-Sleep -Seconds 2

    $logOk = (Test-Path $workLog) -and ((Get-Item $workLog).Length -gt 0)
    $tail = ''
    if ($logOk) {
        $tail = (Get-Content $workLog -Tail 3 -ErrorAction SilentlyContinue) -join ' | '
    }
    Write-Host ("attempt {0}: exit={1} finished={2} log={3}" -f $attempt, $p.ExitCode, $finished, $(if ($logOk) { 'OK' } else { 'EMPTY' }))
    if ($logOk) { Write-Host "    хвост: $tail" }
    if ($logOk -and (Select-String -Path $workLog -Pattern '=== DONE ===' -Quiet)) { break }
    Write-Host "    лог неполный - повторяем"
    Start-Sleep -Seconds 5
}

Stop-CodesysLeftovers
$projBuild = Join-Path $ProjectRoot 'build'
New-Item -ItemType Directory -Force -Path $projBuild | Out-Null
$pairs = @(@((Join-Path $WorkRoot 'log'), (Join-Path $ProjectRoot 'log')),
            @((Join-Path $WorkRoot 'build'), $projBuild))
if (-not $NoSrcCopy) {
    $pairs += , @((Join-Path $WorkRoot 'src'), (Join-Path $ProjectRoot 'src'))
}
foreach ($pair in $pairs) {
    if (Test-Path $pair[0]) {
        try {
            Copy-Item (Join-Path $pair[0] '*') -Destination $pair[1] -Recurse -Force -ErrorAction SilentlyContinue
        } catch { }
    }
}
if (Test-Path $workLog) {
    try { Copy-Item $workLog -Destination $projLog -Force -ErrorAction SilentlyContinue } catch { }
}

Write-Host '--- stdout ---'
Get-Content $stdout -ErrorAction SilentlyContinue
if (Test-Path "$stdout.err") {
    $err = Get-Content "$stdout.err" -ErrorAction SilentlyContinue
    if ($err) { Write-Host '--- stderr (сообщения компилятора) ---'; $err }
}
Write-Host '--- log (из проектной папки) ---'
Get-Content $liveLog -ErrorAction SilentlyContinue
