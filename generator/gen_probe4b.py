# -*- coding: utf-8 -*-
u"""ЭТАП 4, ПРОБА №2: режим симуляции, онлайн-сессия, чтение переменных.

ПРОБА №1 (см. docs/03_ЖУРНАЛ_СБОРКИ.md, п. 15) дала факты:
  + app.create_task_configuration() / tc.create_task() / task.pous.insert() -
    конфигурация задач СОЗДАЁТСЯ и вызов программы в задачу ВСТАВЛЯЕТСЯ
    (в дереве: TaskConfiguration -> MainTask -> PLC_PRG_*);
  + task.kind_of_task по умолчанию = KindOfTask.Cyclic (присваивать строку
    нельзя - TypeError: expected KindOfTask, got str);
  + GVL с инициализатором массива СТРУКТУР и ВЛОЖЕННЫМ массивом компилируется
    (0 ошибок), 2D-инициализатор - тоже;
  + TON и R_TRIG НЕДОСТУПНЫ: "C77: Неизвестный тип: 'TON'/'R_TRIG'" - в проекте
    нет библиотеки Util. Таймеры и детекторы фронта запрещены, счёт - сканами;
  + system.get_messages() НЕ РАБОТАЕТ (возвращает пусто) - сообщения
    компилятора видны только в stderr процесса CODESYS;
  + online.create_online_application(app) работает, login() доходит до
    компиляции и падает ТОЛЬКО из-за ошибок компиляции;
  + oa.set_timeout НЕ существует в обёртке OnlineApplication;
  + app.create_boot_application(путь) падает с SystemError (не тот способ);
  + объект устройства из get_children() не имеет свойства simulation_mode
    (обёртка типизирована как IScriptObject).

ПРОБА №2 проверяет ровно то, что осталось:
  1. как ДОСТАТЬ устройство, у которого есть set_simulation_mode
     (find / active_application / add);
  2. входит ли в симуляцию login() на ЧИСТО собранном проекте;
  3. читаются ли значения онлайн (read_value / read_values);
  4. пишутся ли значения онлайн (set_prepared_value + write_prepared_values);
  5. работает ли start()/stop() и растут ли счётчики сканов;
  6. собирается ли boot-приложение и как именно;
  7. доступен ли блок BYTE_TO_WORD (нужен тестам для порта регистров).
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
_LOG = cb.make_log(u"gen_probe4b.log")


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


PROJ = ROOT + u"/build/PROBE4B.project"
SRC = ROOT + u"/src/probe4b"

DUT = u"""TYPE ST_P4 :
STRUCT
    (* Тестовая структура: проверяем инициализатор массива структур. *)
    Id  : WORD;
    Val : BYTE;
    Cd  : ARRAY[0..3] OF BYTE;
END_STRUCT
END_TYPE
"""

GVL = u"""VAR_GLOBAL
\t(* Данные пробы 2 + счётчики сканов (таймеров в проекте НЕТ). *)
\tCases : ARRAY[0..4] OF ST_P4 := [
\t\t(Id := 1, Val := 16#11, Cd := [1, 2, 3, 4]),
\t\t(Id := 2, Val := 16#22, Cd := [5, 6, 7, 8]),
\t\t(Id := 3, Val := 16#33, Cd := [9, 10, 11, 12]),
\t\t(Id := 4, Val := 16#44, Cd := [13, 14, 15, 16]),
\t\t(Id := 5, Val := 16#55, Cd := [17, 18, 19, 20])];
\tCodes : ARRAY[0..4, 0..3] OF BYTE := [
\t\t1, 2, 3, 4,
\t\t5, 6, 7, 8,
\t\t9, 10, 11, 12,
\t\t13, 14, 15, 16,
\t\t17, 18, 19, 20];
\tIdx    : INT := 2;
\tCnt    : UDINT;
\tTicks  : UDINT;
\tRun    : BOOL := TRUE;
\tWide   : WORD;
\tNarrow : BYTE;
\tPcOut  : WORD;
END_VAR
"""


def make_fb():
    p = Pou(u"FB_P4", u"functionBlock",
            doc=u"Проба: BYTE_TO_WORD, вложенная индексация, счётчик сканов.")
    p.var_in(u"Idx", u"INT", u"индекс")
    p.var_out(u"W", u"WORD", u"байт как слово")
    p.var_out(u"Sum", u"BYTE", u"сумма")
    p.var(u"i", u"INT", u"ограниченный индекс")

    n = p.network(u"СЕТЬ 1. BYTE_TO_WORD (нужен порту регистров CP/M)")
    n.outvar(u"W", n.block(u"BYTE_TO_WORD", [(u"IN", n.invar(u"GVL_P4.Cases[i].Val"))],
                           [u"OUT"]))
    n = p.network(u"СЕТЬ 2. Вложенная индексация и плоский 2D-массив")
    n.outvar(u"i", n.block(u"LIMIT", [(u"MN", n.invar(u"INT#0")),
                                      (u"IN", n.invar(u"Idx")),
                                      (u"MX", n.invar(u"INT#4"))], [u"OUT"]))
    n.outvar(u"Sum", n.block(u"ADD", [
        (u"IN1", n.invar(u"GVL_P4.Cases[i].Cd[0]")),
        (u"IN2", n.invar(u"GVL_P4.Codes[i, 3]"))], [u"OUT"]))
    return p


def make_prg():
    p = Pou(u"PLC_PRG_P4", u"program",
            doc=u"Проба: вызов FB и счётчики сканов задачи.")
    p.var(u"fb", u"FB_P4", u"экземпляр пробы")
    p.var(u"w_l", u"WORD", u"защёлка выхода FB")
    p.var(u"s_l", u"BYTE", u"защёлка выхода FB")
    n = p.network(u"СЕТЬ 1. Счётчик сканов задачи (таймеров нет - считаем сканы)")
    n.outvar(u"GVL_P4.Cnt", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_P4.Cnt")),
                                             (u"IN2", n.invar(u"UDINT#1"))], [u"OUT"]))
    n = p.network(u"СЕТЬ 2. Вызов пробы и защёлкивание ВЫХОДОВ вызова FB")
    fb = n.block(u"FB_P4", [(u"Idx", n.invar(u"GVL_P4.Idx"))], [u"W", u"Sum"],
                 instance=u"fb")
    n.outvar(u"w_l", fb.out(u"W"))
    n.outvar(u"s_l", fb.out(u"Sum"))
    n.outvar(u"GVL_P4.Wide", n.invar(u"w_l"))
    n.outvar(u"GVL_P4.Narrow", n.invar(u"s_l"))
    n.outvar(u"GVL_P4.Ticks", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_P4.Ticks")),
                                               (u"IN2", n.invar(u"UDINT#1"))],
                                      [u"OUT"], fbd_xml.COL_BLK + 200))
    return p


def try_attr(L_, obj, name, tag):
    try:
        v = getattr(obj, name)
        L(u"[OK]   %s.%s -> %r" % (tag, name, v))
        return True
    except Exception as e:
        L(u"[нет]  %s.%s : %s" % (tag, name, s_of(e)))
        return False


def find_device(app, proj):
    u"""Найти объект устройства ВСЕМИ доступными способами и проверить,
    у какого из них есть set_simulation_mode."""
    L(u"    --- способ A: proj.find('Device', True) ---")
    try:
        lst = proj.find(u"Device", True)
        L(u"    найдено: %d" % len(lst))
        for i, o in enumerate(lst):
            tag = u"find[%d]" % i
            L(u"    %s: %s" % (tag, s_of(o)))
            if try_attr(L, o, u"simulation_mode", tag):
                return o, tag
    except Exception:
        L(u"[FAIL] proj.find:\n" + traceback.format_exc())

    L(u"    --- способ B: обход get_children() ---")
    for nm, o in cb.walk(proj, 0, 4, [], None):
        if nm == u"Device":
            L(u"    Device: %s" % s_of(o))
            if try_attr(L, o, u"simulation_mode", u"walk/Device"):
                return o, u"walk"
            if try_attr(L, o, u"is_enabled", u"walk/Device"):
                pass
    L(u"    --- способ C: активное приложение ---")
    L(u"    app: %s" % s_of(app))
    try_attr(L, app, u"simulation_mode", u"app")
    return None, None


def main():
    H(u"[0] СБОРКА ПРОБЫ 2")
    pous = [make_fb(), make_prg()]
    proj, app = cb.new_project(PROJ, L)
    try:
        cb.add_dut(app, u"ST_P4", DUT, L)
        cb.add_gvl(app, u"GVL_P4", GVL, L)
        cb.import_pous_one_by_one(app, pous, SRC, L)
        proj.save()
        cb.build(app, L)
        L(u"[OK] build() выполнен - смотрим stderr процесса на ошибки")
    except Exception:
        L(u"[FAIL] сборка:\n" + traceback.format_exc())

    H(u"[1] КОНФИГУРАЦИЯ ЗАДАЧ")
    try:
        tc = app.create_task_configuration()
        task = tc.create_task(u"MainTask")
        task.priority = u"1"
        task.interval = u"T#10ms"
        task.pous.insert(0, u"PLC_PRG_P4", u"проба 2")
        L(u"[OK] задача MainTask: kind=%r interval=%r pous=%d"
          % (task.kind_of_task, task.interval, len(task.pous)))
    except Exception:
        L(u"[FAIL] задача:\n" + traceback.format_exc())
        task = None

    # интервал можно не задавать вовсе - по умолчанию Cyclic;
    # проверим и второй вариант записи интервала
    if task is not None:
        for attr, val in ((u"interval", u"T#2ms"), (u"interval", u"T#5ms")):
            try:
                setattr(task, attr, val)
                L(u"[OK] task.%s := %r -> %r" % (attr, val, getattr(task, attr)))
            except Exception as e:
                L(u"[FAIL] task.%s := %r : %s" % (attr, val, s_of(e)))
        try:
            task.kind_of_task = scriptengine.KindOfTask.Cyclic
            L(u"[OK] task.kind_of_task := KindOfTask.Cyclic -> %r" % task.kind_of_task)
        except Exception as e:
            L(u"[FAIL] kind_of_task через enum: %s" % s_of(e))
    try:
        proj.save()
        L(u"[OK] проект сохранён")
    except Exception:
        pass
    try:
        cb.build(app, L)
        L(u"[OK] повторная сборка с задачей")
    except Exception:
        L(u"[FAIL] повторная сборка:\n" + traceback.format_exc())

    H(u"[2] УСТРОЙСТВО И РЕЖИМ СИМУЛЯЦИИ")
    dev, tag = find_device(app, proj)
    if dev is not None:
        try:
            dev.set_simulation_mode(True)
            L(u"[OK] %s.set_simulation_mode(True) -> %r" % (tag, dev.simulation_mode))
        except Exception as e:
            L(u"[FAIL] set_simulation_mode: %s" % s_of(e))
    else:
        L(u"[ОТКАЗ] объект с set_simulation_mode не найден")
    try:
        proj.save()
    except Exception:
        pass

    H(u"[3] ОНЛАЙН-СЕССИЯ")
    oa = None
    try:
        oa = scriptengine.online.create_online_application(app)
        L(u"[OK] create_online_application -> %s" % s_of(oa))
        L(u"    члены: %s" % u", ".join(sorted([a for a in dir(oa)
                                                if not a.startswith(u"_")])))
    except Exception:
        L(u"[FAIL] create_online_application:\n" + traceback.format_exc())

    if oa is None:
        L(u"[ОТКАЗ] сессии нет")
    else:
        for opt_name in (u"Never", u"Try", u"Force", u"Keep"):
            try:
                opt = getattr(scriptengine.OnlineChangeOption, opt_name)
            except Exception:
                continue
            try:
                oa.login(opt, False)
                L(u"[OK] login(%s) -> logged_in=%r state=%r"
                  % (opt_name, oa.is_logged_in, oa.application_state))
                break
            except Exception as e:
                L(u"[FAIL] login(%s): %s" % (opt_name, s_of(e)))
        L(u"    is_logged_in=%r" % getattr(oa, u"is_logged_in", None))

        if getattr(oa, u"is_logged_in", False):
            try:
                oa.create_boot_application()
                L(u"[OK] online.create_boot_application()")
            except Exception as e:
                L(u"[FAIL] boot: %s" % s_of(e))
            try:
                oa.start()
                L(u"[OK] start() -> state=%r op=%r"
                  % (oa.application_state, oa.operation_state))
            except Exception as e:
                L(u"[FAIL] start(): %s" % s_of(e))

            for k in range(6):
                time.sleep(1.0)
                try:
                    v = oa.read_values([u"GVL_P4.Cnt", u"GVL_P4.Ticks",
                                        u"GVL_P4.Wide", u"GVL_P4.Narrow",
                                        u"GVL_P4.Cases[2].Val",
                                        u"GVL_P4.Codes[1,3]"])
                    L(u"    t=%d: %s" % (k + 1, u" | ".join([s_of(x) for x in v])))
                except Exception as e:
                    L(u"[FAIL] read_values: %s" % s_of(e))
                    break
            try:
                L(u"    read_value('GVL_P4.Cnt') = %s" % s_of(oa.read_value(u"GVL_P4.Cnt")))
            except Exception as e:
                L(u"[FAIL] read_value: %s" % s_of(e))
            try:
                oa.set_prepared_value(u"GVL_P4.Idx", u"4")
                oa.write_prepared_values()
                time.sleep(0.5)
                L(u"[OK] запись онлайн: Idx=%s Wide=%s"
                  % (s_of(oa.read_value(u"GVL_P4.Idx")),
                     s_of(oa.read_value(u"GVL_P4.Wide"))))
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

    H(u"[4] BOOT-ПРИЛОЖЕНИЕ ЧЕРЕЗ ПРОЕКТ")
    for path in (ROOT + u"/build/PROBE4B.app", ROOT + u"/build/PROBE4B_boot.app"):
        try:
            app.create_boot_application(path)
            L(u"[OK] app.create_boot_application(%s)" % path)
        except Exception as e:
            L(u"[FAIL] app.create_boot_application(%s): %s" % (path, s_of(e)))

    H(u"[5] ЧТЕНИЕ СООБЩЕНИЙ КОМПИЛЯТОРА (system.get_messages)")
    try:
        ms = scriptengine.system.get_messages()
        L(u"    получено: %d" % len(ms))
        for m in ms:
            L(u"  %s" % s_of(m))
    except Exception as e:
        L(u"[FAIL] get_messages: %s" % s_of(e))
    try:
        import System
        L(u"    executable = %s" % scriptengine.system.executable_filename)
        L(u"    ui_present = %r" % scriptengine.system.ui_present)
    except Exception:
        pass

    try:
        proj.save()
        L(u"[OK] проект сохранён: %s" % PROJ)
    except Exception:
        L(u"[FAIL] save:\n" + traceback.format_exc())


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
