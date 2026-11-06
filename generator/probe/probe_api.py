# -*- coding: utf-8 -*-
# probe_api.py - компактная разведка: (a) как добавить устройство в проект, (b) какое
# устройство у поставляемых шаблонов/примеров. Лог намеренно КОРОТКИЙ.
import io, os, sys, shutil, traceback, re
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 2)[0]
LOG  = BASE + "/probe_api.log"
f = io.open(LOG, "w", encoding="utf-8")

def L(m):
    f.write(u"%s\n" % (m,)); f.flush()

def nm(o):
    try:
        return o.get_name()
    except Exception:
        return u"?"

def close_all():
    for p in list(projects.all):
        try:
            p.close()
        except Exception:
            pass

def first_device(o, depth=0):
    if depth > 5:
        return None
    try:
        return (nm(o), o.get_device_identification())
    except Exception:
        pass
    try:
        kids = o.get_children()
    except Exception:
        kids = []
    for k in kids:
        r = first_device(k, depth + 1)
        if r is not None:
            return r
    return None

L(u"[i] python = %s" % sys.version)

# ---------- A. полный API -> файл, затем выборка имён с 'evice' ----------
try:
    d = system.dump_scripting_api()
    p = BASE + "/api_dump.json"
    f2 = io.open(p, "w", encoding="utf-8")
    f2.write(unicode(d))
    f2.close()
    L(u"[A] api dump saved: %s chars" % len(d))
    names = {}
    for m in re.finditer(r'"Name":\s*"([A-Za-z_0-9]*[Dd]evice[A-Za-z_0-9]*)"', d):
        names[m.group(1)] = 1
    L(u"[A] api members containing 'evice': %s" % u", ".join(sorted(names.keys())))
    # ищем в дампе описание расширения проекта
    i = d.find(u"IScriptProjectDeviceExtension")
    if i >= 0:
        seg = d[max(0, i - 3000):i + 3000]
        seg = re.sub(r'\s+', u' ', seg)
        L(u"[A] ProjectDeviceExtension context: %s" % seg[:3000])
except Exception:
    L(u"[A] FAILED\n" + traceback.format_exc())

# ---------- B. пробуем добавить устройство в новый проект ----------
close_all()
try:
    pr = projects.create(ROOT + u"/build/probe_add.project")
    L(u"[B] projects.create OK")
    for meth, args in ((u"add_device", (u"CODESYS Control Win V3",)),
                       (u"add_device", (u"CODESYS Control Win V3", u"3.5.17.30")),
                       (u"create_device", (u"CODESYS Control Win V3",))):
        try:
            r = getattr(pr, meth)(*args)
            L(u"[B] %s%r -> OK %r" % (meth, args, r))
            break
        except Exception:
            L(u"[B] %s%r -> %s" % (meth, args, traceback.format_exc().splitlines()[-1]))
    pr.save()
    pr.close()
except Exception:
    L(u"[B] FAILED\n" + traceback.format_exc())

# ---------- C. устройства поставляемых проектов ----------
cands = [
    u"Templates/Standard.project",
    u"Templates/Empty.project",
    u"Templates/TemplatePlc200_01.project",
    u"Projects/SoftMotion/4.10.0.0/Examples/Tutorial/CNCdirect.project",
    u"Projects/SoftMotion/4.10.0.0/Examples/Tutorial/PLCopenSingle.project",
]
for c in cands:
    close_all()
    src = u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/" + c
    work = ROOT + u"/build/probe_tpl.project"
    try:
        if os.path.exists(work):
            os.remove(work)
        shutil.copyfile(src, work)
    except Exception:
        L(u"[C] copy FAILED %s" % c)
        continue
    try:
        p = projects.open(work)
        d = first_device(p)
        if d:
            L(u"[C] %-55s device=%r ident=%r" % (c, d[0], d[1]))
        else:
            L(u"[C] %-55s device=NONE" % c)
        try:
            L(u"      app=%s" % nm(p.active_application))
        except Exception:
            L(u"      app=NONE")
        p.close()
    except Exception:
        L(u"[C] %s FAILED: %s" % (c, traceback.format_exc().splitlines()[-1]))

close_all()
L(u"=== DONE ===")
f.close()
