# -*- coding: utf-8 -*-
u"""Проба (подшаг 3.1): проверка конструкций, нужных для полного ядра 8080.

Это НЕ часть эмулятора, а разведка диалекта. Каждая POU проверяет ровно одну
конструкцию, которой ещё не было в проекте:

  T_BITS  - побитный доступ к WORD (W.0 .. W.15) + FB_PackByte
  T_MASK  - выделение байта из WORD масками (AND на WORD) + NE на WORD
  T_W2B   - оператор преобразования WORD_TO_BYTE как блок FBD
  T_WSEL  - SEL с 16-разрядными входами (адресный MUX процессора)
  T_CMPW  - сравнения LT/GT/GE/LE/EQ/NE на WORD
  T_REG4  - 4-портовый регистр с обратной связью (Q := ... : Q)
  T_WIDE  - POU с 32 входами и 7 выходами (ширина блока)

Если какая-то конструкция не поддерживается, компилятор укажет на неё
по имени POU - и в основном ядре её заменит проверенная альтернатива.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou


def make_t_bits():
    p = Pou(u"T_BITS", u"functionBlock",
            doc=u"Проба 1: побитный доступ к WORD. Младший и старший байты\n"
                u"\tсобираются блоками FB_PackByte из битов W.0..W.15.")
    p.var_in(u"W", u"WORD", u"исходное слово")
    p.var_out(u"Lo", u"BYTE", u"младший байт")
    p.var_out(u"Hi", u"BYTE", u"старший байт")

    n = p.network(u"СЕТЬ 1. Lo := биты W.0..W.7")
    n.outvar(u"Lo", n.block(u"FB_PackByte",
                            [(u"B%d" % i, n.invar(u"W.%d" % i)) for i in range(8)],
                            [u"B"]))
    n = p.network(u"СЕТЬ 2. Hi := биты W.8..W.15")
    n.outvar(u"Hi", n.block(u"FB_PackByte",
                            [(u"B%d" % i, n.invar(u"W.%d" % (i + 8))) for i in range(8)],
                            [u"B"]))
    return p


def make_t_mask():
    p = Pou(u"T_MASK", u"functionBlock",
            doc=u"Проба 2 (запасной вариант для T_BITS): байт выделяется масками.\n"
                u"\tбит i := (W AND 2^i) <> 0, затем упаковка FB_PackByte.")
    p.var_in(u"W", u"WORD", u"исходное слово")
    p.var_out(u"Lo", u"BYTE", u"младший байт")
    p.var_out(u"Hi", u"BYTE", u"старший байт")

    for n_base, out, bits in ((0, u"Lo", range(8)), (8, u"Hi", range(8, 16))):
        n = p.network(u"СЕТЬ %d. %s := маски WORD" % (n_base // 8 + 1, out))
        ins = []
        for i in bits:
            a = n.block(u"AND", [(u"IN1", n.invar(u"W")),
                                 (u"IN2", n.invar(u"WORD#%d" % (1 << i)))], [u"OUT"])
            ins.append((u"B%d" % (i - n_base),
                        n.block(u"NE", [(u"IN1", a), (u"IN2", n.invar(u"WORD#0"))],
                                [u"OUT"], fbd_xml.COL_BLK2)))
        n.outvar(out, n.block(u"FB_PackByte", ins, [u"B"], fbd_xml.COL_BLK2 + 160))
    return p


def make_t_w2b():
    p = Pou(u"T_W2B", u"functionBlock",
            doc=u"Проба 3 (запасной вариант для T_BITS): оператор преобразования\n"
                u"\tWORD_TO_BYTE как блок FBD.")
    p.var_in(u"W", u"WORD", u"исходное слово")
    p.var_out(u"Lo", u"BYTE", u"младший байт")
    p.var_out(u"Hi", u"BYTE", u"старший байт")

    n = p.network(u"СЕТЬ 1. Lo := WORD_TO_BYTE(W)")
    n.outvar(u"Lo", n.block(u"WORD_TO_BYTE", [(u"IN", n.invar(u"W"))], [u"OUT"]))
    n = p.network(u"СЕТЬ 2. Hi := WORD_TO_BYTE(SHR(W, 8))")
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"W")), (u"IN2", n.invar(u"WORD#8"))], [u"OUT"])
    n.outvar(u"Hi", n.block(u"WORD_TO_BYTE", [(u"IN", sh)], [u"OUT"], fbd_xml.COL_BLK2))
    return p


def make_t_wsel():
    p = Pou(u"T_WSEL", u"functionBlock",
            doc=u"Проба 4: SEL с 16-разрядными входами.\n"
                u"\tТак в ядре выбирается адрес чтения памяти (a16 / BC / DE / SP).")
    p.var_in(u"Sel", u"BYTE", u"код 0..3")
    for i in range(4):
        p.var_in(u"I%d" % i, u"WORD", u"вход %d" % i)
    p.var_out(u"Q", u"WORD", u"выбранный адрес")

    n = p.network(u"СЕТЬ 1. Проверка трёх младших разрядов кода")
    sel = n.invar(u"Sel")
    k = []
    for i in range(4):
        a = n.block(u"AND", [(u"IN1", sel), (u"IN2", n.invar(u"BYTE#%d" % (1 << i)))], [u"OUT"])
        k.append(n.block(u"NE", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#0"))],
                         [u"OUT"], fbd_xml.COL_BLK2))
    n = p.network(u"СЕТЬ 2. Дерево SEL (WORD)")
    t1 = n.block(u"SEL", [(u"G", k[0]), (u"IN0", n.invar(u"I0")), (u"IN1", n.invar(u"I1"))], [u"OUT"])
    t2 = n.block(u"SEL", [(u"G", k[0]), (u"IN0", n.invar(u"I2")), (u"IN1", n.invar(u"I3"))],
                 [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"Q", n.block(u"SEL", [(u"G", k[1]), (u"IN0", t1), (u"IN1", t2)],
                           [u"OUT"], fbd_xml.COL_BLK2 + 140))
    return p


def make_t_cmpw():
    p = Pou(u"T_CMPW", u"functionBlock",
            doc=u"Проба 5: сравнения на 16-разрядных операндах.\n"
                u"\tНужны для флага переноса команды DAD (CY := HL+pair < HL).")
    p.var_in(u"W1", u"WORD", u"первый операнд")
    p.var_in(u"W2", u"WORD", u"второй операнд")
    p.var_out(u"Lt", u"BOOL", u"W1 < W2")
    p.var_out(u"Gt", u"BOOL", u"W1 > W2")
    p.var_out(u"Ge", u"BOOL", u"W1 >= W2")
    p.var_out(u"Le", u"BOOL", u"W1 <= W2")
    p.var_out(u"Eq", u"BOOL", u"W1 = W2")
    p.var_out(u"Ne", u"BOOL", u"W1 <> W2")

    n = p.network(u"СЕТЬ 1. LT / GT / GE / LE / EQ / NE на WORD")
    n.outvar(u"Lt", n.block(u"LT", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))], [u"OUT"]))
    n.outvar(u"Gt", n.block(u"GT", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 120))
    n.outvar(u"Ge", n.block(u"GE", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 240))
    n.outvar(u"Le", n.block(u"LE", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 360))
    n.outvar(u"Eq", n.block(u"EQ", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 480))
    n.outvar(u"Ne", n.block(u"NE", [(u"IN1", n.invar(u"W1")), (u"IN2", n.invar(u"W2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 600))
    return p


def make_t_reg4():
    p = Pou(u"T_REG4", u"functionBlock",
            doc=u"Проба 6: четыре порта записи и обратная связь по Q.\n"
                u"\tQ := CLR ? 0 : (LD1 ? D1 : (LD2 ? D2 : (LD3 ? D3 : (LD4 ? D4 : Q))))\n"
                u"\tИменно так устроен FB_Reg8Q (регистр для XCHG/LHLD/POP).")
    p.var_in(u"D1", u"BYTE", u"данные порта 1")
    p.var_in(u"LD1", u"BOOL", u"запись порта 1")
    p.var_in(u"D2", u"BYTE", u"данные порта 2")
    p.var_in(u"LD2", u"BOOL", u"запись порта 2")
    p.var_in(u"D3", u"BYTE", u"данные порта 3")
    p.var_in(u"LD3", u"BOOL", u"запись порта 3")
    p.var_in(u"D4", u"BYTE", u"данные порта 4")
    p.var_in(u"LD4", u"BOOL", u"запись порта 4")
    p.var_in(u"CLR", u"BOOL", u"сброс")
    p.var_out(u"Q", u"BYTE", u"текущее значение")

    n = p.network(u"СЕТЬ 1. Четыре порта загрузки и сброс")
    q = n.invar(u"Q")
    t = n.block(u"SEL", [(u"G", n.invar(u"LD4")), (u"IN0", q), (u"IN1", n.invar(u"D4"))], [u"OUT"])
    t = n.block(u"SEL", [(u"G", n.invar(u"LD3")), (u"IN0", t), (u"IN1", n.invar(u"D3"))],
                [u"OUT"], fbd_xml.COL_BLK2)
    t = n.block(u"SEL", [(u"G", n.invar(u"LD2")), (u"IN0", t), (u"IN1", n.invar(u"D2"))],
                [u"OUT"], fbd_xml.COL_BLK2 + 140)
    t = n.block(u"SEL", [(u"G", n.invar(u"LD1")), (u"IN0", t), (u"IN1", n.invar(u"D1"))],
                [u"OUT"], fbd_xml.COL_BLK2 + 280)
    n.outvar(u"Q", n.block(u"SEL", [(u"G", n.invar(u"CLR")), (u"IN0", t),
                                    (u"IN1", n.invar(u"BYTE#0"))],
                           [u"OUT"], fbd_xml.COL_BLK2 + 420))
    return p


def make_t_wide():
    p = Pou(u"T_WIDE", u"functionBlock",
            doc=u"Проба 7: POU с 32 входами и 7 выходами - проверка ширины\n"
                u"\tинтерфейса (столько входов у FB_RegFileQ: 4 шины + 28 сигналов LD).")
    names = []
    for i in range(28):
        names.append(p.var_in(u"LD%d" % i, u"BOOL", u"сигнал %d" % i))
    for i in range(4):
        names.append(p.var_in(u"Data%d" % i, u"BYTE", u"шина данных %d" % i))
    for r in u"ABCDEHL":
        p.var_out(u"R%s" % r, u"BYTE", u"выход %s" % r)

    n = p.network(u"СЕТЬ 1. Каждый выход - OR четырёх сигналов и свои данные")
    for k, r in enumerate(u"ABCDEHL"):
        o1 = n.block(u"OR", [(u"IN1", n.invar(u"LD%d" % (k * 4))),
                             (u"IN2", n.invar(u"LD%d" % (k * 4 + 1)))], [u"OUT"])
        o2 = n.block(u"OR", [(u"IN1", n.invar(u"LD%d" % (k * 4 + 2))),
                             (u"IN2", n.invar(u"LD%d" % (k * 4 + 3)))], [u"OUT"],
                     fbd_xml.COL_BLK2)
        g = n.block(u"OR", [(u"IN1", o1), (u"IN2", o2)], [u"OUT"], fbd_xml.COL_BLK2 + 140)
        n.outvar(u"R%s" % r, n.block(
            u"SEL", [(u"G", g), (u"IN0", n.invar(u"Data0")), (u"IN1", n.invar(u"Data%d" % (k % 4)))],
            [u"OUT"], fbd_xml.COL_BLK2 + 280))
    return p


ALL = (make_t_bits, make_t_mask, make_t_w2b, make_t_wsel,
       make_t_cmpw, make_t_reg4, make_t_wide)
