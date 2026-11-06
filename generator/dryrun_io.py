# -*- coding: utf-8 -*-
u"""ЛОКАЛЬНАЯ ПРОВЕРКА ГЕНЕРАЦИИ этапа 3.6 (без CODESYS).

Собирает ВСЕ POU слоя CP/M + аппаратного ввода-вывода так же, как это делает
драйвер gen_cpm.py, но только пишет PLCopenXML и проверяет:
  * что генерация вообще не падает (включая патчи ядра и главной программы);
  * что каждая ссылка вида I(n, "имя") на ПЛОСКИЙ идентификатор объявлена в
    этом POU (ловит опечатки, которые CODESYS увидит только как ошибку
    компиляции, а то и не увидит);
  * что в схемах нет fan-out выходов вызовов FB (правило 9.1/11.2: выход вызова
    FB защёлкивается в переменную, иначе импортёр молча теряет часть схемы);
  * что имена POU уникальны и что у каждого вызова FB задан экземпляр.

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
import pou_io_defs as IOD
import pou_decode_full
import pou_cpu_io
import pou_cpm_trap
import pou_bios
import pou_bdos
import pou_com_loader
import pou_ccp
import pou_io
import pou_io_hw
import pou_prg_io

GROUPS = ((u"процессор", pou_cpu_io.ALL),
          (u"трапы", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"BDOS", pou_bdos.ALL),
          (u"CCP", pou_ccp.ALL),
          (u"загрузчик", pou_com_loader.ALL),
          (u"ввод-вывод", pou_io.ALL),
          (u"адаптер C", pou_io_hw.ALL),
          (u"программа", pou_prg_io.ALL))

IDENT = re.compile(u"^[A-Za-z_][A-Za-z_0-9]*$")
KNOWN = (u"TRUE", u"FALSE")
GVL_PREFIX = (u"GVL_CPU.", u"GVL_MEM.", u"GVL_CPM.", u"GVL_DISK.", u"GVL_IO.",
              u"GVL_IO_Map.", u"GVL_HMI.")
FB_TYPES = (u"FB_",)

POUS = []
for grp, makers in GROUPS:
    for mk in makers:
        p = mk()
        POUS.append((grp, p))

total_blocks = 0
total_nets = 0
bad = []
fanout = []
for grp, p in POUS:
    decl = set([v.name for v in p.inputs] + [v.name for v in p.outputs] +
               [v.name for v in p.locals])
    blocks = 0
    uses = {}
    for net in p.networks:
        for it in net._items:
            if it[0] == u"block":
                blocks += 1
                if it[2].startswith(FB_TYPES) and p._inst.get(it[1]) is None:
                    bad.append((p.name, net.number, u"вызов %s без экземпляра" % it[2]))
                for _pin, s in it[3]:
                    s = s if isinstance(s, fbd_xml.Src) else fbd_xml.Src(int(s))
                    key = (s.eid, s.pin)
                    uses[key] = uses.get(key, 0) + 1
            elif it[0] == u"outvar":
                s = it[3]
                s = s if isinstance(s, fbd_xml.Src) else fbd_xml.Src(int(s))
                key = (s.eid, s.pin)
                uses[key] = uses.get(key, 0) + 1
                e = it[2]
                if IDENT.match(e) and e not in decl and e not in KNOWN:
                    bad.append((p.name, net.number, e))
            elif it[0] == u"invar":
                e = it[2]
                # проверяем только ПЛОСКИЕ идентификаторы: выражения с точкой,
                # скобками и индексами - это GVL, литералы и обращения к памяти
                if IDENT.match(e) and e not in decl and e not in KNOWN:
                    bad.append((p.name, net.number, e))
    # fan-out выхода вызова FB: именно он теряет схему молча (п. 11.2)
    fb_ids = {}
    for net in p.networks:
        for it in net._items:
            if it[0] == u"block" and it[2].startswith(FB_TYPES):
                fb_ids[it[1]] = (it[2], p._inst.get(it[1]))
    for (eid, pin), cnt in uses.items():
        if cnt > 1 and (eid, pin) in fb_ids:
            fanout.append((p.name, fb_ids[(eid, pin)], pin, cnt))
    total_blocks += blocks
    total_nets += len(p.networks)
    print("%-10s POU=%-22s сетей=%3d блоков=%4d" % (grp, p.name, len(p.networks), blocks))

NAMES = [p.name for _g, p in POUS]
dups = sorted(set([n for n in NAMES if NAMES.count(n) > 1]))
print("")
print("всего POU: %d, сетей: %d, блоков: %d" % (len(POUS), total_nets, total_blocks))
print("DUT: %d, GVL: %d (GVL_CPU, GVL_MEM, GVL_CPM, GVL_DISK + %s)"
      % (len(D.DUT_ALL) + len(IOD.DUT_ALL), 4 + len(IOD.GVL_ALL),
         u", ".join([n for n, _f in IOD.GVL_ALL])))
if dups:
    print("ОШИБКА: повторяющиеся имена POU: %s" % u", ".join(dups))
if bad:
    print("ОШИБКА: проблемы с именами/вызовами (%d):" % len(bad))
    for pn, num, e in bad[:40]:
        print("   %s сеть %s : %s" % (pn, num, e))
else:
    print("ссылки на переменные и вызовы FB: OK")
if fanout:
    print("ПРЕДУПРЕЖДЕНИЕ: fan-out выхода вызова FB (%d):" % len(fanout))
    for pn, fb, pin, cnt in fanout[:20]:
        print("   %s : %s.%s -> %d связей" % (pn, fb[0], pin, cnt))
else:
    print("fan-out выходов вызовов FB: нет")

out = u"C:/dsh8080/work/emu_ccp/src/_dryrun_io.plcopenxml"
size = fbd_xml.write_project(out, [p for _g, p in POUS], u"cpm_io_dryrun")
print("XML записан: %s (%d символов)" % (out, size))
