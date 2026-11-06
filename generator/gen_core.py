# -*- coding: utf-8 -*-
u"""ШАГ 3, подшаг 3.1 — первые кастомные функциональные блоки эмулятора Intel 8080.

Все блоки реализованы ТОЛЬКО на FBD (стандартные операторы CODESYS).
Каждый FB снабжён русскими комментариями: назначение, входы, выходы, поведение.

Состав подшага:
  FB_Reg8       — 8-битный регистр с защёлкиванием и сбросом
  FB_Reg16      — 16-битный регистр (PC, SP, временный адрес)
  FB_UnpackByte — распаковка BYTE -> 8 x BOOL (маски и сдвиги)
  FB_PackByte   — упаковка 8 x BOOL -> BYTE
  FB_FullAdder  — одноразрядный полный сумматор (основа АЛУ)
"""

import os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

ROOT = cb.ROOT
L = cb.make_log(u"gen_core.log")
L(u"=== ШАГ 3.1: кастомные FB (регистры, биты, сумматор) ===")
L(u"python: %s" % sys.version)


# ======================================================================
# FB_Reg8 — 8-битный регистр
# ======================================================================
def make_fb_reg8():
    p = Pou(u"FB_Reg8", u"functionBlock",
            doc=u"8-разрядный регистр. Хранит байт между сканами PLC.\n"
                u"\tВходы:  D - данные, LD - защёлкнуть, CLR - сброс (приоритетнее LD)\n"
                u"\tВыходы: Q - текущее значение\n"
                u"\tПоведение: Q := CLR ? 0 : (LD ? D : Q). Чтение Q в этой же схеме\n"
                u"\tдаёт значение ПРЕДЫДУЩЕГО скана - это и есть память регистра.")
    p.var_in(u"D", u"BYTE", u"входные данные")
    p.var_in(u"LD", u"BOOL", u"защёлкнуть: Q := D")
    p.var_in(u"CLR", u"BOOL", u"сброс: Q := 0 (приоритет выше LD)")
    p.var_out(u"Q", u"BYTE", u"текущее значение регистра")

    n = p.network(u"СЕТЬ 1. Защёлкивание и сброс: Q := CLR ? 0 : (LD ? D : Q)")
    d = n.invar(u"D")
    ld = n.invar(u"LD")
    clr = n.invar(u"CLR")
    zero = n.invar(u"BYTE#0")
    q = n.invar(u"Q")
    sel1 = n.block(u"SEL", [(u"G", ld), (u"IN0", q), (u"IN1", d)], [u"OUT"], fbd_xml.COL_BLK)
    sel2 = n.block(u"SEL", [(u"G", clr), (u"IN0", sel1), (u"IN1", zero)], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"Q", sel2)
    return p


# ======================================================================
# FB_Reg16 — 16-битный регистр
# ======================================================================
def make_fb_reg16():
    p = Pou(u"FB_Reg16", u"functionBlock",
            doc=u"16-разрядный регистр (PC, SP, временный адрес).\n"
                u"\tВходы:  D - данные, LD - защёлкнуть, CLR - сброс (приоритетнее LD)\n"
                u"\tВыходы: Q - текущее значение\n"
                u"\tПоведение: полностью аналогично FB_Reg8, но с типом WORD.")
    p.var_in(u"D", u"WORD", u"входные данные")
    p.var_in(u"LD", u"BOOL", u"защёлкнуть: Q := D")
    p.var_in(u"CLR", u"BOOL", u"сброс: Q := 0")
    p.var_out(u"Q", u"WORD", u"текущее значение регистра")

    n = p.network(u"СЕТЬ 1. Защёлкивание и сброс: Q := CLR ? 0 : (LD ? D : Q)")
    d = n.invar(u"D")
    ld = n.invar(u"LD")
    clr = n.invar(u"CLR")
    zero = n.invar(u"WORD#0")
    q = n.invar(u"Q")
    sel1 = n.block(u"SEL", [(u"G", ld), (u"IN0", q), (u"IN1", d)], [u"OUT"], fbd_xml.COL_BLK)
    sel2 = n.block(u"SEL", [(u"G", clr), (u"IN0", sel1), (u"IN1", zero)], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"Q", sel2)
    return p


# ======================================================================
# FB_UnpackByte — распаковка BYTE -> 8 x BOOL
# ======================================================================
def make_fb_unpack():
    p = Pou(u"FB_UnpackByte", u"functionBlock",
            doc=u"Распаковка байта в 8 отдельных бит (BYTE -> 8 x BOOL).\n"
                u"\tМетод: маски и сдвиги. Для каждого разряда i:\n"
                u"\t    Bi := (B AND mask_i) <> 0,   mask_i = 1,2,4,8,16,32,64,128\n"
                u"\tБиты 0..7 - от младшего к старшему.\n"
                u"\tПрименяется для регистра флагов (PSW), кода операции и полей\n"
                u"\tрегистров в командах MOV/MVI.")
    p.var_in(u"B", u"BYTE", u"входной байт")
    for i in range(8):
        p.var_out(u"B%d" % i, u"BOOL", u"разряд %d (вес %d)" % (i, 1 << i))

    masks = [u"BYTE#1", u"BYTE#2", u"BYTE#4", u"BYTE#8",
             u"BYTE#16", u"BYTE#32", u"BYTE#64", u"BYTE#128"]
    zero = None
    for i in range(8):
        n = p.network(u"СЕТЬ %d. Разряд %d: B%d := (B AND %s) <> 0" % (i + 1, i, i, masks[i]))
        b = n.invar(u"B")
        m = n.invar(masks[i])
        z = n.invar(u"BYTE#0")
        a = n.block(u"AND", [(u"IN1", b), (u"IN2", m)], [u"OUT"])
        ne = n.block(u"NE", [(u"IN1", a), (u"IN2", z)], [u"OUT"], fbd_xml.COL_BLK2)
        n.outvar(u"B%d" % i, ne)
    return p


# ======================================================================
# FB_PackByte — упаковка 8 x BOOL -> BYTE
# ======================================================================
def make_fb_pack():
    p = Pou(u"FB_PackByte", u"functionBlock",
            doc=u"Упаковка 8 бит в байт (8 x BOOL -> BYTE).\n"
                u"\tМетод: каждый бит превращается в BYTE через SEL(0, вес),\n"
                u"\tзатем 8 значений складываются по ИЛИ деревом 8->4->2->1.\n"
                u"\tПрименяется для сборки PSW из флагов S,Z,AC,P,CY.")
    for i in range(8):
        p.var_in(u"B%d" % i, u"BOOL", u"разряд %d (вес %d)" % (i, 1 << i))
    p.var_out(u"B", u"BYTE", u"собранный байт")

    n = p.network(u"СЕТЬ 1. Взвешивание и сложение по ИЛИ")
    zero = n.invar(u"BYTE#0")
    parts = []
    for i in range(8):
        bit = n.invar(u"B%d" % i)
        w = n.invar(u"BYTE#%d" % (1 << i))
        parts.append(n.block(u"SEL", [(u"G", bit), (u"IN0", zero), (u"IN1", w)], [u"OUT"]))

    # дерево ИЛИ: 8 -> 4 -> 2 -> 1
    level = parts
    lvl = 0
    while len(level) > 1:
        nxt = []
        for k in range(0, len(level), 2):
            nxt.append(n.block(u"OR", [(u"IN1", level[k]), (u"IN2", level[k + 1])],
                               [u"OUT"], fbd_xml.COL_BLK2 + lvl * 120))
        level = nxt
        lvl += 1
    n.outvar(u"B", level[0])
    return p


# ======================================================================
# FB_FullAdder — одноразрядный полный сумматор
# ======================================================================
def make_fb_adder():
    p = Pou(u"FB_FullAdder", u"functionBlock",
            doc=u"Одноразрядный полный сумматор - основа АЛУ.\n"
                u"\tВходы:  A, B - складываемые разряды, Cin - перенос из младшего разряда\n"
                u"\tВыходы: Sum - сумма, Cout - перенос в старший разряд\n"
                u"\tЛогика: Sum  := A XOR B XOR Cin\n"
                u"\t        Cout := (A AND B) OR (Cin AND (A XOR B))\n"
                u"\t8 таких блоков, соединённых по переносу, дают 8-разрядный сумматор.")
    p.var_in(u"A", u"BOOL", u"разряд A")
    p.var_in(u"B", u"BOOL", u"разряд B")
    p.var_in(u"Cin", u"BOOL", u"перенос из младшего разряда")
    p.var_out(u"Sum", u"BOOL", u"сумма разряда")
    p.var_out(u"Cout", u"BOOL", u"перенос в старший разряд")

    n = p.network(u"СЕТЬ 1. Сумма: Sum := A XOR B XOR Cin")
    a = n.invar(u"A")
    b = n.invar(u"B")
    cin = n.invar(u"Cin")
    x1 = n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
    x2 = n.block(u"XOR", [(u"IN1", x1), (u"IN2", cin)], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"Sum", x2)

    n = p.network(u"СЕТЬ 2. Перенос: Cout := (A AND B) OR (Cin AND (A XOR B))")
    a = n.invar(u"A")
    b = n.invar(u"B")
    cin = n.invar(u"Cin")
    x1 = n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
    and1 = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
    and2 = n.block(u"AND", [(u"IN1", cin), (u"IN2", x1)], [u"OUT"], fbd_xml.COL_BLK2)
    or1 = n.block(u"OR", [(u"IN1", and1), (u"IN2", and2)], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    n.outvar(u"Cout", or1)
    return p


# ======================================================================
# СБОРКА
# ======================================================================
POUS = [make_fb_reg8(), make_fb_reg16(), make_fb_unpack(), make_fb_pack(), make_fb_adder()]
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/core_fb.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"core_fb")
L(u"[1] PLCopenXML записан: %d символов, POU: %s" % (size, u", ".join(NAMES)))

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА создания проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/core_fb_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
