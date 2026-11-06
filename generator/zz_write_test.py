# -*- coding: utf-8 -*-
u"""Проверка: реально ли prepared-запись меняет значение в ПЛК.

Пишем GVL_TEST.Run := FALSE (схема её только читает) и читаем обратно.
Если прочиталось FALSE - запись работает, и провал сброса в другом.
Если TRUE - prepared-механизм НЕ применяет значения.
"""
import io
import traceback
import scriptengine

LOG = u"C:/dsh8080/work/emu_s4/log/zz_write.log"
OUT = u"C:/dsh8080/work/emu_s4/log/zz_write.txt"
PROJ = u"C:/dsh8080/work/emu_s4/build/EMU8080_STAGE4.project"


def w(p, m):
    try:
        h = io.open(p, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


def E(m):
    w(OUT, m)


def rd(oa, e):
    try:
        return u"%s" % oa.read_value(e)
    except Exception, ex:
        return u"ОШИБКА(%s)" % (ex,)


try:
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    oa = scriptengine.online.create_online_application(app)
    oa.login(scriptengine.OnlineChangeOption.Never, False)
    oa.start()
    E(u"--- до записи ---")
    E(u"Run      = %s" % rd(oa, u"GVL_TEST.Run"))
    E(u"Reset    = %s" % rd(oa, u"GVL_TEST.Reset"))

    E(u"--- set_prepared_value(Run, FALSE) + write_prepared_values ---")
    oa.set_prepared_value(u"GVL_TEST.Run", u"FALSE")
    oa.write_prepared_values()
    E(u"Run      = %s" % rd(oa, u"GVL_TEST.Run"))

    E(u"--- force_prepared_values ---")
    oa.set_prepared_value(u"GVL_TEST.Run", u"FALSE")
    try:
        oa.force_prepared_values()
        E(u"force_prepared_values: OK")
    except Exception, ex:
        E(u"force_prepared_values: %s" % (ex,))
    E(u"Run      = %s" % rd(oa, u"GVL_TEST.Run"))

    E(u"--- Reset через prepared ---")
    oa.set_prepared_value(u"GVL_TEST.Reset", u"TRUE")
    oa.write_prepared_values()
    E(u"Reset сразу после записи = %s" % rd(oa, u"GVL_TEST.Reset"))
    E(u"Mode  = %s" % rd(oa, u"GVL_TEST.Mode"))
    E(u"Phase = %s" % rd(oa, u"GVL_TEST.Phase"))
    E(u"Idx   = %s" % rd(oa, u"GVL_TEST.Idx"))
    oa.stop()
    oa.logout()
except Exception:
    E(u"ИСКЛЮЧЕНИЕ:")
    E(traceback.format_exc())
E(u"=== DONE ===")
w(LOG, u"=== DONE ===")
