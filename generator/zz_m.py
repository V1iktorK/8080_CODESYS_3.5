# -*- coding: utf-8 -*-
u"""Замер памяти: попадают ли предустановки тестов по неНУЛЕВЫМ адресам.

Гипотеза: запись по адресу 0 работает (T-331 проходит), а по 0x0100 - нет
(T-371 читает 0). Здесь читаем несколько адресов в течение прогона и печатаем
их изменение по времени вместе с номером текущего кейса.
"""
import io
import time
import traceback

import scriptengine

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_m.log"
OUT = ROOT + u"/log/zz_m.txt"
SEC = int(__import__("os").environ.get(u"DSH_M_SEC") or u"110")

ADDRS = (0x0000, 0x0100, 0x0200, 0x0600, 0x0601)


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
    w(u"=== ЗАМЕР ПАМЯТИ ===")
    w(u"t\tIdx\t" + u"\t".join([u"%04X" % a for a in ADDRS]))
    exprs = [u"GVL_TEST.Idx"] + [u"GVL_MEM.Memory[%d]" % a for a in ADDRS]
    t0 = time.time()
    prev = None
    while time.time() - t0 < SEC:
        try:
            vals = [num(v) for v in oa.read_values(exprs)]
        except Exception, e:
            w(u"[WARN] %s" % e)
            time.sleep(2)
            continue
        row = u"%5.1f\t%d\t" % (time.time() - t0, vals[0]) + \
              u"\t".join([u"%02X" % v for v in vals[1:]])
        if (row != prev) or (176 <= vals[0] <= 188):
            w(row)
            prev = row
        time.sleep(0.25)
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
