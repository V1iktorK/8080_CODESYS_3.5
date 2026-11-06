# -*- coding: utf-8 -*-
u"""Этап 3.6: АДАПТЕР C - реальный ПЛК (физические модули ввода-вывода).

ВНИМАНИЕ: ЭТОТ POU НЕ ВХОДИТ В ОСНОВНУЮ СБОРКУ (его не импортирует gen_cpm.py).
Причина честная: в этой установке CODESYS Control Win V3 нет устройства с
физическими модулями ввода-вывода, поэтому адреса %IB/%QB/%IW/%QW нечем связать,
и компиляция AT-объявлений может дать ошибку. Чтобы основная сборка (профили A/B)
не зависела от этого, адаптер живёт отдельным модулем и проверяется отдельной
пробой gen_probe_hw.py; её результат (сообщения компилятора) идёт в отчёт как есть.

ИНТЕРФЕЙС ОДИНАКОВ С FB_IO_Adapter_Sim / FB_IO_Adapter_SoftPLC:
    En, RW, Kind, Index, WData, Invert, Num, Den -> RData, Fault, Overflow
Поэтому смена профиля - замена ОДНОЙ константы ADAPTER_TYPE в pou_io_defs.py
(плюс импорт этого POU вместо Sim). Прикладной код (ядро 8080, трапы, главная
программа) не меняется вообще.

ГДЕ ЛЕЖАТ AT-АДРЕСА. Физические адреса объявлены не в самом блоке, а в отдельной
GVL (GVL_IO_HW, функция gvl_io_hw_text), потому что:
  * объявление GVL задаётся ТЕКСТОМ через scripting API - значит это настоящее
    объявление `X_IB AT %IB0 : ARRAY[0..7] OF BYTE;`, а не комментарий;
  * в PLCopenXML адрес переменной структурно не передаётся (генератор fbd_xml
    умеет только имя и тип), и `AT` в текстовом дубле интерфейса мог бы не
    попасть в компиляцию - проба потеряла бы смысл.

КАК УСТРОЕНА ПРИВЯЗКА:
  * дискретные входы  - байты %IB0..%IB7: канал k -> байт k/8, бит k%8;
  * дискретные выходы - байты %QB0..%QB7, запись ЧТЕНИЕ-ИЗМЕНЕНИЕ-ЗАПИСЬ,
    иначе один канал затирал бы соседей по байту;
  * аналоговые входы  - слова %IW0..%IW15, аналоговые выходы - %QW0..%QW15;
  * GVL_IO.DI/AI/DO/AO в профиле C работают ЗЕРКАЛОМ физических каналов, чтобы
    HMI и диагностика видели то же, что ушло в железо.
Масштабирование аналога НЕ дублируется: адаптер перекладывает слово модуля в
GVL_IO.AI и вызывает те же FB_IO_AnalogIn / FB_IO_AnalogOut, что профили A и B.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, NOT, AND, OR, EQ, NE, GE, LE, SEL, IF, ORL, ANDL,
                          ADD, SHL, SHR, MOD, B, H)
from pou_io_defs import LIMIT, DIV, XOR, B2I, I2B, I2D, D2I, D2B
from pou_io import ADAPTER_PINS_IN, ADAPTER_PINS_OUT

GVL_IO_HW = u"""VAR_GLOBAL
\t(* ================================================================ *)
\t(* АДАПТЕР C (реальный ПЛК): ФИЗИЧЕСКИЕ АДРЕСА МОДУЛЕЙ ВВОДА-ВЫВОДА  *)
\t(* Используется ТОЛЬКО адаптером FB_IO_Adapter_HW (не входит в        *)
\t(* основную сборку). Адреса - стандартные для CODESYS: %IB/%QB -      *)
\t(* дискретные (по байтам), %IW/%QW - аналоговые (по словам).          *)
\t(* В этой установке устройства с модулями I/O НЕТ, поэтому связывать  *)
\t(* эти адреса не с чем (см. gen_probe_hw.py).                         *)
\t(* ================================================================ *)
\tX_IB AT %IB0 : ARRAY[0..7] OF BYTE;   (* 64 дискретных входа *)
\tX_QB AT %QB0 : ARRAY[0..7] OF BYTE;   (* 64 дискретных выхода *)
\tX_IW AT %IW0 : ARRAY[0..15] OF WORD;  (* 16 аналоговых входов *)
\tX_QW AT %QW0 : ARRAY[0..15] OF WORD;  (* 16 аналоговых выходов *)
END_VAR
"""


def gvl_io_hw_text():
    u"""Объявление GVL_IO_HW: физические адреса адаптера C (AT %IB0 и т.д.)."""
    return GVL_IO_HW


def make_adapter_hw():
    p = Pou(u"FB_IO_Adapter_HW", u"functionBlock",
            doc=u"АДАПТЕР C (реальный ПЛК): каналы - физические модули I/O.\n"
                u"\tАдреса объявлены в GVL_IO_HW: %IB0/%QB0 (дискретные, по 8 байт),\n"
                u"\t%IW0/%QW0 (аналоговые, по 16 слов). Интерфейс блока совпадает с\n"
                u"\tFB_IO_Adapter_Sim / _SoftPLC - прикладной код не меняется.\n"
                u"\tДискретное чтение: канал k -> байт k/8, бит k%8.\n"
                u"\tДискретная запись: чтение-изменение-запись байта.\n"
                u"\tЭтот POU НЕ входит в основную сборку: в установке нет устройства\n"
                u"\tс модулями ввода-вывода, AT-адреса нечем связать (см. gen_probe_hw.py).")
    for nm, t, c in ADAPTER_PINS_IN:
        p.var_in(nm, t, c)
    for nm, t, c in ADAPTER_PINS_OUT:
        p.var_out(nm, t, c)

    p.var(u"is_di", u"BOOL", u"вид канала - дискретный вход")
    p.var(u"is_do", u"BOOL", u"вид канала - дискретный выход")
    p.var(u"is_ai", u"BOOL", u"вид канала - аналоговый вход")
    p.var(u"is_ao", u"BOOL", u"вид канала - аналоговый выход")
    p.var(u"g_in", u"BOOL", u"идёт ввод (IN)")
    p.var(u"g_out", u"BOOL", u"идёт вывод (OUT)")
    p.var(u"ok", u"BOOL", u"номер канала в допустимом диапазоне 0..63")
    p.var(u"e_rd", u"BOOL", u"чтение дискретного входа")
    p.var(u"e_wr", u"BOOL", u"запись дискретного выхода")
    p.var(u"e_ai", u"BOOL", u"чтение аналогового входа")
    p.var(u"e_ao", u"BOOL", u"запись аналогового выхода")
    p.var(u"byte_i", u"INT", u"номер байта модуля: канал / 8 (ограничен 0..7)")
    p.var(u"ai_idx", u"INT", u"номер аналогового канала (ограничен 0..15)")
    p.var(u"d_idx", u"INT", u"номер дискретного канала (ограничен 0..63)")
    p.var(u"bit_n", u"INT", u"номер бита в байте: канал % 8")
    p.var(u"mask", u"BYTE", u"маска бита: 1 SHL (канал % 8)")
    p.var(u"bit", u"BOOL", u"уровень дискретного входа с модуля")
    p.var(u"oldb", u"BYTE", u"прочитанный байт модуля (для изменения бита)")
    p.var(u"newb", u"BYTE", u"байт модуля с изменённым битом")
    p.var(u"wr_byte", u"BYTE", u"новое значение байта модуля")
    p.var(u"wrd", u"WORD", u"прочитанное слово аналогового модуля")
    p.var(u"wrd_i", u"INT", u"то же слово как INT (WORD_TO_INT)")
    p.var(u"ao_w", u"WORD", u"значение аналогового выхода как WORD")
    p.var(u"rd", u"FB_IO_Read", u"чтение дискретного канала (общий блок)")
    p.var(u"wr", u"FB_IO_Write", u"запись дискретного канала (общий блок)")
    p.var(u"ai", u"FB_IO_AnalogIn", u"масштабирование аналогового входа")
    p.var(u"ao", u"FB_IO_AnalogOut", u"масштабирование аналогового выхода")
    for nm, t, c in ((u"rd_data", u"BYTE", u"защёлка байта дискретного входа"),
                     (u"rd_flt", u"BOOL", u"защёлка ошибки дискретного входа"),
                     (u"wr_bit", u"BOOL", u"защёлка бита дискретного выхода"),
                     (u"wr_flt", u"BOOL", u"защёлка ошибки дискретного выхода"),
                     (u"ai_data", u"BYTE", u"защёлка байта аналогового входа"),
                     (u"ai_flt", u"BOOL", u"защёлка ошибки аналогового входа"),
                     (u"ai_ovf", u"BOOL", u"защёлка выхода за диапазон (вход)"),
                     (u"ao_val", u"INT", u"защёлка значения аналогового выхода"),
                     (u"ao_flt", u"BOOL", u"защёлка ошибки аналогового выхода"),
                     (u"ao_ovf", u"BOOL", u"защёлка выхода за диапазон (выход)")):
        p.var(nm, t, c)

    # ------------------------------------------------------------------
    # СЕТЬ 1. Вид канала, стробы, номер байта и маска бита
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 1. Вид канала, стробы и адрес бита в модуле")
    n.outvar(u"is_di", EQ(n, I(n, u"Kind"), I(n, H % 1)))
    n.outvar(u"is_do", EQ(n, I(n, u"Kind"), I(n, H % 2), fbd_xml.COL_BLK + 120))
    n.outvar(u"is_ai", EQ(n, I(n, u"Kind"), I(n, H % 3), fbd_xml.COL_BLK + 240))
    n.outvar(u"is_ao", EQ(n, I(n, u"Kind"), I(n, H % 4), fbd_xml.COL_BLK + 360))
    n.outvar(u"g_in", AND(n, I(n, u"En_IO"), NOT(n, I(n, u"RW"), fbd_xml.COL_BLK + 480),
                          fbd_xml.COL_BLK + 600))
    n.outvar(u"g_out", AND(n, I(n, u"En_IO"), I(n, u"RW"), fbd_xml.COL_BLK + 720))
    n.outvar(u"ok", ANDL(n, [GE(n, I(n, u"Index"), I(n, u"INT#0")),
                             LE(n, I(n, u"Index"), I(n, u"INT#63"),
                                fbd_xml.COL_BLK + 140)], x0=fbd_xml.COL_BLK + 280))
    n.outvar(u"e_rd", ANDL(n, [I(n, u"g_in"), I(n, u"is_di"), I(n, u"ok")],
                           x0=fbd_xml.COL_BLK + 420))
    n.outvar(u"e_wr", ANDL(n, [I(n, u"g_out"), I(n, u"is_do"), I(n, u"ok")],
                           x0=fbd_xml.COL_BLK + 560))
    n.outvar(u"e_ai", ANDL(n, [I(n, u"g_in"), I(n, u"is_ai")], x0=fbd_xml.COL_BLK + 700))
    n.outvar(u"e_ao", ANDL(n, [I(n, u"g_out"), I(n, u"is_ao")], x0=fbd_xml.COL_BLK + 840))
    # Index имеет тип INT, поэтому деление на 8 и остаток берутся операциями
    # DIV/MOD, а не SHR/AND: сдвиг и маска в CODESYS определены только для
    # битовых типов (C32 'INT' -> 'ANY_BIT', найдено на этапе 4).
    n.outvar(u"byte_i", LIMIT(n, I(n, u"INT#0"),
                              DIV(n, I(n, u"Index"), I(n, u"INT#8"),
                                  fbd_xml.COL_BLK + 980),
                              I(n, u"INT#7"), fbd_xml.COL_BLK + 1120))
    n.outvar(u"ai_idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#15"),
                              fbd_xml.COL_BLK + 1260))
    n.outvar(u"d_idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#63"),
                             fbd_xml.COL_BLK + 1260))
    n.outvar(u"bit_n", MOD(n, I(n, u"Index"), I(n, u"INT#8"), fbd_xml.COL_BLK + 1400))
    n.outvar(u"mask", SHL(n, I(n, H % 1), I(n, u"bit_n"), fbd_xml.COL_BLK + 1540))

    # ------------------------------------------------------------------
    # СЕТЬ 2. Дискретный вход: бит байта %IB -> зеркало GVL_IO.DI -> FB_IO_Read
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 2. Дискретный вход: бит модуля %IB в канал GVL_IO.DI")
    n.outvar(u"bit", NE(n, AND(n, I(n, u"GVL_IO_HW.X_IB[byte_i]"), I(n, u"mask")),
                        I(n, H % 0), fbd_xml.COL_BLK + 200))
    tgt = u"GVL_IO.DI[d_idx]"
    n.outvar(tgt, IF(n, I(n, u"e_rd"), I(n, u"bit"), I(n, tgt),
                     fbd_xml.COL_BLK + 340))
    rd = n.block(u"FB_IO_Read", [(u"En_IO", I(n, u"e_rd")), (u"Index", I(n, u"Index")),
                                 (u"Invert", I(n, u"Invert"))],
                 [u"RData", u"Bit", u"Fault"], instance=u"rd", x=fbd_xml.COL_BLK + 480)
    n.outvar(u"rd_data", rd.out(u"RData"))
    n.outvar(u"rd_flt", rd.out(u"Fault"))

    # ------------------------------------------------------------------
    # СЕТЬ 3. Дискретный выход: канал -> бит байта %QB (чтение-изменение-запись)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 3. Дискретный выход: канал -> бит байта %QB модуля")
    wr = n.block(u"FB_IO_Write", [(u"En_IO", I(n, u"e_wr")), (u"Index", I(n, u"Index")),
                                  (u"WData", I(n, u"WData")),
                                  (u"Invert", I(n, u"Invert"))],
                 [u"Bit", u"Fault"], instance=u"wr")
    n.outvar(u"wr_bit", wr.out(u"Bit"))
    n.outvar(u"wr_flt", wr.out(u"Fault"))
    n.outvar(u"oldb", I(n, u"GVL_IO_HW.X_QB[byte_i]"))
    n.outvar(u"newb", IF(n, I(n, u"wr_bit"),
                         OR(n, I(n, u"oldb"), I(n, u"mask"), fbd_xml.COL_BLK + 200),
                         AND(n, I(n, u"oldb"),
                             NOT(n, I(n, u"mask"), fbd_xml.COL_BLK + 340),
                             fbd_xml.COL_BLK + 480),
                         fbd_xml.COL_BLK + 620))
    # ФАЗА B. ЗАПИСЬ В МОДУЛЬ ТОЛЬКО ПО ПОСТОЯННОМУ ИНДЕКСУ.
    # Было: outvar(u"GVL_IO_HW.X_QB[byte_i]", ...) - запись по ВЫЧИСЛЯЕМОМУ
    # индексу. Импортёр PLCopenXML такие записи МОЛЧА ТЕРЯЕТ (та же ловушка,
    # что с GVL_MEM.Memory[c_p1a] и GVL_IO.DO[idx]). Из-за этого ВСЕ выходные
    # каналы не работали: OUT 00h не ставил DO[0], OUT 20h не писал AO[0].
    for _k in range(8):
        _e = u"GVL_IO_HW.X_QB[%d]" % _k
        n.outvar(_e, IF(n, AND(n, I(n, u"e_wr"),
                               EQ(n, I(n, u"byte_i"), I(n, u"INT#%d" % _k),
                                  fbd_xml.COL_BLK2 + 800 + 40 * _k),
                               fbd_xml.COL_BLK2 + 1200 + 40 * _k),
                      I(n, u"newb"), I(n, _e),
                      fbd_xml.COL_BLK2 + 1600 + 40 * _k))
    # ЗЕРКАЛО ЛОГИЧЕСКИХ КАНАЛОВ. Тест (и VISU) читают GVL_IO.DO[], а диспетчер
    # писал только в образ модуля %QB, поэтому DO[0] оставался FALSE после OUT.
    for _k in range(64):
        _e = u"GVL_IO.DO[%d]" % _k
        n.outvar(_e, IF(n, AND(n, I(n, u"e_wr"),
                               EQ(n, I(n, u"d_idx"), I(n, u"INT#%d" % _k),
                                  fbd_xml.COL_BLK2 + 2600 + 40 * (_k % 16)),
                               fbd_xml.COL_BLK2 + 3300 + 40 * (_k % 16)),
                      I(n, u"wr_bit"), I(n, _e),
                      fbd_xml.COL_BLK2 + 4000 + 40 * (_k % 16)))

    # ------------------------------------------------------------------
    # СЕТЬ 4. Аналоговый вход: слово %IW -> зеркало GVL_IO.AI -> масштабирование
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 4. Аналоговый вход: слово %IW в зеркало GVL_IO.AI")
    n.outvar(u"wrd", I(n, u"GVL_IO_HW.X_IW[ai_idx]"))
    n.outvar(u"wrd_i", n.block(u"WORD_TO_INT", [(u"IN", I(n, u"wrd"))], [u"OUT"],
                               fbd_xml.COL_BLK + 200))
    tgt = u"GVL_IO.AI[ai_idx]"
    n.outvar(tgt, IF(n, I(n, u"e_ai"), I(n, u"wrd_i"), I(n, tgt),
                     fbd_xml.COL_BLK + 340))
    ai = n.block(u"FB_IO_AnalogIn", [(u"En_IO", I(n, u"e_ai")), (u"Index", I(n, u"Index")),
                                     (u"Num", I(n, u"Num")), (u"Den", I(n, u"Den")),
                                     (u"Invert", I(n, u"Invert"))],
                 [u"RData", u"Raw", u"Overflow", u"Fault"], instance=u"ai",
                 x=fbd_xml.COL_BLK + 480)
    n.outvar(u"ai_data", ai.out(u"RData"))
    n.outvar(u"ai_ovf", ai.out(u"Overflow"))
    n.outvar(u"ai_flt", ai.out(u"Fault"))

    # ------------------------------------------------------------------
    # СЕТЬ 5. Аналоговый выход: масштабирование -> слово %QW
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 5. Аналоговый выход: значение -> слово %QW модуля")
    ao = n.block(u"FB_IO_AnalogOut", [(u"En_IO", I(n, u"e_ao")), (u"Index", I(n, u"Index")),
                                      (u"WData", I(n, u"WData")), (u"Num", I(n, u"Num")),
                                      (u"Den", I(n, u"Den"))],
                 [u"AOut", u"Overflow", u"Fault"], instance=u"ao")
    n.outvar(u"ao_val", ao.out(u"AOut"))
    n.outvar(u"ao_ovf", ao.out(u"Overflow"))
    n.outvar(u"ao_flt", ao.out(u"Fault"))
    n.outvar(u"ao_w", n.block(u"INT_TO_WORD", [(u"IN", I(n, u"ao_val"))], [u"OUT"],
                              fbd_xml.COL_BLK + 200))
    # ФАЗА B. Аналоговый выход - тоже только по постоянному индексу
    # (запись по вычисляемому индексу импортёр теряет).
    for _k in range(16):
        _e = u"GVL_IO_HW.X_QW[%d]" % _k
        n.outvar(_e, IF(n, AND(n, I(n, u"e_ao"),
                               EQ(n, I(n, u"ai_idx"), I(n, u"INT#%d" % _k),
                                  fbd_xml.COL_BLK2 + 800 + 40 * _k),
                               fbd_xml.COL_BLK2 + 1400 + 40 * _k),
                      I(n, u"ao_w"), I(n, _e),
                      fbd_xml.COL_BLK2 + 2000 + 40 * _k))
    # зеркало логических аналоговых каналов (его читают тест и VISU)
    for _k in range(16):
        _e = u"GVL_IO.AO[%d]" % _k
        n.outvar(_e, IF(n, AND(n, I(n, u"e_ao"),
                               EQ(n, I(n, u"ai_idx"), I(n, u"INT#%d" % _k),
                                  fbd_xml.COL_BLK2 + 800 + 40 * _k),
                               fbd_xml.COL_BLK2 + 4400 + 40 * _k),
                      I(n, u"ao_val"), I(n, _e),
                      fbd_xml.COL_BLK2 + 5000 + 40 * _k))

    # ------------------------------------------------------------------
    # СЕТЬ 6. Сборка результата (интерфейс тот же, что у Sim/SoftPLC)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 6. Сборка результата: байт, неисправность, диапазон")
    d = I(n, H % 0x00)
    d = IF(n, I(n, u"is_di"), I(n, u"rd_data"), d, fbd_xml.COL_BLK)
    d = IF(n, I(n, u"is_ai"), I(n, u"ai_data"), d, fbd_xml.COL_BLK + 160)
    n.outvar(u"RData", d)
    n.outvar(u"Fault", ORL(n, [
        AND(n, I(n, u"is_di"), I(n, u"rd_flt")),
        AND(n, I(n, u"is_do"), I(n, u"wr_flt"), fbd_xml.COL_BLK + 140),
        AND(n, I(n, u"is_ai"), I(n, u"ai_flt"), fbd_xml.COL_BLK + 280),
        AND(n, I(n, u"is_ao"), I(n, u"ao_flt"), fbd_xml.COL_BLK + 420)],
        x0=fbd_xml.COL_BLK + 560))
    n.outvar(u"Overflow", ORL(n, [
        AND(n, I(n, u"is_ai"), I(n, u"ai_ovf")),
        AND(n, I(n, u"is_ao"), I(n, u"ao_ovf"), fbd_xml.COL_BLK + 140)],
        x0=fbd_xml.COL_BLK + 280))
    return p


ALL = (make_adapter_hw,)
