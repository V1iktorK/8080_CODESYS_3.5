# -*- coding: utf-8 -*-
u"""Бисекция №2: что именно губит POU — разветвление выхода блока или ссылки между сетями?

Варианты (каждый — отдельный минимальный POU):
  A — выход блока идёт на ДВА входа в ОДНОЙ сети (fan-out внутри сети)
  B — выход блока используется в СЛЕДУЮЩЕЙ сети (одна ссылка)
  C — выход блока используется в двух РАЗНЫХ сетях
  D — две независимые сети, перекрёстных ссылок нет (контроль)
  E — как C, но между сетями сигнал передаётся через ЛОКАЛЬНУЮ переменную
"""
import os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 1)[0]
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

L = cb.Log(BASE + "/probe_split.log")
L(u"=== БИСЕКЦИЯ №2: fan-out и межсетевые ссылки ===")

POUS = []

# A -------------------------------------------------------------------
p = Pou(u"T_FANOUT_A", u"functionBlock", doc=u"выход блока на два входа в одной сети")
p.var_in(u"A", u"BOOL"); p.var_in(u"B", u"BOOL"); p.var_out(u"Q", u"BOOL")
n = p.network(u"fan-out внутри сети")
a = n.invar(u"A"); b = n.invar(u"B")
g = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
n.outvar(u"Q", n.block(u"OR", [(u"IN1", g), (u"IN2", g)], [u"OUT"], fbd_xml.COL_BLK2))
POUS.append(p)

# B -------------------------------------------------------------------
p = Pou(u"T_CROSS_B", u"functionBlock", doc=u"выход блока используется в следующей сети")
p.var_in(u"A", u"BOOL"); p.var_in(u"B", u"BOOL"); p.var_out(u"Q", u"BOOL")
n = p.network(u"сеть 1 - источник")
a = n.invar(u"A"); b = n.invar(u"B")
g = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
n2 = p.network(u"сеть 2 - потребитель")
n2.outvar(u"Q", g)
POUS.append(p)

# C -------------------------------------------------------------------
p = Pou(u"T_CROSS_C", u"functionBlock", doc=u"выход блока используется в двух разных сетях")
p.var_in(u"A", u"BOOL"); p.var_in(u"B", u"BOOL"); p.var_out(u"Q1", u"BOOL"); p.var_out(u"Q2", u"BOOL")
n = p.network(u"сеть 1 - источник")
a = n.invar(u"A"); b = n.invar(u"B")
g = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
n2 = p.network(u"сеть 2")
n2.outvar(u"Q1", g)
n3 = p.network(u"сеть 3")
n3.outvar(u"Q2", g)
POUS.append(p)

# D -------------------------------------------------------------------
p = Pou(u"T_INDEP_D", u"functionBlock", doc=u"две независимые сети (контроль)")
p.var_in(u"A", u"BOOL"); p.var_in(u"B", u"BOOL"); p.var_out(u"Q1", u"BOOL"); p.var_out(u"Q2", u"BOOL")
n = p.network(u"сеть 1")
a = n.invar(u"A"); b = n.invar(u"B")
n.outvar(u"Q1", n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
n2 = p.network(u"сеть 2")
a = n2.invar(u"A"); b = n2.invar(u"B")
n2.outvar(u"Q2", n2.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
POUS.append(p)

# E -------------------------------------------------------------------
p = Pou(u"T_VAR_E", u"functionBlock", doc=u"передача между сетями через локальную переменную")
p.var_in(u"A", u"BOOL"); p.var_in(u"B", u"BOOL"); p.var_out(u"Q", u"BOOL")
p.var(u"tmp", u"BOOL", u"промежуточный сигнал между сетями")
n = p.network(u"сеть 1: tmp := A AND B")
a = n.invar(u"A"); b = n.invar(u"B")
n.outvar(u"tmp", n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
n2 = p.network(u"сеть 2: Q := tmp")
n2.outvar(u"Q", n2.invar(u"tmp"))
POUS.append(p)

NAMES = [x.name for x in POUS]

try:
    proj, app = cb.new_project(ROOT + u"/build/probe_split.project", L)
except Exception:
    L(u"ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src/split", L)
    L(u"[3] --- ЧТО ДОЕХАЛО ---")
    for nm_ in NAMES:
        L(u"    %-12s %s" % (nm_, u"ЕСТЬ" if cb.find_deep(app, nm_) is not None else u"ПОТЕРЯН"))
    proj.save()
    cb.build(app, L)
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
