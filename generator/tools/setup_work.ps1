# setup_work.ps1 - подготовка рабочего корня CODESYS для пересборки проекта.
#
# ЗАЧЕМ. Генератор (gen_stage4.py) пишет проект, схемы PLCopenXML, журналы и
# отчёт в рабочий корень, а не в папку репозитория. Рабочий корень НЕЛЬЗЯ держать
# внутри дерева git (44 МБ сгенерированных схем) и НЕЛЬЗЯ держать в OneDrive
# (CODESYS не читает пути OneDrive - docs/КОНСПЕКТЫ_ДЛЯ_КОЛЛЕГ/01, п. 1.3).
# Поэтому он создаётся отдельно, а этот скрипт делает это одной командой.
#
# ЧТО ДЕЛАЕТ:
#   1. создаёт рабочий корень и подпапки build/ src/ log/ report/ и сцену;
#   2. копирует туда готовый проект из репозитория (build/EMU8080_STAGE4.project)
#      как исходную точку - первый прогон не начинается с пустого каталога;
#   3. при --WithDeps кладёт снимок зависимостей ядра (src/dep_fix) в
#      C:\dsh8080\work\dep_ccp - его ищут пробы и инструменты проверки.
#
# ПРИМЕР:
#   .\setup_work.ps1
#   .\setup_work.ps1 -WorkRoot D:\emu8080 -WithDeps
#
# После этого запускается сборка:
#   .\run_stage4.ps1 -Script ..\gen_stage4.py -MaxAttempts 8 -RunTimeoutSec 2700 -NoSrcCopy

param(
    [string]$WorkRoot = 'C:\dsh8080\work\emu_s4',
    [string]$Stage    = 'C:\dsh8080\work\stage_s4',
    [string]$DepRoot  = 'C:\dsh8080\work\dep_ccp',
    [switch]$WithDeps,
    [switch]$Force
)

$ErrorActionPreference = 'Stop'

# Корень репозитория = на два уровня выше generator\tools
$ProjectRoot = Split-Path -Parent (Split-Path -Parent $PSScriptRoot)

Write-Host "project : $ProjectRoot"
Write-Host "work    : $WorkRoot"
Write-Host "stage   : $Stage"

foreach ($d in @($WorkRoot, (Join-Path $WorkRoot 'build'), (Join-Path $WorkRoot 'src'),
                 (Join-Path $WorkRoot 'log'), (Join-Path $WorkRoot 'report'), $Stage)) {
    if (-not (Test-Path $d)) { New-Item -ItemType Directory -Force -Path $d | Out-Null; Write-Host "created : $d" }
    else { Write-Host "exists  : $d" }
}

# Исходная точка: готовый проект из репозитория (перезаписываем только с -Force)
$seedSrc = Join-Path $ProjectRoot 'build\EMU8080_STAGE4.project'
$seedDst = Join-Path (Join-Path $WorkRoot 'build') 'EMU8080_STAGE4.project'
if (Test-Path $seedSrc) {
    if (-not (Test-Path $seedDst) -or $Force) {
        Copy-Item $seedSrc $seedDst -Force
        Write-Host "seeded  : $seedDst"
    } else {
        Write-Host "kept    : $seedDst (уже есть; перезапись - с -Force)"
    }
} else {
    Write-Host "warning : в репозитории нет build\EMU8080_STAGE4.project - проект будет создан заново"
}

if ($WithDeps) {
    $snap = Join-Path $ProjectRoot 'src\dep_fix'
    if (-not (Test-Path $snap)) {
        Write-Host "warning : в репозитории нет src\dep_fix - снимок зависимостей не скопирован"
    } else {
        if (-not (Test-Path $DepRoot)) { New-Item -ItemType Directory -Force -Path $DepRoot | Out-Null }
        Copy-Item (Join-Path $snap '*') -Destination $DepRoot -Force
        $n = (Get-ChildItem $DepRoot -Filter '*.plcopenxml' -File).Count
        Write-Host "deps    : $n файлов в $DepRoot"
    }
}

Write-Host ''
Write-Host 'Готово. Дальше - сборка:'
Write-Host ('  ' + (Join-Path $PSScriptRoot 'run_stage4.ps1') +
            ' -Script ' + (Join-Path $ProjectRoot 'generator\gen_stage4.py') +
            ' -Stage "' + $Stage + '" -WorkRoot "' + $WorkRoot + '" -MaxAttempts 8 -RunTimeoutSec 2700 -NoSrcCopy')
