# -*- coding: utf-8 -*-
u"""Замер диска CP/M: каталог и первые записи, плюс фазы CCP."""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_disk.log"
OUT = ROOT + u"/log/zz_disk.txt"
WAIT = int(__import__("os").environ.get(u"DSH_D_WAIT") or u"320")


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
    w(u"=== ДИСК CP/M ===")
    time.sleep(20)
    t0 = time.time()
    while time.time() - t0 < WAIT:
        time.sleep(5)
        try:
            if num(oa.read_value(u"GVL_TEST.DoneCpm")):
                break
        except Exception:
            pass
    for nm in (u"GVL_CPM.CCP_Cnt", u"GVL_CPM.CCP_Phase",
               u"GVL_CPM.Con_Log_Len"):
        try:
            w(u"%-24s = %s" % (nm, oa.read_value(nm)))
        except Exception, e:
            w(u"%-24s : ОШИБКА %s" % (nm, e))
    try:
        res = [num(oa.read_value(u"GVL_TEST.Cpm_Res[%d]" % i)) for i in range(16)]
        w(u"Cpm_Res = %s" % res)
    except Exception, e:
        w(u"Cpm_Res : ОШИБКА %s" % e)
    # каталог диска: первые 256 байт образа и область каталога
    try:
        vals = [num(v) for v in oa.read_values(
            [u"GVL_DISK.Disk[%d]" % i for i in range(256)])]
        w(u"диск[0..63]  : %s" % u" ".join([u"%02X" % c for c in vals[:64]]))
        w(u"диск[64..127]: %s" % u" ".join([u"%02X" % c for c in vals[64:128]]))
        w(u"диск[128..191]: %s" % u" ".join([u"%02X" % c for c in vals[128:192]]))
    except Exception, e:
        w(u"диск: ОШИБКА %s" % e)
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
