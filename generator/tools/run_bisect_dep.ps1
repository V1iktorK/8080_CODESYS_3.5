# run_bisect_dep.ps1 - ЧЕТВЁРТЫЙ УРОВЕНЬ БИСЕКЦИИ: СЕТИ ВНУТРИ ЗАВИСИМОСТИ ЯДРА.
#
# ПУТЬ ЛОКАЛИЗАЦИИ (этап A5), три уровня уже пройдены:
#   1) по телам 67 POU      -> FB_CPU8080_FULL
#   2) по сетям этого POU   -> сеть 17 ("Флаги S/Z/P результата DAA")
#   3) по элементам сети    -> виновник появляется вместе с ВЫЗОВОМ FB_ALU8
#                              (первые 4 элемента = только литералы, ошибки нет;
#                               добавляем вызов FB_ALU8 - ошибка есть)
# Отсюда вывод: ошибка внутри САМОЙ ЗАВИСИМОСТИ FB_ALU8, а не в схеме этапа 4.
#
# ПОЧЕМУ ЭТО НЕ БЫЛО ВИДНО РАНЬШЕ: тело зависимости кодогенерируется ТОЛЬКО
# если её кто-то вызывает. FB_ALU8 вызывается ровно из двух мест, и оба - в
# FB_CPU8080_FULL. Поэтому сборка с опустошённым телом FB_CPU8080_FULL была
# "чистой" и создавала ложное впечатление, что зависимости в порядке.
#
# T(k) = "C32 есть, если у FB_ALU8 оставить только первые k сетей".
# T(0) = ложь, T(N) = истина (полное тело + вызов - проверено). Ищем
# k* = min{k : T(k) = истина}; виновник - сеть k*-1.
#
# Результат: C:\dsh8080\work\bisect_dep_result.txt

param(
    [string]$NamesFile = 'C:\dsh8080\work\pou_names.txt',
    [string]$OutFile = 'C:\dsh8080\work\bisect_dep_result.txt',
    [string]$Caller = 'FB_CPU8080_FULL',
    [int]$CallerNet = 17,
    [string]$Dep = 'FB_ALU8',
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
Say "=== БИСЕКЦИЯ ПО СЕТЯМ ЗАВИСИМОСТИ $Dep (вызывает $Caller сеть $CallerNet) ==="

$all = @(Get-Content $NamesFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() })
$others = @($all | Where-Object { $_ -ne $Caller })
$keepNets = @(0..32 | Where-Object { $_ -ne $CallerNet })
Say "опустошаются тела $($others.Count) POU; в $Caller остаётся только сеть $CallerNet"

if ($NetCount -le 0) {
    $py = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import pou_deps
p = pou_deps.make(u'$Dep')
print(len(p.networks))
"@
    $tmp = Join-Path $env:TEMP 'depcount.py'
    Set-Content -Path $tmp -Value $py -Encoding UTF8
    $NetCount = [int](& python -X utf8 $tmp | Select-Object -Last 1)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
Say "сетей в $Dep : $NetCount"
if ($NetCount -le 1) { Say 'не удалось определить число сетей - стоп'; exit 2 }

function Invoke-Build {
    param([int]$Keep, [string]$Label)
    for ($a = 1; $a -le $BuildAttempts; $a++) {
        $env:DSH_BISECT_EMPTY = ($others -join ',')
        $env:DSH_BISECT_NET_POU = $Caller
        $env:DSH_BISECT_NET = ($keepNets -join ',')
        Remove-Item Env:\DSH_BISECT_ITEM_KEEP -ErrorAction SilentlyContinue
        $env:DSH_BISECT_DEP_POU = $Dep
        $env:DSH_BISECT_DEP_KEEP = "$Keep"
        Remove-Item Env:\DSH_BISECT_DEP -ErrorAction SilentlyContinue
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
        Say ("    [$Label] попытка $a : скрипт=$ran компиляция=$compiled C32=$c32 (сетей $Dep = $Keep)")
        if ($ran -and $compiled) { return @{ ok = $true; c32 = $c32 } }
        Start-Sleep -Seconds 6
    }
    return @{ ok = $false; c32 = $false }
}

$r = Invoke-Build -Keep $NetCount -Label 'ЦЕЛИКОМ'
if (-not $r.ok) { Say 'не удалось выполнить базовую сборку - стоп'; exit 2 }
if (-not $r.c32) { Say "при целом теле $Dep ошибки НЕТ - база не подтверждена, стоп"; exit 3 }
Say "БАЗА: при целом теле $Dep ошибка есть - верно."

$lo = 0
$hi = $NetCount
while (($hi - $lo) -gt 1) {
    $mid = [int][math]::Floor(($lo + $hi) / 2.0)
    Say "--- оставляем первые k=$mid сетей $Dep ---"
    $r = Invoke-Build -Keep $mid -Label "k=$mid"
    if (-not $r.ok) { Say 'не удалось выполнить сборку - стоп'; exit 2 }
    if ($r.c32) {
        Say "    C32 есть -> виновник внутри: hi=$mid"
        $hi = $mid
    } else {
        Say "    C32 нет -> виновник дальше: lo=$mid"
        $lo = $mid
    }
}

$hit = $hi - 1
Say "НАЙДЕНА СЕТЬ ЗАВИСИМОСТИ: индекс $hit (k* = $hi)"

$py2 = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import pou_deps
p = pou_deps.make(u'$Dep')
nets = p.networks
for j in ($hit - 1, $hit, $hit + 1):
    if 0 <= j < len(nets):
        mark = u'  <== ВИНОВНИК' if j == $hit else u''
        print(u'[%d] сетей-блоков=%d  %s%s' % (j, len(nets[j]._items), nets[j].title, mark))
"@
$tmp2 = Join-Path $env:TEMP 'showdep.py'
Set-Content -Path $tmp2 -Value $py2 -Encoding UTF8
& python -X utf8 $tmp2 2>&1 | ForEach-Object { Say "    $_" }
Remove-Item $tmp2 -Force -ErrorAction SilentlyContinue

Say '=== ГОТОВО ==='
exit 0
