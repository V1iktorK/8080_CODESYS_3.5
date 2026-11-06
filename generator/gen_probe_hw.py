# -*- coding: utf-8 -*-
u"""Проба этапа 3.6 отдельно для АДАПТЕРА C (реальный ПЛК, AT %IB0/%QB0/%IW0/%QW0).

ЗАЧЕМ ОТДЕЛЬНАЯ ПРОБА. Адаптер FB_IO_Adapter_HW не входит в основную сборку:
в этой установке CODESYS Control Win V3 нет устройства с физическими модулями
ввода-вывода, поэтому адреса %I/%Q нечем связать. Но вопрос "скомпилируется ли
AT-объявление вообще" надо решить ФАКТОМ, а не догадкой. Эта проба строит
отдельный проект (build/PROBE_HW.project), создаёт GVL_IO_HW с AT-адресами,
импортирует адаптер и четыре общих блока каналов и собирает проект.

Результат (сообщения компилятора) попадает в log/gen_probe_hw.log и в отчёт
этапа 3.6 как есть. Основная сборка от этой пробы не зависит никак.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_io_defs as IOD
import pou_io_hw
import pou_io

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_probe_hw.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


L(u"=== ПРОБА 3.6-C: адаптер реального ПЛК (AT %IB0/%QB0/%IW0/%QW0) ===")
L(u"python: %s" % sys.version)
L(u"корень: %s" % ROOT)

POUS = []
for mk in (pou_io.make_io_read, pou_io.make_io_write, pou_io.make_io_analog_in,
           pou_io.make_io_analog_out, pou_io_hw.make_adapter_hw):
    p = mk()
    POUS.append(p)
    L(u"[0] POU: %-24s сетей=%d блоков=%d"
      % (p.name, len(p.networks),
         sum([1 for net in p.networks for it in net._items if it[0] == u"block"])))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/probe_hw.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"probe_hw")
cn = fbd_xml.count_elements(src_path)
L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
  % (size, cn[0], cn[3], cn[4]))

try:
    proj, app = cb.new_project(ROOT + u"/build/PROBE_HW.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    _LOG.close()
    raise

try:
    for nm, text in IOD.DUT_ALL:
        cb.add_dut(app, nm, text, L)
    for nm, fn in IOD.GVL_ALL:
        cb.add_gvl(app, nm, fn(), L)
    # ---- ГЛАВНОЕ В ЭТОЙ ПРОБЕ: GVL с физическими адресами ----
    try:
        cb.add_gvl(app, u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text(), L)
    except Exception:
        L(u"[2] GVL_IO_HW НЕ СОЗДАНА:\n" + traceback.format_exc())
        L(u"    текст, который не принят:\n%s" % pou_io_hw.gvl_io_hw_text())

    for i, p in enumerate(POUS):
        one = u"%s/src/%s.plcopenxml" % (ROOT, p.name)
        fbd_xml.write_project(one, [p], p.name)
        L(u"    импорт %s ..." % p.name)
        app.import_xml(one)
        L(u"    импорт %s OK" % p.name)
    L(u"    импортировано по одному файлу: %d POU" % len(POUS))

    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/probe_hw_reexport.xml", L)
    proj.save()
    L(u"[2] проект сохранён")
    cb.build(app, L)
    L(u"[3] ИТОГ (связи): %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"СООБЩЕНИЯ КОМПИЛЯТОРА - в stderr процесса (файл probe_hw.stdout.txt.err)")
L(u"=== DONE ===")
_LOG.close()
