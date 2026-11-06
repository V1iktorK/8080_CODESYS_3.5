# -*- coding: utf-8 -*-
u"""Проверка диалекта ВЫЗОВА пользовательского FB в FBD.

Без этого нельзя собрать ни АЛУ (8 экземпляров FB_FullAdder), ни главную схему
(FB_CPU8080 вызывает FB_Reg8/FB_ALU8/FB_Memory64K).

Проверяются два варианта записи имени экземпляра:
  V1 — атрибут instanceName у <block>
  V2 — дочерний addData/BlockInstance
"""
import os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 1)[0]
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

L = cb.Log(BASE + "/probe_fbcall.log")
L(u"=== ПРОВЕРКА ВЫЗОВА ПОЛЬЗОВАТЕЛЬСКОГО FB ===")


def make_caller(name, mode):
    p = Pou(name, u"functionBlock",
            doc=u"Проверка вызова FB_FullAdder. Режим записи имени: %s" % mode)
    p.var_in(u"A", u"BOOL")
    p.var_in(u"B", u"BOOL")
    p.var_in(u"C", u"BOOL")
    p.var_out(u"S", u"BOOL")
    p.var_out(u"CO", u"BOOL")
    p.var(u"fa0", u"FB_FullAdder", u"экземпляр сумматора")
    p.var(u"fa1", u"FB_FullAdder", u"экземпляр сумматора")

    n = p.network(u"СЕТЬ 1. Каскад двух сумматоров: (A+B) + C")
    a = n.invar(u"A")
    b = n.invar(u"B")
    lo = n.invar(u"FALSE")
    c = n.invar(u"C")
    fa0 = n.block(u"FB_FullAdder",
                  [(u"A", a), (u"B", b), (u"Cin", lo)],
                  [u"Sum", u"Cout"], fbd_xml.COL_BLK, instance=u"fa0")
    fa1 = n.block(u"FB_FullAdder",
                  [(u"A", fa0.out(u"Sum")), (u"B", c), (u"Cin", lo)],
                  [u"Sum", u"Cout"], fbd_xml.COL_BLK2, instance=u"fa1")
    n.outvar(u"S", fa1.out(u"Sum"))
    n.outvar(u"CO", fa1.out(u"Cout"))
    return p


POUS = [make_caller(u"FB_CALL_V1", u"атрибут instanceName"),
        make_caller(u"FB_CALL_V2", u"атрибут instanceName (второй POU для контроля")]
NAMES = [p.name for p in POUS]

try:
    proj, app = cb.new_project(ROOT + u"/build/probe_fbcall.project", L)
except Exception:
    L(u"ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    # сначала зависимость — сам FB_FullAdder
    app.import_xml(ROOT + u"/src/FB_FullAdder.plcopenxml")
    L(u"    FB_FullAdder импортирован: %s"
      % (u"ЕСТЬ" if cb.find_deep(app, u"FB_FullAdder") is not None else u"НЕТ"))

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src/call", L)

    L(u"[3] --- ЧТО ДОЕХАЛО ---")
    for nm_ in NAMES:
        L(u"    %-14s %s" % (nm_, u"ЕСТЬ" if cb.find_deep(app, nm_) is not None else u"ПОТЕРЯН"))

    found = [cb.find_deep(app, x) for x in NAMES]
    found = [x for x in found if x is not None]
    if found:
        proj.export_xml(found, path=ROOT + u"/src/call_reexport.xml", declarations_as_plaintext=True)
        t = fbd_xml.io.open(ROOT + u"/src/call_reexport.xml", "r", encoding="utf-8").read()
        i = t.find(u"<FBD>")
        L(u"[4] --- ТЕЛО ПОСЛЕ ОБРАТНОЙ ВЫГРУЗКИ ---")
        L(t[i:i + 2200] if i >= 0 else u"нет <FBD>")

    proj.save()
    cb.build(app, L)
except Exception:
    L(u"[5] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
