# run_bisect.ps1 - АВТОМАТИЧЕСКАЯ БИСЕКЦИЯ ОШИБКИ КОМПИЛЯЦИИ ПО ТЕЛАМ POU.
#
# ЗАЧЕМ. Headless-компилятор CODESYS печатает у ошибки только код и текст
# ("C32: Невозможно конвертировать тип 'BYTE' в тип 'BOOL'") БЕЗ имени POU и
# номера сети. Статическая проверка tools/check_types.py после закрытия всех
# найденных слепых зон ошибку не находит. Значит, локализовать её должен
# компилятор - бисекцией.
#
# ИДЕЯ. Обозначим T(S) = "ошибка C32 есть, если ОПУСТОШИТЬ тела POU из S"
# (интерфейсы всех POU остаются на месте, поэтому проект всегда
# САМОСОГЛАСОВАН и каскада C0046 не возникает - в этом отличие от удаления POU).
# Известно T(пусто) = истина. Делим множество кандидатов cur на A и B:
#     T(A) = ложь -> ошибка внутри A  -> cur := A
#     T(A) = истина -> ошибки в A нет -> cur := B
# Так как ошибка ровно одна, после log2(N) сборок остаётся один POU.
#
# КАЖДАЯ СБОРКА - ОТДЕЛЬНЫЙ ПРОЦЕСС CODESYS: делает её gen_bisect2.py
# (переменная окружения DSH_BISECT_EMPTY), запускается через run_stage4.ps1.
#
# Запуск:
#   & '.\tools\run_bisect.ps1'
# Результат: C:\dsh8080\work\bisect_result.txt (и журнал в консоль).

param(
    [string]$NamesFile = 'C:\dsh8080\work\pou_names.txt',
    [string]$OutFile = 'C:\dsh8080\work\bisect_result.txt',
    [int]$BuildAttempts = 4,
    [int]$RunTimeoutSec = 1500
)

$ErrorActionPreference = 'Continue'
$GenDir = Split-Path -Parent $PSScriptRoot
$Runner = Join-Path $PSScriptRoot 'run_stage4.ps1'
$Script = Join-Path $GenDir 'gen_bisect2.py'
$ErrLog = 'C:\dsh8080\work\stage_s4\gen_bisect2.stdout.txt.err'
$WorkLog = 'C:\dsh8080\work\emu_s4\log\gen_bisect2.log'

function Say($m) {
    $line = '[{0:HH:mm:ss}] {1}' -f (Get-Date), $m
    Write-Host $line
    Add-Content -Path $OutFile -Value $line -Encoding UTF8
}

if (Test-Path $OutFile) { Remove-Item $OutFile -Force }
Say "=== БИСЕКЦИЯ ОШИБКИ КОМПИЛЯЦИИ ==="
Say "генератор: $Script"
Say "имена    : $NamesFile"

# --- одна сборка; возвращает @{ok=...; c32=...} ---
function Invoke-Build {
    param([string[]]$Empty, [string]$Label)
    for ($a = 1; $a -le $BuildAttempts; $a++) {
        $env:DSH_BISECT_EMPTY = ($Empty -join ',')
        $env:DSH_S4_NO_ONLINE = '1'
        Remove-Item $ErrLog -Force -ErrorAction SilentlyContinue
        Remove-Item $WorkLog -Force -ErrorAction SilentlyContinue
        & $Runner -Script $Script -MaxAttempts 1 -RunTimeoutSec $RunTimeoutSec `
                  -QuietSec 5 -NoSrcCopy *> $null
        $ran = (Test-Path $WorkLog) -and ((Get-Item $WorkLog -ErrorAction SilentlyContinue).Length -gt 0)
        $compiled = $false
        $c32 = $false
        if (Test-Path $ErrLog) {
            $t = Get-Content $ErrLog -Raw -Encoding UTF8
            if ($t) {
                $compiled = $t -match 'Компиляция завершена'
                $c32 = $t -match 'C32'
            }
        }
        Say ("    [$Label] попытка $a : скрипт=$ran компиляция=$compiled C32=$c32 (опустошено $($Empty.Count))")
        if ($ran -and $compiled) { return @{ ok = $true; c32 = $c32 } }
        Start-Sleep -Seconds 6
    }
    return @{ ok = $false; c32 = $false }
}

$all = @(Get-Content $NamesFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() })
Say "всего имён-кандидатов: $($all.Count)"

# --- ШАГ 0: базовая линия, опустошены ВСЕ тела ---
$r = Invoke-Build -Empty $all -Label 'ШАГ0'
if (-not $r.ok) { Say 'НЕ УДАЛОСЬ выполнить сборку шага 0 - стоп'; exit 2 }
if ($r.c32) {
    Say 'ИТОГ: ошибка C32 ОСТАЁТСЯ даже при полностью опустошённых телах всех 67 POU.'
    Say '      Значит, она НЕ в этих POU, а в 27 зависимостях ядра, в DUT или в GVL.'
    exit 3
}
Say 'ШАГ0: при пустых телах C32 исчезла -> ошибка ВНУТРИ одного из 67 POU.'

# --- бисекция ---
$cur = $all
$iter = 0
while ($cur.Count -gt 1) {
    $iter++
    $half = [int][math]::Ceiling($cur.Count / 2.0)
    $A = @($cur[0..($half - 1)])
    $B = @($cur[$half..($cur.Count - 1)])
    Say "--- итерация $iter : кандидатов $($cur.Count), опустошаем A ($($A.Count)) ---"
    $r = Invoke-Build -Empty $A -Label "ИТ$iter"
    if (-not $r.ok) { Say 'НЕ УДАЛОСЬ выполнить сборку - стоп'; exit 2 }
    if ($r.c32) {
        Say "    C32 осталась -> ошибка НЕ в A, продолжаем с B ($($B.Count))"
        $cur = $B
    } else {
        Say "    C32 исчезла -> ошибка ВНУТРИ A ($($A.Count))"
        $cur = $A
    }
}

$hit = $cur[0]
Say "НАЙДЕН POU-КАНДИДАТ: $hit"

# --- проверка: опустошаем только его ---
$r = Invoke-Build -Empty @($hit) -Label 'ПРОВ'
if (-not $r.ok) { Say 'НЕ УДАЛОСЬ выполнить проверочную сборку'; exit 2 }
if ($r.c32) {
    Say "ПРОВЕРКА: C32 осталась -> $hit НЕ виноват (влияние нескольких ошибок?)"
    exit 4
}
Say "ПОДТВЕРЖДЕНО: опустошение тела $hit убирает C32 -> ошибка в этом POU."
Say '=== ГОТОВО ==='
exit 0
