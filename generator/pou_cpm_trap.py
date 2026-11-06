# -*- coding: utf-8 -*-
u"""Ловушки CP/M: FB_CPM_Trap, инициализация памяти FB_CPM_MemInit, заглушка CCP.

ИДЕЯ ТРАПА (HLE - high level emulation).
  В эмулируемой памяти по адресам CP/M лежат НАСТОЯЩИЕ команды перехода:
    0000h : JMP 0E003h   - вектор RST 0 -> WBOOT BIOS
    0005h : JMP 0F000h   - точка входа BDOS
    0008h : JMP 0F000h   - вектор RST 1 (BDOS)
    E000h : 17 записей по 3 байта, i-я = JMP (0FE00h + 3*i)
  Поэтому программа CP/M работает как обычно: CALL 0005h попадает на JMP,
  процессор выполняет его и PC оказывается на адресе-ловушке. Тут включается
  FB_CPM_Trap: он видит PC, равный адресу ловушки, останавливает процессор,
  снимает со стека адрес возврата, отдаёт управление диспетчеру BDOS/BIOS/CCP
  и после его квитанции пишет регистры (A, H, L, PC, SP) через порт CP/M
  процессора. Процессор продолжает работу с адреса возврата.

АВТОМАТ (поле GVL_CPM.Trap_Phase):
  0 - старт: PC := 0100h (точка входа TPA);        1 - старт: SP := 0F200h;
  8 - рабочий режим: ждём PC на адресе ловушки;
  3 - трап: диспетчер выполняет функцию (может занять много сканов);
  4 - запись A результата;  5 - запись H;  6 - запись L;
  7 - запись PC (адрес возврата) и SP (SP+2);      9 - снятие трапа -> 8.
Запись регистров процессор применяет на СЛЕДУЮЩЕМ скане (он вызывается первым
и читает GVL_CPM.CPM_*), поэтому каждая фаза занимает ровно один скан.

Почему возврат не сразу: пока трап активен, CPU_Enable = FALSE, процессор не
выполняет тактов и регистры стабильны. Это ровно то поведение, которое
описано в docs/04_ПЛАН_CPM.md (раздел 7): длинная операция BIOS/BDOS ждёт,
процессор стоит.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
import pou_cpm_defs as D
import pou_demo
from pou_cpm_defs import (I, K, NOT, AND, OR, EQ, NE, IF, SEL, ADD, SHL, SHR, W2B,
                          ORL, ANDL, CHAIN, latch, B, H, W, WH, U1)

# фазы автомата трапа
PH_PC = 0
PH_SP = 1
PH_TRAP = 3
PH_WA = 4
PH_WH = 5
PH_WL = 6
PH_WPC = 7
PH_WORK = 8
PH_OFF = 9


def make_cpm_trap():
    p = Pou(u"FB_CPM_Trap", u"functionBlock",
            doc=u"Ловушка CP/M: распознавание попадания PC на адрес ловушки,\n"
                u"\tснятие адреса возврата со стека и запись регистров результата.\n"
                u"\tВходов нет: всё состояние - в GVL_CPM (PC, SP, регистры приходят\n"
                u"\tс порта CP/M процессора, вызовы функций - через Trap_BDOS/BIOS/CCP).\n"
                u"\tВыходы (через GVL_CPM): Trap_*, CPU_Enable, Ret_Addr, Ret_SP,\n"
                u"\tCPM_WE/CPM_Sel1..2/CPM_Data1..2/CPM_LD1..2 - порт записи регистров.\n"
                u"\tПорядок такта: процессор -> этот блок -> диспетчер функции ->\n"
                u"\tна следующем скане запись регистров -> возврат к адресу со стека.")
    p.var_in(u"Enable", u"BOOL", u"работа трапа разрешена (обычно TRUE)")
    p.var_out(u"Trap_Active", u"BOOL", u"трап обрабатывается, процессор остановлен")
    loc = (
        (u"ph", u"BYTE", u"фаза автомата трапа"),
    (u"init_pending", u"BOOL", u"нужен повторный старт: трап был выключен"),
        (u"pc", u"WORD", u"текущий PC процессора"),
        (u"sp", u"WORD", u"текущий SP процессора"),
        (u"is_bdos", u"BOOL", u"PC на точке входа BDOS"),
        (u"is_ccp", u"BOOL", u"PC на точке входа CCP"),
        (u"is_bios", u"BOOL", u"PC на точке входа функции BIOS"),
        (u"bios_num", u"BYTE", u"номер функции BIOS 0..16"),
        (u"trap_here", u"BOOL", u"PC стоит на любой из ловушек"),
        (u"func_done", u"BOOL", u"диспетчер сообщил о выполнении функции"),
        (u"ra_lo", u"BYTE", u"младший байт адреса возврата со стека"),
        (u"ra_hi", u"BYTE", u"старший байт адреса возврата со стека"),
        (u"ra_lo_w", u"WORD", u"младший байт как слово"),
        (u"ra_hi_w", u"WORD", u"старший байт как слово"),
        (u"rh_w", u"WORD", u"Reg_H, расширенный до слова (для сдвига на 8)"),
        (u"ret_addr", u"WORD", u"адрес возврата"),
        (u"ret_sp", u"WORD", u"SP после снятия адреса возврата"),
        (u"a_w", u"WORD", u"значение, возвращаемое в A (как слово)"),
        (u"hl_hi", u"BYTE", u"старший байт возвращаемого HL"),
        (u"hl_hi_w", u"WORD", u"старший байт HL как слово"),
        (u"hl_lo", u"BYTE", u"младший байт возвращаемого HL"),
        (u"hl_lo_w", u"WORD", u"младший байт HL как слово"),
        (u"hl_cur", u"WORD", u"текущая пара HL процессора"),
        (u"hl_eff", u"WORD", u"что писать в HL: результат функции или текущий HL"),
        (u"jp_pc", u"WORD", u"адрес возврата с учётом Jump_Req"),
        (u"jp_sp", u"WORD", u"SP с учётом Jump_Req"),
        (u"wb", u"BOOL", u"идёт запись регистров результата"),
        (u"we", u"BOOL", u"разрешение порта записи регистров"),
        (u"sel1", u"BYTE", u"номер регистра, канал 1"),
        (u"data1", u"WORD", u"значение, канал 1"),
        (u"sel2", u"BYTE", u"номер регистра, канал 2"),
        (u"data2", u"WORD", u"значение, канал 2"),
        (u"trap_cnt_inc", u"UDINT", u"единица для счётчика трапов"),
    )
    for nm, t, c in loc:
        p.var(nm, t, c)
    # признаки отдельных фаз (нужны и в переходах, и в выборе значений)
    phn = (u"f_pc", u"f_sp", u"f_tr", u"f_wa", u"f_wh", u"f_wl", u"f_wpc",
           u"f_wk", u"f_off")
    for nm in phn:
        p.var(nm, u"BOOL", u"фаза автомата")

    # ==================================================================
    n = p.network(u"СЕТЬ 1. ЧТЕНИЕ PC/SP, РАСПОЗНАВАНИЕ ЛОВУШЕК, АДРЕС ВОЗВРАТА")
    n.outvar(u"pc", I(n, u"GVL_CPM.Reg_PC"))
    n.outvar(u"sp", I(n, u"GVL_CPM.Reg_SP"))
    n.outvar(u"is_bdos", EQ(n, I(n, u"pc"), I(n, W % D.BDOS_ENTRY)))
    n.outvar(u"is_ccp", EQ(n, I(n, u"pc"), I(n, W % D.CCP_ENTRY),
                           fbd_xml.COL_BLK + 140))
    # 17 адресов функций BIOS: PC == 0FE00h + 3*i. Сравнения дают и признак,
    # и номер функции - деление на 3 в схеме не нужно.
    hits = []
    for i in range(D.BIOS_COUNT):
        hits.append(EQ(n, I(n, u"pc"), I(n, W % (D.BIOS_TRAP + 3 * i)),
                       fbd_xml.COL_BLK + 280 + 80 * (i % 8), 40 + 30 * i))
    n.outvar(u"is_bios", ORL(n, hits, x0=fbd_xml.COL_BLK + 900))
    n.outvar(u"bios_num", CHAIN(n, I(n, B % 0),
                                [(hits[i], I(n, B % i)) for i in range(D.BIOS_COUNT)],
                                x0=fbd_xml.COL_BLK + 900))
    n.outvar(u"trap_here", ORL(n, [I(n, u"is_bdos"), I(n, u"is_bios"), I(n, u"is_ccp")],
                               x0=fbd_xml.COL_BLK + 1400))
    n.outvar(u"func_done", I(n, u"GVL_CPM.Func_Done"))
    # адрес возврата лежит на вершине стека: CP/M-программа вызвала BDOS
    # командой CALL, поэтому снимаем два байта и увеличиваем SP на 2
    n.outvar(u"ra_lo", I(n, u"GVL_MEM.Memory[sp]"))
    n.outvar(u"ra_hi", I(n, u"GVL_MEM.Memory[sp + 1]"))
    n.outvar(u"ra_lo_w", I(n, u"ra_lo"))
    n.outvar(u"ra_hi_w", I(n, u"ra_hi"))
    n.outvar(u"ret_addr", OR(n, SHL(n, I(n, u"ra_hi_w"), I(n, W % 8),
                                    fbd_xml.COL_BLK + 400), I(n, u"ra_lo_w"),
                             fbd_xml.COL_BLK + 520))
    n.outvar(u"ret_sp", ADD(n, I(n, u"sp"), I(n, W % 2), fbd_xml.COL_BLK + 640))
    # значения, которые вернёт функция: A (младший байт) и HL.
    # HL пишется только тогда, когда функция явно вернула его (Ret_HL_En):
    # настоящий BDOS сохраняет HL у большинства функций, и программы CP/M
    # на это рассчитывают.
    # ВНИМАНИЕ: Reg_H - это BYTE. Сдвигать BYTE на 8 нельзя (CODESYS:
    # Warning C308 "Сдвиг на 8 превышает размер типа BYTE", а результат теряет
    # старший байт и даёт ещё и C32 'BYTE' -> 'BOOL'). Поэтому, как и в ядре,
    # байт сначала переносится в переменную WORD (rh_w), и только потом SHL.
    n.outvar(u"rh_w", I(n, u"GVL_CPM.Reg_H"))
    n.outvar(u"hl_cur", OR(n, SHL(n, I(n, u"rh_w"), I(n, W % 8),
                                 fbd_xml.COL_BLK + 700),
                           I(n, u"GVL_CPM.Reg_L"), fbd_xml.COL_BLK + 820))
    n.outvar(u"hl_eff", SEL(n, I(n, u"GVL_CPM.Ret_HL_En"), I(n, u"hl_cur"),
                            I(n, u"GVL_CPM.Ret_HL"), fbd_xml.COL_BLK + 940))
    n.outvar(u"a_w", I(n, u"GVL_CPM.Ret_Val"))
    # Старший байт HL: сдвиг ВПРАВО на 8 внутри WORD даёт ровно старший байт.
    # Раньше здесь стоял сдвиг ВЛЕВО на 8 (C0308: превышает размер WORD) -
    # он всегда давал 0, то есть старший байт HL возвращался нулевым, и любой
    # .COM, ожидающий адрес в HL, получал младший байт с нулём сверху.
    n.outvar(u"hl_hi", W2B(n, SHR(n, I(n, u"hl_eff"), I(n, W % 8),
                                  fbd_xml.COL_BLK + 1060), fbd_xml.COL_BLK + 1180))
    n.outvar(u"hl_hi_w", I(n, u"hl_hi"))
    n.outvar(u"hl_lo", W2B(n, I(n, u"hl_eff"), fbd_xml.COL_BLK + 1300))
    n.outvar(u"hl_lo_w", I(n, u"hl_lo"))
    # возврат по адресу со стека - или туда, куда попросила функция
    # (WBOOT перезагружает CCP, загрузчик .COM запускает программу)
    n.outvar(u"jp_pc", SEL(n, I(n, u"GVL_CPM.Jump_Req"), I(n, u"ret_addr"),
                           I(n, u"GVL_CPM.Jump_PC"), fbd_xml.COL_BLK + 1120))
    n.outvar(u"jp_sp", SEL(n, I(n, u"GVL_CPM.Jump_Req"), I(n, u"ret_sp"),
                           I(n, u"GVL_CPM.Jump_SP"), fbd_xml.COL_BLK + 1240))

    # ==================================================================
    n = p.network(u"СЕТЬ 2. АВТОМАТ ТРАПА: фазы, порт записи регистров, публикация")
    for k, (nm, code) in enumerate(zip(phn, (PH_PC, PH_SP, PH_TRAP, PH_WA, PH_WH,
                                             PH_WL, PH_WPC, PH_WORK, PH_OFF))):
        n.outvar(nm, EQ(n, I(n, u"ph"), I(n, B % code),
                        fbd_xml.COL_BLK + 130 + 130 * k))
    n.outvar(u"GVL_CPM.Trap_Phase", I(n, u"ph"))
    n.outvar(u"ph", CHAIN(n, I(n, u"ph"), [
        (I(n, u"f_pc"), I(n, B % PH_SP)),
        (I(n, u"f_sp"), I(n, B % PH_WORK)),
        (AND(n, I(n, u"f_wk"), I(n, u"trap_here")), I(n, B % PH_TRAP)),
        (AND(n, I(n, u"f_tr"), I(n, u"func_done")), I(n, B % PH_WA)),
        # ВЫХОД ИЗ TRAP БЕЗ ДИСПЕТЧЕРА (фаза B). Если PC не совпал ни с одной
        # точкой входа (trap_here = FALSE), ни BDOS, ни BIOS, ни CCP НЕ
        # вызовутся, квитанция Func_Done не придёт никогда, и трап навсегда
        # останется в фазе TRAP. Тогда CPU_Enable (= f_wk) навсегда FALSE,
        # процессор не тактируется (наблюдалось: Reg_PC = 0, Step_Cnt замер
        # на 243, Trap_Phase = 3) - эмулятор мёртв.
        # Теперь такой «висящий» трап возвращается в WORK и отдаёт процессор.
        (AND(n, I(n, u"f_tr"), NOT(n, I(n, u"trap_here"),
                                   fbd_xml.COL_BLK + 3400),
             fbd_xml.COL_BLK + 3500), I(n, B % PH_WORK)),
        (I(n, u"f_wa"), I(n, B % PH_WH)),
        (I(n, u"f_wh"), I(n, B % PH_WL)),
        (I(n, u"f_wl"), I(n, B % PH_WPC)),
        (I(n, u"f_wpc"), I(n, B % PH_OFF)),
        (I(n, u"f_off"), I(n, B % PH_WORK)),
        # АРБИТРАЖ (фаза B). Шаг стоит ПОСЛЕДНИМ, поэтому перекрывает все
        # предыдущие: при Enable = FALSE автомат трапа принудительно в фазе
        # WORK. Это нужно, чтобы ОТКЛЮЧЁННЫЙ трап:
        #   * не выполнял стартовые записи PC := 0F100h и SP (иначе он всё
        #     равно уводил бы процессор в CCP - проверено, гейт только на
        #     Enable у вызова этого не предотвращал);
        #   * не выставлял Trap_Active, иначе тестовая схема считала бы, что
        #     процессор занят, и не начинала прогон;
        #   * оставлял CPU_Enable = f_wk = TRUE, чтобы процессор мог работать
        #     под управлением теста.
        (NOT(n, I(n, u"Enable")), I(n, B % PH_WORK)),
        # ВОЗВРАТ В НАЧАЛО ПРИ ВКЛЮЧЕНИИ (фаза B). Пока трап был выключен на
        # время набора 8080, автомат удерживался в фазе WORK. Когда набор
        # заканчивается и трап включается, он ОБЯЗАН пройти стартовые фазы
        # заново (PC := 0F100h и SP := 0F200h), иначе CCP не запускается
        # вообще: наблюдалось CCP_Phase = 0, CCP_Cnt = 0, Con_Log_Len = 0 при
        # Disk_Ready = TRUE и Dir_Used = 4 - то есть диск загружен, а
        # консольный процессор даже не начал работу, и все проверки CP/M
        # оставались FAIL.
        # ВНИМАНИЕ: AND здесь ДВУХвходовый (pou_cpm_defs), поэтому условие
        # собрано в два шага, а не одним вызовом с тремя аргументами.
        (AND(n, I(n, u"Enable"),
             AND(n, I(n, u"f_wk"), I(n, u"init_pending"),
                 fbd_xml.COL_BLK + 3300),
             fbd_xml.COL_BLK + 3400), I(n, B % PH_PC)),
    ]))
    # ВЗВЕДЕНИЕ "НУЖЕН СТАРТ" (фаза B). Взводится, пока трап ВЫКЛЮЧЕН
    # (idle на время набора 8080), и сбрасывается в том скане, когда трап
    # включился и старт перехвачен переходом в PH_PC. Без отдельного сброса
    # условие оставалось бы истинным и после старта, зацикливая автомат.
    # ПЕРЕНОС (фаза B): init_pending пишется ОТДЕЛЬНОЙ сетью ПОСЛЕ автомата.
    # В одной сети с ph переменные f_tr/f_wk читались бы в СТАРОМ значении
    # (они тоже пишутся этой сетью), и условие восстановления никогда не
    # выполнялось. Теперь порядок: сеть 2 (автомат) -> сеть 2Б (init_pending).
    n2 = p.network(u"СЕТЬ 2Б (ПОРТ CP/M). Признак необходимости повторного старта")
    _need = ORL(n2, [NOT(n2, I(n2, u"Enable"), fbd_xml.COL_BLK + 100),
                     AND(n2, I(n2, u"f_tr"),
                         NOT(n2, I(n2, u"trap_here"), fbd_xml.COL_BLK + 200),
                         fbd_xml.COL_BLK + 300)],
                x0=fbd_xml.COL_BLK + 400)
    n2.outvar(u"init_pending",
              IF(n2, AND(n2, I(n2, u"Enable"), I(n2, u"f_wk"),
                         fbd_xml.COL_BLK + 600),
                 I(n2, u"FALSE"), _need, fbd_xml.COL_BLK + 700),
              x=fbd_xml.COL_BLK + 800)
    p.networks.remove(n2)
    p.networks.insert(2, n2)
    # --- строб записи: фазы старта и записи результата ---
    n.outvar(u"wb", ORL(n, [I(n, u"f_wa"), I(n, u"f_wh"), I(n, u"f_wl"),
                            I(n, u"f_wpc")], x0=fbd_xml.COL_BLK + 200))
    n.outvar(u"we", ORL(n, [I(n, u"f_pc"), I(n, u"f_sp"), I(n, u"wb")],
                        x0=fbd_xml.COL_BLK + 400))
    # --- канал 1: старт PC, затем A, H, L, затем адрес возврата ---
    n.outvar(u"sel1", CHAIN(n, I(n, B % 0), [
        (I(n, u"f_pc"), I(n, B % 7)), (I(n, u"f_wa"), I(n, B % 0)),
        (I(n, u"f_wh"), I(n, B % 5)), (I(n, u"f_wl"), I(n, B % 6)),
        (I(n, u"f_wpc"), I(n, B % 7))], x0=fbd_xml.COL_BLK + 600))
    # Старт системы: PC := 0F100h - точка входа CCP (как после WBOOT в
    # настоящем CP/M). Раньше здесь стояло 0100h: CCP был заглушкой, и в TPA
    # лежала тестовая программа. Теперь программы приходят из образа диска.
    n.outvar(u"data1", CHAIN(n, I(n, W % 0), [
        (I(n, u"f_pc"), I(n, W % D.CCP_ENTRY)), (I(n, u"f_wa"), I(n, u"a_w")),
        (I(n, u"f_wh"), I(n, u"hl_hi_w")), (I(n, u"f_wl"), I(n, u"hl_lo_w")),
        (I(n, u"f_wpc"), I(n, u"jp_pc"))], x0=fbd_xml.COL_BLK + 800))
    # --- канал 2: старт SP и SP при возврате ---
    n.outvar(u"sel2", CHAIN(n, I(n, B % 0), [
        (I(n, u"f_sp"), I(n, B % 8)), (I(n, u"f_wpc"), I(n, B % 8))],
        x0=fbd_xml.COL_BLK + 1000))
    n.outvar(u"data2", CHAIN(n, I(n, W % 0), [
        (I(n, u"f_sp"), I(n, W % D.STACK_TOP)), (I(n, u"f_wpc"), I(n, u"jp_sp"))],
        x0=fbd_xml.COL_BLK + 1200))
    n.outvar(u"GVL_CPM.CPM_WE", I(n, u"we"))
    n.outvar(u"GVL_CPM.CPM_Sel1", I(n, u"sel1"))
    n.outvar(u"GVL_CPM.CPM_Data1", I(n, u"data1"))
    n.outvar(u"GVL_CPM.CPM_LD1", I(n, u"we"))
    n.outvar(u"GVL_CPM.CPM_Sel2", I(n, u"sel2"))
    n.outvar(u"GVL_CPM.CPM_Data2", I(n, u"data2"))
    n.outvar(u"GVL_CPM.CPM_LD2", OR(n, I(n, u"f_sp"), I(n, u"f_wpc"),
                                    fbd_xml.COL_BLK + 1400))
    # --- состояние трапа для диспетчеров и диагностики ---
    n.outvar(u"GVL_CPM.Trap_BDOS", AND(n, I(n, u"f_tr"), I(n, u"is_bdos"),
                                       fbd_xml.COL_BLK + 1600))
    n.outvar(u"GVL_CPM.Trap_BIOS", AND(n, I(n, u"f_tr"), I(n, u"is_bios"),
                                       fbd_xml.COL_BLK + 1700))
    n.outvar(u"GVL_CPM.Trap_CCP", AND(n, I(n, u"f_tr"), I(n, u"is_ccp"),
                                      fbd_xml.COL_BLK + 1800))
    n.outvar(u"GVL_CPM.Trap_Active", ORL(n, [I(n, u"f_tr"), I(n, u"f_wa"),
                                             I(n, u"f_wh"), I(n, u"f_wl"),
                                             I(n, u"f_wpc")],
                                         x0=fbd_xml.COL_BLK + 1900))
    n.outvar(u"GVL_CPM.CPU_Enable", I(n, u"f_wk"))
    n.outvar(u"GVL_CPM.Ret_Addr", I(n, u"ret_addr"))
    n.outvar(u"GVL_CPM.Ret_SP", I(n, u"ret_sp"))
    n.outvar(u"GVL_CPM.BIOS_Func", I(n, u"bios_num"))
    # квитанция "функция вернула HL" снимается в момент обнаружения трапа
    n.outvar(u"GVL_CPM.Ret_HL_En",
             SEL(n, AND(n, I(n, u"f_wk"), I(n, u"trap_here"),
                        fbd_xml.COL_BLK + 1980),
                 I(n, u"GVL_CPM.Ret_HL_En"), I(n, u"FALSE"),
                 fbd_xml.COL_BLK + 2100))
    n.outvar(u"trap_cnt_inc", ADD(n, I(n, u"GVL_CPM.Diag.Trap_Cnt"), I(n, U1),
                                  fbd_xml.COL_BLK + 2100))
    n.outvar(u"GVL_CPM.Diag.Trap_Cnt",
             SEL(n, AND(n, I(n, u"f_wk"), I(n, u"trap_here"),
                        fbd_xml.COL_BLK + 2200),
                 I(n, u"GVL_CPM.Diag.Trap_Cnt"), I(n, u"trap_cnt_inc"),
                 fbd_xml.COL_BLK + 2320))
    # квитанция снимается в конце обработки трапа
    n.outvar(u"GVL_CPM.Func_Done",
             SEL(n, I(n, u"f_off"), I(n, u"GVL_CPM.Func_Done"), I(n, u"FALSE"),
                 fbd_xml.COL_BLK + 2440))
    # запрос нестандартного возврата действует только на один трап
    n.outvar(u"GVL_CPM.Jump_Req",
             SEL(n, I(n, u"f_off"), I(n, u"GVL_CPM.Jump_Req"), I(n, u"FALSE"),
                 fbd_xml.COL_BLK + 2560))
    n.outvar(u"Trap_Active", I(n, u"GVL_CPM.Trap_Active"))
    return p


# ======================================================================
def _dpb_bytes():
    u"""15 байт таблицы параметров диска (DPB) так, как их читает программа."""
    pr = D.DISK_PROFILE
    b = []
    b += [pr[u"SPT"] & 0xFF, (pr[u"SPT"] >> 8) & 0xFF]
    b += [pr[u"BSH"] & 0xFF, pr[u"BLM"] & 0xFF, pr[u"EXM"] & 0xFF]
    b += [pr[u"DSM"] & 0xFF, (pr[u"DSM"] >> 8) & 0xFF]
    b += [pr[u"DRM"] & 0xFF, (pr[u"DRM"] >> 8) & 0xFF]
    b += [pr[u"AL0"] & 0xFF, pr[u"AL1"] & 0xFF]
    b += [pr[u"CKS"] & 0xFF, (pr[u"CKS"] >> 8) & 0xFF]
    b += [pr[u"OFF"] & 0xFF, (pr[u"OFF"] >> 8) & 0xFF]
    return b


def make_mem_init():
    p = Pou(u"FB_CPM_MemInit", u"functionBlock",
            doc=u"Инициализация памяти CP/M 2.2 (выполняется схемой, а не текстом).\n"
                u"\tЗаполняется страница нулевого адреса, таблица переходов BIOS,\n"
                u"\tловушки BDOS/BIOS/CCP, DPB и DPH, каталог диска, битовая карта\n"
                u"\tзанятости блоков, демонстрационные .COM-программы и бутстрап-\n"
                u"\tзаглушка запуска. Постоянные таблицы (страница нуля, таблица\n"
                u"\tBIOS, ловушки, DPB, бутстрап) пишутся КАЖДЫЙ скан - они\n"
                u"\tнеизменяемы, зато схема не зависит от порядка сканов; изменяемые\n"
                u"\tячейки (диск, флаги GVL) - только в первом скане через SEL.")
    p.var_in(u"Enable", u"BOOL", u"выполнять инициализацию (обычно TRUE)")
    p.var(u"notdone", u"BOOL", u"инициализация ещё не выполнена")
    p.var(u"cu_w", u"WORD", u"номер пользователя как слово")
    p.var(u"cd_w", u"WORD", u"номер диска как слово")
    p.var(u"du_w", u"WORD", u"байт 0004h: диск и пользователь")
    p.var(u"du_b", u"BYTE", u"байт 0004h")
    p.var_out(u"Done", u"BOOL", u"инициализация выполнена")

    def wmem(net, addr_expr, val):
        u"""Запись ячейки памяти с гейтом по Enable.

        При Enable = FALSE в память пишется её же текущее значение,
        то есть память НЕ ТРОГАЕТСЯ. Раньше постоянные таблицы
        переписывались каждый скан, и предустановки тестов 8080 в
        области нулевой страницы и TPA затирались до чтения.
        """
        e = u"GVL_MEM.Memory[%s]" % addr_expr
        net.outvar(e, SEL(net, I(net, u"Enable"), I(net, e), val))


    # ---- 1. страница нулевого адреса ----
    n = p.network(u"СЕТЬ 1. Страница нулевого адреса: векторы RST, IOBYTE, JMP BDOS")
    n.outvar(u"notdone", NOT(n, I(n, u"GVL_CPM.Init_Done")))
    n.outvar(u"cu_w", I(n, u"GVL_CPM.CurUser"))
    n.outvar(u"cd_w", I(n, u"GVL_CPM.CurDisk"))
    n.outvar(u"du_w", OR(n, SHL(n, I(n, u"cu_w"), I(n, W % 4),
                               fbd_xml.COL_BLK + 200), I(n, u"cd_w"),
                         fbd_xml.COL_BLK + 320))
    n.outvar(u"du_b", W2B(n, I(n, u"du_w"), fbd_xml.COL_BLK + 440))
    zero = (
        (0x0000, 0xC3), (0x0001, 0x03), (0x0002, 0xE0),
        (0x0005, 0xC3), (0x0006, 0x00), (0x0007, 0xF0),
        (0x0008, 0xC3), (0x0009, 0x00), (0x000A, 0xF0),
        (0x0010, 0xC9), (0x0018, 0xC9), (0x0020, 0xC9),
        (0x0028, 0xC9), (0x0030, 0xC9), (0x0038, 0xC9),
    )
    for addr, val in zero:
        wmem(n, WH % addr, I(n, H % val))
    wmem(n, WH % 0x0003, I(n, u"GVL_CPM.IOBYTE"))
    wmem(n, WH % 0x0004, I(n, u"du_b"))

    # ---- 2. таблица переходов BIOS и ловушки ----
    n = p.network(u"СЕТЬ 2. Таблица переходов BIOS (17*3) и ловушки CP/M")
    for i in range(D.BIOS_COUNT):
        base = D.BIOS_TABLE + 3 * i
        wmem(n, WH % base, I(n, H % 0xC3))
        wmem(n, WH % (base + 1), I(n, H % (3 * i)))
        wmem(n, WH % (base + 2), I(n, H % 0xFE))
        wmem(n, WH % (D.BIOS_TRAP + 3 * i), I(n, H % 0xC9))
    wmem(n, WH % D.BDOS_ENTRY, I(n, H % 0xC9))
    wmem(n, WH % D.CCP_ENTRY, I(n, H % 0xC9))

    # ---- 3. DPB (по профилю диска) и DPH ----
    n = p.network(u"СЕТЬ 3. DPB по профилю диска по адресу %s и DPH по адресу %s"
                  % (WH % D.DPB_ADDR, WH % D.DPH_ADDR))
    for k, v in enumerate(_dpb_bytes()):
        wmem(n, WH % (D.DPB_ADDR + k), I(n, H % v))
    dph = ((0, 0x00), (1, 0x00), (2, 0x00), (3, 0x00), (4, 0x00), (5, 0x00),
           (6, 0x00), (7, 0x00), (8, D.DIRBUF_ADDR & 0xFF),
           (9, (D.DIRBUF_ADDR >> 8) & 0xFF),
           (10, D.DPB_ADDR & 0xFF), (11, (D.DPB_ADDR >> 8) & 0xFF),
           (12, 0x00), (13, 0x00), (14, 0x00), (15, 0x00))
    for off, val in dph:
        wmem(n, WH % (D.DPH_ADDR + off), I(n, H % val))
    for nm, val in ((u"SPT", D.SPT), (u"DSM", D.DSM), (u"DRM", D.DRM),
                    (u"CKS", D.CKS), (u"OFF", D.OFF)):
        n.outvar(u"GVL_DISK.DPB.%s" % nm, I(n, W % val))
    for nm, val in ((u"BSH", D.BSH), (u"BLM", D.BLM), (u"EXM", D.EXM),
                    (u"AL0", D.AL0), (u"AL1", D.AL1)):
        n.outvar(u"GVL_DISK.DPB.%s" % nm, I(n, H % val))

    # ---- 4. образ диска: каталог, файлы, карта занятости, бутстрап ----
    pou_demo.build_image(p, I(n, u"notdone"))

    # ---- 5. разовые состояния GVL ----
    n = p.network(u"СЕТЬ 5. Разовые состояния GVL: DMA, TPA, подсказка "
                  u"размещения, флаг инициализации")
    n.outvar(u"GVL_CPM.DMA", IF(n, I(n, u"notdone"), I(n, W % D.DMA_DEF),
                                I(n, u"GVL_CPM.DMA")))
    n.outvar(u"GVL_CPM.TPA_Top", IF(n, I(n, u"notdone"), I(n, W % D.TPA_TOP),
                                    I(n, u"GVL_CPM.TPA_Top"),
                                    fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.CPU_Run", IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                                    I(n, u"GVL_CPM.CPU_Run"),
                                    fbd_xml.COL_BLK + 400))
    n.outvar(u"GVL_CPM.Next_Block",
             IF(n, I(n, u"notdone"), I(n, H % pou_demo.next_block()),
                I(n, u"GVL_CPM.Next_Block"), fbd_xml.COL_BLK + 600))
    n.outvar(u"GVL_CPM.IOBYTE", IF(n, I(n, u"notdone"), I(n, H % 0x3D),
                                   I(n, u"GVL_CPM.IOBYTE"),
                                   fbd_xml.COL_BLK + 800))
    n.outvar(u"GVL_CPM.Search_Idx", IF(n, I(n, u"notdone"), I(n, W % 0),
                                       I(n, u"GVL_CPM.Search_Idx"),
                                       fbd_xml.COL_BLK + 1000))
    n.outvar(u"GVL_CPM.CurUser", IF(n, I(n, u"notdone"), I(n, H % 0),
                                    I(n, u"GVL_CPM.CurUser"),
                                    fbd_xml.COL_BLK + 1200))
    n.outvar(u"GVL_CPM.CCP_Cnt", IF(n, I(n, u"notdone"), I(n, u"UDINT#0"),
                                    I(n, u"GVL_CPM.CCP_Cnt"),
                                    fbd_xml.COL_BLK + 1400))
    n.outvar(u"GVL_DISK.Disk_Ready", IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                                        I(n, u"GVL_DISK.Disk_Ready"),
                                        fbd_xml.COL_BLK + 1600))
    n.outvar(u"GVL_DISK.Dir_Used", IF(n, I(n, u"notdone"),
                                      I(n, W % pou_demo.dir_used()),
                                      I(n, u"GVL_DISK.Dir_Used"),
                                      fbd_xml.COL_BLK + 1800))
    n.outvar(u"GVL_CPM.Init_Done", I(n, u"TRUE"))
    n.outvar(u"Done", I(n, u"notdone"))
    return p


ALL = (make_cpm_trap, make_mem_init)
NAMES = (u"FB_CPM_Trap", u"FB_CPM_MemInit")
