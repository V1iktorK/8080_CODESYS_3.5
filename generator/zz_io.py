# -*- coding: utf-8 -*-
u"""Замер: что видел аппаратный слой I/O при последнем обращении."""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_io.log"
OUT = ROOT + u"/log/zz_io.txt"
WAIT = int(__import__("os").environ.get(u"DSH_D_WAIT") or u"120")

NAMES = (u"GVL_IO.Diag.Read_Cnt", u"GVL_IO.Diag.Write_Cnt",
         u"GVL_IO.Diag.Unmapped_Cnt", u"GVL_IO.Diag.Diag_Cnt",
         u"GVL_IO.Diag.Fault_Cnt", u"GVL_IO.Diag.Range_Cnt",
         u"GVL_IO.Diag.Console_Cnt", u"GVL_IO.Diag.Event_Cnt",
         u"GVL_IO.Diag.Last_Port", u"GVL_IO.Diag.Last_Kind",
         u"GVL_IO.Diag.Last_Index", u"GVL_IO.Diag.Last_Value",
         u"GVL_IO.Diag.Last_RW", u"GVL_IO.Diag.Err_Code",
         u"GVL_IO.Diag.Err_Port",
         u"GVL_IO.DOx[0]", u"GVL_IO.DO[0]", u"GVL_IO.AO[0]",
         u"GVL_IO.AI[0]", u"GVL_IO.Req", u"GVL_IO.Ack",
         u"GVL_TEST.Io_Pass", u"GVL_TEST.Io_Fail", u"GVL_TEST.Mode", u"GVL_IO.Dbg_Req", u"GVL_IO.Dbg_Ready", u"GVL_IO.Dbg_Rd", u"GVL_IO.Dbg_Wr", u"GVL_IO.Dbg_Scan", u"GVL_IO.Dbg_Inj", u"GVL_IO.Dbg_ReqL", u"GVL_IO.Dbg_Miss", u"GVL_IO.Dbg_RData", u"GVL_IO.Dbg_Kind", u"GVL_IO.Dbg_Err", u"GVL_IO_Map.MissingPortMode", u"GVL_IO.Dbg_PC", u"GVL_IO.Dbg_Step", u"GVL_IO.Dbg_ReqC", u"GVL_IO.Dbg_AckC", u"GVL_IO.Dbg_WaitC", u"GVL_IO_Map.Map_Ready", u"GVL_IO.Diag.Dbg_Rdy", u"GVL_IO.Diag.Dbg_Scan", u"GVL_IO.Dbg_N", u"GVL_IO.Dbg_AL", u"GVL_IO.Dbg_A", u"GVL_IO.Dbg_IoW", u"GVL_IO.Dbg_IoA", u"GVL_IO.Dbg_IoD", u"GVL_IO.Dbg_IoL", u"GVL_IO.Dbg_RdL", u"GVL_IO.Dbg_AL", u"GVL_IO.Dbg_Rdy", u"GVL_IO.Dbg_P10", u"GVL_IO.Dbg_CH", u"GVL_IO.Dbg_AD", u"GVL_IO.Dbg_RDO", u"GVL_IO.Dbg_N", u"GVL_IO.Dbg_SD", u"GVL_IO.Dbg_SR", u"GVL_IO.Dbg_ARd", u"GVL_IO.Dbg_CRd", u"GVL_IO.Dbg_CP", u"GVL_IO.Dbg_TB", u"GVL_IO.Dbg_WdT", u"GVL_IO.Dbg_WdE", u"GVL_IO.Dbg_BS", u"GVL_IO.Dbg_Lim", u"GVL_HMI.Wd_Timeout", u"GVL_HMI.Wd_Busy_Scans", u"GVL_HMI.Wd_Timeout_Cnt", u"GVL_HMI.Wd_Scan_Cnt")


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
    w(u"=== ДИАГНОСТИКА I/O ===")
    time.sleep(20)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        time.sleep(5)
        try:
            mode = num(oa.read_value(u"GVL_TEST.Mode"))
            done = num(oa.read_value(u"GVL_TEST.Io_Pass")) + num(oa.read_value(u"GVL_TEST.Io_Fail")) > 0
        except Exception:
            continue
        if mode >= 4 or done:
            break
    for nm in NAMES:
        try:
            w(u"%-28s = %s" % (nm, oa.read_value(nm)))
        except Exception, e:
            w(u"%-28s : ОШИБКА %s" % (nm, e))
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
