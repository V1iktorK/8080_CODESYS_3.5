# -*- coding: utf-8 -*-
u"""Проба этапа 3.6 - драйвер: проверка конструкций аппаратного I/O в CODESYS.

Строит ОТДЕЛЬНЫЙ маленький проект (build/PROBE_IO.project), создаёт DUT/GVL
аппаратного слоя, импортирует 4 пробных POU и собирает проект. Схемы - в
pou_probe_io.py, объявления - в pou_io_defs.py (то есть проверяются РЕАЛЬНЫЕ
объявления слоя, а не их копия).

Зачем: в этом диалекте FBD всё непроверенное МОЛЧА теряется (журнал сборки,
пункты 4.3, 8.2, 9.1, 11.2). Маппинг портов требует сразу трёх новых
конструкций: поле структуры в массиве по ВЫЧИСЛЯЕМОМУ индексу, запись в это
поле и обращение к массивам каналов по индексу, ограниченному LIMIT. Дешевле
проверить их сборкой на 200 блоков, чем ловить молчаливую потерю схемы в сборке
на 4500 блоков.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_io_defs as D
import pou_probe_io

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_probe_io.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


L(u"=== ПРОБА 3.6: карта портов, LIMIT, DINT-масштабирование, массивы каналов ===")
L(u"python: %s" % sys.version)
L(u"корень: %s" % ROOT)

POUS = []
for mk in pou_probe_io.ALL:
    p = mk()
    POUS.append(p)
    L(u"[0] POU: %-12s сетей=%d блоков=%d"
      % (p.name, len(p.networks),
         sum([1 for net in p.networks for it in net._items if it[0] == u"block"])))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/probe_io.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"probe_io")
cn = fbd_xml.count_elements(src_path)
L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
  % (size, cn[0], cn[3], cn[4]))

try:
    proj, app = cb.new_project(ROOT + u"/build/PROBE_IO.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    _LOG.close()
    raise

try:
    for nm, text in D.DUT_ALL:
        cb.add_dut(app, nm, text, L)
    for nm, fn in D.GVL_ALL:
        cb.add_gvl(app, nm, fn(), L)

    for i, p in enumerate(POUS):
        one = u"%s/src/%s.plcopenxml" % (ROOT, p.name)
        fbd_xml.write_project(one, [p], p.name)
        L(u"    импорт %s ..." % p.name)
        app.import_xml(one)
        L(u"    импорт %s OK" % p.name)
    L(u"    импортировано по одному файлу: %d POU" % len(POUS))

    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/probe_io_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
_LOG.close()
