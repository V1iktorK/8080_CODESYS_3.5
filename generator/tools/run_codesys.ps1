# run_codesys.ps1 - запуск скрипта в CODESYS Scripting Engine (headless).
#
# ПОЧЕМУ ВСЁ РАБОТАЕТ В ЛОКАЛЬНОЙ ПАПКЕ:
#   CODESYS 3.5 SP17 не дружит с папками, синхронизируемыми OneDrive:
#     * .py из такой папки НЕ ЧИТАЕТСЯ - процесс стартует, висит ~2 минуты и
#       завершается, не выполнив скрипт (лог-файл даже не появляется);
#     * если скрипт всё же стартовал (запущен из локальной папки), то запись
#       лога в OneDrive ВИСИТ: файл создаётся нулевой длины и дальше ничего.
#   Проверено экспериментально: из C:\dsh8080 тот же скрипт проходит целиком.
#
#   Поэтому схема такая:
#     - исходники и результаты ЖИВУТ в проектной папке (их видит пользователь);
#     - на время запуска скрипты копируются в локальную папку $Stage;
#     - CODESYS работает в локальном корне $WorkRoot (src/, build/, log/);
#     - перед запуском src/ подтягивается из проекта, после запуска результаты
#       копируются обратно средствами PowerShell.
#
# Usage:
#   run_codesys.ps1 -Script <путь\к\скрипту.py> [-ProjectRoot <папка 8080_EMU>] [-MaxAttempts 3]

param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$ProjectRoot,
    [int]$MaxAttempts = 3,
    [int]$RunTimeoutSec = 150
)

$ErrorActionPreference = 'Stop'
$codesysExe = 'C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe'
$profile    = 'CODESYS V3.5 SP17 Patch 3'
$Stage      = 'C:\dsh8080\work\stage'
$WorkRoot   = 'C:\dsh8080\work\emu'

if (-not (Test-Path $Script)) { throw "script not found: $Script" }
$Script = (Resolve-Path $Script).Path
$srcDir = Split-Path -Parent $Script
if (-not $ProjectRoot) { $ProjectRoot = Split-Path -Parent $srcDir }

$logName = [System.IO.Path]::GetFileNameWithoutExtension($Script) + '.log'
$projLog = Join-Path (Join-Path $ProjectRoot 'log') $logName
$workLog = Join-Path (Join-Path $WorkRoot 'log') $logName

New-Item -ItemType Directory -Force -Path $Stage, $WorkRoot, (Join-Path $WorkRoot 'src'),
    (Join-Path $WorkRoot 'build'), (Join-Path $WorkRoot 'log'),
    (Join-Path $ProjectRoot 'log') | Out-Null

function Stop-CodesysLeftovers {
    # Процесс-сирота держит мьютекс single-instance и блокирует все запуски.
    # Ждём, пока он реально исчезнет: если стартовать раньше, CODESYS повиснет.
    for ($i = 0; $i -lt 20; $i++) {
        if (-not (Get-Process -Name CODESYS -ErrorAction SilentlyContinue)) { break }
        & taskkill /F /T /IM CODESYS.exe 2>&1 | Out-Null
        Start-Sleep -Seconds 2
    }
    Start-Sleep -Seconds 3
}

function Wait-CodesysExit {
    param([int]$TimeoutSec = 150)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name CODESYS -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

# --- сцена: исходники -> локальная папка ---
Get-ChildItem $srcDir -Filter '*.py' -File | ForEach-Object { Copy-Item $_.FullName -Destination $Stage -Force }
$staged = Join-Path $Stage ([System.IO.Path]::GetFileName($Script))
$stdout = Join-Path $Stage ([System.IO.Path]::GetFileNameWithoutExtension($Script) + '.stdout.txt')

# --- зависимости, наработанные предыдущими подшагами, подтянуть в локальный корень ---
$projSrc = Join-Path $ProjectRoot 'src'
if (Test-Path $projSrc) {
    Get-ChildItem $projSrc -Filter '*.plcopenxml' -File -ErrorAction SilentlyContinue |
        ForEach-Object { Copy-Item $_.FullName -Destination (Join-Path $WorkRoot 'src') -Force }
}

$env:DSH_EMU_ROOT = $WorkRoot.Replace('\', '/')
Write-Host "project : $ProjectRoot"
Write-Host "work    : $WorkRoot"
Write-Host "stage   : $Stage"

# ВАЖНО: лог прошлого запуска ЭТОГО ЖЕ скрипта надо убрать до начала.
# Иначе проверка "лог непустой = попытка удалась" срабатывает на старом файле:
# CODESYS выходит мгновенно (чужой мьютекс), а раннер считает, что всё прошло,
# и печатает старый лог. Проверено на gen_core_full.
if (Test-Path $workLog) { Remove-Item $workLog -Force -ErrorAction SilentlyContinue }

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Stop-CodesysLeftovers
    Start-Sleep -Seconds 3
    # lock-файлы CODESYS от убитых процессов вешают projects.create() навсегда
    Get-ChildItem (Join-Path $WorkRoot 'build') -Filter '*.~*' -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue
    Get-ChildItem $WorkRoot -Filter '*.~*' -Force -ErrorAction SilentlyContinue |
        Remove-Item -Force -ErrorAction SilentlyContinue

    $argLine = '--profile="' + $profile + '" --runscript="' + $staged + '" --noUI'
    $p = Start-Process -FilePath $codesysExe -ArgumentList $argLine -PassThru -NoNewWindow `
                       -RedirectStandardOutput $stdout -RedirectStandardError "$stdout.err"
    [void](Wait-CodesysExit -TimeoutSec $RunTimeoutSec)
    Start-Sleep -Seconds 2

    $logOk = (Test-Path $workLog) -and ((Get-Item $workLog).Length -gt 0)
    Write-Host ("attempt {0}: exit={1} log={2}" -f $attempt, $p.ExitCode, $(if ($logOk) { 'OK' } else { 'EMPTY' }))
    if ($logOk) { break }
}

# --- вернуть результаты в проектную папку ---
Stop-CodesysLeftovers          # иначе CODESYS держит файлы и копирование падает
$projBuild = Join-Path $ProjectRoot 'build'
New-Item -ItemType Directory -Force -Path $projBuild | Out-Null
foreach ($pair in @(@((Join-Path $WorkRoot 'src'), $projSrc),
                    @((Join-Path $WorkRoot 'log'), (Join-Path $ProjectRoot 'log')),
                    @((Join-Path $WorkRoot 'build'), $projBuild))) {
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
    if ($err) { Write-Host '--- stderr ---'; $err }
}
Write-Host '--- log ---'
Get-Content $projLog -ErrorAction SilentlyContinue
