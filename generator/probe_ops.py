# -*- coding: utf-8 -*-
u"""Бисекция: какой именно стандартный FBD-блок заставляет CODESYS молча выбросить POU.

Генерируем по одному МИНИМАЛЬНОМУ POU на оператор, импортируем каждый отдельным
файлом и смотрим, какие объекты появились в приложении.
"""
import os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 1)[0]
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

L = cb.Log(BASE + "/probe_ops.log")
L(u"=== БИСЕКЦИЯ ОПЕРАТОРОВ FBD ===")

POUS = []

def add(name, doc, in_vars, out_vars, build_net):
    p = Pou(name, u"functionBlock", doc=doc)
    for n_, t_ in in_vars:
        p.var_in(n_, t_)
    for n_, t_ in out_vars:
        p.var_out(n_, t_)
    build_net(p)
    POUS.append(p)

# --- BOOL-логика ---
def n_and(p):
    n = p.network(u"AND")
    a = n.invar(u"A"); b = n.invar(u"B")
    n.outvar(u"Q", n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
add(u"T_BOOL_AND", u"проверка AND", [(u"A", u"BOOL"), (u"B", u"BOOL")], [(u"Q", u"BOOL")], n_and)

def n_or(p):
    n = p.network(u"OR")
    a = n.invar(u"A"); b = n.invar(u"B")
    n.outvar(u"Q", n.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
add(u"T_BOOL_OR", u"проверка OR", [(u"A", u"BOOL"), (u"B", u"BOOL")], [(u"Q", u"BOOL")], n_or)

def n_xor(p):
    n = p.network(u"XOR")
    a = n.invar(u"A"); b = n.invar(u"B")
    n.outvar(u"Q", n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
add(u"T_BOOL_XOR", u"проверка XOR", [(u"A", u"BOOL"), (u"B", u"BOOL")], [(u"Q", u"BOOL")], n_xor)

def n_not(p):
    n = p.network(u"NOT")
    a = n.invar(u"A")
    n.outvar(u"Q", n.block(u"NOT", [(u"IN", a)], [u"OUT"]))
add(u"T_BOOL_NOT", u"проверка NOT", [(u"A", u"BOOL")], [(u"Q", u"BOOL")], n_not)

# --- BYTE-операции ---
def n_add8(p):
    n = p.network(u"ADD BYTE")
    x = n.invar(u"X"); y = n.invar(u"Y")
    n.outvar(u"R", n.block(u"ADD", [(u"IN1", x), (u"IN2", y)], [u"OUT"]))
add(u"T_BYTE_ADD", u"проверка ADD", [(u"X", u"BYTE"), (u"Y", u"BYTE")], [(u"R", u"BYTE")], n_add8)

def n_and8(p):
    n = p.network(u"AND BYTE")
    x = n.invar(u"X"); y = n.invar(u"Y")
    n.outvar(u"R", n.block(u"AND", [(u"IN1", x), (u"IN2", y)], [u"OUT"]))
add(u"T_BYTE_AND", u"проверка AND", [(u"X", u"BYTE"), (u"Y", u"BYTE")], [(u"R", u"BYTE")], n_and8)

def n_or8(p):
    n = p.network(u"OR BYTE")
    x = n.invar(u"X"); y = n.invar(u"Y")
    n.outvar(u"R", n.block(u"OR", [(u"IN1", x), (u"IN2", y)], [u"OUT"]))
add(u"T_BYTE_OR", u"проверка OR", [(u"X", u"BYTE"), (u"Y", u"BYTE")], [(u"R", u"BYTE")], n_or8)

def n_sel(p):
    n = p.network(u"SEL")
    g = n.invar(u"G"); x = n.invar(u"X"); y = n.invar(u"Y")
    n.outvar(u"R", n.block(u"SEL", [(u"G", g), (u"IN0", x), (u"IN1", y)], [u"OUT"]))
add(u"T_SEL", u"проверка SEL", [(u"G", u"BOOL"), (u"X", u"BYTE"), (u"Y", u"BYTE")], [(u"R", u"BYTE")], n_sel)

def n_move(p):
    n = p.network(u"MOVE")
    x = n.invar(u"X")
    n.outvar(u"R", n.block(u"MOVE", [(u"IN", x)], [u"OUT"]))
add(u"T_MOVE", u"проверка MOVE", [(u"X", u"BYTE")], [(u"R", u"BYTE")], n_move)

def n_assign(p):
    n = p.network(u"присваивание")
    x = n.invar(u"X")
    n.outvar(u"R", x)
add(u"T_ASSIGN", u"проверка прямого присваивания", [(u"X", u"BYTE")], [(u"R", u"BYTE")], n_assign)

# --- два вывода в одном POU ---
def n_two(p):
    n = p.network(u"XOR -> Sum")
    a = n.invar(u"A"); b = n.invar(u"B")
    n.outvar(u"Sum", n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
    n = p.network(u"AND -> Cout")
    a = n.invar(u"A"); b = n.invar(u"B")
    n.outvar(u"Cout", n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
add(u"T_TWO_OUT", u"два вывода", [(u"A", u"BOOL"), (u"B", u"BOOL")],
    [(u"Sum", u"BOOL"), (u"Cout", u"BOOL")], n_two)

# --- два SEL (как в FB_Reg8) ---
def n_two_sel(p):
    n = p.network(u"каскад SEL")
    d = n.invar(u"D"); ld = n.invar(u"LD"); q = n.invar(u"Q"); z = n.invar(u"BYTE#0")
    s1 = n.block(u"SEL", [(u"G", ld), (u"IN0", q), (u"IN1", d)], [u"OUT"])
    s2 = n.block(u"SEL", [(u"G", ld), (u"IN0", s1), (u"IN1", z)], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"Q", s2)
add(u"T_TWO_SEL", u"каскад из двух SEL", [(u"D", u"BYTE"), (u"LD", u"BOOL")],
    [(u"Q", u"BYTE")], n_two_sel)

NAMES = [p.name for p in POUS]
L(u"[1] сгенерировано POU: %d" % len(NAMES))

try:
    proj, app = cb.new_project(ROOT + u"/build/probe_ops.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src/ops", L)
    L(u"[3] --- ЧТО ДОЕХАЛО ---")
    for name in NAMES:
        o = cb.find_deep(app, name)
        L(u"    %-14s %s" % (name, u"ЕСТЬ" if o is not None else u"ПОТЕРЯН"))
    proj.save()
    cb.build(app, L)
    L(u"[4] дерево:")
    cb.walk(app, 1, 3, [], L)
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
