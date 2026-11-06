# -*- coding: utf-8 -*-
u"""ЭТАП 4, ПРОБА №3: режим симуляции через МЕТОД + онлайн-сессия целиком.

ФАКТ ИЗ ПРОБЫ №2 (gen_probe4b.py):
  * устройство находится и обходом, и через proj.find('Device', True);
  * `dev.simulation_mode` (СВОЙСТВО) НЕ существует, а вот метод есть:
        walk/Device.is_enabled -> <built-in method is_enabled of ScriptDeviceObject>
    то есть в этой версии API set_simulation_mode - это МЕТОД, а не свойство:
        dev.set_simulation_mode(True);
  * login() без режима симуляции падает:
        "Невозможно подключиться к устройству ...
         Некорректная конфигурация Gateway";
  * обёртка OnlineApplication умеет: login/logout/start/stop/read_value/
    read_values/set_prepared_value/write_prepared_values/create_boot_application/
    reset/get_online_device и свойство timeout (метода set_timeout НЕТ);
  * app.create_boot_application(путь) РАБОТАЕТ (в пробе 1 падал SystemError
    только потому, что приложение не собралось из-за ошибок TON/R_TRIG).

Проба 3 проверяет ровно одно: поднимается ли онлайн-сессия В РЕЖИМЕ СИМУЛЯЦИИ
на чисто собранном проекте с конфигурацией задач, и читаются ли значения.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import scriptengine
import fbd_xml
from fbd_xml import Pou
import codesys_build as cb

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_probe4c.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


def H(msg):
    L(u"")
    L(u"==== %s ====" % msg)


def s_of(v):
    try:
        return u"%s" % v
    except Exception:
        return u"<нет repr>"


PROJ = ROOT + u"/build/PROBE4C.project"
SRC = ROOT + u"/src/probe4c"
BOOT = ROOT + u"/build/PROBE4C.app"

GVL = u"""VAR_GLOBAL
\t(* Данные пробы 3: счётчики сканов (таймеров в проекте нет) *)
\tCnt   : UDINT;
\tPhase : BYTE;
\tMark  : BYTE := 16#5A;
\tArr   : ARRAY[0..7] OF BYTE := [1, 2, 3, 4, 5, 6, 7, 8];
END_VAR
"""


def make_prg():
    p = Pou(u"PLC_PRG_P4C", u"program",
            doc=u"Проба: счётчик сканов задачи и переключаемая фаза.")
    p.var(u"p", u"BYTE", u"фаза")
    n = p.network(u"СЕТЬ 1. Счётчик сканов: доказательство, что задача идёт")
    n.outvar(u"GVL_P4C.Cnt", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_P4C.Cnt")),
                                              (u"IN2", n.invar(u"UDINT#1"))], [u"OUT"]))
    n = p.network(u"СЕТЬ 2. Простая работа со данными (проверка чтения онлайн)")
    n.outvar(u"GVL_P4C.Phase", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_P4C.Phase")),
                                                (u"IN2", n.invar(u"BYTE#1"))],
                                       [u"OUT"], fbd_xml.COL_BLK + 200))
    return p


def find_device(proj):
    for nm, o in cb.walk(proj, 0, 4, [], None):
        if nm == u"Device":
            return o
    return None


def main():
    H(u"[0] СБОРКА И ЗАДАЧА")
    proj, app = cb.new_project(PROJ, L)
    try:
        cb.add_gvl(app, u"GVL_P4C", GVL, L)
        cb.import_pous_one_by_one(app, [make_prg()], SRC, L)
        proj.save()
        cb.build(app, L)
        tc = app.create_task_configuration()
        task = tc.create_task(u"MainTask")
        task.priority = u"1"
        task.interval = u"T#5ms"
        task.pous.insert(0, u"PLC_PRG_P4C", u"проба 3")
        proj.save()
        cb.build(app, L)
        L(u"[OK] проект собран, задача MainTask: interval=%r pous=%d"
          % (task.interval, len(task.pous)))
    except Exception:
        L(u"[FAIL] сборка/задача:\n" + traceback.format_exc())

    H(u"[1] РЕЖИМ СИМУЛЯЦИИ - КАК МЕТОД")
    dev = find_device(proj)
    if dev is None:
        L(u"[ОТКАЗ] устройство не найдено")
    else:
        for meth in (u"get_simulation_mode", u"set_simulation_mode",
                     u"is_enabled", u"get_address", u"get_gateway"):
            try:
                f = getattr(dev, meth)
                L(u"[OK]   метод %s -> %s" % (meth, s_of(f)))
            except Exception as e:
                L(u"[нет]  метод %s: %s" % (meth, s_of(e)))
        try:
            L(u"    simulation_mode до: %r" % dev.get_simulation_mode())
        except Exception as e:
            L(u"[FAIL] get_simulation_mode: %s" % s_of(e))
        try:
            dev.set_simulation_mode(True)
            L(u"[OK] set_simulation_mode(True) -> %r" % dev.get_simulation_mode())
        except Exception as e:
            L(u"[FAIL] set_simulation_mode(True): %s" % s_of(e))
        try:
            proj.save()
            L(u"[OK] проект сохранён с режимом симуляции")
        except Exception:
            pass

    H(u"[2] BOOT-ПРИЛОЖЕНИЕ")
    try:
        app.create_boot_application(BOOT)
        L(u"[OK] app.create_boot_application(%s)" % BOOT)
    except Exception as e:
        L(u"[FAIL] boot: %s" % s_of(e))

    H(u"[3] ОНЛАЙН-СЕССИЯ В СИМУЛЯЦИИ")
    oa = None
    try:
        oa = scriptengine.online.create_online_application(app)
        L(u"[OK] create_online_application -> %s" % s_of(oa))
    except Exception:
        L(u"[FAIL] create_online_application:\n" + traceback.format_exc())

    if oa is not None:
        try:
            oa.timeout = 60000
            L(u"    timeout = %r" % oa.timeout)
        except Exception as e:
            L(u"[WARN] timeout: %s" % s_of(e))
        for opt_name in (u"Never", u"Try", u"Force", u"Keep"):
            try:
                opt = getattr(scriptengine.OnlineChangeOption, opt_name)
            except Exception:
                continue
            try:
                oa.login(opt, False)
                L(u"[OK] login(%s, False) -> logged_in=%r state=%r"
                  % (opt_name, oa.is_logged_in, oa.application_state))
                break
            except Exception as e:
                L(u"[FAIL] login(%s): %s" % (opt_name, s_of(e)))
        L(u"    is_logged_in = %r" % getattr(oa, u"is_logged_in", None))

        if getattr(oa, u"is_logged_in", False):
            try:
                oa.create_boot_application()
                L(u"[OK] online.create_boot_application()")
            except Exception as e:
                L(u"[FAIL] online boot: %s" % s_of(e))
            try:
                oa.start()
                L(u"[OK] start() -> state=%r op=%r"
                  % (oa.application_state, oa.operation_state))
            except Exception as e:
                L(u"[FAIL] start(): %s" % s_of(e))

            prev = -1
            for k in range(8):
                time.sleep(1.0)
                try:
                    vals = oa.read_values([u"GVL_P4C.Cnt", u"GVL_P4C.Phase",
                                           u"GVL_P4C.Mark", u"GVL_P4C.Arr[3]",
                                           u"PLC_PRG_P4C.p"])
                    L(u"    t=%d: %s" % (k + 1, u" | ".join([s_of(v) for v in vals])))
                    try:
                        cur = int(oa.read_value(u"GVL_P4C.Cnt"))
                        if prev >= 0:
                            L(u"          сканов за секунду: %d" % (cur - prev))
                        prev = cur
                    except Exception:
                        pass
                except Exception as e:
                    L(u"[FAIL] read_values: %s" % s_of(e))
                    break
            try:
                L(u"    read_value('GVL_P4C.Mark') = %s"
                  % s_of(oa.read_value(u"GVL_P4C.Mark")))
            except Exception as e:
                L(u"[FAIL] read_value: %s" % s_of(e))
            try:
                oa.set_prepared_value(u"GVL_P4C.Mark", u"16#77")
                oa.write_prepared_values()
                time.sleep(0.5)
                L(u"[OK] запись онлайн: Mark=%s"
                  % s_of(oa.read_value(u"GVL_P4C.Mark")))
            except Exception as e:
                L(u"[FAIL] запись онлайн: %s" % s_of(e))
            try:
                oa.stop()
                L(u"[OK] stop()")
            except Exception as e:
                L(u"[FAIL] stop(): %s" % s_of(e))
            try:
                oa.logout()
                L(u"[OK] logout()")
            except Exception as e:
                L(u"[FAIL] logout(): %s" % s_of(e))

    try:
        proj.save()
        L(u"[OK] проект сохранён: %s" % PROJ)
    except Exception:
        pass


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
