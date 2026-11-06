# -*- coding: utf-8 -*-
u"""PLC_PRG_CPM - главная программа эмулятора с CP/M (порядок исполнения).

ПОРЯДОК СЕТЕЙ (= порядок исполнения в скане):
  1. FB_CPM_MemInit  - заполнение страницы нуля, таблицы BIOS, ловушек, DPB,
                       каталога диска и тестовой программы в TPA (один раз);
  2. включение процессора: GVL_CPU.Enable := GVL_CPM.CPU_Run;
  3. FB_CPU8080_FULL - один такт 8080 за скан + порт CP/M: процессор выкладывает
                       регистры в GVL_CPM.Reg_* и применяет запись регистров,
                       которую сделал слой CP/M на прошлом скане;
  4. FB_CPM_Trap     - распознаёт попадание PC на ловушку (0F000h, 0FE00h+3*i,
                       0F100h), снимает адрес возврата со стека, гасит процессор
                       на время операции и возвращает регистры, когда диспетчер
                       выставит квитанцию Func_Done;
  5. FB_BDOS / FB_BIOS / FB_CCP - диспетчеры выполняют вызванную функцию.

Ключевая деталь: и трап, и диспетчеры работают В ТОМ ЖЕ СКАНЕ, что и такт
процессора, поэтому CP/M-вызов не тратит лишний такт: программа видит возврат
из BDOS ровно так же, как на настоящей машине (только медленнее).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import I, NOT, AND, OR, ORL, EQ, GT, SEL, IF, ADD, MOD, CHAIN, H, W, B
import pou_cpm_defs as D

PUBLISH = (
    (u"CPM_A", u"GVL_CPM.Reg_A"),
    (u"CPM_B", u"GVL_CPM.Reg_B"),
    (u"CPM_C", u"GVL_CPM.Reg_C"),
    (u"CPM_D", u"GVL_CPM.Reg_D"),
    (u"CPM_E", u"GVL_CPM.Reg_E"),
    (u"CPM_H", u"GVL_CPM.Reg_H"),
    (u"CPM_L", u"GVL_CPM.Reg_L"),
    (u"CPM_PC", u"GVL_CPM.Reg_PC"),
    (u"CPM_SP", u"GVL_CPM.Reg_SP"),
    (u"CPM_PSW", u"GVL_CPM.Reg_PSW"),
)


# Последовательность команд CP/M: DIR + CR, затем TYPE README.TXT + CR
CMD_SEQ = ([0x44, 0x49, 0x52, 0x0D]
           + [ord(c) for c in u"TYPE README.TXT"] + [0x0D])


def make_plc_prg_cpm():
    p = Pou(u"PLC_PRG_CPM", u"program",
            doc=u"Главная программа эмулятора CP/M: инициализация, такт процессора,\n"
                u"\tтрап и диспетчеры BDOS/BIOS/CCP. Один скан PLC = один такт 8080\n"
                u"\t(плюс обработка трапа, если PC попал на точку входа CP/M).\n"
                u"\tРегистры процессора для слоя CP/M берутся с порта CP/M блока\n"
                u"\tFB_CPU8080_FULL и публикуются в GVL_CPM (Reg_A..Reg_PSW).")
    p.var(u"cpu", u"FB_CPU8080_FULL", u"процессор 8080 с портом доступа CP/M")
    p.var(u"init", u"FB_CPM_MemInit", u"инициализация памяти и таблиц CP/M")
    p.var(u"trap", u"FB_CPM_Trap", u"ловушка CP/M")
    p.var(u"bdos", u"FB_BDOS", u"диспетчер BDOS (28 функций)")
    p.var(u"bios", u"FB_BIOS", u"диспетчер BIOS (17 функций)")
    p.var(u"ccp", u"FB_CCP", u"CCP (заглушка этапа 3.2)")
    p.var(u"cpu_en", u"BOOL", u"процессор выполняет такт (нет трапа)")
    p.var(u"cpu_halted", u"BOOL", u"процессор остановлен командой HLT")
    p.var(u"cpu_step", u"WORD", u"номер выполненного такта")
    p.var(u"dbg_k", u"UDINT", u"опыт: счётчик сканов подачи")
    p.var(u"dbg_i", u"UDINT", u"опыт: номер знака")
    p.var(u"dbg_adv", u"BOOL", u"опыт: пора сменить знак")
    p.var(u"cmd_go", u"BOOL", u"подача команд CP/M активна")
    p.var(u"cmd_rdy", u"BOOL", u"знак был выставлен")
    p.var(u"cmd_taken", u"BOOL", u"CCP принял знак")
    p.var(u"cmd_k", u"UDINT", u"номер поданного знака")

    n = p.network(u"СЕТЬ 1. Инициализация памяти CP/M (страница нуля, таблицы, диск)")
    # ФАЗА B: пока идёт набор 8080, инициализация памяти CP/M ОТКЛЮЧЕНА.
    # Иначе FB_CPM_MemInit (работающий, пока GVL_CPM.Init_Done = FALSE) каждый
    # скан перезаписывает нулевую страницу и таблицы, и предустановки тестов в
    # области 0..FFh стираются до чтения. Симптом был отчётливый: LDA 0000h и
    # MOV A,M при HL=0000 читали C3h (опкод JMP нулевой страницы CP/M) вместо
    # значения, которое тест туда положил.
    test8080_active_init = AND(n, EQ(n, I(n, u"GVL_TEST.Mode"), I(n, B % 1),
                                   fbd_xml.COL_BLK + 200),
                               NOT(n, I(n, u"GVL_TEST.Done8080"),
                                   fbd_xml.COL_BLK + 330),
                               fbd_xml.COL_BLK + 460)
    n.block(u"FB_CPM_MemInit",
            [(u"Enable", NOT(n, test8080_active_init, fbd_xml.COL_BLK + 590))],
            [u"Done"], instance=u"init")

    n = p.network(u"СЕТЬ 2. Включение процессора: один такт 8080 за скан")
    n.outvar(u"GVL_CPU.Enable", I(n, u"GVL_CPM.CPU_Run"))
    n.outvar(u"cpu_en", AND(n, I(n, u"GVL_CPM.CPU_Run"), I(n, u"GVL_CPM.CPU_Enable"),
                            fbd_xml.COL_BLK + 200))
    cpu = n.block(u"FB_CPU8080_FULL", [
        (u"Enable", I(n, u"cpu_en")),
        (u"CPM_WE", I(n, u"GVL_CPM.CPM_WE")),
        (u"CPM_Sel1", I(n, u"GVL_CPM.CPM_Sel1")),
        (u"CPM_Data1", I(n, u"GVL_CPM.CPM_Data1")),
        (u"CPM_LD1", I(n, u"GVL_CPM.CPM_LD1")),
        (u"CPM_Sel2", I(n, u"GVL_CPM.CPM_Sel2")),
        (u"CPM_Data2", I(n, u"GVL_CPM.CPM_Data2")),
        (u"CPM_LD2", I(n, u"GVL_CPM.CPM_LD2")),
    ], [u"Halted", u"Step", u"CPM_A", u"CPM_B", u"CPM_C", u"CPM_D", u"CPM_E",
        u"CPM_H", u"CPM_L", u"CPM_PC", u"CPM_SP", u"CPM_PSW"],
        instance=u"cpu", x=fbd_xml.COL_BLK + 400)
    # выходы вызова FB защёлкиваются в переменные POU (правило 9.1 журнала)
    n.outvar(u"cpu_halted", cpu.out(u"Halted"))
    n.outvar(u"cpu_step", cpu.out(u"Step"))
    for out, gvl in PUBLISH:
        n.outvar(gvl, cpu.out(out))

    n = p.network(u"СЕТЬ 3. Ловушка CP/M: распознавание и возврат из функции")
    # АРБИТРАЖ ПРОЦЕССОРА (фаза B). Пока идёт прогон набора тестов 8080, слой
    # CP/M ОТКЛЮЧЁН. Иначе CCP (точка входа 0F100h сама является ловушкой)
    # занимает процессор НЕПРЕРЫВНО: автомат трапов почти всегда находится вне
    # фазы WORK, CPU_Enable (= f_wk) почти всегда FALSE, тестовая схема не
    # получает ни одного такта - и весь набор из 199 кейсов остаётся FAIL
    # (наблюдалось: Pass=0, Fail=0, Idx=0, Con_Log растёт без остановки).
    # Как только набор 8080 завершён (GVL_TEST.Done8080), трап включается и
    # CP/M работает штатно - в том числе в режимах тестов CP/M и ввода-вывода.
    test8080_active = AND(n, EQ(n, I(n, u"GVL_TEST.Mode"), I(n, B % 1),
                                fbd_xml.COL_BLK + 200),
                          NOT(n, I(n, u"GVL_TEST.Done8080"), fbd_xml.COL_BLK + 330),
                          fbd_xml.COL_BLK + 460)
    n.block(u"FB_CPM_Trap",
            [(u"Enable", NOT(n, test8080_active, fbd_xml.COL_BLK + 590))],
            [u"Trap_Active"], instance=u"trap")

    n = p.network(u"СЕТЬ 4. Диспетчеры: выполнение вызванной функции CP/M")
    n.block(u"FB_BDOS", [(u"Start", I(n, u"GVL_CPM.Trap_BDOS"))], [u"Done"],
            instance=u"bdos")
    n.block(u"FB_BIOS", [(u"Start", I(n, u"GVL_CPM.Trap_BIOS"))], [u"Done"],
            instance=u"bios", x=fbd_xml.COL_BLK + 200)
    # CCP ЗАПУСКАЕТСЯ ПО САМОМУ PC, А НЕ ТОЛЬКО ПО TRAP_CCP (фаза B).
    # Замер: Reg_PC = 0F100h (точка входа CCP) держится в окне CP/M десятки
    # сканов, а Trap_CCP НИ РАЗУ не становится TRUE - автомат трапа входит в
    # фазу TRAP всего на 1-4 скана, и в этот момент PC ещё не равен 0F100h
    # (гонка фаз). Пока CCP вызывался только по Trap_CCP, он не исполнялся
    # вовсе: CCP_Phase = 0, журнал консоли пуст, каталог не печатался.
    # Теперь Enable CCP = "PC стоит на точке входа CCP" ИЛИ Trap_CCP.
    # CCP сам сообщает трапу о готовности квитанцией Func_Done (done_gate).
    ccp_en = ORL(n, [I(n, u"GVL_CPM.Trap_CCP"),
                     EQ(n, I(n, u"GVL_CPM.Reg_PC"), I(n, W % D.CCP_ENTRY),
                        fbd_xml.COL_BLK + 520)],
                 x0=fbd_xml.COL_BLK + 580)
    n.block(u"FB_CCP", [(u"Enable", ccp_en)], [u"Done"],
            instance=u"ccp", x=fbd_xml.COL_BLK + 400)
    # ------------------------------------------------------------------
    # ЖУРНАЛ КОНСОЛИ CP/M.
    #
    # Замеры: чтение Con_Log[k] работает; БЕЗУСЛОВНАЯ запись Con_Log[0]
    # работает (проверено: 41h в байте 0); УСЛОВНАЯ запись, где индекс
    # считался в одной сети и использовался в другой, не срабатывала -
    # значение переменной POU видно только на следующем скане.
    # Поэтому здесь индекс ВЫЧИСЛЯЕТСЯ ВНУТРИ КАЖДОГО УСЛОВИЯ (одна
    # сеть = условие + запись), а все чтения идут прямо из GVL:
    #   idx = (Con_Log_Len - 1) MOD 256 - счётчик длины ведут сами
    #   источники консоли (emit_char BIOS/CCP), в этом блоке он НЕ
    #   инкрементируется, поэтому задержка одинакова для всех величин.
    # ------------------------------------------------------------------
    for bank in range(8):
        n = p.network(u"СЕТЬ %d. Журнал консоли: индексы %d..%d"
                       % (10 + bank, bank * 32, bank * 32 + 31))
        idx_expr = MOD(n, ADD(n, I(n, u"GVL_CPM.Con_Log_Len"),
                             I(n, u"INT#255"), fbd_xml.COL_BLK + 60),
                        I(n, u"INT#256"), fbd_xml.COL_BLK + 120)
        for k in range(bank * 32, bank * 32 + 32):
            e = u"GVL_CPM.Con_Log[%d]" % k
            hit = AND(n, I(n, u"GVL_CPM.LogWr"),
                      EQ(n, idx_expr, I(n, u"INT#%d" % k),
                         x=fbd_xml.COL_BLK + 130 * (k % 8), y=40 + 30 * (k % 32)),
                      x=fbd_xml.COL_BLK + 1100 + 130 * (k % 8),
                      y=40 + 30 * (k % 32))
            n.outvar(e, SEL(n, hit, I(n, e), I(n, u"GVL_CPM.LogCh"),
                            x=fbd_xml.COL_BLK + 2100 + 130 * (k % 8),
                            y=40 + 30 * (k % 32)))

    return p


ALL = (make_plc_prg_cpm,)
