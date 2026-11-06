# -*- coding: utf-8 -*-
u"""ЭТАП 4, ПРОБА: конфигурация задач, режим симуляции, онлайн-прогон.

ЭТО ПРОБНЫЙ ПРОГОН, А НЕ СБОРКА ПРОЕКТА. Цель - получить ФАКТЫ, а не схему:
все конструкции этапа 4 в этом проекте ещё не проверялись, а каждая
непроверенная конструкция в этом диалекте молча теряется (docs/03, п. 11.2).
Проба маленькая (1 FB + 1 PRG, ~20 блоков), поэтому прогон стоит секунды,
а не минуты, и отвечает сразу на все открытые вопросы этапа 4:

  1. app.create_task_configuration()            - есть ли конфигурация задач;
  2. tc.create_task(name)                       - создаётся ли задача;
  3. task.pous.add / task.pous.insert           - вставляется ли ВЫЗОВ программы;
  4. task.kind_of_task / priority / interval    - какие значения принимаются;
  5. device.set_simulation_mode(True)           - включается ли симуляция;
  6. online.create_online_application(app)      - поднимается ли сессия;
     .login(...) / .is_logged_in / .start()     - вход и ПУСК;
     .read_value / .read_values / .set_prepared_value + .write_prepared_values;
  7. вложенная индексация Tests[Idx].Code[0]    - массив структур по ПЕРЕМЕННОМУ
     индексу + вложенный массив: на этом держится табличный прогон тестов.
     РЯДОМ проверяется плоский 2D-массив - если вложенный инициализатор не
     примет компилятор, тестовые данные переедут в плоский вариант;
  8. app.create_boot_application(path)          - сборка boot-приложения;
  9. TON / R_TRIG / счётчики UDINT              - нужны раннеру тестов;
 10. вызов пользовательского FB из программы    - на этом стоит весь проект,
     но НА ИСПОЛНЕНИИ он ни разу не проверялся.

ПОЧЕМУ ОТДЕЛЬНАЯ ПРОБА. На основной сборке (64 POU, ~10 минут холодного
прогона) каждая неудача стоила бы полного цикла. Здесь неудача стоит секунд
и сразу говорит, ЧТО именно не работает.
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
_LOG = cb.make_log(u"gen_probe_stage4.log")


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


PROJ = ROOT + u"/build/PROBE_STAGE4.project"
SRC = ROOT + u"/src/probe_stage4"
APP_PATH = ROOT + u"/build/PROBE_STAGE4.app"
BOOT_PATH = ROOT + u"/build/PROBE_STAGE4_boot.app"

# ----------------------------------------------------------------------
# DUT: структура тест-кейса (урезанная копия ST_TestCase плана Шага 2)
# ----------------------------------------------------------------------
DUT_CASE = u"""TYPE ST_ProbeCase :
STRUCT
    (* Тест-кейс табличного прогона: в пробе проверяется ДОСТУПНОСТЬ полей -
       массив структур по переменному индексу и ВЛОЖЕННЫЙ массив байт. *)
    Id      : WORD;
    Name    : STRING(16);
    Code    : ARRAY[0..3] OF BYTE;
    ExpA    : BYTE;
    ExpPC   : WORD;
    PSWMask : BYTE;
END_STRUCT
END_TYPE
"""

GVL_TEST = u"""VAR_GLOBAL
\t(* Данные пробы. Инициализатор массива структур с ВЛОЖЕННЫМ массивом -
\t   именно это и проверяется: если инициализатор не примет компилятор,
\t   тестовые данные этапа 4 переедут в плоский 2D-массив Codes. *)
\tCases : ARRAY[0..2] OF ST_ProbeCase := [
\t\t(Id := 1, Name := 'MOV A,B', Code := [1, 2, 3, 4], ExpA := 16#22, ExpPC := 16#0001, PSWMask := 16#D7),
\t\t(Id := 2, Name := 'ADD A,B', Code := [16#80, 0, 0, 0], ExpA := 16#33, ExpPC := 16#0001, PSWMask := 16#D7),
\t\t(Id := 3, Name := 'HLT', Code := [16#76, 0, 0, 0], ExpA := 16#00, ExpPC := 16#0000, PSWMask := 16#00)];
\t(* Плоский вариант тех же данных: 2D-инициализатор проверен на этапе 3.5. *)
\tCodes : ARRAY[0..2, 0..3] OF BYTE := [
\t\t1, 2, 3, 4,
\t\t16#80, 0, 0, 0,
\t\t16#76, 0, 0, 0];
\tIdx   : INT;
\tRun   : BOOL := TRUE;
\t(* результаты чтения вложенных полей и плоского массива *)
\tGotA  : BYTE;
\tGotPC : WORD;
\tGotC0 : BYTE;
\tGotC3 : BYTE;
\tGotF0 : BYTE;
\tGotF3 : BYTE;
\tCnt   : UDINT;
\tTicks : UDINT;
\tTon_Q : BOOL;
\tTrig_Q : BOOL;
\tFbOut : BYTE;
END_VAR
"""

GVL_MEM_PROBE = u"""VAR_GLOBAL
\t(* Память 64 КБ: проверяется запись по ВЫЧИСЛЯЕМОМУ индексу - на этом
\t   держится загрузка тестового кода в память. *)
\tMemory  : ARRAY[0..65535] OF BYTE;
\tWr_Addr : WORD;
\tWr_Val  : BYTE;
END_VAR
"""


def make_probe_index():
    u"""FB: чтение вложенных полей и запись в память по вычисляемому адресу."""
    p = Pou(u"FB_PROBE_INDEX", u"functionBlock",
            doc=u"Проба диалекта: массив структур по переменному индексу,\n"
                u"\tвложенный массив байт, плоский 2D-массив, запись в память\n"
                u"\tпо вычисляемому адресу. Выход - сумма прочитанного.")
    p.var_in(u"Idx", u"INT", u"индекс тест-кейса")
    p.var_out(u"Sum", u"BYTE", u"контрольная сумма прочитанного")
    p.var(u"i", u"INT", u"индекс, ограниченный границами")

    n = p.network(u"СЕТЬ 1. Границы индекса и загрузка вложенных полей тест-кейса")
    n.outvar(u"i", n.block(u"LIMIT", [(u"MN", n.invar(u"INT#0")),
                                      (u"IN", n.invar(u"Idx")),
                                      (u"MX", n.invar(u"INT#2"))], [u"OUT"]))
    n.outvar(u"GVL_TEST.GotA", n.invar(u"GVL_TEST.Cases[i].ExpA"))
    n.outvar(u"GVL_TEST.GotPC", n.invar(u"GVL_TEST.Cases[i].ExpPC"))
    n.outvar(u"GVL_TEST.GotC0", n.invar(u"GVL_TEST.Cases[i].Code[0]"))
    n.outvar(u"GVL_TEST.GotC3", n.invar(u"GVL_TEST.Cases[i].Code[3]"))

    n = p.network(u"СЕТЬ 2. Плоский 2D-массив: Codes[индекс, байт]")
    n.outvar(u"GVL_TEST.GotF0", n.invar(u"GVL_TEST.Codes[i, 0]"))
    n.outvar(u"GVL_TEST.GotF3", n.invar(u"GVL_TEST.Codes[i, 3]"))

    n = p.network(u"СЕТЬ 3. Запись байта в память по вычисляемому адресу")
    n.outvar(u"GVL_MEM_PROBE.Memory[GVL_MEM_PROBE.Wr_Addr]",
             n.invar(u"GVL_MEM_PROBE.Wr_Val"))
    n.outvar(u"Sum", n.invar(u"GVL_TEST.GotA"))
    return p


def make_probe_main():
    u"""PRG: счётчики сканов, TON, R_TRIG, вызов FB - и всё, что нужно рантайму."""
    p = Pou(u"PLC_PRG_PROBE", u"program",
            doc=u"Главная программа пробы. Именно её имя вставляется в задачу\n"
                u"\tчерез task.pous - это вопрос 3 пробы. Внутри - счётчик сканов,\n"
                u"\tтаймер TON, R_TRIG и вызов пользовательского FB.")
    p.var(u"pi", u"FB_PROBE_INDEX", u"проба индексации массивов")
    p.var(u"pi_sum", u"BYTE", u"защёлка выхода FB")
    p.var(u"ton1", u"TON", u"таймер 200 мс")
    p.var(u"trig", u"R_TRIG", u"детектор фронта")

    n = p.network(u"СЕТЬ 1. Счётчики сканов задачи (без таймеров и часов)")
    n.outvar(u"GVL_TEST.Cnt", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_TEST.Cnt")),
                                               (u"IN2", n.invar(u"UDINT#1"))], [u"OUT"]))
    n.outvar(u"GVL_TEST.Ticks", n.block(u"ADD", [(u"IN1", n.invar(u"GVL_TEST.Ticks")),
                                                 (u"IN2", n.invar(u"UDINT#1"))], [u"OUT"],
                                        x=fbd_xml.COL_BLK + 200))

    n = p.network(u"СЕТЬ 2. Таймер TON: 200 мс от запуска задачи")
    n.outvar(u"GVL_TEST.Ton_Q",
             n.block(u"TON", [(u"IN", n.invar(u"GVL_TEST.Run")),
                              (u"PT", n.invar(u"T#200ms"))], [u"Q", u"ET"],
                     instance=u"ton1"))

    n = p.network(u"СЕТЬ 3. R_TRIG: фронт сигнала RUN")
    n.outvar(u"GVL_TEST.Trig_Q",
             n.block(u"R_TRIG", [(u"CLK", n.invar(u"GVL_TEST.Run"))], [u"Q"],
                     instance=u"trig"))

    n = p.network(u"СЕТЬ 4. Вызов пользовательского FB (выход защёлкивается)")
    fb = n.block(u"FB_PROBE_INDEX", [(u"Idx", n.invar(u"GVL_TEST.Idx"))], [u"Sum"],
                 instance=u"pi", x=fbd_xml.COL_BLK + 200)
    n.outvar(u"pi_sum", fb.out(u"Sum"))
    n.outvar(u"GVL_TEST.FbOut", n.invar(u"pi_sum"))
    return p


def main():
    H(u"[0] СБОРКА ПРОБНОГО ПРОЕКТА")
    pous = [make_probe_index(), make_probe_main()]
    for p in pous:
        L(u"    POU %-16s тип=%-14s сетей=%d блоков=%d"
          % (p.name, p.pou_type, len(p.networks),
             sum([1 for net in p.networks for it in net._items if it[0] == u"block"])))

    proj, app = cb.new_project(PROJ, L)
    try:
        cb.add_dut(app, u"ST_ProbeCase", DUT_CASE, L)
        cb.add_gvl(app, u"GVL_TEST", GVL_TEST, L)
        cb.add_gvl(app, u"GVL_MEM_PROBE", GVL_MEM_PROBE, L)
        cb.import_pous_one_by_one(app, pous, SRC, L)
        proj.save()
        cb.build(app, L)
        L(u"[OK] build() выполнен")
    except Exception:
        L(u"[FAIL] сборка пробы:\n" + traceback.format_exc())

    H(u"[5-А] СООБЩЕНИЯ КОМПИЛЯТОРА ПОСЛЕ СБОРКИ ПРОБЫ")
    try:
        for m in scriptengine.system.get_messages():
            L(u"  [%s] %s" % (getattr(m, u"severity", u"?"), getattr(m, u"text", u"?")))
    except Exception:
        L(u"[FAIL] get_messages:\n" + traceback.format_exc())

    # ==================================================================
    H(u"[1] КОНФИГУРАЦИЯ ЗАДАЧ")
    dev = None
    for nm, o in cb.walk(proj, 0, 4, [], None):
        if nm == u"Device":
            dev = o
    L(u"    устройство: %r" % (dev,))

    tc = None
    try:
        tc = app.create_task_configuration()
        L(u"[OK] app.create_task_configuration() -> %s" % s_of(tc))
    except Exception:
        L(u"[FAIL] create_task_configuration:\n" + traceback.format_exc())

    task = None
    if tc is not None:
        try:
            task = tc.create_task(u"MainTask")
            L(u"[OK] tc.create_task('MainTask') -> %s" % s_of(task))
        except Exception:
            L(u"[FAIL] create_task:\n" + traceback.format_exc())

    if task is not None:
        for attr, val in ((u"priority", u"1"), (u"interval", u"T#10ms"),
                          (u"interval_unit", u"ms"), (u"kind_of_task", u"Cyclic")):
            try:
                setattr(task, attr, val)
                L(u"[OK] task.%-14s := %-8r -> %r" % (attr, val, getattr(task, attr)))
            except Exception:
                L(u"[FAIL] task.%s := %r :\n%s" % (attr, val, traceback.format_exc()))
        try:
            L(u"    task.pous до вставки: len=%d" % len(task.pous))
        except Exception:
            L(u"[FAIL] len(task.pous):\n" + traceback.format_exc())
        try:
            task.pous.insert(0, u"PLC_PRG_PROBE", u"проба этапа 4")
            L(u"[OK] task.pous.insert(0,'PLC_PRG_PROBE',...) len=%d" % len(task.pous))
        except Exception:
            L(u"[FAIL] task.pous.insert:\n" + traceback.format_exc())
        try:
            L(u"    task.pous[0] = %s" % s_of(task.pous[0]))
        except Exception:
            L(u"[WARN] чтение task.pous[0]: %s" % s_of(traceback.format_exc()))
        try:
            L(u"    kind_of_task=%r priority=%r interval=%r unit=%r"
              % (task.kind_of_task, task.priority, task.interval, task.interval_unit))
        except Exception:
            pass
        try:
            proj.save()
            L(u"[OK] проект сохранён после правки задачи")
        except Exception:
            L(u"[FAIL] proj.save:\n" + traceback.format_exc())
        try:
            cb.build(app)
            L(u"[OK] повторный build() с задачей")
        except Exception:
            L(u"[FAIL] build после задачи:\n" + traceback.format_exc())

    L(u"    --- дерево приложения ---")
    cb.walk(app, 1, 4, [], L)

    # ==================================================================
    H(u"[2] РЕЖИМ СИМУЛЯЦИИ УСТРОЙСТВА")
    if dev is not None:
        try:
            L(u"    simulation_mode до: %r" % dev.simulation_mode)
            dev.set_simulation_mode(True)
            L(u"[OK] set_simulation_mode(True) -> %r" % dev.simulation_mode)
        except Exception:
            L(u"[FAIL] set_simulation_mode:\n" + traceback.format_exc())
    try:
        proj.save()
    except Exception:
        pass

    # ==================================================================
    H(u"[3] BOOT-ПРИЛОЖЕНИЕ")
    try:
        app.create_boot_application(BOOT_PATH)
        L(u"[OK] app.create_boot_application(%s)" % BOOT_PATH)
    except Exception:
        L(u"[FAIL] create_boot_application(path):\n" + traceback.format_exc())

    # ==================================================================
    H(u"[4] ОНЛАЙН-СЕССИЯ В СИМУЛЯЦИИ")
    oa = None
    try:
        oa = scriptengine.online.create_online_application(app)
        L(u"[OK] create_online_application -> %s" % s_of(oa))
    except Exception:
        L(u"[FAIL] create_online_application:\n" + traceback.format_exc())

    if oa is not None:
        try:
            oa.set_timeout(60000)
            L(u"    timeout = %r" % oa.timeout)
        except Exception:
            L(u"[WARN] set_timeout: %s" % s_of(traceback.format_exc()))
        if not oa.is_logged_in:
            for opt_name in (u"Never", u"Try", u"Force", u"Keep"):
                try:
                    opt = getattr(scriptengine.OnlineChangeOption, opt_name)
                except Exception:
                    L(u"[WARN] OnlineChangeOption.%s недоступен" % opt_name)
                    continue
                try:
                    oa.login(opt, False)
                    L(u"[OK] login(OnlineChangeOption.%s, False) -> is_logged_in=%r state=%r"
                      % (opt_name, oa.is_logged_in, oa.application_state))
                    break
                except Exception:
                    L(u"[FAIL] login(%s):\n%s" % (opt_name, traceback.format_exc()))
        else:
            L(u"    уже залогинены")

        if oa.is_logged_in:
            try:
                oa.start()
                L(u"[OK] start() -> application_state=%r operation_state=%r"
                  % (oa.application_state, oa.operation_state))
            except Exception:
                L(u"[FAIL] start():\n" + traceback.format_exc())

            L(u"    прогон 6 с, опрос каждую секунду ...")
            for k in range(6):
                time.sleep(1.0)
                try:
                    vals = oa.read_values([u"GVL_TEST.Cnt", u"GVL_TEST.Ticks",
                                           u"GVL_TEST.Idx", u"GVL_TEST.GotA",
                                           u"GVL_TEST.GotPC", u"GVL_TEST.GotC0",
                                           u"GVL_TEST.GotC3", u"GVL_TEST.GotF0",
                                           u"GVL_TEST.GotF3", u"GVL_TEST.Ton_Q",
                                           u"GVL_TEST.FbOut"])
                    L(u"    t=%d с: %s" % (k + 1, u" | ".join([s_of(v) for v in vals])))
                except Exception:
                    L(u"[FAIL] read_values:\n" + traceback.format_exc())
                    break
                try:
                    L(u"    read_value('GVL_TEST.Cnt') = %s" % s_of(oa.read_value(u"GVL_TEST.Cnt")))
                except Exception:
                    L(u"[FAIL] read_value:\n" + traceback.format_exc())

            try:
                oa.set_prepared_value(u"GVL_TEST.Idx", u"2")
                oa.write_prepared_values()
                L(u"[OK] запись онлайн: Idx=%s" % s_of(oa.read_value(u"GVL_TEST.Idx")))
            except Exception:
                L(u"[FAIL] set_prepared_value/write_prepared_values:\n" + traceback.format_exc())

            try:
                oa.set_prepared_value(u"GVL_MEM_PROBE.Wr_Addr", u"100")
                oa.set_prepared_value(u"GVL_MEM_PROBE.Wr_Val", u"16#5A")
                oa.write_prepared_values()
                time.sleep(0.5)
                L(u"[OK] запись в память онлайн -> Memory[100] = %s"
                  % s_of(oa.read_value(u"GVL_MEM_PROBE.Memory[100]")))
            except Exception:
                L(u"[FAIL] запись в память онлайн:\n" + traceback.format_exc())

            try:
                oa.stop()
                L(u"[OK] stop()")
            except Exception:
                L(u"[FAIL] stop():\n" + traceback.format_exc())
            try:
                oa.logout()
                L(u"[OK] logout()")
            except Exception:
                L(u"[FAIL] logout():\n" + traceback.format_exc())
        else:
            L(u"[ОТКАЗ] сессия не поднята: is_logged_in = False")

    H(u"[5] СООБЩЕНИЯ КОМПИЛЯТОРА (итог)")
    try:
        for m in scriptengine.system.get_messages():
            L(u"  [%s] %s" % (getattr(m, u"severity", u"?"), getattr(m, u"text", u"?")))
    except Exception:
        L(u"[FAIL] get_messages:\n" + traceback.format_exc())

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
