# -*- coding: utf-8 -*-
u"""ЭТАП 4: ОНЛАЙН-ПРОГОН В СИМУЛЯЦИИ и сборка отчёта.

ЧТО ПРОВЕРЕНО ФАКТИЧЕСКИ (проба gen_probe4c.py, окно 20.3..37.7 с):
  * dev.set_simulation_mode(True) - это МЕТОД (свойства simulation_mode нет!);
    после него компилируется компонент Device.Sim.Device.Application;
  * app.create_boot_application(путь) - работает;
  * online.create_online_application(app).login(OnlineChangeOption.Never, False)
    -> is_logged_in = True (в симуляции Gateway не нужен; БЕЗ режима симуляции
    login падает с "Некорректная конфигурация Gateway");
  * .create_boot_application(), .start() -> ApplicationState.run;
  * .read_values([...]) и .read_value(...) - читают значения с типом
    ("UDINT#73", "BYTE#90");
  * .set_prepared_value(...) + .write_prepared_values() - ПИШУТ значения онлайн;
  * .stop(), .logout().
  * скорость: задача T#5ms давала ~90..100 сканов/с (скан ~10 мс).

ЗДЕСЬ ЭТО ИСПОЛЬЗУЕТСЯ. Скрипт поднимает сессию, ждёт окончания наборов тестов
(они идут сами: TEST_8080 -> CP/M -> TEST_CPM -> TEST_IO, переключаясь полем
GVL_TEST.Mode), затем ЧИТАЕТ все результаты, расшифровывает журнал консоли
CP/M и пишет отчёт report/stage4_report.md.
"""

import io, os, time, traceback

import scriptengine

# СБРОС ПЕРЕД ПРОГОНОМ (фаза B).
#
# Онлайн-сессия CODESYS стартует со значений, СОХРАНЁННЫХ В ПРОЕКТЕ, а не с
# инициализаторов объявлений. Кроме того, ЛОКАЛЬНЫЕ переменные POU (ph, idx,
# tact в TEST_8080 и TEST_CPM) тоже сохраняются, а извне их не записать.
#
# Поэтому сброс делает САМА СХЕМА по явному сигналу GVL_TEST.Reset: она
# ставит ph := IDLE, idx := 0, Mode := 1, обнуляет счётчики и снимает сигнал
# в конце того же скана. Хосту остаётся только попросить сброс.
#
# Писать по отдельности Mode/Idx/Done* из скрипта НЕЛЬЗЯ: схема перезаписывает
# их в том же скане, и наблюдалось Mode = 3 через два скана после сброса
# (старый ph = HAND давал Mode := 2, затем TEST_CPM давал 3).
RESET_STATE = (
    (u"GVL_TEST.Reset", u"TRUE"),
    (u"GVL_TEST.Run", u"TRUE"),
)

SCALARS = (
    u"GVL_TEST.Done8080", u"GVL_TEST.DoneCpm", u"GVL_TEST.DoneIo",
    u"GVL_TEST.Pass_Cnt", u"GVL_TEST.Fail_Cnt", u"GVL_TEST.First_Fail",
    u"GVL_TEST.Idx", u"GVL_TEST.Phase", u"GVL_TEST.Scans", u"GVL_TEST.N_Cases",
    u"GVL_TEST.Mode",
    u"GVL_TEST.Cpm_Pass", u"GVL_TEST.Cpm_Fail", u"GVL_TEST.Cpm_LogLen",
    u"GVL_TEST.Cpm_Base", u"GVL_TEST.Cpm_Prompt", u"GVL_TEST.Cpm_Step",
    u"GVL_TEST.Cpm_Typed",
    u"GVL_TEST.Io_Pass", u"GVL_TEST.Io_Fail", u"GVL_TEST.Io_Step",
    u"GVL_CPM.CPU_Run", u"GVL_CPM.Init_Done", u"GVL_CPM.Trap_Phase",
    u"GVL_CPM.CCP_Cnt", u"GVL_CPM.Con_Log_Len", u"GVL_CPM.CurDisk",
    u"GVL_CPM.DMA", u"GVL_CPM.Diag.Trap_Cnt", u"GVL_CPM.Diag.BDOS_Cnt",
    u"GVL_CPM.Diag.BIOS_Cnt", u"GVL_CPM.Diag.Last_Func",
    u"GVL_CPM.Diag.Last_Err", u"GVL_CPM.Diag.Search_Cnt",
    u"GVL_CPM.Reg_A", u"GVL_CPM.Reg_PC", u"GVL_CPM.Reg_SP", u"GVL_CPM.Reg_PSW",
    u"GVL_CPU.Step_Cnt", u"GVL_CPU.Halted",
    u"GVL_IO.Diag.Read_Cnt", u"GVL_IO.Diag.Write_Cnt", u"GVL_IO.Diag.Unmapped_Cnt",
    u"GVL_IO.Diag.Diag_Cnt", u"GVL_IO.Diag.Fault_Cnt", u"GVL_IO.Diag.Range_Cnt",
    u"GVL_IO.Diag.Console_Cnt", u"GVL_IO.Diag.Err_Code", u"GVL_IO.Diag.Err_Port",
    # ВНИМАНИЕ: GVL_IO.DO ПЕРЕИМЕНОВАНО В GVL_IO.DOx (этап 4): имя DO совпадает
    # с ключевым словом FOR..DO и ломало кодогенерацию (C189/C4). Пока здесь
    # стояло GVL_IO.DO, КАЖДОЕ пакетное чтение скаляров падало с
    # "Некорректное выражение" и весь блок одиночных переменных терялся.
    u"GVL_IO.DOx[0]", u"GVL_IO.DOx[1]", u"GVL_IO.AI[0]", u"GVL_IO.AO[0]",
    u"GVL_HMI.Wd_Timeout", u"GVL_HMI.Wd_Scan_Cnt", u"GVL_HMI.Wd_Timeout_Cnt",
    u"GVL_HMI.Alarm_Active", u"GVL_HMI.Alarm_Code", u"GVL_HMI.Cpu_PC",
)

# ---- массивы (читаем кусками) ----
ARRAYS = (
    # ВНИМАНИЕ: массивы результатов объявлены как ARRAY[0..198] - это РОВНО
    # 199 элементов. Пока здесь стояло 200, скрипт читал несуществующий
    # элемент [199], получал "Неверное выражение" и ТЕРЯЛ ВЕСЬ МАССИВ
    # (отсюда пустая таблица результатов в отчёте).
    (u"GVL_TEST.Results", 199), (u"GVL_TEST.ActA", 199),
    (u"GVL_TEST.ActPC", 199), (u"GVL_TEST.ActSP", 199),
    (u"GVL_TEST.ActPSW", 199),
    (u"GVL_TEST.Cpm_Res", 16), (u"GVL_TEST.Io_Res", 16),
    (u"GVL_TEST.Cpm_Snap", 32),
    (u"GVL_CPM.Con_Log", 256),
)


def s_of(v):
    try:
        return u"%s" % v
    except Exception:
        return u"<нет repr>"


def num(v):
    u"""Строка значения CODESYS ("BYTE#90", "UDINT#73", "TRUE") -> число."""
    s = s_of(v)
    if u"#" in s:
        s = s.split(u"#", 1)[1]
    try:
        return int(float(s))
    except Exception:
        if s.upper() in (u"TRUE", u"FALSE"):
            return 1 if s.upper() == u"TRUE" else 0
        return None


def find_device(proj):
    u"""Устройство проекта (единственный объект с именем Device в дереве)."""
    dev = None
    try:
        for nm, o in _walk(proj):
            if nm == u"Device":
                dev = o
    except Exception:
        pass
    return dev


def _walk(o, ind=0, depth=4):
    out = []
    try:
        out.append((_nm(o), o))
    except Exception:
        return out
    if ind >= depth:
        return out
    try:
        kids = o.get_children()
    except Exception:
        kids = []
    for k in kids:
        out.extend(_walk(k, ind + 1, depth))
    return out


def _nm(o):
    try:
        return o.get_name()
    except Exception:
        return u"?"


def enable_simulation(proj, L):
    u"""Включить режим симуляции устройства (ЭТО МЕТОД, а не свойство)."""
    dev = find_device(proj)
    if dev is None:
        L(u"[FAIL] устройство не найдено - режим симуляции не включён")
        return False
    try:
        L(u"    simulation_mode до: %r" % dev.get_simulation_mode())
    except Exception, e:
        L(u"[WARN] get_simulation_mode: %s" % s_of(e))
    try:
        dev.set_simulation_mode(True)
        L(u"[OK] dev.set_simulation_mode(True) -> %r" % dev.get_simulation_mode())
    except Exception, e:
        L(u"[FAIL] set_simulation_mode: %s" % s_of(e))
        return False
    try:
        proj.save()
        L(u"[OK] проект сохранён с режимом симуляции")
    except Exception, e:
        L(u"[WARN] save: %s" % s_of(e))
    return True


def online_run(app, L, wait_sec=420, tail_sec=20, poll=5):
    u"""Поднять сессию, дождаться окончания тестов, прочитать всё.

    Возвращает словарь прочитанных значений (или None, если сессия не поднялась).
    """
    oa = None
    try:
        oa = scriptengine.online.create_online_application(app)
        L(u"[OK] online.create_online_application()")
    except Exception, e:
        L(u"[FAIL] create_online_application: %s" % s_of(e))
        return None
    try:
        oa.timeout = 60000
    except Exception:
        pass

    try:
        oa.login(scriptengine.OnlineChangeOption.Never, False)
        L(u"[OK] login(OnlineChangeOption.Never, False) -> logged_in=%r state=%r"
          % (oa.is_logged_in, oa.application_state))
    except Exception, e:
        L(u"[FAIL] login: %s" % s_of(e))
        try:
            oa.login(scriptengine.OnlineChangeOption.Force, False)
            L(u"[OK] login(Force) -> logged_in=%r" % oa.is_logged_in)
        except Exception, e2:
            L(u"[FAIL] login(Force): %s" % s_of(e2))
            return None
    if not oa.is_logged_in:
        L(u"[ОТКАЗ] сессия не поднята (is_logged_in = False)")
        return None

    try:
        oa.create_boot_application()
        L(u"[OK] online.create_boot_application() - boot-приложение сохранено")
    except Exception, e:
        L(u"[WARN] online.create_boot_application: %s" % s_of(e))

    try:
        oa.start()
        L(u"[OK] start() -> state=%r op=%r"
          % (oa.application_state, oa.operation_state))
    except Exception, e:
        L(u("[FAIL] start(): %s" % s_of(e)))
        return None

    # ---- СБРОС СОСТОЯНИЯ ПРОГОНА (фаза B) ----
    # ОНЛАЙН-СЕССИЯ СТАРТУЕТ СО ЗНАЧЕНИЙ, СОХРАНЁННЫХ В ПРОЕКТЕ, А НЕ С
    # ИНИЦИАЛИЗАТОРОВ ОБЪЯВЛЕНИЙ. Пока это не учитывалось, прогон начинался
    # с состояния ПРЕДЫДУЩЕГО запуска: Mode = 0 (режим CP/M!), DoneCpm = TRUE,
    # DoneIo = TRUE, Scans = 94. Из-за Mode = 0 тестовая схема не работала
    # вообще: набор 8080 не выполнялся ни разу (Pass = 0, Fail = 0, Idx = 0),
    # а слой CP/M бесконечно печатал приглашение (журнал консоли рос без
    # остановки - 11 тысяч знаков). Теперь перед прогоном состояние
    # принудительно приводится к начальному.
    # СПОСОБ ЗАПИСИ (проверен пробами gen_api3.py и zz_write_test.py): у
    # OnlineApplication НЕТ метода write_value. Есть prepared-механизм:
    #     set_prepared_value(имя, значение_СТРОКОЙ)  - подготовить,
    #     write_prepared_values()                    - применить.
    # И ВАЖНО: писать надо ПО ОДНОМУ значению за цикл. Если подготовить два и
    # вызвать write_prepared_values() один раз, применяется только ПОСЛЕДНЕЕ -
    # Reset до схемы не доходил, и прогон начинался со старого состояния
    # (наблюдалось Mode = 3 вместо 1 сразу после "сброса").
    n_reset = 0
    for nm, val in RESET_STATE:
        try:
            oa.set_prepared_value(nm, val)
            oa.write_prepared_values()
            n_reset += 1
        except Exception, e:
            L(u"[WARN] сброс %s: %s" % (nm, s_of(e)))
    L(u"[OK] состояние прогона сброшено (%d из %d переменных)"
      % (n_reset, len(RESET_STATE)))

    # ---- ожидание прогона ----
    t0 = time.time()
    scans0 = _rd(oa, u"GVL_TEST.Scans")
    done = False
    # ПРОГРЕСС НАБОРА 8080 (фаза B). Набор 199 кейсов занимает ~70 с (по одному
    # такту на скан), поэтому:
    #   * опрос делаем чаще (1 с), чтобы не проскочить момент завершения;
    #   * отдельно ждём ПОЯВЛЕНИЯ Mode = 2/3 или Done8080, а не только DoneIo.
    # Пока этого не было, отчёт снимался на 5-й секунде, когда набор 8080 ещё
    # шёл (Idx ~ 20 из 199), наборы CP/M и I/O не стартовали, и почти все
    # проверки в отчёте были FAIL при реально работающем эмуляторе.
    while time.time() - t0 < wait_sec:
        time.sleep(poll)
        v = _rd_many(oa, (u"GVL_TEST.Scans", u"GVL_TEST.Mode", u"GVL_TEST.Idx",
                          u"GVL_TEST.Pass_Cnt", u"GVL_TEST.Fail_Cnt",
                          u"GVL_TEST.Done8080", u"GVL_TEST.DoneCpm",
                          u"GVL_TEST.DoneIo", u"GVL_CPM.Con_Log_Len",
                          u"GVL_CPM.CCP_Cnt"))
        # ВНИМАНИЕ: _rd_many возвращает СЛОВАРЬ {выражение: значение}.
        L(u"    t=%4.0f с: %s" % (time.time() - t0,
                                  u" | ".join([u"%s=%s" % (k.split(u".")[-1], v2)
                                               for k, v2 in v.items()])))
        if v.get(u"GVL_TEST.DoneIo"):
            done = True
            break
    L(u"[%s] прогон завершён за %.0f с (DoneIo=%s)"
      % (u"OK" if done else u"ПРЕДЕЛ", time.time() - t0, done))
    try:
        L(u"    сканов всего: %s (было %s)" % (_rd(oa, u"GVL_TEST.Scans"), scans0))
    except Exception:
        pass

    # ---- даём CP/M поработать и читаем всё ----
    time.sleep(tail_sec)
    data = {}
    try:
        vals = oa.read_values(list(SCALARS))
        for k, v in zip(SCALARS, vals):
            data[k] = v
        L(u"[OK] прочитано одиночных переменных: %d" % len(vals))
    except Exception, e:
        L(u"[FAIL] read_values(скаляры): %s" % s_of(e))
    for name, cnt in ARRAYS:
        try:
            exprs = [u"%s[%d]" % (name, i) for i in range(cnt)]
            out = []
            for i in range(0, cnt, 64):
                out.extend(oa.read_values(exprs[i:i + 64]))
            data[name] = out
            L(u"[OK] прочитан массив %s[0..%d]" % (name, cnt - 1))
        except Exception, e:
            L(u"[FAIL] чтение массива %s: %s" % (name, s_of(e)))

    try:
        oa.stop()
        L(u"[OK] stop()")
    except Exception, e:
        L(u"[WARN] stop(): %s" % s_of(e))
    try:
        oa.logout()
        L(u"[OK] logout()")
    except Exception, e:
        L(u"[WARN] logout(): %s" % s_of(e))
    return data


def _rd(oa, expr):
    try:
        return s_of(oa.read_value(expr))
    except Exception:
        return u"?"


def _rd_many(oa, exprs):
    d = {}
    try:
        vals = oa.read_values(list(exprs))
        for k, v in zip(exprs, vals):
            d[k] = num(v)
    except Exception:
        pass
    return d


def console_dump(text):
    u"""Дамп журнала консоли: строки по 64 знака + прямая запись управляющих.

    НАЙДЕНО ПРИ ПОДГОТОВКЕ К ПУБЛИКАЦИИ: отчёт печатал журнал «как есть», а он
    содержит CR/LF - каждый знак оказывался на СВОЕЙ строке, и дамп читался
    как столбик "A>." В таком виде расхождение «проверки PASS, а в журнале
    только приглашения» не видно ни автору, ни читателю. Здесь журнал
    переносится по 64 знака, служебные коды показываются явно.
    """
    SHOW = {0x0D: u"\\r", 0x0A: u"\\n", 0x09: u"\\t", 0x1A: u"^Z", 0x03: u"^C"}
    out = []
    for b in range(0, len(text), 64):
        chunk = text[b:b + 64]
        row = []
        for ch in chunk:
            o = ord(ch)
            if o in SHOW:
                row.append(SHOW[o])
            elif 32 <= o < 127:
                row.append(ch)
            else:
                row.append(u"\\x%02X" % o)
        out.append(u"%-64s | %02X" % (u"".join(row), b))
    return u"\n".join(out)


def console_text(data):
    u"""Расшифровать кольцевой журнал консоли CP/M в текст."""
    raw = data.get(u"GVL_CPM.Con_Log")
    if not raw:
        return u""
    log = [num(v) or 0 for v in raw]
    ln = num(data.get(u"GVL_CPM.Con_Log_Len")) or 0
    if ln <= 0:
        return u""
    if ln <= len(log):
        seq = log[:ln]
    else:
        st = ln % len(log)
        seq = log[st:] + log[:st]
    out = []
    for b in seq:
        if b == 0x0D:
            out.append(u"\r")
        elif b == 0x0A:
            out.append(u"\n")
        elif 32 <= b < 127:
            out.append(unichr(b))
        else:
            out.append(u".")
    return u"".join(out)


def write_report(root, data, L):
    u"""Отчёт этапа 4: таблица тест -> ожидание -> факт -> PASS/FAIL."""
    import pou_test_defs as TD
    cases = TD.build_all()
    res = [num(v) for v in data.get(u"GVL_TEST.Results", [])]
    acta = [num(v) for v in data.get(u"GVL_TEST.ActA", [])]
    actpc = [num(v) for v in data.get(u"GVL_TEST.ActPC", [])]
    actsp = [num(v) for v in data.get(u"GVL_TEST.ActSP", [])]
    actpsw = [num(v) for v in data.get(u"GVL_TEST.ActPSW", [])]

    d = os.path.join(root, u"report")
    if not os.path.isdir(d):
        try:
            os.makedirs(d)
        except Exception:
            pass
    path = os.path.join(d, u"stage4_report.md")
    f = io.open(path, "w", encoding=u"utf-8")
    w = f.write

    def g(k):
        return num(data.get(k))

    def s(k):
        return s_of(data.get(k, u"?"))

    w(u"# ЭТАП 4: ПРОТОКОЛ ПРОГОНА (сгенерирован gen_stage4.py)\n\n")
    w(u"## 1. Состояние прогона\n\n")
    w(u"| Показатель | Значение |\n|---|---|\n")
    for k, t in ((u"GVL_TEST.Scans", u"сканов задачи"),
                 (u"GVL_TEST.Done8080", u"набор 8080 пройден"),
                 (u"GVL_TEST.DoneCpm", u"набор CP/M пройден"),
                 (u"GVL_TEST.DoneIo", u"набор ввода-вывода пройден"),
                 (u"GVL_TEST.First_Fail", u"первый FAIL (индекс)"),
                 (u"GVL_TEST.Cpm_Pass", u"PASS в наборе CP/M"),
                 (u"GVL_TEST.Cpm_Fail", u"FAIL в наборе CP/M"),
                 (u"GVL_TEST.Io_Pass", u"PASS в наборе I/O"),
                 (u"GVL_TEST.Io_Fail", u"FAIL в наборе I/O"),
                 (u"GVL_CPM.CCP_Cnt", u"команд выполнено CCP"),
                 (u"GVL_CPM.Trap_Phase", u"фаза автомата трапа"),
                 (u"GVL_CPM.Con_Log_Len", u"знаков в журнале консоли"),
                 (u"GVL_CPM.Diag.Trap_Cnt", u"срабатываний ловушек CP/M"),
                 (u"GVL_CPM.Diag.BDOS_Cnt", u"вызовов BDOS"),
                 (u"GVL_CPM.Diag.BIOS_Cnt", u"вызовов BIOS"),
                 (u"GVL_CPU.Step_Cnt", u"тактов 8080 выполнено"),
                 (u"GVL_CPM.Reg_PC", u"PC после прогона"),
                 (u"GVL_CPM.Reg_A", u"A после прогона"),
                 (u"GVL_CPM.Reg_PSW", u"PSW после прогона"),
                 (u"GVL_IO.Diag.Read_Cnt", u"IN выполнено"),
                 (u"GVL_IO.Diag.Write_Cnt", u"OUT выполнено"),
                 (u"GVL_IO.Diag.Unmapped_Cnt", u"обращений к портам без канала"),
                 (u"GVL_IO.Diag.Err_Code", u"код аварии I/O"),
                 (u"GVL_HMI.Wd_Timeout", u"watchdog: тайм-аут такта"),
                 (u"GVL_HMI.Wd_Timeout_Cnt", u"срабатываний watchdog")):
        w(u"| %s | %s |\n" % (t, s(k)))

    w(u"\n## 2. Таблица тестов ядра 8080 (%d кейсов)\n\n" % len(cases))
    w(u"| ID | Гр | Тест | Ожидание (A PC PSW/mask) | Факт (A PC SP) | Итог |\n")
    w(u"|---|---|---|---|---|---|\n")
    npass = nfail = 0
    for i, c in enumerate(cases):
        e = c[u"exp"]
        r = res[i] if i < len(res) else None
        verdict = u"PASS" if r == 1 else (u"FAIL" if r == 0 else u"нет данных")
        if r == 1:
            npass += 1
        elif r == 0:
            nfail += 1
        w(u"| %s | %d | %s | A=%02X PC=%04X PSW=%02X/%02X | A=%s PC=%s SP=%s | %s |\n"
          % (c[u"id"], c[u"group"], c[u"name"], e[u"A"], e[u"PC"],
             c[u"exp_psw"], c[u"mask"],
             _hx(acta, i), _hxw(actpc, i), _hxw(actsp, i), verdict))
    w(u"\n**Итог по набору 8080: PASS=%d FAIL=%d**\n" % (npass, nfail))

    w(u"\n## 3. Проверки слоя CP/M\n\n")
    w(u"| # | Что проверяется | Результат |\n|---|---|---|\n")
    cpm_items = (u"приглашение A>",
                 u"эхо DIR в журнале (поиск «DI»)",
                 u"каталог: имя HELLO (поиск в журнале)",
                 u"завершение набора и рост журнала",
                 u"каталог: расширение COM (поиск в журнале)",
                 u"эхо TYPE в журнале (поиск «TY»)",
                 u"содержимое README.TXT (поиск «HELLO.COM»)",
                 u"счётчики CCP и ловушек (без содержимого)",
                 u"реальный .COM: строка «HELLO FROM» в журнале")
    for i, t in enumerate(cpm_items):
        w(u"| %d | %s | %s |\n" % (i, t, _verdict(data, u"GVL_TEST.Cpm_Res", i)))
    w(u"\nЖурнал консоли CP/M (расшифровка GVL_CPM.Con_Log, длина %s):\n\n"
      % s(u"GVL_CPM.Con_Log_Len"))
    _ctext = console_text(data)
    w(u"```\n%s\n```\n" % _ctext.replace(u"\r", u""))
    # Дамп с явными управляющими кодами и адресами: по нему видно, что именно
    # напечатала система, а не только «сколько знаков» (проверки CP/M местами
    # сравнивают ДЛИНУ журнала, поэтому дамп - единственное доказательство
    # СОДЕРЖИМОГО вывода).
    w(u"\nДамп журнала (64 знака в строке, служебные коды явно):\n\n")
    w(u"```\n%s\n```\n" % console_dump(_ctext))
    # ДИАГНОСТИКА СЛОЯ CP/M. Без этих значений разбор провала набора CP/M
    # упирается в догадки: журнал консоли показывает только то, что CCP успел
    # НАПЕЧАТАТЬ, но не показывает, где именно он остановился.
    #   CCP_Phase  - фаза автомата CCP (3 = чтение команды, 34/35 = конец);
    #   Cpm_Res[8..15] - защёлки фаз CCP (какие фазы он проходил);
    #   Cpm_Typed  - сколько знаков схеме удалось подать в консоль.
    w(u"\nДиагностика CP/M:\n\n```\n")
    for k in (u"GVL_CPM.CCP_Phase", u"GVL_CPM.CCP_Cnt", u"GVL_CPM.Con_Log_Len",
              u"GVL_TEST.Cpm_Typed", u"GVL_TEST.Cpm_On",
              u"GVL_TEST.Cpm_Step", u"GVL_CPM.ConIn_Ready",
              u"GVL_CPM.ConIn_Char", u"GVL_TEST.Mode",
              u"GVL_CPM.Diag.Last_Func", u"GVL_CPM.Diag.Last_Err",
              u"GVL_TEST.Cpm_Res[8]", u"GVL_TEST.Cpm_Res[9]",
              u"GVL_TEST.Cpm_Res[10]", u"GVL_TEST.Cpm_Res[11]",
              u"GVL_TEST.Cpm_Res[12]", u"GVL_TEST.Cpm_Res[13]",
              u"GVL_TEST.Cpm_Res[14]", u"GVL_TEST.Cpm_Res[15]"):
        w(u"%-26s = %s\n" % (k, s(k)))
    w(u"```\n")

    w(u"\n## 4. Проверки аппаратного ввода-вывода\n\n")
    w(u"| # | Что проверяется | Результат |\n|---|---|---|\n")
    io_items = (u"OUT 00h -> DO[0] (лампа Останов)",
                u"IN 10h -> 01h (дискретный вход DI[0])",
                u"IN 14h -> 01h (канал с инверсией)",
                u"IN 28h -> FFh (масштаб аналога 27648 -> 255)",
                u"OUT 20h -> AO[0] = 27648 (обратный масштаб)",
                u"IN 90h -> FFh (порт без канала, STUB)",
                u"порт без канала: счётчик Unmapped_Cnt вырос",
                u"порт без канала в режиме FAULT -> код 1",
                u"IN 10h ЧЕРЕЗ ПРОЦЕССОР -> A = 01h (wait state)",
                u"watchdog: такт не завершился -> тайм-аут")
    for i, t in enumerate(io_items):
        w(u"| %d | %s | %s |\n" % (i, t, _verdict(data, u"GVL_TEST.Io_Res", i)))

    w(u"\n## 5. Состояние эмулятора после прогона\n\n")
    w(u"```\n")
    for k in (u"GVL_CPM.CPU_Run", u"GVL_CPM.Trap_Phase", u"GVL_CPM.Init_Done",
              u"GVL_CPM.CurDisk", u"GVL_CPM.DMA", u"GVL_CPU.Halted",
              u"GVL_CPM.Reg_PC", u"GVL_CPM.Reg_SP", u"GVL_CPM.Reg_A",
              u"GVL_CPM.Reg_PSW", u"GVL_CPM.Diag.Last_Func",
              u"GVL_CPM.Diag.Last_Err", u"GVL_IO.DOx[0]", u"GVL_IO.AI[0]",
              u"GVL_IO.AO[0]", u"GVL_IO.Diag.Err_Port",
              u"GVL_HMI.Alarm_Active", u"GVL_HMI.Alarm_Code"):
        w(u"%-28s = %s\n" % (k, s(k)))
    w(u"```\n")
    f.close()
    L(u"[OK] отчёт записан: %s" % path)
    return path


def _hx(arr, i):
    if i < len(arr) and arr[i] is not None:
        return u"%02X" % arr[i]
    return u"--"


def _hxw(arr, i):
    if i < len(arr) and arr[i] is not None:
        return u"%04X" % arr[i]
    return u"----"


def _verdict(data, name, i):
    a = data.get(name) or []
    if i >= len(a):
        return u"нет данных"
    v = num(a[i])
    if v == 1:
        return u"**PASS**"
    if v == 0:
        return u"**FAIL**"
    return u"нет данных"
