# -*- coding: utf-8 -*-
u"""Отдельная ПРОВЕРКА СВЯЗЕЙ собранного проекта CP/M (короткий прогон).

Зачем отдельный скрипт: полная сборка импортирует 79 POU и занимает ~7 минут,
а самая тяжёлая операция - обратная выгрузка 52 POU для сверки числа блоков.
CODESYS однопроцессный, и параллельный запуск соседнего проекта (Z80_EMU)
снимает процесс через taskkill. Если это случилось уже после сборки, нет
смысла импортировать всё заново: проект сохранён, и достаточно открыть его и
выполнить сверку. Сгенерированный XML (src/cpm_full.plcopenxml) остаётся на
диске от gen_cpm.py - из него берутся имена POU и эталонное число блоков.
"""

import io, os, re, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import scriptengine
import codesys_build as cb

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"verify_cpm.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


PROJ_PATH = ROOT + u"/build/EMU8080_CPM.project"
SRC_PATH = ROOT + u"/src/cpm_full.plcopenxml"
REEXPORT = ROOT + u"/src/cpm_full_reexport.xml"

L(u"=== ПРОВЕРКА СВЯЗЕЙ собранного проекта CP/M ===")
try:
    txt = io.open(SRC_PATH, "r", encoding="utf-8").read()
except Exception:
    L(u"нет файла %s - сначала нужно выполнить gen_cpm.py" % SRC_PATH)
    _LOG.close()
    raise
NAMES = re.findall(r'<pou name="([^"]+)"', txt)
L(u"POU в сгенерированном XML: %d" % len(NAMES))

try:
    cb.close_all()
    cb.clean_locks(PROJ_PATH)
    proj = scriptengine.projects.open(PROJ_PATH)
    L(u"проект открыт: %s" % PROJ_PATH)
    app = proj.active_application
    L(u"application = %s" % cb.nm(app))
    ok = cb.verify_import(proj, app, NAMES, SRC_PATH, REEXPORT, L)
    proj.save()
    L(u"[1] ПРОВЕРКА СВЯЗЕЙ: %s" % (u"OK" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[1] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
_LOG.close()
