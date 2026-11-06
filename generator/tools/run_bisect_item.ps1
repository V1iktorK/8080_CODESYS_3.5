# run_bisect_item.ps1 - ТРЕТИЙ УРОВЕНЬ БИСЕКЦИИ: ПРЕФИКС ЭЛЕМЕНТОВ ОДНОЙ СЕТИ.
#
# ЗАЧЕМ. Компилятор сообщает только "C32: Невозможно конвертировать тип 'BYTE' в
# тип 'BOOL'". Бисекция по телам POU дала FB_CPU8080_FULL, по сетям - сеть 17
# ("СЕТЬ 18 (ФАЗА 6). Флаги S/Z/P результата DAA"). Проверка показала, что
# сеть 17 достаточно, чтобы ошибка воспроизвелась (остальные 32 сети и 66 POU
# опустошены), но её XML типологически БЕЗУПРЕЧЕН: все связи BYTE->BYTE и
# BOOL->BOOL. Значит, делим саму сеть.
#
# T(k) = "C32 есть, если в сети 17 оставить только ПЕРВЫЕ k элементов".
# T(0) = ложь (элементов нет), T(N) = истина (сеть целиком - проверено).
# T монотонна; ищем k* = min{k : T(k) = истина} -> виноват элемент k*-1.
#
# ПОЧЕМУ ПРЕФИКС КОРРЕКТЕН. Связи в FBD ссылаются только НАЗАД (на элемент с
# меньшим localId), поэтому у любого оставленного элемента все его источники
# тоже в префиксе - XML остаётся разбираемым (в отличие от удаления
# произвольного подмножества, которое дало неразборный XML в прошлой попытке).
#
# Результат: C:\dsh8080\work\bisect_item_result.txt

param(
    [string]$NamesFile = 'C:\dsh8080\work\pou_names.txt',
    [string]$OutFile = 'C:\dsh8080\work\bisect_item_result.txt',
    [string]$Pou = 'FB_CPU8080_FULL',
    [int]$NetIdx = 17,
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
Say "=== БИСЕКЦИЯ ПО ЭЛЕМЕНТАМ СЕТИ $NetIdx POU $Pou ==="

$all = @(Get-Content $NamesFile -Encoding UTF8 | Where-Object { $_.Trim() -ne '' } | ForEach-Object { $_.Trim() })
$others = @($all | Where-Object { $_ -ne $Pou })
# оставляем в POU ровно одну сеть $NetIdx
$keepNets = @(0..32 | Where-Object { $_ -ne $NetIdx })
Say "опустошаются тела $($others.Count) POU и сети $($keepNets -join ',')"

if ($ItemCount -le 0) {
    $py = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import check_types as CT
for grp, mk in CT.GROUPS:
    for m in mk:
        p = m()
        if p.name == u'$Pou':
            print(len(p.networks[$NetIdx]._items))
            break
"@
    $tmp = Join-Path $env:TEMP 'itemcount.py'
    Set-Content -Path $tmp -Value $py -Encoding UTF8
    $ItemCount = [int](& python -X utf8 $tmp | Select-Object -Last 1)
    Remove-Item $tmp -Force -ErrorAction SilentlyContinue
}
Say "элементов в сети: $ItemCount"
if ($ItemCount -le 1) { Say 'не удалось определить число элементов - стоп'; exit 2 }

function Invoke-Build {
    param([int]$Keep, [string]$Label)
    for ($a = 1; $a -le $BuildAttempts; $a++) {
        $env:DSH_BISECT_EMPTY = ($others -join ',')
        $env:DSH_BISECT_NET_POU = $Pou
        $env:DSH_BISECT_NET = ($keepNets -join ',')
        $env:DSH_BISECT_ITEM_POU = $Pou
        $env:DSH_BISECT_ITEM_IDX = "$NetIdx"
        $env:DSH_BISECT_ITEM_KEEP = "$Keep"
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
        Say ("    [$Label] попытка $a : скрипт=$ran компиляция=$compiled C32=$c32 (оставлено $Keep)")
        if ($ran -and $compiled) { return @{ ok = $true; c32 = $c32 } }
        Start-Sleep -Seconds 6
    }
    return @{ ok = $false; c32 = $false }
}

# база: сеть целиком -> ошибка должна быть
$r = Invoke-Build -Keep $ItemCount -Label 'ЦЕЛИКОМ'
if (-not $r.ok) { Say 'не удалось выполнить базовую сборку - стоп'; exit 2 }
if (-not $r.c32) { Say 'при целом теле сети ошибки НЕТ - база не подтверждена, стоп'; exit 3 }
Say 'БАЗА: при целом теле сети ошибка есть - верно.'

$lo = 0
$hi = $ItemCount
while (($hi - $lo) -gt 1) {
    $mid = [int][math]::Floor(($lo + $hi) / 2.0)
    Say "--- оставляем первые k=$mid элементов ---"
    $r = Invoke-Build -Keep $mid -Label "k=$mid"
    if (-not $r.ok) { Say 'не удалось выполнить сборку - стоп'; exit 2 }
    if ($r.c32) {
        Say "    C32 есть -> виновник уже внутри: hi=$mid"
        $hi = $mid
    } else {
        Say "    C32 нет -> виновник дальше: lo=$mid"
        $lo = $mid
    }
}

$hit = $hi - 1
Say "НАЙДЕН ЭЛЕМЕНТ: индекс $hit (k* = $hi)"

# показать сам элемент
$py2 = @"
import sys
sys.path.insert(0, r'$GenDir')
sys.path.insert(0, r'$GenDir\tools')
import check_types as CT
for grp, mk in CT.GROUPS:
    for m in mk:
        p = m()
        if p.name == u'$Pou':
            its = p.networks[$NetIdx]._items
            for j, it in enumerate(its):
                if j == $hit or j == $hit - 1 or j == $hit + 1:
                    mark = u'  <== ВИНОВНИК' if j == $hit else u''
                    print(u'[%d] %s%s' % (j, repr(it)[:300], mark))
            break
"@
$tmp2 = Join-Path $env:TEMP 'showitem.py'
Set-Content -Path $tmp2 -Value $py2 -Encoding UTF8
& python -X utf8 $tmp2 2>&1 | ForEach-Object { Say "    $_" }
Remove-Item $tmp2 -Force -ErrorAction SilentlyContinue

Say '=== ГОТОВО ==='
exit 0
