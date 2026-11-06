# -*- coding: utf-8 -*-
u"""Замер РЕГИСТРОВ по ходу прогона: что реально пишется в B/C/D/E/H/L/SP.

Нужно, чтобы не гадать по отчёту (он печатает только A/PC/SP). Читаем
опубликованные GVL_CPM.Reg_* вместе с номером текущего кейса.
"""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_reg.log"
OUT = ROOT + u"/log/zz_reg.txt"
SEC = int(__import__("os").environ.get(u"DSH_R_SEC") or u"60")

NAMES = (u"A", u"B", u"C", u"D", u"E", u"H", u"L", u"SP", u"PC")
EXTRA = (u"GVL_CPU.C_RP", u"GVL_CPU.C_Class", u"GVL_CPU.C_Len",
         u"GVL_CPU.C_RdSel", u"GVL_CPU.C_WReg1", u"GVL_CPU.C_WReg2")


def w(m):
    try:
        h = io.open(OUT, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


def num(v):
    s = u"%s" % v
    if u"TRUE" in s.upper():
        return 1
    if u"FALSE" in s.upper():
        return 0
    try:
        return int(s.split(u"#")[-1])
    except Exception:
        return 0


def main():
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    oa = scriptengine.online.create_online_application(app)
    oa.login(scriptengine.OnlineChangeOption.Never, False)
    oa.start()
    oa.set_prepared_value(u"GVL_TEST.Reset", u"TRUE")
    oa.write_prepared_values()
    w(u"=== ЗАМЕР РЕГИСТРОВ ===")
    w(u"t\tIdx\t" + u"\t".join(NAMES) + u"\t" +
      u"\t".join([e.split(u".")[-1] for e in EXTRA]))
    exprs = [u"GVL_TEST.Idx"] + [u"GVL_CPM.Reg_%s" % n for n in NAMES] + list(EXTRA)
    t0 = time.time()
    prev = None
    while time.time() - t0 < SEC:
        try:
            vals = [num(v) for v in oa.read_values(exprs)]
        except Exception, e:
            w(u"[WARN] %s" % e)
            time.sleep(1)
            continue
        row = u"%5.1f\t%d\t" % (time.time() - t0, vals[0]) + \
              u"\t".join([u"%02X" % v if v < 256 else u"%04X" % v for v in vals[1:]])
        if row != prev:
            w(row)
            prev = row
        time.sleep(0.2)
    try:
        oa.stop()
        oa.logout()
    except Exception:
        pass


try:
    main()
except Exception:
    w(u"ИСКЛЮЧЕНИЕ:")
    w(traceback.format_exc())
w(u"=== DONE ===")
try:
    h = io.open(LOG, u"wb")
    h.write(b"=== DONE ===\n")
    h.close()
except Exception:
    pass
