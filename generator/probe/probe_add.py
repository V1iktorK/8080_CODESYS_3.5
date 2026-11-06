# -*- coding: utf-8 -*-
# probe_add.py - создаём ЧИСТЫЙ проект и добавляем в него устройство CODESYS Control Win V3.
# Из дампа API: IScriptProjectDeviceExtension содержит 'add' (Projects which can contain devices).
# Установлено: type=4096, id='0000 0001', version='3.5.17.30'.
import io, os, sys, shutil, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 2)[0]
LOG  = BASE + "/probe_add.log"
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

def close_all():
    for p in list(projects.all):
        try:
            p.close()
        except Exception:
            pass

L(u"[i] python = %s" % sys.version)
close_all()

work = ROOT + u"/build/probe_add.project"
if os.path.exists(work):
    os.remove(work)

pr = projects.create(work)
L(u"[1] projects.create OK")

dev = None
attempts = [
    (u"add(name,type,id,version)", dict(name=u"Device", type=4096, id=u"0000 0001", version=u"3.5.17.30")),
    (u"add(name,type,id,version,module)", dict(name=u"Device", type=4096, id=u"0000 0001", version=u"3.5.17.30", module=None)),
]
try:
    ident = device_repository.create_device_identification(4096, u"0000 0001", u"3.5.17.30")
    L(u"[2] create_device_identification -> %r" % (ident,))
    attempts.append((u"add(name,device)", dict(name=u"Device", device=ident)))
except Exception:
    L(u"[2] create_device_identification FAILED: %s" % traceback.format_exc().splitlines()[-1])

for label, kw in attempts:
    try:
        dev = pr.add(**kw)
        L(u"[3] %s -> OK %r" % (label, dev))
        break
    except Exception:
        L(u"[3] %s -> %s" % (label, traceback.format_exc().splitlines()[-1]))

L(u"[4] --- TREE ---")
walk(pr, 0, 6)

try:
    L(u"[5] active_application -> %s" % nm(pr.active_application))
except Exception:
    L(u"[5] active_application FAILED: %s" % traceback.format_exc().splitlines()[-1])

if dev is not None:
    try:
        dev.set_simulation_mode(True)
        L(u"[6] set_simulation_mode(True) OK")
    except Exception:
        L(u"[6] set_simulation_mode FAILED: %s" % traceback.format_exc().splitlines()[-1])

try:
    pr.save()
    L(u"[7] saved")
except Exception:
    L(u"[7] save FAILED: %s" % traceback.format_exc().splitlines()[-1])

close_all()
L(u"=== DONE ===")
f.close()
