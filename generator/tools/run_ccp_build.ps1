# run_ccp_build.ps1 - запуск скрипта CODESYS в ИЗОЛИРОВАННОЙ сцене (этапы 3.4/3.5).
#
# ПОЧЕМУ ОТДЕЛЬНЫЙ РАННЕР, А НЕ run_codesys.ps1:
#   Рядом на той же машине собирается соседний проект Z80_EMU. Его раннер
#   использует ТУ ЖЕ сцену C:\dsh8080\work\stage и ТУ ЖЕ рабочую папку
#   C:\dsh8080\work\emu и перед каждым запуском делает taskkill CODESYS.exe.
#   Последствия (проверено, см. docs/03_ЖУРНАЛ_СБОРКИ.md п. 12.6):
#     * чужой запуск снимает наш процесс CODESYS (лог обрывается);
#     * чужие модули .py копируются в общую сцену;
#     * чужие *.plcopenxml подменяют зависимости ядра 8080.
#
#   Здесь всё то же самое, но в СВОИХ папках:
#     сцена      C:\dsh8080\work\stage_ccp
#     рабочий    C:\dsh8080\work\emu_ccp   (src/, build/, log/)
#   Плюс ожидание «тихого окна»: запуск начинается только тогда, когда
#   процессов CODESYS.exe нет в течение QuietSec секунд подряд.
#   Если во время прогона появился чужой процесс CODESYS - попытка считается
#   сорванной (лог пуст или оборван) и повторяется.
#
# Usage:
#   run_ccp_build.ps1 -Script <путь\к\драйверу.py> [-MaxAttempts 3] [-RunTimeoutSec 900]

param(
    [Parameter(Mandatory = $true)][string]$Script,
    [string]$ProjectRoot,
    [int]$MaxAttempts = 3,
    [int]$RunTimeoutSec = 900,
    [int]$QuietSec = 30
)

$ErrorActionPreference = 'Stop'
$codesysExe = 'C:\Program Files (x86)\CODESYS 3.5.17.30\CODESYS\Common\CODESYS.exe'
$profile    = 'CODESYS V3.5 SP17 Patch 3'
$Stage      = 'C:\dsh8080\work\stage_ccp'
$WorkRoot   = 'C:\dsh8080\work\emu_ccp'

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

# «Тихое окно»: ни одного процесса CODESYS QuietSec секунд подряд.
function Wait-QuietWindow {
    param([int]$Seconds = 30, [int]$MaxWaitSec = 180)
    $quietFrom = $null
    $deadline = (Get-Date).AddSeconds($MaxWaitSec)
    while ((Get-Date) -lt $deadline) {
        if (Get-Process -Name CODESYS -ErrorAction SilentlyContinue) {
            $quietFrom = $null
            Start-Sleep -Seconds 3
        } else {
            if (-not $quietFrom) { $quietFrom = Get-Date }
            if (((Get-Date) - $quietFrom).TotalSeconds -ge $Seconds) { return $true }
            Start-Sleep -Seconds 3
        }
    }
    return $false
}

function Wait-CodesysExit {
    param([int]$TimeoutSec = 900)
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        if (-not (Get-Process -Name CODESYS -ErrorAction SilentlyContinue)) { return $true }
        Start-Sleep -Seconds 2
    }
    return $false
}

# --- сцена: исходники -> своя локальная папка ---
Get-ChildItem $srcDir -Filter '*.py' -File | ForEach-Object { Copy-Item $_.FullName -Destination $Stage -Force }
$staged = Join-Path $Stage ([System.IO.Path]::GetFileName($Script))
$stdout = Join-Path $Stage ([System.IO.Path]::GetFileNameWithoutExtension($Script) + '.stdout.txt')

# --- зависимости ядра: из отдельной папки dep_ccp (копия src проекта 8080_CODESYS_3.5) ---
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

# лог прошлого запуска удаляем ДО цикла: иначе «лог непустой = успех» сработает
# на старом файле (docs/03_ЖУРНАЛ_СБОРКИ.md, п. 11.3)
if (Test-Path $workLog) { Remove-Item $workLog -Force -ErrorAction SilentlyContinue }

for ($attempt = 1; $attempt -le $MaxAttempts; $attempt++) {
    Write-Host "--- attempt $attempt : ждём тихое окно ($QuietSec с) ---"
    [void](Wait-QuietWindow -Seconds $QuietSec -MaxWaitSec 900)
    Stop-CodesysLeftovers
    Start-Sleep -Seconds 3
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
    # успех = лог непустой И дошли до конца драйвера (строка === DONE ===)
    if ($logOk -and (Select-String -Path $workLog -Pattern '=== DONE ===' -Quiet)) { break }
    Write-Host "    лог неполный - повторяем"
}

Stop-CodesysLeftovers
$projBuild = Join-Path $ProjectRoot 'build'
New-Item -ItemType Directory -Force -Path $projBuild | Out-Null
foreach ($pair in @(@((Join-Path $WorkRoot 'src'), (Join-Path $ProjectRoot 'src')),
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
    if ($err) { Write-Host '--- stderr (сообщения компилятора) ---'; $err }
}
Write-Host '--- log (из проектной папки) ---'
Get-Content $liveLog -ErrorAction SilentlyContinue
