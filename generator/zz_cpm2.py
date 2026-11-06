# -*- coding: utf-8 -*-
u"""Замер CP/M после перезапуска: фаза трапа, флаги, журнал консоли."""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_cpm.log"
OUT = ROOT + u"/log/zz_cpm.txt"
WAIT = int(__import__("os").environ.get(u"DSH_D_WAIT") or u"170")


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
        return -1


def main():
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    oa = scriptengine.online.create_online_application(app)
    oa.login(scriptengine.OnlineChangeOption.Never, False)
    oa.start()
    oa.set_prepared_value(u"GVL_TEST.Reset", u"TRUE")
    oa.write_prepared_values()
    w(u"=== CP/M после перезапуска ===")
    time.sleep(20)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        time.sleep(5)
        try:
            if num(oa.read_value(u"GVL_TEST.DoneCpm")):
                break
        except Exception:
            pass
    for nm in (u"GVL_CPM.Trap_Phase", u"GVL_CPM.Trap_Active",
               u"GVL_CPM.Trap_CCP", u"GVL_IO.Dbg_PC", u"GVL_TEST.Cpm_Phase", u"GVL_TEST.Cpm_Step",
               u"GVL_CPM.CCP_Cnt", u"GVL_CPM.CCP_Phase", u"GVL_CPM.Con_Log_Len", u"GVL_CPM.Diag.Cmd_Cnt",
               u"GVL_CPM.Reg_PC", u"GVL_CPM.Reg_SP",
               u"GVL_CPM.Diag.Trap_Cnt", u"GVL_CPM.Diag.BDOS_Cnt",
               u"GVL_CPM.Diag.BIOS_Cnt", u"GVL_TEST.Cpm_Pass",
               u"GVL_TEST.Cpm_Fail"):
        try:
            w(u"%-26s = %s" % (nm, oa.read_value(nm)))
        except Exception, e:
            w(u"%-26s : ОШИБКА %s" % (nm, e))
    try:
        res = [num(oa.read_value(u"GVL_TEST.Cpm_Res[%d]" % i)) for i in range(16)]
        w(u"Cpm_Res = %s" % res)
    except Exception, e:
        w(u"Cpm_Res : ОШИБКА %s" % e)
    n = 120
    try:
        vals = [num(v) for v in oa.read_values(
            [u"GVL_CPM.Con_Log[%d]" % i for i in range(n)])]
        txt = u"".join([chr(c) if 32 <= c < 127 else u"." for c in vals])
        w(u"журнал[0..%d]: |%s|" % (n - 1, txt))
        w(u"байты: %s" % u" ".join([u"%02X" % c for c in vals[:60]]))
    except Exception, e:
        w(u"журнал: ОШИБКА %s" % e)
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
