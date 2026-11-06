# -*- coding: utf-8 -*-
u"""Замер В МОМЕНТ ТАКТА: ловим сэмплы, где декодер активен (C_Class != 0).

Только так видно, с каким C_RP/C_Class реально исполняется команда: обычный
опрос с паузой попадает между тактами, где все поля декодера нулевые.
"""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_tact.log"
OUT = ROOT + u"/log/zz_tact.txt"
SEC = float(__import__("os").environ.get(u"DSH_T_SEC") or u"5")

NAMES = (u"A", u"B", u"C", u"D", u"E", u"H", u"L", u"SP", u"PC")
EXTRA = (u"GVL_CPU.C_Class", u"GVL_CPU.C_RP", u"GVL_CPU.C_Len",
         u"GVL_CPU.C_RdSel", u"GVL_CPU.C_WReg1", u"GVL_CPU.C_WReg2",
         u"GVL_CPU.Bus_IR")


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
    w(u"=== ЗАМЕР В МОМЕНТ ТАКТА ===")
    w(u"t\tIdx\t" + u"\t".join(NAMES) + u"\t" +
      u"\t".join([e.split(u".")[-1] for e in EXTRA]))
    exprs = [u"GVL_TEST.Idx"] + [u"GVL_CPM.Reg_%s" % n for n in NAMES] + list(EXTRA)
    t0 = time.time()
    seen = 0
    while time.time() - t0 < SEC:
        try:
            vals = [num(v) for v in oa.read_values(exprs)]
        except Exception:
            continue
        # C_Class - предпоследний блок в EXTRA? нет: первый
        ccls = vals[len(NAMES) + 1]
        if ccls != 0:
            seen += 1
            row = u"%5.2f\t%d\t" % (time.time() - t0, vals[0]) + \
                  u"\t".join([u"%02X" % v if v < 256 else u"%04X" % v for v in vals[1:]])
            w(row)
    w(u"сэмплов с активным декодером: %d" % seen)
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
