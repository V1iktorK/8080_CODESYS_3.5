# -*- coding: utf-8 -*-
u"""Бисекция FB_FlagsReg: что именно вешает импортёр CODESYS.

V1 - только распаковка PSW_In в биты (без флагов и упаковки)
V2 - только пять флагов с защёлкиванием (без PSW вообще)
V3 - флаги + упаковка PSW (без распаковки)
V4 - полный FB_FlagsReg (контроль; ожидается зависание)
"""
import os, sys
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

L = cb.make_log(u"probe_flags.log")
ROOT = cb.ROOT
L(u"=== БИСЕКЦИЯ FB_FlagsReg ===")

POUS = []

# --- V1: только распаковка ---
p = Pou(u"V1_UNPACK", u"functionBlock", doc=u"только распаковка PSW")
p.var_in(u"PSW_In", u"BYTE")
for i in range(8):
    p.var_out(u"B%d" % i, u"BOOL")
p.var(u"upsw", u"FB_UnpackByte")
n = p.network(u"распаковка")
up = n.block(u"FB_UnpackByte", [(u"B", n.invar(u"PSW_In"))],
             [u"B%d" % i for i in range(8)], instance=u"upsw")
for i in range(8):
    n.outvar(u"B%d" % i, up.out(u"B%d" % i))
POUS.append(p)

# --- V2: только флаги с защёлкиванием ---
p = Pou(u"V2_FLAGS", u"functionBlock", doc=u"только флаги с LD")
for nm_ in (u"S_In", u"Z_In", u"AC_In", u"P_In", u"CY_In"):
    p.var_in(nm_, u"BOOL")
p.var_in(u"LD", u"BOOL")
for nm_ in (u"S", u"Z", u"AC", u"P", u"CY"):
    p.var_out(nm_, u"BOOL")
for i, (iname, oname) in enumerate(((u"S_In", u"S"), (u"Z_In", u"Z"), (u"AC_In", u"AC"),
                                    (u"P_In", u"P"), (u"CY_In", u"CY"))):
    n = p.network(u"флаг %s" % oname)
    ld = n.invar(u"LD"); newv = n.invar(iname); old = n.invar(oname)
    n.outvar(oname, n.block(u"SEL", [(u"G", ld), (u"IN0", old), (u"IN1", newv)], [u"OUT"]))
POUS.append(p)

# --- V3: флаги + упаковка ---
p = Pou(u"V3_PACK", u"functionBlock", doc=u"флаги + упаковка PSW")
for nm_ in (u"S_In", u"Z_In", u"AC_In", u"P_In", u"CY_In", u"LD"):
    p.var_in(nm_, u"BOOL")
for nm_ in (u"S", u"Z", u"AC", u"P", u"CY"):
    p.var_out(nm_, u"BOOL")
p.var_out(u"PSW", u"BYTE")
p.var(u"ppsw", u"FB_PackByte")
for i, (iname, oname) in enumerate(((u"S_In", u"S"), (u"Z_In", u"Z"), (u"AC_In", u"AC"),
                                    (u"P_In", u"P"), (u"CY_In", u"CY"))):
    n = p.network(u"флаг %s" % oname)
    ld = n.invar(u"LD"); newv = n.invar(iname); old = n.invar(oname)
    n.outvar(oname, n.block(u"SEL", [(u"G", ld), (u"IN0", old), (u"IN1", newv)], [u"OUT"]))
n = p.network(u"упаковка PSW")
n.outvar(u"PSW", n.block(u"FB_PackByte", [
    (u"B0", n.invar(u"CY")), (u"B1", n.invar(u"TRUE")), (u"B2", n.invar(u"P")),
    (u"B3", n.invar(u"FALSE")), (u"B4", n.invar(u"AC")), (u"B5", n.invar(u"FALSE")),
    (u"B6", n.invar(u"Z")), (u"B7", n.invar(u"S")),
], [u"B"], instance=u"ppsw"))
POUS.append(p)

NAMES = [x.name for x in POUS]
L(u"сгенерировано: %s" % u", ".join(NAMES))

try:
    proj, app = cb.new_project(ROOT + u"/build/probe_flags.project", L)
    for dep in (u"FB_UnpackByte", u"FB_PackByte"):
        L(u"  зависимость %s ..." % dep)
        app.import_xml(ROOT + u"/src/%s.plcopenxml" % dep)
        L(u"  зависимость %s OK" % dep)
    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    L(u"--- ЧТО ДОЕХАЛО ---")
    for nm_ in NAMES:
        L(u"  %-10s %s" % (nm_, u"ЕСТЬ" if cb.find_deep(app, nm_) is not None else u"ПОТЕРЯН"))
except Exception:
    import traceback
    L(u"ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
