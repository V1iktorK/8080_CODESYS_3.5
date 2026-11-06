# -*- coding: utf-8 -*-
u"""ЛОКАЛЬНАЯ ПРОВЕРКА ГЕНЕРАЦИИ (без CODESYS).

Собирает все POU слоя CP/M так же, как это делает драйвер, но только пишет
PLCopenXML и проверяет:
  * что генерация вообще не падает;
  * что каждая ссылка вида I(n, "имя") на ПЛОСКИЙ идентификатор объявлена
    в этом POU (ловит опечатки, которые CODESYS увидит только как ошибку
    компиляции, а то и не увидит);
  * сколько блоков и сетей получилось (для оценки времени сборки).

Запускается обычным Python (внутри CODESYS - IronPython): кодогенерация от
версии не зависит, кроме unicode/str.
"""

import sys, os

try:
    unicode
except NameError:
    import builtins
    builtins.unicode = str

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import re
import fbd_xml
import pou_cpm_defs as D
import pou_decode_full
import pou_cpu_cpm
import pou_cpm_trap
import pou_bios
import pou_bdos
import pou_com_loader
import pou_ccp
import pou_prg_cpm

GROUPS = ((u"процессор", pou_cpu_cpm.ALL),
          (u"трапы", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"BDOS", pou_bdos.ALL),
          (u"CCP", pou_ccp.ALL),
          (u"загрузчик", pou_com_loader.ALL),
          (u"программа", pou_prg_cpm.ALL))

IDENT = re.compile(u"^[A-Za-z_][A-Za-z_0-9]*$")
KNOWN = (u"TRUE", u"FALSE")

POUS = []
for grp, makers in GROUPS:
    for mk in makers:
        p = mk()
        POUS.append((grp, p))

total_blocks = 0
total_nets = 0
bad = []
for grp, p in POUS:
    decl = set([v.name for v in p.inputs] + [v.name for v in p.outputs] +
               [v.name for v in p.locals])
    blocks = 0
    for net in p.networks:
        for it in net._items:
            if it[0] == u"block":
                blocks += 1
                for pin, src in it[3]:
                    pass
            elif it[0] == u"invar":
                e = it[2]
                # проверяем только ПЛОСКИЕ идентификаторы: выражения с точкой,
                # скобками и индексами - это GVL, литералы и обращения к памяти
                if IDENT.match(e) and e not in decl and e not in KNOWN:
                    bad.append((p.name, net.number, e))
            elif it[0] == u"outvar":
                e = it[2]
                if IDENT.match(e) and e not in decl and e not in KNOWN:
                    bad.append((p.name, net.number, e))
    total_blocks += blocks
    total_nets += len(p.networks)
    print("%-12s %-24s POU=%-22s сетей=%3d блоков=%4d"
          % (grp, "", p.name, len(p.networks), blocks))

NAMES = [p.name for _g, p in POUS]
dups = set([n for n in NAMES if NAMES.count(n) > 1])
print("")
print("всего POU: %d, сетей: %d, блоков: %d" % (len(POUS), total_nets, total_blocks))
if dups:
    print("ОШИБКА: повторяющиеся имена POU: %s" % u", ".join(sorted(dups)))
if bad:
    print("ОШИБКА: ссылки на необъявленные имена POU (%d):" % len(bad))
    for pn, num, e in bad[:40]:
        print("   %s сеть %s : %s" % (pn, num, e))
else:
    print("ссылки на переменные: OK (все плоские идентификаторы объявлены)")

out = u"C:/dsh8080/work/emu_ccp/src/_dryrun_cpm.plcopenxml"
size = fbd_xml.write_project(out, [p for _g, p in POUS], u"cpm_dryrun")
print("XML записан: %s (%d символов)" % (out, size))
