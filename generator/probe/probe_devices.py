# -*- coding: utf-8 -*-
# probe_devices.py - как получить базовый проект с УСТАНОВЛЕННЫМ устройством.
# Ключевые факты: projects.create() даёт пустой проект (нет Device/Application),
# значит нужен шаблон/пример, у которого устройство есть в репозитории (напр. id 4096 = CODESYS Control Win V3).
import io, os, sys, shutil, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 2)[0]          # .../8080_CODESYS_3.5
LOG  = BASE + "/probe_devices.log"
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

def device_of(o, depth=0):
    """возвращает (имя_узла, identification) первого устройства в поддереве"""
    if depth > 5:
        return None
    try:
        ident = o.get_device_identification()
        return (nm(o), ident)
    except Exception:
        pass
    try:
        kids = o.get_children()
    except Exception:
        kids = []
    for k in kids:
        r = device_of(k, depth + 1)
        if r is not None:
            return r
    return None

L(u"[i] ROOT = %s" % ROOT)
L(u"[i] python = %s" % sys.version)

# ---------- 0. полный дамп scripting API ----------
for args in ((), (BASE + u"/api_dump",), (BASE + u"/api_dump.txt",)):
    try:
        r = system.dump_scripting_api(*args)
        L(u"[0] dump_scripting_api%r -> %r" % (args, r))
        break
    except Exception:
        L(u"[0] dump_scripting_api%r FAILED: %s" % (args, traceback.format_exc().splitlines()[-1]))

# ---------- 1. какие устройства у поставляемых шаблонов и примеров ----------
cands = [
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/Empty.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/Standard.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/TemplatePlc200_01.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/TemplatePlc210_01.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Projects/SoftMotion/4.10.0.0/Examples/Tutorial/CNCdirect.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Projects/SoftMotion/4.10.0.0/Examples/Tutorial/PLCopenSingle.project",
    u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Projects/SoftMotion/4.10.0.0/SoftMotionLight/SML_CompatibilityCheck_DS402.project",
]

for cand in cands:
    close_all()
    work = ROOT + u"/build/probe_tpl.project"
    try:
        if os.path.exists(work):
            os.remove(work)
        shutil.copyfile(cand, work)          # открываем КОПИЮ, чтобы не портить установку
    except Exception:
        L(u"[1] copy of %s FAILED: %s" % (cand, traceback.format_exc().splitlines()[-1]))
        continue
    try:
        p = projects.open(work)
        d = device_of(p)
        L(u"[1] OK   %s" % cand.rsplit(u"/", 1)[-1])
        L(u"      device node=%r  ident=%r" % (d[0], d[1]) if d else u"      device: НЕТ")
        try:
            app = p.active_application
            L(u"      application=%s" % nm(app))
        except Exception:
            L(u"      application: НЕТ")
        p.close()
    except Exception:
        L(u"[1] FAIL %s\n%s" % (cand, traceback.format_exc()))

# ---------- 2. пробуем режим симуляции на найденном устройстве ----------
close_all()
work = ROOT + u"/build/probe_std.project"
try:
    if os.path.exists(work):
        os.remove(work)
    shutil.copyfile(u"C:/Program Files (x86)/CODESYS 3.5.17.30/CODESYS/Templates/Standard.project", work)
    p2 = projects.open(work)
    dev = None
    for k in p2.get_children():
        if nm(k) == u"PLCWinNT":
            dev = k
    if dev is not None:
        try:
            L(u"[2] dev members device-like: %s" % u", ".join([m for m in dir(dev) if u"device" in m.lower() or u"simul" in m.lower()]))
        except Exception:
            L(u"[2] dir FAILED")
        try:
            L(u"[2] get_device_identification() -> %r" % (dev.get_device_identification(),))
        except Exception:
            L(u"[2] ident FAILED: %s" % traceback.format_exc().splitlines()[-1])
        try:
            dev.set_simulation_mode(True)
            L(u"[2] set_simulation_mode(True) OK")
        except Exception:
            L(u"[2] set_simulation_mode FAILED: %s" % traceback.format_exc().splitlines()[-1])
    else:
        L(u"[2] устройство PLCWinNT не найдено среди детей проекта")
    p2.close()
except Exception:
    L(u"[2] FAILED\n" + traceback.format_exc())

close_all()
L(u"=== DONE ===")
f.close()
