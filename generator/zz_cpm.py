# -*- coding: utf-8 -*-
u"""Замер слоя CP/M: результаты проверок и первые байты журнала консоли."""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_cpm.log"
OUT = ROOT + u"/log/zz_cpm.txt"
WAIT = int(__import__("os").environ.get(u"DSH_D_WAIT") or u"150")
NLEN = 260


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
    w(u"=== CP/M: журнал и результаты ===")
    time.sleep(20)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        time.sleep(5)
        try:
            done = num(oa.read_value(u"GVL_TEST.DoneCpm"))
        except Exception:
            continue
        if done:
            break
    res = []
    for i in range(8):
        try:
            res.append(num(oa.read_value(u"GVL_TEST.Cpm_Res[%d]" % i)))
        except Exception:
            res.append(-1)
    w(u"проверки CP/M (0..7): %s" % res)
    try:
        w(u"длина журнала: %s" % oa.read_value(u"GVL_CPM.Con_Log_Len"))
    except Exception:
        pass
    try:
        w(u"счётчик CCP: %s" % oa.read_value(u"GVL_IO.Dbg_PC", u"GVL_CPM.CCP_Cnt"))
        w(u"ловушек: %s" % oa.read_value(u"GVL_CPM.Diag.Trap_Cnt"))
        w(u"BDOS: %s" % oa.read_value(u"GVL_CPM.Diag.BDOS_Cnt"))
        w(u"BIOS: %s" % oa.read_value(u"GVL_CPM.Diag.BIOS_Cnt"))
    except Exception:
        pass
    # первые байты журнала как текст
    try:
        vals = [num(v) for v in oa.read_values(
            [u"GVL_CPM.Con_Log[%d]" % i for i in range(NLEN)])]
        txt = u"".join([chr(c) if 32 <= c < 127 else u"."
                        for c in vals])
        w(u"журнал[0..%d]: |%s|" % (NLEN - 1, txt))
        w(u"байты: %s" % u" ".join([u"%02X" % c for c in vals[:80]]))
    except Exception, e:
        w(u"[WARN] журнал: %s" % e)
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
