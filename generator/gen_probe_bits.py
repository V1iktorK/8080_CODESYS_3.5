# -*- coding: utf-8 -*-
u"""Подшаг 3.1, проба: проверка конструкций FBD, которых ещё не было в проекте.

Схемы - в pou_probe_bits.py. Результат - log/gen_probe_bits.log и сообщения
компилятора CODESYS в gen_probe_bits.stdout.txt.err.
"""

import os, sys, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_probe_bits

ROOT = cb.ROOT
L = cb.make_log(u"gen_probe_bits.log")
L(u"=== ПРОБА 3.1: битовый доступ, SEL(WORD), 4 порта, широкий интерфейс ===")
L(u"python: %s" % sys.version)

POUS = []
for _m in pou_probe_bits.ALL:
    _p = _m()
    POUS.append(_p)
    L(u"[0] POU собран: %-10s сетей=%d" % (_p.name, len(_p.networks)))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/probe_bits.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"probe_bits")
L(u"[1] PLCopenXML записан: %d символов" % size)

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.add_gvl(app, u"GVL_MEM",
               u"VAR_GLOBAL\n\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n", L)
    L(u"    импорт зависимости FB_PackByte ...")
    app.import_xml(ROOT + u"/src/FB_PackByte.plcopenxml")
    L(u"    импорт зависимости FB_PackByte OK")

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/probe_bits_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
