# -*- coding: utf-8 -*-
u"""Минимальная проба: CODESYS запускается и исполняет скрипт."""
import io
import sys
import traceback

LOG = u"C:/dsh8080/work/emu_s4/log/zz_ping.log"
OUT = u"C:/dsh8080/work/emu_s4/log/zz_ping.txt"


def w(p, m):
    try:
        h = io.open(p, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


w(OUT, u"start")
try:
    import scriptengine
    w(OUT, u"scriptengine OK")
    w(OUT, u"projects=%r" % (scriptengine.projects,))
except Exception:
    w(OUT, u"scriptengine FAIL")
    w(OUT, traceback.format_exc())
w(LOG, u"=== DONE ===")
w(OUT, u"done")
