# -*- coding: utf-8 -*-
u"""Прогон + отчёт БЕЗ пересборки проекта.

Зачем отдельный скрипт: шаг экспорта XML в gen_stage4.py на этом проекте
падает (13 МБ XML), но проект к тому моменту уже собран и сохранён. Здесь мы
открываем готовый проект, прогоняем его в симуляции и пишем тот же отчёт,
который пишет gen_stage4.py - только без генерации и экспорта.
"""
import io
import time
import traceback

import run_online

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_report.log"
OUT = ROOT + u"/log/zz_report.txt"
WAIT_SEC = 90
TAIL_SEC = 12


def w(p, m):
    try:
        h = io.open(p, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


def L(m):
    w(OUT, m)


def main():
    import scriptengine
    L(u"=== ПРОГОН И ОТЧЁТ (без пересборки) ===")
    L(u"проект: %s" % PROJ)
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    L(u"[OK] проект открыт")
    data = run_online.online_run(app, L, wait_sec=WAIT_SEC, tail_sec=TAIL_SEC)
    if not data:
        L(u"[FAIL] онлайн-прогон не дал данных")
        return
    L(u"[OK] данные прогона получены")
    run_online.write_report(ROOT, data, L)
    L(u"[OK] отчёт записан")
    try:
        proj.save()
    except Exception:
        pass


try:
    main()
except Exception:
    L(u"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ:")
    L(traceback.format_exc())
L(u"=== DONE ===")
w(LOG, u"=== DONE ===")
