# -*- coding: utf-8 -*-
u"""TEST_8080 - табличный прогон тестов ядра 8080 (FBD, один автомат на все кейсы).

ИДЕЯ (план docs/02, разд. 1): тесты - это ДАННЫЕ (`GVL_TEST.Tests`), а схема
прогона одна. Она ставит тест-кейс в процессор, даёт ему ровно столько тактов,
сколько нужно, снимает факт и сравнивает его с ожиданием через EQ -> BOOL.

ПОЧЕМУ ПРОГОН ИДЁТ ПО ОБЩЕМУ ЯДРУ ПРОЕКТА, А НЕ ПО КОПИИ.
В `FB_CPU8080_FULL` декодер пишет управляющее слово в GVL_CPU БЕЗ гейта, поэтому
два экземпляра процессора в одном скане затирают друг другу управляющее слово -
второй экземпляр сломал бы первый. Поэтому тесты НЕ создают второй процессор:
они пользуются тем же экземпляром, что и слой CP/M (программа PLC_PRG_CPM), и
управляют им через штатный ПОРТ CP/M (`GVL_CPM.CPM_*`: 0=A..6=L, 7=PC, 8=SP,
9=Flags). Это заодно проверяет и сам порт.

ПОРЯДОК В ЗАДАЧЕ. TEST_8080 стоит ПЕРЕД PLC_PRG_CPM, поэтому:

  скан N : TEST_8080 (фаза W1..W5)  ->  PLC_PRG_CPM: процессор применяет запись
           регистров В ТОМ ЖЕ СКАНЕ (порт подключён к сетям записи регистрового
           файла, PC/SP и флагов);
  скан N : TEST_8080 (фаза RUN)     ->  PLC_PRG_CPM: процессор выполняет ТАКТ.
           Один скан фазы RUN = ровно один такт 8080.

АВТОМАТ (поле GVL_TEST.Phase):
  0 IDLE  ждём готовности: карта портов готова, трап CP/M в рабочей фазе 8
  1 LOAD  загрузка полей кейса в локальные переменные схемы
  2 MEM   запись кода и предустановок в GVL_MEM
  3..7 W1..W5  запись 10 регистров через порт CP/M (по 2 за скан)
  8 RUN   выполнение тактов (CPU_Run := TRUE)
  9 STOP  процессор остановлен
 10 CMP   снимок и сравнение с ожиданием -> GVL_TEST.Results[idx]
 11 NEXT  idx+1, счётчики PASS/FAIL
 12 HAND  подготовка передачи управления CP/M (CPU_Run := FALSE, PC := 0300h)
 13 HAND2 переинициализация памяти CP/M и передача PC := 0F100h (CCP)
 14 DONE  набор пройден, схема больше ничего не трогает

ПОЧЕМУ HAND/HAND2. Тесты пишут в ту же память GVL_MEM, что и CP/M, поэтому
после набора память надо пересобрать: сбрасываем `GVL_CPM.Init_Done` - и
FB_CPM_MemInit (он сам гейтится этим признаком) заливает всё заново в одном
скане. PC при этом переводится на точку входа CCP (0F100h) - ловушка CP/M её
узнаёт и запускает консольный процессор. Так система стартует без единой правки
в уже собранных POU предыдущих этапов.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, NOT, AND, OR, EQ, NE, GE, SEL, IF, ADD, ORL, ANDL,
                          B, H, W, WH)
import pou_test_defs as TD

# фазы автомата
PH_IDLE, PH_LOAD, PH_MEM = 0, 1, 2
PH_W1, PH_W2, PH_W3, PH_W4, PH_W5 = 3, 4, 5, 6, 7
PH_RUN, PH_STOP, PH_CMP, PH_NEXT = 8, 9, 10, 11
PH_HAND, PH_HAND2, PH_DONE = 12, 13, 14

# ВНИМАНИЕ: число 8 означает РАЗНОЕ в двух автоматах!
#   здесь  PH_RUN  = 8  - фаза выполнения тактов АВТОМАТА ТЕСТА;
#   у трапа PH_WORK = 8 - фаза, в которой трап СВОБОДЕН и процессор разрешён.
# Совпадение значений - случайность, поэтому у трапа своя именованная
# константа: читаемость важнее краткости (см. pou_cpm_trap.PH_WORK).
TRAP_PH_WORK = 8

SETTLE = int(os.environ.get(u"DSH_S4_SETTLE") or u"10")

CODE_BASE = TD.CODE_BASE
N_CASES = len(TD.build_all())


def _pre_addrs():
    u"""Все различные адреса предустановок во всей таблице кейсов.

    Нужны, чтобы писать память по КОНСТАНТНОМУ индексу: запись по вычисляемому
    индексу и запись через вызов блока FB в этом CODESYS не исполняются
    (проверено измерением).
    """
    addrs = set()
    for c in TD.build_all():
        for a, v in c["pre"]:
            if not (a == 0 and v == 0):
                addrs.add(a)
    return sorted(addrs)


PRE_ADDRS = _pre_addrs()

PSW_MASK_MEANING = 0xD7   # S Z AC P CY
CCP_ENTRY = 0x0F100
STACK_TOP = 0x0F200
SAFE_PC = 0x0300          # адрес из нулей (NOP) - безопасный «холостой» PC

# ----------------------------------------------------------------------
# ЛОКАЛЬНЫЕ ПЕРЕМЕННЫЕ СХЕМЫ
# ----------------------------------------------------------------------
LOCALS = [
    (u"ph", u"BYTE", u"фаза автомата прогона"),
    (u"n", u"INT", u"число кейсов в таблице"),
    (u"idx", u"INT", u"номер текущего кейса"),
    (u"tact", u"INT", u"тактов выдано текущему кейсу"),
    (u"stop_now", u"BOOL", u"норма тактов исчерпана"),
    (u"settle", u"INT", u"холостых сканов после последнего такта"),
    (u"fire", u"BOOL", u"в этом скане выдаётся такт"),
    (u"own", u"BOOL", u"схема владеет процессором (идёт прогон)"),
    (u"start_ok", u"BOOL", u"условия старта прогона выполнены"),
    (u"f_idle", u"BOOL", u"фаза: ожидание"),
    (u"f_load", u"BOOL", u"фаза: загрузка кейса"),
    (u"f_mem", u"BOOL", u"фаза: запись памяти"),
    (u"f_wk", u"BOOL", u"фаза: запись регистров (W1..W5)"),
    (u"f_run", u"BOOL", u"фаза: выполнение тактов"),
    (u"f_stop", u"BOOL", u"фаза: останов процессора"),
    (u"f_cmp", u"BOOL", u"фаза: сравнение"),
    (u"f_next", u"BOOL", u"фаза: переход к следующему кейсу"),
    (u"f_hand", u"BOOL", u"фаза: подготовка передачи CP/M"),
    (u"f_hand2", u"BOOL", u"фаза: переинициализация памяти CP/M"),
    (u"f_done", u"BOOL", u"фаза: набор пройден"),
    # ---- поля текущего кейса, прочитанные из таблицы ----
    (u"c_id", u"WORD", u"номер кейса"),
    (u"c_grp", u"BYTE", u"группа кейса"),
    (u"c_len", u"BYTE", u"длина программы"),
    (u"c_tacts", u"WORD", u"сколько тактов даём кейсу"),
    (u"c_a", u"BYTE", u"начальный A"), (u"c_b", u"BYTE", u"начальный B"),
    (u"c_c", u"BYTE", u"начальный C"), (u"c_d", u"BYTE", u"начальный D"),
    (u"c_e", u"BYTE", u"начальный E"), (u"c_h", u"BYTE", u"начальный H"),
    (u"c_l", u"BYTE", u"начальный L"), (u"c_sp", u"WORD", u"начальный SP"),
    (u"c_pc", u"WORD", u"начальный PC"), (u"c_ipsw", u"BYTE", u"начальные флаги"),
    (u"c_xa", u"BYTE", u"ожидаемый A"), (u"c_xb", u"BYTE", u"ожидаемый B"),
    (u"c_xc", u"BYTE", u"ожидаемый C"), (u"c_xd", u"BYTE", u"ожидаемый D"),
    (u"c_xe", u"BYTE", u"ожидаемый E"), (u"c_xh", u"BYTE", u"ожидаемый H"),
    (u"c_xl", u"BYTE", u"ожидаемый L"), (u"c_xsp", u"WORD", u"ожидаемый SP"),
    (u"c_xpc", u"WORD", u"ожидаемый PC"), (u"c_xpsw", u"BYTE", u"ожидаемые флаги"),
    (u"c_mask", u"BYTE", u"маска сверки флагов"),
    (u"c_chk", u"BOOL", u"проверять память"),
    (u"c_ma", u"WORD", u"адрес проверяемой ячейки"),
    (u"c_mv", u"BYTE", u"ожидаемое значение ячейки"),
    (u"c_p1a", u"WORD", u"предустановка 1: адрес"), (u"c_p1v", u"BYTE", u"значение"),
    (u"c_p2a", u"WORD", u"предустановка 2: адрес"), (u"c_p2v", u"BYTE", u"значение"),
    (u"c_p3a", u"WORD", u"предустановка 3: адрес"), (u"c_p3v", u"BYTE", u"значение"),
    # ---- регистры как WORD (для порта CP/M) ----
    (u"w_a", u"WORD", u"A для порта"), (u"w_b", u"WORD", u"B для порта"),
    (u"w_c", u"WORD", u"C для порта"), (u"w_d", u"WORD", u"D для порта"),
    (u"w_e", u"WORD", u"E для порта"), (u"w_h", u"WORD", u"H для порта"),
    (u"w_l", u"WORD", u"L для порта"), (u"w_psw", u"WORD", u"PSW для порта"),
    # ---- порт CP/M ----
    (u"sel1", u"BYTE", u"код регистра канала 1"),
    (u"sel2", u"BYTE", u"код регистра канала 2"),
    (u"dat1", u"WORD", u"данные канала 1"),
    (u"dat2", u"WORD", u"данные канала 2"),
    (u"port_wr", u"BOOL", u"строб записи порта CP/M"),
    # ---- сравнение и счётчики ----
    (u"psw_ref", u"BYTE", u"эталонный байт флагов (по маске)"),
    (u"psw_ok", u"BOOL", u"флаги совпали"),
    (u"mem_ok", u"BOOL", u"память совпала"),
    (u"res_all", u"BOOL", u"кейс пройден"),
    (u"lk_a", u"BOOL", u"A совпал"), (u"lk_b", u"BOOL", u"B совпал"),
    (u"lk_c", u"BOOL", u"C совпал"), (u"lk_d", u"BOOL", u"D совпал"),
    (u"lk_e", u"BOOL", u"E совпал"), (u"lk_h", u"BOOL", u"H совпал"),
    (u"lk_l", u"BOOL", u"L совпал"), (u"lk_sp", u"BOOL", u"SP совпал"),
    (u"lk_pc", u"BOOL", u"PC совпал"),
    (u"pass_n", u"INT", u"PASS всего"),
    (u"fail_n", u"INT", u"FAIL всего"),
    (u"pass_i", u"INT", u"PASS по кейсам"),
    (u"fail_i", u"INT", u"FAIL по кейсам"),
    (u"first_fail", u"INT", u"номер первого FAIL"),
    # ФАЗА B (исправление): номер такта на предыдущем скане. Нужен, чтобы
    # отличить РЕАЛЬНО выполненный такт от скана, в котором такта не было.
    (u"step_prev", u"WORD", u"GVL_CPU.Step_Cnt на предыдущем скане"),
    (u"step_chg", u"BOOL", u"такт действительно выполнен (Step_Cnt изменился)"),
    (u"rst", u"BOOL", u"запрошен сброс прогона (GVL_TEST.Reset)"),
    # Экземпляры записи/чтения памяти для предустановок и проверки памяти.
    # Нужны потому, что запись по ВЫЧИСЛЯЕМОМУ индексу (Memory[c_p1a]) импортёр
    # молча теряет; у блока адрес - обычный вход, он импортируется штатно.
    (u"pw0", u"FB_Memory64K", u"запись предустановки 1"),
    (u"pw1", u"FB_Memory64K", u"запись предустановки 2"),
    (u"pw2", u"FB_Memory64K", u"запись предустановки 3"),
    (u"pchk", u"FB_Memory64K", u"чтение памяти для проверки кейса"),
    (u"mem_val", u"BYTE", u"прочитанное значение памяти для проверки"),
    (u"pwv0", u"BYTE", u"прочитанное значение блока записи 1 (держит вызов живым)"),
    (u"pwv1", u"BYTE", u"прочитанное значение блока записи 2 (держит вызов живым)"),
    (u"pwv2", u"BYTE", u"прочитанное значение блока записи 3 (держит вызов живым)"),
    (u"pc0", u"FB_Memory64K", u"очистка предустановки 1 после кейса"),
    (u"pc1", u"FB_Memory64K", u"очистка предустановки 2 после кейса"),
    (u"pc2", u"FB_Memory64K", u"очистка предустановки 3 после кейса"),
    (u"pcv0", u"BYTE", u"чтение блока очистки 1 (держит вызов живым)"),
    (u"pcv1", u"BYTE", u"чтение блока очистки 2 (держит вызов живым)"),
    (u"pcv2", u"BYTE", u"чтение блока очистки 3 (держит вызов живым)"),
    (u"prb", u"FB_Memory64K", u"обратное чтение предустановки (диагностика)"),
]

# по 16 байт кода
for _k in range(16):
    LOCALS.append((u"c_k%d" % _k, u"BYTE", u"байт кода %d" % _k))


def _load_case(n):
    u"""СЕТЬ 1: прочитать поля текущего кейса из таблицы в локальные переменные.

    Читается ОДИН раз за кейс (все сравнения работают с локальными копиями):
    во-первых, вложенная индексация Tests[idx].<поле> используется ровно один
    раз на поле (меньше риск диалекта), во-вторых, снимок кейса не разъедется,
    если idx поменяется на последнем такте.
    """
    def r(f, t=None):
        return u"GVL_TEST.Tests[idx].%s" % f
    for k in range(16):
        n.outvar(u"c_k%d" % k, I(n, r(u"Code[%d]" % k)))
    for nm, f in ((u"c_id", u"Id"), (u"c_grp", u"Group"), (u"c_len", u"CodeLen"),
                  (u"c_a", u"InitA"), (u"c_b", u"InitB"), (u"c_c", u"InitC"),
                  (u"c_d", u"InitD"), (u"c_e", u"InitE"), (u"c_h", u"InitH"),
                  (u"c_l", u"InitL"), (u"c_sp", u"InitSP"), (u"c_pc", u"InitPC"),
                  (u"c_ipsw", u"InitPSW"), (u"c_xa", u"ExpA"), (u"c_xb", u"ExpB"),
                  (u"c_xc", u"ExpC"), (u"c_xd", u"ExpD"), (u"c_xe", u"ExpE"),
                  (u"c_xh", u"ExpH"), (u"c_xl", u"ExpL"), (u"c_xsp", u"ExpSP"),
                  (u"c_xpc", u"ExpPC"), (u"c_xpsw", u"ExpPSW"), (u"c_mask", u"PSWMask"),
                  (u"c_chk", u"CheckMem"), (u"c_ma", u"ExpMemAddr"),
                  (u"c_mv", u"ExpMemVal"), (u"c_p1a", u"Pre1Addr"), (u"c_p1v", u"Pre1Val"),
                  (u"c_p2a", u"Pre2Addr"), (u"c_p2v", u"Pre2Val"), (u"c_p3a", u"Pre3Addr"),
                  (u"c_p3v", u"Pre3Val"), (u"c_tacts", u"MaxTacts")):
        n.outvar(nm, I(n, r(f)))
    # копии байтов регистров в WORD - входы порта CP/M имеют тип WORD
    for nm, src in ((u"w_a", u"c_a"), (u"w_b", u"c_b"), (u"w_c", u"c_c"),
                    (u"w_d", u"c_d"), (u"w_e", u"c_e"), (u"w_h", u"c_h"),
                    (u"w_l", u"c_l"), (u"w_psw", u"c_ipsw")):
        n.outvar(nm, n.block(u"BYTE_TO_WORD", [(u"IN", I(n, src))], [u"OUT"],
                             fbd_xml.COL_BLK + 200))


def _flags(n, base):
    u"""Вычислить признаки фаз из текущего значения ph."""
    for k, (nm, code) in enumerate(((u"f_idle", PH_IDLE), (u"f_load", PH_LOAD),
                                    (u"f_mem", PH_MEM), (u"f_run", PH_RUN),
                                    (u"f_stop", PH_STOP), (u"f_cmp", PH_CMP),
                                    (u"f_next", PH_NEXT), (u"f_hand", PH_HAND),
                                    (u"f_hand2", PH_HAND2), (u"f_done", PH_DONE))):
        n.outvar(nm, EQ(n, I(n, u"ph"), I(n, B % code), x=base + 130 * k))
    # f_wk - любая из фаз записи регистров W1..W5
    ws = []
    for k, code in enumerate((PH_W1, PH_W2, PH_W3, PH_W4, PH_W5)):
        ws.append(EQ(n, I(n, u"ph"), I(n, B % code), x=base + 130 * 10 + 130 * k))
    n.outvar(u"f_wk", ORL(n, ws, x0=base + 130 * 15))


def make_test_8080():
    u"""TEST_8080: программа табличного прогона тестов ядра 8080."""
    p = Pou(u"TEST_8080", u"program",
            doc=u"Табличный прогон тестов ядра Intel 8080 (этап 4).\n"
                u"\tТесты - ДАННЫЕ (GVL_TEST.Tests), схема прогона одна.\n"
                u"\tПрогон идёт по ОБЩЕМУ экземпляру процессора (тот, что вызывает\n"
                u"\tPLC_PRG_CPM): управление - через порт CP/M (GVL_CPM.CPM_Sel1/Data1/LD1).\n"
                u"\tпамять - GVL_MEM, регистры читаются из GVL_CPM.Reg_*.\n"
                u"\tОдин скан фазы RUN = ровно один такт 8080.\n"
                u"\tРезультат каждого кейса - BOOL в GVL_TEST.Results[idx].")
    p.var(u"n", u"INT", u"число кейсов")
    for nm, t, c in LOCALS:
        if nm == u"n":
            continue
        p.var(nm, t, c)

    # ------------------------------------------------------------------
    # СЕТЬ 1. ПОЛЯ ТЕКУЩЕГО КЕЙСА
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 1. Чтение полей текущего тест-кейса (таблица данных)")
    n.outvar(u"n", I(n, u"GVL_TEST.N_Cases"))
    _load_case(n)

    # ------------------------------------------------------------------
    # СЕТЬ 2. ПРИЗНАКИ ФАЗ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 2. Признаки фаз автомата прогона (ph -> f_*)")
    _flags(n, fbd_xml.COL_BLK)
    # Явный сброс: хост ставит GVL_TEST.Reset, схема снимает его в конце скана.
    n.outvar(u"rst", I(n, u"GVL_TEST.Reset"), fbd_xml.COL_BLK + 2000)
    # ФАЗА B. АРБИТРАЖ ПРОЦЕССОРА МЕЖДУ ТЕСТОМ И СЛОЕМ CP/M.
    # Раньше здесь было own := NOT(f_done). Этого МАЛО: тест продолжал писать
    # регистры через порт и в те сканы, когда автомат трапов уже ушёл из фазы
    # WORK(8) в TRAP(3). Из-за этого PC переставал совпадать с точкой входа
    # (is_ccp/is_bdos/is_bios становились FALSE), диспетчер терял Enable и НЕ
    # выставлял квитанцию GVL_CPM.Func_Done. Трап навсегда оставался в фазе
    # TRAP, CPU_Enable (= f_wk) навсегда становился FALSE, процессор не выполнял
    # ни одного такта - весь прогон вставал (наблюдалось: Trap_Phase=3,
    # Reg_PC=0, тактов=3).
    # Теперь тест владеет процессором ТОЛЬКО пока трап в фазе WORK - ровно то же
    # условие, по которому он вообще стартует (start_ok).
    n.outvar(u"own", AND(n, NOT(n, I(n, u"f_done"), fbd_xml.COL_BLK + 2100),
                         NOT(n, I(n, u"GVL_CPM.Trap_Active"), fbd_xml.COL_BLK + 2200),
                         fbd_xml.COL_BLK + 2300))
    n.outvar(u"start_ok", ANDL(n, [
        I(n, u"GVL_TEST.Run"),
        EQ(n, I(n, u"GVL_TEST.Mode"), I(n, B % 1), fbd_xml.COL_BLK + 2420),
        NOT(n, I(n, u"GVL_CPM.Trap_Active"), fbd_xml.COL_BLK + 2550),
        I(n, u"GVL_IO_Map.Map_Ready"),
        LT(n, I(n, u"idx"), I(n, u"n"), fbd_xml.COL_BLK + 2810)],
        x0=fbd_xml.COL_BLK + 2940))

    # ------------------------------------------------------------------
    # СЕТЬ 3. СЧЁТЧИК ТАКТОВ И ПРИЗНАК КОНЦА НОРМЫ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 3. Счётчик тактов кейса и признак «норма исчерпана»")
    # ФАЗА B. ГЛАВНАЯ ОШИБКА ПРОГОНА БЫЛА ЗДЕСЬ.
    # Такт считается выполненным ТОЛЬКО если GVL_CPU.Step_Cnt изменился.
    # Раньше фаза RUN длилась РОВНО ОДИН скан, и переход RUN -> STOP был
    # безусловным. Но внутри FB_CPU8080_FULL такт разрешён условием
    #     run = Enable AND NOT Halted,   Enable = CPU_Run AND CPU_Enable,
    # где CPU_Enable := f_wk - признак того, что автомат трапов CP/M находится
    # в фазе WORK(8). Если скан фазы RUN не совпал с фазой WORK, такт НЕ
    # выполнялся, PC не двигался, кейс помечался FAIL, и так все 199 кейсов.
    # (Трассировка подтвердила: CPU_Run=TRUE наблюдался только в паре с
    # Trap_Phase = 0 или 3, ни разу с 8.)
    # Теперь tact считает РЕАЛЬНЫЕ такты, а фаза RUN держится, пока их не
    # наберётся c_tacts - см. переход RUN -> STOP в сети 7.
    n.outvar(u"step_chg", NE(n, I(n, u"GVL_CPU.Step_Cnt"), I(n, u"step_prev"),
                             fbd_xml.COL_BLK + 120))
    n.outvar(u"step_prev", I(n, u"GVL_CPU.Step_Cnt"), fbd_xml.COL_BLK + 240)
    # СЧЁТ ТАКТОВ. Считаем ВЫДАННЫЕ такты, а не "увиденные": step_chg
    # (изменение GVL_CPU.Step_Cnt) отстаёт на один скан, потому что процессор
    # исполняется в PLC_PRG_CPM - ПОЗЖЕ этой схемы в том же скане. Из-за этого
    # отставания фаза RUN успевала выдать ещё один такт, и для однобайтовой
    # команды получалось PC = 0202 вместо 0201 (проверено прогоном).
    # Выданный такт точнее: такт разрешён ровно при RAM = f_run AND NOT stop_now,
    # и в этом же скане процессор его исполняет (CPU_Enable = TRUE, трап на
    # время набора отключён).
    # УСТАНОВКА КОНВЕЙЕРА (фаза B).
    #
    # В FBD промежуточные величины передаются через outvar/invar и видны
    # адресату только со СЛЕДУЮЩЕГО скана. В ядре так построены ВСЕ цепочки:
    # PC -> pc1/pc2 -> байты команды -> a16 -> адрес перехода. Поэтому в
    # многотактовой программе операнд читался из ПРЕДЫДУЩЕЙ позиции PC:
    # замер для JMP 0300h давал адрес C311h - это байты 11h,C3h от прошлой
    # позиции, а не 00h,03h от текущей.
    #
    # ЛЕЧЕНИЕ БЕЗ ПЕРЕДЕЛКИ ЯДРА: между тактами схема делает SETTLE "холостых"
    # сканов, в которых процессор ВЫКЛЮЧЕН (CPU_Run = FALSE). За это время
    # цепочки успевают установиться, и такт исполняется на уже верных
    # значениях. Такт по-прежнему один за скан (ТЗ), просто между ними
    # появились паузы; на счётчик тактов паузы не влияют.
    n.outvar(u"settle", IF(n, I(n, u"f_run"),
                           IF(n, GE(n, I(n, u"settle"), I(n, u"INT#%d" % SETTLE),
                                      fbd_xml.COL_BLK + 1100),
                              I(n, u"INT#0"),
                              ADD(n, I(n, u"settle"), I(n, u"INT#1"),
                                  fbd_xml.COL_BLK + 1220),
                              fbd_xml.COL_BLK + 1340),
                           I(n, u"INT#0"), fbd_xml.COL_BLK + 1460))
    n.outvar(u"fire", AND(n, I(n, u"f_run"),
                          GE(n, I(n, u"settle"), I(n, u"INT#%d" % SETTLE),
                             fbd_xml.COL_BLK + 1580),
                          fbd_xml.COL_BLK + 1700))
    n.outvar(u"stop_now", AND(n, I(n, u"f_run"),
                              GE(n, I(n, u"tact"), I(n, u"c_tacts"),
                                 fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 400))
    n.outvar(u"tact", IF(n, I(n, u"f_run"),
                         IF(n, I(n, u"fire"),
                            ADD(n, I(n, u"tact"), I(n, u"INT#1"), fbd_xml.COL_BLK + 900),
                            I(n, u"tact"), fbd_xml.COL_BLK + 960),
                         I(n, u"INT#0"), fbd_xml.COL_BLK + 1040))

    # ------------------------------------------------------------------
    # СЕТЬ 4. ПАМЯТЬ: КОД ТЕСТА И ПРЕДУСТАНОВКИ (только в фазе MEM)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 4. Загрузка кода теста и предустановок памяти (фаза MEM)")
    for k in range(16):
        e = u"GVL_MEM.Memory[%d]" % (CODE_BASE + k)
        n.outvar(e, IF(n, I(n, u"f_mem"), I(n, u"c_k%d" % k), I(n, e),
                       fbd_xml.COL_BLK + 200 * (k % 4), 40 + 30 * k))
    # ПРЕДУСТАНОВКИ ПИШУТСЯ ЧЕРЕЗ БЛОК ПАМЯТИ, А НЕ ЧЕРЕЗ ИНДЕКС-ПЕРЕМЕННУЮ.
    # ПРЕДУСТАНОВКИ ПИШУТСЯ ПО ПОСТОЯННОМУ ИНДЕКСУ.
    #
    # Проверено измерением: запись по ВЫЧИСЛЯЕМОМУ индексу (Memory[c_p1a]) и
    # запись через вызов блока FB_Memory64K в этом CODESYS НЕ РАБОТАЮТ. При
    # Wr = TRUE и верном адресе 0600h обратное чтение давало 00 - блок просто
    # не исполнялся (тело вызова выбрасывается, даже когда выход идёт в
    # глобальную переменную). А запись по КОНСТАНТНОМУ индексу работает:
    # именно так выше грузится код теста.
    #
    # Различных адресов предустановок во всей таблице всего девять, поэтому
    # пишем по одному условному присваиванию на адрес:
    #   Memory[a] := IF(f_mem и адрес слота совпал, значение слота, Memory[a])
    # и отдельно, в фазе NEXT, обнуляем те же ячейки (иначе значения предыдущего
    # кейса видны следующему).
    _slots = ((u"c_p1a", u"c_p1v"), (u"c_p2a", u"c_p2v"), (u"c_p3a", u"c_p3v"))
    _empty = []
    for _a, _v in _slots:
        _empty.append(AND(n, EQ(n, I(n, _a), I(n, W % 0), fbd_xml.COL_BLK + 3000),
                          EQ(n, I(n, _v), I(n, B % 0), fbd_xml.COL_BLK + 3130),
                          fbd_xml.COL_BLK + 3260))
    for _k, _addr in enumerate(PRE_ADDRS):
        _e = u"GVL_MEM.Memory[%d]" % _addr
        _acc = I(n, _e)
        for _j, (_a, _v) in enumerate(_slots):
            _hit = AND(n, NOT(n, _empty[_j], fbd_xml.COL_BLK + 3400),
                       EQ(n, I(n, _a), I(n, W % _addr), fbd_xml.COL_BLK + 3530),
                       fbd_xml.COL_BLK + 3660)
            # запись предустановки в фазе MEM
            _acc = IF(n, AND(n, I(n, u"f_mem"), _hit, fbd_xml.COL_BLK + 3790),
                      I(n, _v), _acc, fbd_xml.COL_BLK + 3920)
            # очистка в фазе NEXT
            _acc = IF(n, AND(n, I(n, u"f_next"), _hit, fbd_xml.COL_BLK + 4050),
                      I(n, B % 0), _acc, fbd_xml.COL_BLK + 4180)
        n.outvar(_e, _acc, fbd_xml.COL_BLK + 200 * (_k % 4), 40 + 30 * (_k % 12 + 16))
    # диагностика: что лежит по адресу 0600h В МОМЕНТ ТАКТА (постоянный индекс,
    # чтобы исключить влияние динамической адресации). Именно этот адрес
    # используют кейсы ADD M / SUB M / ORA M.
    n.outvar(u"GVL_TEST.ActPre[idx]",
             IF(n, I(n, u"f_cmp"), I(n, u"GVL_MEM.Memory[1791]"),
                I(n, u"GVL_TEST.ActPre[idx]"), fbd_xml.COL_BLK2 + 4400),
             40, 40 + 30 * 28)
    # диагностика: операнд M, который реально пришёл в АЛУ
    n.outvar(u"GVL_TEST.ActW[idx]",
             IF(n, I(n, u"f_run"), I(n, u"GVL_CPU.Bus_Data"),
                I(n, u"GVL_TEST.ActW[idx]"), fbd_xml.COL_BLK2 + 4520),
             40, 40 + 30 * 30)
    f1 = EQ(n, I(n, u"ph"), I(n, B % PH_W1))
    f2 = EQ(n, I(n, u"ph"), I(n, B % PH_W2), fbd_xml.COL_BLK + 140)
    f3 = EQ(n, I(n, u"ph"), I(n, B % PH_W3), fbd_xml.COL_BLK + 280)
    f4 = EQ(n, I(n, u"ph"), I(n, B % PH_W4), fbd_xml.COL_BLK + 420)
    f5 = EQ(n, I(n, u"ph"), I(n, B % PH_W5), fbd_xml.COL_BLK + 560)
    # канал 1: A(0) C(2) E(4) L(6) SP(8); канал 2: B(1) D(3) H(5) PC(7) PSW(9)
    #
    # ВНИМАНИЕ, БЫЛА ГРУБАЯ ОШИБКА (фаза B): цепочки были собраны как
    #     SEL(f1, 0, SEL(f2, 2, SEL(f3, 4, SEL(f4, 6, 8))))
    # а SEL в этом проекте возвращает IN1 при G = TRUE ("при G=TRUE результат
    # IN1, иначе IN0", см. pou_cpm_defs.SEL). Такая запись означает:
    # "если f1 - то НЕ 0, иначе 0", то есть в фазе W1 выбиралось последнее
    # значение (8 = SP вместо 0 = A), в W2 - 0, и так далее: канал и данные
    # были СДВИНУТЫ, регистры писались не те. Правильная форма - "первое
    # совпадение выигрывает", она и собрана ниже через _first.
    n.outvar(u"sel1", _first(n, [(f1, I(n, B % 0)), (f2, I(n, B % 2)),
                                 (f3, I(n, B % 4)), (f4, I(n, B % 6))],
                              I(n, B % 8), fbd_xml.COL_BLK + 700))
    n.outvar(u"sel2", _first(n, [(f1, I(n, B % 1)), (f2, I(n, B % 3)),
                                 (f3, I(n, B % 5)), (f4, I(n, B % 7))],
                              I(n, B % 9), fbd_xml.COL_BLK + 1400))
    n.outvar(u"dat1", _first(n, [(f1, I(n, u"w_a")), (f2, I(n, u"w_c")),
                                 (f3, I(n, u"w_e")), (f4, I(n, u"w_l"))],
                              I(n, u"c_sp"), fbd_xml.COL_BLK + 2100))
    n.outvar(u"dat2", _first(n, [(f1, I(n, u"w_b")), (f2, I(n, u"w_d")),
                                 (f3, I(n, u"w_h")), (f4, I(n, u"c_pc"))],
                              I(n, u"w_psw"), fbd_xml.COL_BLK + 2800))
    n.outvar(u"port_wr", ORL(n, [f1, f2, f3, f4, f5], x0=fbd_xml.COL_BLK + 3360))

    # Порт CP/M выставляется ТОЛЬКО когда схема владеет прогоном.
    #
    # ФАЗА B: ЗДЕСЬ БЫЛА ПРИЧИНА ПОЛНОГО ОТКАЗА ПРОГОНА.
    # Раньше в ветке "не владею" порт принудительно ОБНУЛЯЛСЯ:
    #     CPM_WE := IF(own, port_wr, FALSE), Sel1 := IF(own, sel1, 0), ...
    # Но TEST_8080 стоит в задаче ПЕРВЫМ, а трап пишет порт в PLC_PRG_CPM
    # ПОЗЖЕ (и вызов процессора там же, но раньше трапа). Значит значения,
    # выставленные трапом в скане N, должны дожить до вызова процессора в
    # скане N+1. Обнуляя порт в начале каждого скана, тест стирал их - и
    # стартовая запись PC := 0F100h (и все записи регистров от трапа) до
    # процессора НЕ ДОХОДИЛИ. Итог: Reg_PC=0, автомат трапов навсегда
    # застревал в фазе TRAP, CPU_Enable=FALSE, процессор не делал ни одного
    # такта (наблюдалось: тактов=3 за весь прогон).
    # Теперь, не владея процессором, схема НЕ ТРОГАЕТ порт - пишет обратно
    # текущее значение. Это и есть "не мешать слою CP/M".
    for tgt, src in ((u"GVL_CPM.CPM_WE", u"port_wr"),
                     (u"GVL_CPM.CPM_LD1", u"port_wr"),
                     (u"GVL_CPM.CPM_LD2", u"port_wr")):
        n.outvar(tgt, IF(n, I(n, u"own"), I(n, src), I(n, tgt),
                         fbd_xml.COL_BLK + 3500))
    n.outvar(u"GVL_CPM.CPM_Sel1",
             IF(n, I(n, u"own"), I(n, u"sel1"), I(n, u"GVL_CPM.CPM_Sel1"),
                fbd_xml.COL_BLK + 3630))
    n.outvar(u"GVL_CPM.CPM_Sel2",
             IF(n, I(n, u"own"), I(n, u"sel2"), I(n, u"GVL_CPM.CPM_Sel2"),
                fbd_xml.COL_BLK + 3760))
    n.outvar(u"GVL_CPM.CPM_Data1",
             IF(n, I(n, u"own"), I(n, u"dat1"), I(n, u"GVL_CPM.CPM_Data1"),
                fbd_xml.COL_BLK + 3890))
    n.outvar(u"GVL_CPM.CPM_Data2",
             IF(n, I(n, u"own"), I(n, u"dat2"), I(n, u"GVL_CPM.CPM_Data2"),
                fbd_xml.COL_BLK + 4020))

    # передача CP/M: PC := 0F100h и SP := 0F200h (фаза HAND2)
    n.outvar(u"GVL_CPM.CPM_WE", IF(n, I(n, u"f_hand2"), I(n, u"TRUE"),
                                   I(n, u"GVL_CPM.CPM_WE"), fbd_xml.COL_BLK + 4150))
    n.outvar(u"GVL_CPM.CPM_LD1", IF(n, I(n, u"f_hand2"), I(n, u"TRUE"),
                                    I(n, u"GVL_CPM.CPM_LD1"), fbd_xml.COL_BLK + 4280))
    n.outvar(u"GVL_CPM.CPM_LD2", IF(n, I(n, u"f_hand2"), I(n, u"TRUE"),
                                    I(n, u"GVL_CPM.CPM_LD2"), fbd_xml.COL_BLK + 4410))
    n.outvar(u"GVL_CPM.CPM_Sel1", IF(n, I(n, u"f_hand2"), I(n, B % 7),
                                     I(n, u"GVL_CPM.CPM_Sel1"), fbd_xml.COL_BLK + 4540))
    n.outvar(u"GVL_CPM.CPM_Sel2", IF(n, I(n, u"f_hand2"), I(n, B % 8),
                                     I(n, u"GVL_CPM.CPM_Sel2"), fbd_xml.COL_BLK + 4670))
    n.outvar(u"GVL_CPM.CPM_Data1", IF(n, I(n, u"f_hand2"), I(n, W % CCP_ENTRY),
                                      I(n, u"GVL_CPM.CPM_Data1"), fbd_xml.COL_BLK + 4800))
    n.outvar(u"GVL_CPM.CPM_Data2", IF(n, I(n, u"f_hand2"), I(n, W % STACK_TOP),
                                      I(n, u"GVL_CPM.CPM_Data2"), fbd_xml.COL_BLK + 4930))

    # ------------------------------------------------------------------
    # СЕТЬ 6. ПРОЦЕССОР: ВКЛЮЧЕНИЕ И ОСТАНОВ, СБРОС HLT
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 6. Процессор: такты в фазе RUN, останов в остальных фазах")
    # ВАЖНО (фаза B): такт разрешён ТОЛЬКО пока норма не исчерпана, то есть
    # RAM = f_run AND NOT stop_now, а не просто f_run.
    # Иначе процессор успевал сделать ЛИШНИЙ такт в том скане, когда автомат
    # уже собирался уйти из RUN: stop_now вычисляется ДО обновления tact, и в
    # скане перехода RUN -> STOP процессор всё ещё был включён. Для
    # однобайтовой команды это давало PC = 0203 вместо 0201 (наблюдалось в
    # таблице прогона на всех однобайтовых кейсах).
    n.outvar(u"GVL_CPM.CPU_Run",
             IF(n, I(n, u"own"), I(n, u"fire"),
                I(n, u"GVL_CPM.CPU_Run"), fbd_xml.COL_BLK + 200))
    # ФАЗА B. ЗАЩЁЛКУ HLT НЕЛЬЗЯ СНИМАТЬ В ТАКТЕ.
    # Раньше здесь стояло "пока владею - Halted := FALSE", то есть признак
    # останова снимался КАЖДЫЙ скан. Из-за этого HLT не останавливал процессор:
    # он продолжал исполнять нули (NOP) за командой, PC уезжал (0204 вместо
    # 0201), и в конце концов обнулялся аккумулятор - поэтому ВСЕ кейсы,
    # заканчивающиеся HLT (T-284, T-419 и вся группа 6: T-371..T-373),
    # получали A=00. Теперь защёлка снимается только в НАЧАЛЕ кейса
    # (фазы LOAD/MEM), а в такте остаётся как есть.
    n.outvar(u"GVL_CPU.Halted",
             IF(n, AND(n, I(n, u"own"),
                       OR(n, I(n, u"f_load"), I(n, u"f_mem"), fbd_xml.COL_BLK + 100),
                       fbd_xml.COL_BLK + 140),
                I(n, u"FALSE"), I(n, u"GVL_CPU.Halted"),
                fbd_xml.COL_BLK + 200))
    # ЗАЩЁЛКА ДИАГНОСТИКИ: пока идёт такт, запоминаем опкод/класс/пару,
    # которые реально обрабатывал декодер. Поля GVL_CPU.C_* живут один скан,
    # поэтому снаружи их не поймать (проба zz_tact.py поймала 2 сэмпла за 6 с).
    for _tgt, _src in ((u"GVL_TEST.ActIR[idx]", u"GVL_CPU.Bus_IR"),
                       (u"GVL_TEST.ActCls[idx]", u"GVL_CPU.C_Class"),
                       (u"GVL_TEST.ActRP[idx]", u"GVL_CPU.C_RP"),
                       (u"GVL_TEST.ActUnc[idx]", u"GVL_CPU.C_Uncond"),
                       (u"GVL_TEST.ActAddr[idx]", u"GVL_CPU.Bus_Addr")):
        n.outvar(_tgt, IF(n, I(n, u"f_run"), I(n, _src), I(n, _tgt),
                          fbd_xml.COL_BLK + 500))
    # (защёлка c_p1a убрана: она перекрывала реальный HL в этой же колонке)
    # защита такта на время набора тестов выключена: прогон сам управляет
    # тактами и не должен сниматься в аварию по тайм-ауту
    n.outvar(u"GVL_IO_Map.Watchdog_Enable",
             IF(n, I(n, u"own"), I(n, u"FALSE"), I(n, u"TRUE"),
                fbd_xml.COL_BLK + 200))

    # ------------------------------------------------------------------
    # СЕТЬ 7. ПЕРЕХОДЫ АВТОМАТА
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 7. Таблица переходов автомата прогона (ph -> ph)")
    # ВНИМАНИЕ (фаза B): перехода RUN -> STOP в таблице БОЛЬШЕ НЕТ. Он вынесен
    # ниже и обусловлен реально выполненными тактами (stop_now). Иначе фаза RUN
    # заканчивалась через один скан, не успев выполнить такт, - см. сеть 3.
    seq = [(PH_IDLE, PH_LOAD), (PH_LOAD, PH_MEM), (PH_MEM, PH_W1),
           (PH_W1, PH_W2), (PH_W2, PH_W3), (PH_W3, PH_W4), (PH_W4, PH_W5),
           (PH_W5, PH_RUN),
           (PH_STOP, PH_CMP),
           (PH_CMP, PH_NEXT), (PH_NEXT, PH_LOAD), (PH_HAND, PH_HAND2),
           (PH_HAND2, PH_DONE)]
    acc = I(n, u"ph")
    for k, (a, b) in enumerate(seq):
        cond = EQ(n, I(n, u"ph"), I(n, B % a), x=fbd_xml.COL_BLK + 130 * (k % 8),
                  y=40 + 30 * k)
        acc = SEL(n, cond, acc, I(n, B % b), fbd_xml.COL_BLK + 1100 + 130 * (k % 8),
                  y=40 + 30 * k)
    # RUN -> STOP: только когда выполнено c_tacts РЕАЛЬНЫХ тактов
    acc = SEL(n, AND(n, I(n, u"f_run"), I(n, u"stop_now"), fbd_xml.COL_BLK + 2050),
              acc, I(n, B % PH_STOP), fbd_xml.COL_BLK + 2180)
    # ПАУЗА (фаза B): пока тест НЕ владеет процессором (трап ушёл из фазы WORK),
    # автомат стоит на месте. Иначе он «проскакивал» бы фазы записи регистров,
    # пока порт закрыт, и кейс сравнивался бы по устаревшим значениям.
    acc = SEL(n, NOT(n, I(n, u"own"), fbd_xml.COL_BLK + 3310),
              acc, I(n, u"ph"), fbd_xml.COL_BLK + 3440)
    # IDLE -> LOAD только по условию старта, NEXT -> HAND в конце набора
    acc = SEL(n, AND(n, I(n, u"f_idle"), I(n, u"start_ok"), fbd_xml.COL_BLK + 2300),
              acc, I(n, B % PH_LOAD), fbd_xml.COL_BLK + 2440)
    # ФАЗА B. ГРАНИЦА НАБОРА. Счётчик idx останавливается на n-1 (условие
    # idx+1 < n), поэтому проверка "idx >= n" НЕ СРАБАТЫВАЛА НИКОГДА: набор
    # заканчивался на последнем кейсе и крутился на нём бесконечно (в протоколе
    # PASS=1538 вместо 199), а передачи управления CP/M не происходило.
    acc = SEL(n, AND(n, I(n, u"f_next"), GE(n, ADD(n, I(n, u"idx"), I(n, u"INT#1"),
                                                 fbd_xml.COL_BLK + 2400),
                                            I(n, u"n"), fbd_xml.COL_BLK + 2560),
                     fbd_xml.COL_BLK + 2680),
              acc, I(n, B % PH_HAND), fbd_xml.COL_BLK + 2820)
    # СБРОС - САМЫМ ПОСЛЕДНИМ, чтобы перекрыть ВСЕ переходы выше.
    # Раньше он стоял ДО перехода NEXT -> HAND и мог быть им перекрыт: при
    # сохранённой фазе NEXT и idx >= n автомат уходил в HAND, минуя сброс, -
    # набор объявлялся пройденным, Mode уходил 1 -> 2 -> 3, кейсы не шли.
    acc = SEL(n, I(n, u"rst"), acc, I(n, B % PH_IDLE), fbd_xml.COL_BLK + 3960)
    n.outvar(u"ph", acc)
    n.outvar(u"GVL_TEST.Phase", I(n, u"ph"))

    # ------------------------------------------------------------------
    # СЕТЬ 8. СРАВНЕНИЕ: СНИМОК РЕГИСТРОВ, ФЛАГОВ И ПАМЯТИ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 8. Сравнение факта с ожиданием (EQ -> BOOL по каждому полю)")
    ra, rb, rc, rd = I(n, u"GVL_CPM.Reg_A"), I(n, u"GVL_CPM.Reg_B"), \
        I(n, u"GVL_CPM.Reg_C"), I(n, u"GVL_CPM.Reg_D")
    re_, rh, rl = I(n, u"GVL_CPM.Reg_E"), I(n, u"GVL_CPM.Reg_H"), I(n, u"GVL_CPM.Reg_L")
    n.outvar(u"lk_a", EQ(n, ra, I(n, u"c_xa")))
    n.outvar(u"lk_b", EQ(n, rb, I(n, u"c_xb"), fbd_xml.COL_BLK + 130))
    n.outvar(u"lk_c", EQ(n, rc, I(n, u"c_xc"), fbd_xml.COL_BLK + 260))
    n.outvar(u"lk_d", EQ(n, rd, I(n, u"c_xd"), fbd_xml.COL_BLK + 390))
    n.outvar(u"lk_e", EQ(n, re_, I(n, u"c_xe"), fbd_xml.COL_BLK + 520))
    n.outvar(u"lk_h", EQ(n, rh, I(n, u"c_xh"), fbd_xml.COL_BLK + 650))
    n.outvar(u"lk_l", EQ(n, rl, I(n, u"c_xl"), fbd_xml.COL_BLK + 780))
    n.outvar(u"lk_sp", EQ(n, I(n, u"GVL_CPM.Reg_SP"), I(n, u"c_xsp"),
                          fbd_xml.COL_BLK + 910))
    n.outvar(u"lk_pc", EQ(n, I(n, u"GVL_CPM.Reg_PC"), I(n, u"c_xpc"),
                          fbd_xml.COL_BLK + 1040))
    # эталон флагов по маске: бит маски 1 -> ExpPSW, бит маски 0 -> InitPSW.
    # ВНИМАНИЕ: AND/OR здесь вызываются с ЯВНЫМИ ключевыми аргументами.
    # Позиционная форма AND(n, a, b, x, y) уже привела к ошибке кодогенерации
    # C32 'BYTE' -> 'BOOL' в этом месте, поэтому пишем однозначно.
    n.outvar(u"psw_ref", OR(n,
                            a=AND(n, a=I(n, u"c_xpsw"), b=I(n, u"c_mask"),
                                  x=fbd_xml.COL_BLK + 1170),
                            b=AND(n, a=I(n, u"c_ipsw"),
                                  b=NOT(n, I(n, u"c_mask"), fbd_xml.COL_BLK + 1300),
                                  x=fbd_xml.COL_BLK + 1430),
                            x=fbd_xml.COL_BLK + 1560))
    n.outvar(u"psw_ok", EQ(n, AND(n, I(n, u"GVL_CPM.Reg_PSW"),
                                  I(n, H % PSW_MASK_MEANING), fbd_xml.COL_BLK + 1690),
                           AND(n, I(n, u"psw_ref"), I(n, H % PSW_MASK_MEANING),
                               fbd_xml.COL_BLK + 1820), fbd_xml.COL_BLK + 1950))
    # Проверка памяти - тоже через блок (см. пояснение в сети 4).
    pk = n.block(u"FB_Memory64K",
                 [(u"Addr", I(n, u"c_ma")), (u"Wr", I(n, u"FALSE")),
                  (u"DataIn", I(n, B % 0))],
                 [u"DataOut"], instance=u"pchk", x=fbd_xml.COL_BLK + 2200)
    n.outvar(u"mem_val", pk.out(u"DataOut"), fbd_xml.COL_BLK + 2350)
    n.outvar(u"mem_ok", OR(n, NOT(n, I(n, u"c_chk"), fbd_xml.COL_BLK + 2080),
                           EQ(n, I(n, u"mem_val"), I(n, u"c_mv"),
                              fbd_xml.COL_BLK + 2210), fbd_xml.COL_BLK + 2340))
    n.outvar(u"res_all", ANDL(n, [
        I(n, u"lk_a"), I(n, u"lk_b"), I(n, u"lk_c"), I(n, u"lk_d"), I(n, u"lk_e"),
        I(n, u"lk_h"), I(n, u"lk_l"), I(n, u"lk_sp"), I(n, u"lk_pc"),
        I(n, u"psw_ok"), I(n, u"mem_ok")], x0=fbd_xml.COL_BLK + 2470))

    # ------------------------------------------------------------------
    # СЕТЬ 9. РЕЗУЛЬТАТ КЕЙСА И СЧЁТЧИКИ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 9. Запись результата кейса и счётчиков PASS/FAIL")
    for tgt, src in ((u"GVL_TEST.Results[idx]", u"res_all"),
                     (u"GVL_TEST.ActA[idx]", u"GVL_CPM.Reg_A"),
                     (u"GVL_TEST.ActPC[idx]", u"GVL_CPM.Reg_PC"),
                     (u"GVL_TEST.ActSP[idx]", u"GVL_CPM.Reg_SP"),
                     (u"GVL_TEST.ActPSW[idx]", u"GVL_CPM.Reg_PSW")):
        n.outvar(tgt, IF(n, I(n, u"f_cmp"), I(n, src), I(n, tgt)))
    n.outvar(u"pass_n", IF(n, AND(n, I(n, u"f_cmp"), I(n, u"res_all"),
                                  fbd_xml.COL_BLK + 200),
                           ADD(n, I(n, u"pass_n"), I(n, u"INT#1"), fbd_xml.COL_BLK + 330),
                           I(n, u"pass_n"), fbd_xml.COL_BLK + 460))
    n.outvar(u"fail_n", IF(n, AND(n, I(n, u"f_cmp"), NOT(n, I(n, u"res_all"),
                                                      fbd_xml.COL_BLK + 590),
                                  fbd_xml.COL_BLK + 720),
                           ADD(n, I(n, u"fail_n"), I(n, u"INT#1"), fbd_xml.COL_BLK + 850),
                           I(n, u"fail_n"), fbd_xml.COL_BLK + 980))
    # счётчики по НОМЕРАМ кейсов: считаем ТОЛЬКО в фазе NEXT, когда результат
    # уже записан в Results[idx] (в остальных фазах Results[idx] ещё пуст)
    n.outvar(u"pass_i", IF(n, AND(n, I(n, u"f_next"),
                                  I(n, u"GVL_TEST.Results[idx]"),
                                  fbd_xml.COL_BLK + 1110),
                           ADD(n, I(n, u"pass_i"), I(n, u"INT#1"), fbd_xml.COL_BLK + 1240),
                           I(n, u"pass_i"), fbd_xml.COL_BLK + 1370))
    n.outvar(u"fail_i", IF(n, AND(n, I(n, u"f_next"),
                                  NOT(n, I(n, u"GVL_TEST.Results[idx]"),
                                      fbd_xml.COL_BLK + 1500),
                                  fbd_xml.COL_BLK + 1630),
                           ADD(n, I(n, u"fail_i"), I(n, u"INT#1"), fbd_xml.COL_BLK + 1760),
                           I(n, u"fail_i"), fbd_xml.COL_BLK + 1890))
    n.outvar(u"first_fail", IF(n, AND3(n, I(n, u"f_next"),
                                       NOT(n, I(n, u"GVL_TEST.Results[idx]"),
                                           fbd_xml.COL_BLK + 2020),
                                       EQ(n, I(n, u"first_fail"), I(n, u"INT#-1"),
                                          fbd_xml.COL_BLK + 2150),
                                       fbd_xml.COL_BLK + 2280),
                                I(n, u"idx"), I(n, u"first_fail"), fbd_xml.COL_BLK + 2410))
    # Счётчики и флаги готовности сбрасываются тем же сигналом rst.
    # счётчик PASS/FAIL не должен считать лишний шаг на ПЕРЕХОДЕ к CP/M:
    # раньше он давал 200 при 199 кейсах (f_next срабатывал и на последнем
    # переходе, когда idx уже равен n-1).
    # Считаем PASS/FAIL по фазе СРАВНЕНИЯ: она бывает ровно один скан
    # на кейс, поэтому счётчик детерминирован (с f_next получалось то
    # 199, то 200 из-за задержки распространения idx).
    cnt_en = I(n, u"f_cmp")
    n.outvar(u"GVL_TEST.Pass_Cnt",
             IF(n, I(n, u"rst"), I(n, u"INT#0"),
                IF(n, cnt_en, I(n, u"pass_i"),
                   I(n, u"GVL_TEST.Pass_Cnt"), fbd_xml.COL_BLK + 2440),
                fbd_xml.COL_BLK + 2540))
    n.outvar(u"GVL_TEST.Fail_Cnt",
             IF(n, I(n, u"rst"), I(n, u"INT#0"),
                IF(n, cnt_en, I(n, u"fail_i"),
                   I(n, u"GVL_TEST.Fail_Cnt"), fbd_xml.COL_BLK + 2570),
                fbd_xml.COL_BLK + 2670))
    n.outvar(u"GVL_TEST.First_Fail",
             IF(n, I(n, u"rst"), I(n, u"INT#-1"),
                IF(n, I(n, u"f_next"), I(n, u"first_fail"),
                   I(n, u"GVL_TEST.First_Fail"), fbd_xml.COL_BLK + 2700),
                fbd_xml.COL_BLK + 2800))
    n.outvar(u"GVL_TEST.Done8080",
             IF(n, I(n, u"rst"), I(n, u"FALSE"),
                OR(n, I(n, u"GVL_TEST.Done8080"), I(n, u"f_hand"),
                   fbd_xml.COL_BLK + 2830), fbd_xml.COL_BLK + 2930))
    n.outvar(u"GVL_TEST.Idx", I(n, u"idx"))
    n.outvar(u"GVL_TEST.Scans",
             IF(n, I(n, u"rst"), I(n, u"UDINT#0"),
                ADD(n, I(n, u"GVL_TEST.Scans"), I(n, u"UDINT#1"),
                    fbd_xml.COL_BLK + 2960), fbd_xml.COL_BLK + 3060))

    # ------------------------------------------------------------------
    # СЕТЬ 10. ПЕРЕДАЧА УПРАВЛЕНИЯ СЛОЮ CP/M
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 10. Передача управления CP/M: переинициализация памяти и PC")
    # индекс следующего кейса (при сбросе - в начало)
    n.outvar(u"idx",
             IF(n, I(n, u"rst"), I(n, u"INT#0"),
                IF(n, AND(n, I(n, u"f_next"), LT(n, ADD(n, I(n, u"idx"),
                                                        I(n, u"INT#1"),
                                                        fbd_xml.COL_BLK + 200),
                                           I(n, u"n"), fbd_xml.COL_BLK + 330),
                          fbd_xml.COL_BLK + 460),
                   ADD(n, I(n, u"idx"), I(n, u"INT#1"), fbd_xml.COL_BLK + 590),
                   I(n, u"idx"), fbd_xml.COL_BLK + 720), fbd_xml.COL_BLK + 760))
    # сначала безопасный PC (нули = NOP), потом переинициализация памяти
    n.outvar(u"GVL_CPM.CPM_WE", IF(n, I(n, u"f_hand"), I(n, u"TRUE"),
                                   I(n, u"GVL_CPM.CPM_WE"), fbd_xml.COL_BLK + 850))
    n.outvar(u"GVL_CPM.CPM_LD1", IF(n, I(n, u"f_hand"), I(n, u"TRUE"),
                                    I(n, u"GVL_CPM.CPM_LD1"), fbd_xml.COL_BLK + 980))
    n.outvar(u"GVL_CPM.CPM_Sel1", IF(n, I(n, u"f_hand"), I(n, B % 7),
                                     I(n, u"GVL_CPM.CPM_Sel1"), fbd_xml.COL_BLK + 1110))
    n.outvar(u"GVL_CPM.CPM_Data1", IF(n, I(n, u"f_hand"), I(n, W % SAFE_PC),
                                      I(n, u"GVL_CPM.CPM_Data1"), fbd_xml.COL_BLK + 1240))
    n.outvar(u"GVL_CPM.Init_Done", IF(n, I(n, u"f_hand2"), I(n, u"FALSE"),
                                      I(n, u"GVL_CPM.Init_Done"), fbd_xml.COL_BLK + 1370))
    # Режим: при сбросе принудительно 1 (прогон 8080), иначе - по концу набора.
    # Гейт по rst обязателен: иначе в скане сброса старый ph ещё равен HAND и
    # CHAIN_MODE успевал поставить 2, а следующий скан давал 3.
    n.outvar(u"GVL_TEST.Mode",
             IF(n, I(n, u"rst"), I(n, B % 1), CHAIN_MODE(n),
                fbd_xml.COL_BLK + 1600))
    # Снять запрос сброса - ровно на один скан.
    n.outvar(u"GVL_TEST.Reset", I(n, u"FALSE"))
    return p


def _first(n, pairs, dflt, x0=None):
    u"""Первое совпадение: cond1 ? v1 : (cond2 ? v2 : ( ... : dflt)).

    ПОЛЯРНОСТЬ SEL. В этом проекте SEL(G, IN0, IN1) возвращает IN1 при G = TRUE
    (pou_cpm_defs.SEL: "при G=TRUE результат IN1, иначе IN0"). Поэтому
    "если cond то val, иначе acc" записывается как SEL(cond, acc, val), а
    цепочку надо строить С КОНЦА - тогда первое условие окажется внешним и
    выиграет. Именно на этом ошибались цепочки каналов порта в сети 5.
    """
    acc = dflt
    for cond, val in reversed(list(pairs)):
        acc = SEL(n, cond, acc, val, x0)
    return acc


def CHAIN_MODE(n):
    u"""Режим: 2 - тесты CP/M (ставится ТОЛЬКО по концу набора 8080), иначе - как есть.

    ВНИМАНИЕ, БЫЛА ОШИБКА (фаза B): стояло SEL(f_hand, 2, Mode). А SEL в этом
    проекте возвращает IN1 при G = TRUE (см. pou_cpm_defs.SEL: "при G=TRUE
    результат IN1, иначе IN0"), поэтому выражение читалось наоборот:
    "если набор НЕ закончен, то 2". Из-за этого Mode становился 2 сразу после
    старта, следующий POU (TEST_CPM) видел Mode = 2 и своим f_done добивал его
    до 3, а набор 8080 не выполнялся ни разу (Pass = 0, Fail = 0, Idx = 0).
    Правильно: SEL(f_hand, Mode, 2) - при f_hand TRUE результат 2, иначе Mode.
    """
    return SEL(n, I(n, u"f_hand"), I(n, u"GVL_TEST.Mode"), I(n, B % 2),
               fbd_xml.COL_BLK + 1500)


def LT(n, a, b, x=None, y=None):
    return n.block(u"LT", [(u"IN1", a), (u"IN2", b)], [u"OUT"],
                   fbd_xml.COL_BLK if x is None else x, y)


def AND3(n, a, b, c, x=None, y=None):
    u"""AND с ТРЕМЯ входами (в pou_cpm_defs.py есть только двухвходовый)."""
    ab = AND(n, a, b, x, y)
    return AND(n, ab, c, fbd_xml.COL_BLK if x is None else x + 130, y)


ALL = (make_test_8080,)
