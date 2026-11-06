# run_bisect_net.ps1 - ВТОРОЙ УРОВЕНЬ БИСЕКЦИИ: ПО СЕТЯМ ВНУТРИ ОДНОГО POU.
#
# ЗАЧЕМ. tools/run_bisect.ps1 локализовал ошибку C32 до POU FB_CPU8080_FULL
# (опустошение его тела убирает ошибку, опустошение любых других POU - нет).
# Но статическая проверка tools/check_types.py внутри этого POU ошибку не
# видит, а голова компилятора не сообщает ни сети, ни имени. Поэтому тот же
# приём применяется уровнем ниже: опустошаются не тела POU, а ОТДЕЛЬНЫЕ СЕТИ
# внутри FB_CPU8080_FULL (DSH_BISECT_NET), при этом остальные 66 POU тоже
# опустошены, чтобы кодогенерировался ровно один этот POU и сигнал был
# однозначным.
#
# Логика та же: T(S) = "C32 есть, если опустошить сети из S". Известно
# T(пусто) = истина (ошибка есть) и T(все) = ложь (это равно опустошению тела,
# проверено). Делим cur на A и B: T(A)=ложь -> ошибка в A, иначе - в B.
#
# Результат: C:\dsh8080\work\bisect_net_result.txt

param(
    [string]$NamesFile = 'C:\dsh8080\work\pou_names.txt',
    [string]$OutFile = 'C:\dsh8080\work\bisect_net_result.txt',
    [string]$Pou = 'FB_CPU8080_FULL',
    [int]$NetCount = 0,
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
Say "=== БИСЕКЦИЯ ПО СЕТЯМ ВНУТРИ $Pou ==="

# остальные POU опустошаем, чтобы кодогенерировался только целевой POU
$all = @(Get-Content $NamesFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() })
$others = @($all | Where-Object { $_ -ne $Pou })
Say "опустошаются тела $($others.Count) POU (все, кроме $Pou)"

if ($NetCount -le 0) {
    # число сетей берём у самого генератора
    $py = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import check_types as CT
for grp, mk in CT.GROUPS:
    for m in mk:
        p = m()
        if p.name == u'$Pou':
            print(len(p.networks))
            break
"@
    $tmp = Join-Path $env:TEMP 'netcount.py'
    Set-Content -Path $tmp -Value $py -Encoding UTF8
    $NetCount = [int](& python -X utf8 $tmp | Select-Object -Last 1)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
Say "сетей в $Pou : $NetCount"
if ($NetCount -le 1) { Say 'не удалось определить число сетей - стоп'; exit 2 }

function Invoke-Build {
    param([int[]]$Empty, [string]$Label)
    for ($a = 1; $a -le $BuildAttempts; $a++) {
        $env:DSH_BISECT_EMPTY = ($others -join ',')
        $env:DSH_BISECT_NET_POU = $Pou
        $env:DSH_BISECT_NET = (($Empty | ForEach-Object { "$_" }) -join ',')
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
        Say ("    [$Label] попытка $a : скрипт=$ran компиляция=$compiled C32=$c32 (сетей опустошено $($Empty.Count))")
        if ($ran -and $compiled) { return @{ ok = $true; c32 = $c32 } }
        Start-Sleep -Seconds 6
    }
    return @{ ok = $false; c32 = $false }
}

# --- БАЗА: ничего не опустошаем -> ошибка ДОЛЖНА быть ---
$r = Invoke-Build -Empty @() -Label 'БАЗА'
if (-not $r.ok) { Say 'не удалось выполнить базовую сборку - стоп'; exit 2 }
if (-not $r.c32) {
    Say 'ОШИБКИ НЕТ уже при целом теле - база не подтверждена, стоп'
    exit 3
}
Say 'БАЗА: при целом теле ошибка C32 есть - верно.'

# ================= БИСЕКЦИЯ ПО СУФФИКСУ СЕТЕЙ =================
# ПОЧЕМУ ИМЕННО СУФФИКС, А НЕ ПРОИЗВОЛЬНОЕ ПОДМНОЖЕСТВО.
# Первая версия опустошала ПРОИЗВОЛЬНЫЕ сети (первую половину) - и сборка
# падала, не дойдя до компиляции. Причина: связи в схеме ссылаются на localId,
# и ссылка всегда идёт НАЗАД (на элемент более ранней сети или той же сети).
# Убрав ПЕРВЫЕ сети, мы оставляем в последующих сетях ссылки на несуществующие
# элементы - XML становится неразборным.
# Если же опустошать СУФФИКС (сети k..N-1), то все оставленные сети 0..k-1
# ссылаются только на себя и на ещё более ранние - ссылки ЦЕЛЫ.
#
# T(k) = "C32 есть, если опустошить сети k..N-1". T(0) = ложь (опустошено всё -
# это равно пустому телу, проверено), T(N) = истина (ничего не опустошено).
# T монотонна по k; ищем k* = min{k : T(k) = истина}, тогда ошибка в сети k*-1.
$lo = 0
$hi = $NetCount
Say "суффиксная бисекция: T(0)=ложь (всё опустошено), T($hi)=истина (тело целое)"
while (($hi - $lo) -gt 1) {
    $mid = [int][math]::Floor(($lo + $hi) / 2.0)
    $S = @($mid..($NetCount - 1))
    Say "--- опустошаем суффикс k=$mid : сети $($S -join ',') (остаётся $mid) ---"
    $r = Invoke-Build -Empty $S -Label "k=$mid"
    if (-not $r.ok) { Say 'не удалось выполнить сборку - стоп'; exit 2 }
    if ($r.c32) {
        Say "    C32 осталась -> ошибка НЕ в суффиксе, ищем ниже: hi=$mid"
        $hi = $mid
    } else {
        Say "    C32 исчезла -> ошибка В суффиксе, ищем выше: lo=$mid"
        $lo = $mid
    }
}

$hit = $hi - 1
Say "НАЙДЕНА СЕТЬ: индекс $hit (k* = $hi)"
if ($hit -lt 0 -or $hit -ge $NetCount) { Say 'граница вне диапазона - стоп'; exit 5 }
$r = Invoke-Build -Empty @($hit) -Label 'ПРОВ'
if (-not $r.ok) { Say 'не удалось выполнить проверочную сборку'; exit 2 }
if ($r.c32) { Say "ПРОВЕРКА: опустошение сети $hit ошибку НЕ убирает"; exit 4 }
Say "ПОДТВЕРЖДЕНО: ошибка C32 в СЕТИ $hit POU $Pou."
Say '=== ГОТОВО ==='
exit 0
