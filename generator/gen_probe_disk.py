# -*- coding: utf-8 -*-
u"""Проба этапа 3.5 - драйвер: проверка конструкций дискового образа в CODESYS.

Строит ОТДЕЛЬНЫЙ маленький проект (build/PROBE_DISK.project), импортирует 5
пробных POU и собирает его. Схемы - в pou_probe_disk.py.

Зачем: в этом диалекте FBD всё непроверенное МОЛЧА теряется (журнал сборки,
пункты 4.3, 8.2, 9.1, 11.2), а новый формат диска требует сразу трёх новых
конструкций: двумерного массива с вычисляемым вторым индексом, образа 8 МБ и
инициализатора массива в GVL. Дешевле проверить их отдельной сборкой за минуту,
чем ловить потерю POU в сборке на 4000 блоков.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_probe_disk

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_probe_disk.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


L(u"=== ПРОБА 3.5: образ диска (2D-массив, 8 МБ, DWORD-адрес, инициализатор) ===")
L(u"python: %s" % sys.version)
L(u"корень: %s" % ROOT)

POUS = []
for mk in pou_probe_disk.ALL:
    p = mk()
    POUS.append(p)
    L(u"[0] POU: %-12s сетей=%d блоков=%d"
      % (p.name, len(p.networks),
         sum([1 for net in p.networks for it in net._items if it[0] == u"block"])))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/probe_disk.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"probe_disk")
cn = fbd_xml.count_elements(src_path)
L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
  % (size, cn[0], cn[3], cn[4]))

try:
    proj, app = cb.new_project(ROOT + u"/build/PROBE_DISK.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    _LOG.close()
    raise

try:
    for gname, gtext in pou_probe_disk.GVLS:
        cb.add_gvl(app, gname, gtext, L)
    cb.add_gvl(app, u"GVL_MEM",
               u"VAR_GLOBAL\n\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n", L)

    for i, p in enumerate(POUS):
        one = u"%s/src/%s.plcopenxml" % (ROOT, p.name)
        fbd_xml.write_project(one, [p], p.name)
        L(u"    импорт %s ..." % p.name)
        app.import_xml(one)
        L(u"    импорт %s OK" % p.name)
    L(u"    импортировано по одному файлу: %d POU" % len(POUS))

    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/probe_disk_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
_LOG.close()
