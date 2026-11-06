# run_bisect_depitem.ps1 - ПЯТЫЙ УРОВЕНЬ: ЭЛЕМЕНТЫ ПЕРВОЙ СЕТИ ЗАВИСИМОСТИ.
#
# ПУТЬ ЛОКАЛИЗАЦИИ ОШИБКИ C32 'BYTE' -> 'BOOL' (этап A5):
#   1) по телам 67 POU     -> FB_CPU8080_FULL
#   2) по сетям POU        -> сеть 17 (вызов FB_ALU8)
#   3) по элементам сети   -> ошибка появляется, когда выход вызова FB_ALU8
#                             НАЧИНАЮТ ЧИТАТЬ (вызов становится "живым")
#   4) по сетям FB_ALU8    -> сеть 1 ("Признаки операции: IsSub, Logic, IsAna")
#   5) ЗДЕСЬ: по элементам сети 1 FB_ALU8 (12 элементов: 5 литералов + 7 блоков).
#
# Конфигурация сборки: FB_CPU8080_FULL содержит ТОЛЬКО сеть 17 (чтобы вызов
# FB_ALU8 был живым), остальные 66 POU опустошены, у FB_ALU8 оставлены все сети,
# но в сети 0 - только первые k элементов.
#
# T(k) = "C32 есть при первых k элементах сети 0". T(0)=ложь, T(12)=истина.
# Ищем k* = min{k : T(k)=истина}; виновник - элемент k*-1.

param(
    [string]$NamesFile = 'C:\dsh8080\work\pou_names.txt',
    [string]$OutFile = 'C:\dsh8080\work\bisect_depitem_result.txt',
    [string]$Caller = 'FB_CPU8080_FULL',
    [int]$CallerNet = 17,
    [string]$Dep = 'FB_ALU8',
    [int]$DepNetIdx = 0,
    [int]$DepNetKeep = 0,
    [int]$ItemCount = 0,
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
Say "=== БИСЕКЦИЯ ПО ЭЛЕМЕНТАМ СЕТИ $DepNetIdx ЗАВИСИМОСТИ $Dep ==="

$all = @(Get-Content $NamesFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() })
$others = @($all | Where-Object { $_ -ne $Caller })
$keepNets = @(0..32 | Where-Object { $_ -ne $CallerNet })
Say "в $Caller остаётся только сеть $CallerNet; тела $($others.Count) POU опустошены"

$py = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import pou_deps
p = pou_deps.make(u'$Dep')
print(len(p.networks))
print(len(p.networks[$DepNetIdx]._items))
"@
$tmp = Join-Path $env:TEMP 'depitem.py'
Set-Content -Path $tmp -Value $py -Encoding UTF8
$out = @(& python -X utf8 $tmp)
Remove-Item $tmp -Force -ErrorAction SilentlyContinue
$DepNetCount = [int]$out[$out.Count - 2]
if ($ItemCount -le 0) { $ItemCount = [int]$out[$out.Count - 1] }
# ВАЖНО: по умолчанию оставляем ТОЛЬКО сеть $DepNetIdx. Иначе усечение её
# элементов рвёт ссылки из ПОСЛЕДУЮЩИХ сетей на её блоки (issub/islogic/isana),
# XML становится неразборным, и результат бисекции оказывается АРТЕФАКТОМ -
# именно так получился ложный ответ "виновник - последний блок EQ".
if ($DepNetKeep -le 0) { $DepNetKeep = $DepNetIdx + 1 }
Say "$Dep : сетей $DepNetCount, элементов в сети $DepNetIdx = $ItemCount; оставляем сетей $DepNetKeep"
if ($ItemCount -le 1) { Say 'не удалось определить число элементов - стоп'; exit 2 }

function Invoke-Build {
    param([int]$Keep, [string]$Label)
    for ($a = 1; $a -le $BuildAttempts; $a++) {
        $env:DSH_BISECT_EMPTY = ($others -join ',')
        $env:DSH_BISECT_NET_POU = $Caller
        $env:DSH_BISECT_NET = ($keepNets -join ',')
        Remove-Item Env:\DSH_BISECT_ITEM_KEEP -ErrorAction SilentlyContinue
        Remove-Item Env:\DSH_BISECT_DEP -ErrorAction SilentlyContinue
        $env:DSH_BISECT_DEP_POU = $Dep
        $env:DSH_BISECT_DEP_KEEP = "$DepNetKeep"
        $env:DSH_BISECT_DEP_ITEM_IDX = "$DepNetIdx"
        $env:DSH_BISECT_DEP_ITEM_KEEP = "$Keep"
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
        Say ("    [$Label] попытка $a : скрипт=$ran компиляция=$compiled C32=$c32 (элементов $Keep)")
        if ($ran -and $compiled) { return @{ ok = $true; c32 = $c32 } }
        Start-Sleep -Seconds 6
    }
    return @{ ok = $false; c32 = $false }
}

$r = Invoke-Build -Keep $ItemCount -Label 'ЦЕЛИКОМ'
if (-not $r.ok) { Say 'не удалось выполнить базовую сборку - стоп'; exit 2 }
if (-not $r.c32) { Say 'при целом теле сети ошибки НЕТ - база не подтверждена, стоп'; exit 3 }
Say 'БАЗА: при целом теле сети ошибка есть - верно.'

$lo = 0
$hi = $ItemCount
while (($hi - $lo) -gt 1) {
    $mid = [int][math]::Floor(($lo + $hi) / 2.0)
    Say "--- оставляем первые k=$mid элементов сети $DepNetIdx ---"
    $r = Invoke-Build -Keep $mid -Label "k=$mid"
    if (-not $r.ok) { Say 'не удалось выполнить сборку - стоп'; exit 2 }
    if ($r.c32) { Say "    C32 есть -> виновник внутри: hi=$mid"; $hi = $mid }
    else { Say "    C32 нет -> виновник дальше: lo=$mid"; $lo = $mid }
}

$hit = $hi - 1
Say "НАЙДЕН ЭЛЕМЕНТ: индекс $hit (k* = $hi)"

$py2 = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import pou_deps
p = pou_deps.make(u'$Dep')
its = p.networks[$DepNetIdx]._items
for j in range(max(0, $hit - 2), min(len(its), $hit + 3)):
    mark = u'  <== ВИНОВНИК' if j == $hit else u''
    t = its[j]
    if t[0] == u'block':
        print(u'[%d] БЛОК %s  входы=%s  выходы=%s%s' % (j, t[2], [q[0] for q in t[3]], t[4], mark))
    else:
        print(u'[%d] %s %s%s' % (j, t[0], t[2], mark))
"@
$tmp2 = Join-Path $env:TEMP 'showdepitem.py'
Set-Content -Path $tmp2 -Value $py2 -Encoding UTF8
& python -X utf8 $tmp2 2>&1 | ForEach-Object { Say "    $_" }
Remove-Item $tmp2 -Force -ErrorAction SilentlyContinue

Say '=== ГОТОВО ==='
exit 0
