# -*- coding: utf-8 -*-
u"""ФАЗА B: ТРАССИРОВКА ПРОГОННОГО АВТОМАТА TEST_8080 ПО СКАНАМ.

ЗАЧЕМ. Прогон проходит все 199 кейсов мгновенно и все помечает FAIL, причём
фактический PC оказывается в области ловушек BIOS (E003/FE03/03C3) вместо
ожидаемого 0201. Похоже, запись регистров через порт CP/M до процессора не
доходит. Чтобы это увидеть, нужен ПОСКАНОВЫЙ след фаз автомата.

КАК. Обычная задача идёт с интервалом T#2ms, и 199 кейсов проходят за ~2500
сканов = ~5 с: скрипт не успевает опрашивать. Поэтому проект собирается с
ЗАМЕДЛЕННЫМ интервалом (DSH_S4_INTERVAL=T#200ms) - прогон растягивается, и
каждый опрос попадает на свой скан. Пересборка при этом НЕ нужна: этот скрипт
работает с уже собранным проектом.

ЧТО ЧИТАЕМ. Маленький набор (чем меньше, тем быстрее опрос):
  Phase, Idx        - фаза автомата и номер кейса
  Reg_PC, Reg_A     - что реально в процессоре
  CPM_WE/LD2/Sel2/Data2 - что автомат выставил на порт (фаза записи PC)
  Trap_Phase, Halted, CPU_Run - состояние слоя трапов и процессора
  Memory[512], Memory[513]    - загружен ли код теста по адресу 0200h

Результат: C:\dsh8080\work\emu_s4\log\trace_run.log
"""

import io
import os
import sys
import time
import traceback
import scriptengine

LOG_CAND = (u"C:/dsh8080/work/emu_s4/log/trace_run.log",
            u"C:/dsh8080/work/emu_s4/trace_run.log")
RUNNER_LOG = u"C:/dsh8080/work/emu_s4/log/gen_probe_run.log"
PROJ = u"C:/dsh8080/work/emu_s4/build/EMU8080_STAGE4.project"

SECONDS = int(os.environ.get(u"DSH_TRACE_SEC") or u"90")
PERIOD = float(os.environ.get(u"DSH_TRACE_PERIOD") or u"0.7")

_path = None
for _c in LOG_CAND:
    try:
        h = io.open(_c, u"wb")
        h.close()
        _path = _c
        break
    except Exception:
        _path = None
if _path is None:
    raise SystemExit(1)
try:
    h = io.open(RUNNER_LOG, u"wb")
    h.close()
except Exception:
    RUNNER_LOG = None


def put(p, m):
    if not p:
        return
    try:
        h = io.open(p, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


def E(m):
    put(_path, m)


def s_of(v):
    try:
        return u"%s" % v
    except Exception:
        return u"?"


WATCH = (u"GVL_TEST.Mode", u"GVL_TEST.Idx", u"GVL_TEST.Scans",
         u"GVL_TEST.Pass_Cnt", u"GVL_TEST.Fail_Cnt",
         u"GVL_CPM.CCP_Phase", u"GVL_CPM.CCP_Cnt", u"GVL_CPM.Con_Log_Len",
         u"GVL_CPM.ConIn_Ready", u"GVL_CPM.ConIn_Char",
         u"GVL_TEST.Cpm_Step", u"GVL_TEST.DoneCpm",
         # состояние процессора и трапа: без него не видно, ПОЧЕМУ CCP не
         # исполняется в режиме 2 (наблюдалось: 3530 сканов, а CCP_Phase = 0)
         u"GVL_CPM.Reg_PC", u"GVL_CPM.Trap_Phase", u"GVL_CPM.Trap_CCP",
         u"GVL_CPM.Trap_Active", u"GVL_CPM.CPU_Enable", u"GVL_CPM.CPU_Run",
         u"GVL_CPU.Enable", u"GVL_CPM.CPM_WE", u"GVL_CPU.Step_Cnt",
         u"GVL_CPM.Trap_BIOS", u"GVL_CPM.Trap_BDOS", u"GVL_TEST.Done8080")

# Тот же сброс, что делает рабочий прогон. Порядок и ПООДИНОЧНАЯ запись важны:
# при нескольких подготовленных значениях с одним write_prepared_values
# применяется только последнее (проверено пробой).
RESET = (
    (u"GVL_TEST.Mode", u"1"),
    (u"GVL_TEST.Run", u"TRUE"),
    (u"GVL_TEST.N_Cases", u"199"),
    (u"GVL_TEST.Done8080", u"FALSE"),
    (u"GVL_TEST.DoneCpm", u"FALSE"),
    (u"GVL_TEST.DoneIo", u"FALSE"),
    (u"GVL_TEST.Pass_Cnt", u"0"),
    (u"GVL_TEST.Fail_Cnt", u"0"),
    (u"GVL_TEST.First_Fail", u"-1"),
    (u"GVL_TEST.Idx", u"0"),
    (u"GVL_TEST.Busy", u"FALSE"),
    (u"GVL_TEST.Phase", u"0"),
    (u"GVL_TEST.Scans", u"0"),
)


def _reset(oa):
    u"""Сброс состояния прогона через prepared-механизм.

    ВАЖНО: писать надо ПО ОДНОМУ значению за цикл
    set_prepared_value -> write_prepared_values. Проверено пробой
    zz_write_test.py: при двух подготовленных значениях и одном вызове
    write_prepared_values применяется только последнее, и Reset до схемы
    не доходил (наблюдалось Mode = 3 вместо 1 после сброса).
    """
    ok = 0
    for nm, val in RESET:
        try:
            oa.set_prepared_value(nm, val)
            oa.write_prepared_values()
            ok += 1
        except Exception, e:
            E(u"[WARN] запись %s: %s" % (nm, s_of(e)))
    E(u"[OK] сброс применён (%d/%d)" % (ok, len(RESET)))


def main():
    E(u"=== ТРАССИРОВКА ПРОГОННОГО АВТОМАТА (фаза B) ===")
    E(u"секунд наблюдения: %d, период опроса: %.2f с" % (SECONDS, PERIOD))
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    E(u"[OK] проект открыт")
    oa = scriptengine.online.create_online_application(app)
    try:
        oa.login(scriptengine.OnlineChangeOption.Never, False)
    except Exception, e:
        E(u"[FAIL] login: %s" % s_of(e))
        return
    E(u"[OK] login: logged_in=%s" % oa.is_logged_in)
    try:
        oa.start()
    except Exception, e:
        E(u"[FAIL] start: %s" % s_of(e))
        return
    E(u"[OK] start")
    _reset(oa)

    hdr = u"t,cканы," + u",".join([w.split(u".")[-1] for w in WATCH])
    E(hdr)

    t0 = time.time()
    n = 0
    # ПЕРВЫЕ ПРОБЫ - БЕЗ ПАУЗЫ. Сброс действует один скан, и переходы Mode
    # (1 -> 2 -> 3) укладываются в единицы сканов; при периоде 0.4 с они
    # полностью теряются между пробами. Быстрые пробы дают след по каждому
    # скану в самый важный момент - сразу после сброса.
    fast = 40
    while n < fast:
        try:
            vals = oa.read_values(list(WATCH))
        except Exception, e:
            E(u"%6.3f  ОШИБКА ЧТЕНИЯ %s" % (time.time() - t0, s_of(e)))
            break
        n += 1
        cells = []
        for v in vals:
            cells.append(s_of(v).split(u"#")[-1])
        E(u"%6.3f БЫСТРО,%s" % (time.time() - t0, u",".join(cells)))
    while time.time() - t0 < SECONDS:
        try:
            vals = oa.read_values(list(WATCH))
        except Exception, e:
            E(u"%6.1f  ОШИБКА ЧТЕНИЯ %s" % (time.time() - t0, s_of(e)))
            time.sleep(PERIOD)
            continue
        n += 1
        cells = []
        for v in vals:
            cells.append(s_of(v).split(u"#")[-1])
        E(u"%6.1f,%s" % (time.time() - t0, u",".join(cells)))
        time.sleep(PERIOD)

    E(u"[OK] опросов: %d" % n)
    try:
        oa.stop()
        oa.logout()
        E(u"[OK] stop/logout")
    except Exception, e:
        E(u"[WARN] stop/logout: %s" % s_of(e))
    E(u"=== DONE ===")


try:
    main()
except Exception:
    E(u"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ:")
    E(traceback.format_exc())
    E(u"=== DONE ===")
if RUNNER_LOG:
    put(RUNNER_LOG, u"[trace] отчёт: %s" % _path)
    put(RUNNER_LOG, u"=== DONE ===")
