# -*- coding: utf-8 -*-
u"""Поскайсовая диагностика: что реально исполнил процессор в каждом кейсе.

Читает латчи ActIR/ActCls/ActRP (их пишет TEST_8080 во время такта) плюс
Results/ActA/ActPC и печатает ТОЛЬКО упавшие кейсы с опкодом, классом и парой.
"""
import io
import sys
import time
import traceback

import scriptengine
import pou_test_defs as TD

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_diag.log"
OUT = ROOT + u"/log/zz_diag.txt"
WAIT = int(__import__("os").environ.get(u"DSH_D_WAIT") or u"160")


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


def arr(oa, name, n):
    try:
        return [num(v) for v in oa.read_values(
            [u"GVL_TEST.%s[%d]" % (name, i) for i in range(n)])]
    except Exception, e:
        w(u"[WARN] %s: %s" % (name, e))
        return None


def main():
    cases = TD.build_all()
    n = len(cases)
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    oa = scriptengine.online.create_online_application(app)
    oa.login(scriptengine.OnlineChangeOption.Never, False)
    oa.start()
    oa.set_prepared_value(u"GVL_TEST.Reset", u"TRUE")
    oa.write_prepared_values()
    w(u"=== ДИАГНОСТИКА КЕЙСОВ ===")
    time.sleep(20)
    t0 = time.time()
    idx = 0
    while time.time() - t0 < WAIT:
        time.sleep(5)
        try:
            idx = num(oa.read_value(u"GVL_TEST.Idx"))
            done = num(oa.read_value(u"GVL_TEST.Done8080"))
        except Exception:
            continue
        if done or idx >= n - 2:
            break
    w(u"[OK] прогон до Idx=%s" % idx)
    ir = arr(oa, u"ActIR", n)
    cl = arr(oa, u"ActCls", n)
    rp = arr(oa, u"ActRP", n)
    res = [num(v) for v in oa.read_values(
        [u"GVL_TEST.Results[%d]" % i for i in range(n)])]
    a_ = arr(oa, u"ActA", n)
    pc = arr(oa, u"ActPC", n)
    ps = arr(oa, u"ActPSW", n)
    un = arr(oa, u"ActUnc", n)
    ad = arr(oa, u"ActAddr", n)
    pr = arr(oa, u"ActPre", n)
    aw = arr(oa, u"ActW", n)
    un = arr(oa, u"ActUnc", n)
    try:
        oa.stop()
        oa.logout()
    except Exception:
        pass
    if ir is None:
        w(u"[FAIL] ActIR не прочитан")
        return
    npass = sum(1 for x in res if x)
    w(u"PASS=%d FAIL=%d" % (npass, n - npass))
    w(u"")
    w(u"| idx | ID | Тест | IR | Cls | PSW | MemCmp | A | PC |")
    w(u"|---|---|---|---|---|---|---|---|---|")
    for i, c in enumerate(cases):
        if res[i]:
            continue
        w(u"| %d | %s | %s | %02X | %02X | %02X | %02X | %02X | %04X |"
          % (i, c[u"id"], c[u"name"], ir[i], cl[i], ps[i], (pr[i] if pr else 0), a_[i], pc[i]))


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
