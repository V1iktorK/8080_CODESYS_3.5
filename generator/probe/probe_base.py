# -*- coding: utf-8 -*-
# probe_base.py - ищем базовый проект с УСТАНОВЛЕННЫМ устройством (CODESYS Control Win V3, id 4096).
# IronPython 2: НЕЛЬЗЯ писать ur"C:\Users\..." ( \U - битая escape-последовательность ).
import io, os, sys, shutil, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 2)[0]          # .../8080_CODESYS_3.5
LOG  = BASE + "/probe_base.log"
f = io.open(LOG, "w", encoding="utf-8")

def L(m):
    f.write(u"%s\n" % (m,)); f.flush()

def nm(o):
    try:
        return o.get_name()
    except Exception:
        return u"?"

def walk(o, ind=0, depth=6):
    L(u"%s- %s [%s]" % (u"  " * ind, nm(o), type(o).__name__))
    if ind >= depth:
        return
    try:
        kids = o.get_children()
    except Exception:
        kids = []
    for k in kids:
        walk(k, ind + 1, depth)

L(u"[i] BASE = %s" % BASE)
L(u"[i] ROOT = %s" % ROOT)
L(u"[i] python = %s" % sys.version)

for p in list(projects.all):
    try:
        p.close()
    except Exception:
        pass

# ---------- 1. что создаёт projects.create() ----------
try:
    pr = projects.create(ROOT + u"/build/probe_created.project")
    L(u"[1] projects.create OK")
    walk(pr, 0, 4)
    try:
        L(u"[1] active_application -> %r" % (pr.active_application,))
    except Exception:
        L(u"[1] active_application FAILED: %s" % traceback.format_exc())
    pr.save()
except Exception:
    L(u"[1] FAILED\n" + traceback.format_exc())

# ---------- 2. устройство внутри Standard.project ----------
try:
    work = ROOT + u"/build/probe_std.project"
    if os.path.exists(work):
        os.remove(work)
    shutil.copyfile(u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/Standard.project", work)
    p2 = projects.open(work)
    dev = None
    try:
        found = p2.find(u"PLCWinNT", True)
        L(u"[2] find(PLCWinNT) -> %r" % (found,))
        if found is not None and len(found) > 0:
            dev = found[0]
    except Exception:
        L(u"[2] find FAILED\n" + traceback.format_exc())

    if dev is not None:
        try:
            L(u"[2] dev members: %s" % u", ".join([m for m in dir(dev) if not m.startswith(u"_")]))
        except Exception:
            L(u"[2] dir FAILED")
        try:
            L(u"[2] get_device_identification() -> %r" % (dev.get_device_identification(),))
        except Exception:
            L(u"[2] get_device_identification FAILED: %s" % traceback.format_exc())
        try:
            dev.set_simulation_mode(True)
            L(u"[2] set_simulation_mode(True) OK")
        except Exception:
            L(u"[2] set_simulation_mode FAILED: %s" % traceback.format_exc())
    p2.close()
except Exception:
    L(u"[2] FAILED\n" + traceback.format_exc())

# ---------- 3. какое устройство у готовых примеров ----------
for cand in (u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Projects/SoftMotion/4.10.0.0/Examples/Tutorial/CNCdirect.project",
             u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Projects/SoftMotion/4.10.0.0/Examples/Tutorial/PLCopenSingle.project"):
    try:
        p3 = projects.open(cand)
        L(u"[3] opened %s" % cand)
        for ch in p3.get_children():
            L(u"[3]   child: %s [%s]" % (nm(ch), type(ch).__name__))
        p3.close()
    except Exception:
        L(u"[3] %s FAILED\n%s" % (cand, traceback.format_exc()))

L(u"=== DONE ===")
f.close()
