# -*- coding: utf-8 -*-
u"""Обёртка: исполнить gen_stage4.py и записать ЛЮБОЕ исключение."""
import io
import sys
import traceback

OUT = u"C:/dsh8080/work/emu_s4/log/zz_run.txt"
LOG = u"C:/dsh8080/work/emu_s4/log/zz_run.log"


def w(p, m):
    try:
        h = io.open(p, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


w(OUT, u"start")
sys.path.insert(0, u"C:/dsh8080/work/stage_s4")
try:
    execfile(u"C:/dsh8080/work/stage_s4/gen_stage4.py")
    w(OUT, u"exec завершён без исключения")
except Exception:
    w(OUT, u"ИСКЛЮЧЕНИЕ:")
    w(OUT, traceback.format_exc())
except SystemExit, e:
    w(OUT, u"SystemExit: %r" % (e,))
w(OUT, u"end")
w(LOG, u"=== DONE ===")
