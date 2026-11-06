# -*- coding: utf-8 -*-
u"""ШАГ 3, подшаг 3.1 - драйвер сборки ПОЛНОГО ядра Intel 8080.

Собирается 19 POU:
  * 7 новых вспомогательных блоков (pou_extra.py);
  * 10 декодеров полного набора команд (pou_decode_full.py);
  * FB_CPU8080_FULL и PLC_PRG_FULL (pou_cpu_full.py).
Плюс импортируются зависимости, собранные ранее (подшаги 3.2-3.4) - они
не менялись: FB_PackByte, FB_UnpackByte, FB_FullAdder, FB_ALU8, FB_CtrlUnit,
FB_Mux8x8, FB_Mux8x16, FB_Memory64K.

Объявление GVL_CPU генерируется из таблицы классов pou_decode_full, поэтому
комментарии с кодами классов физически не могут разойтись со схемой декодера.

Драйвер намеренно короткий: загрузчик скриптов CODESYS не выполняет файл
больше ~25 КБ (см. docs/03_ЖУРНАЛ_СБОРКИ.md, п. 9.2).
"""

import os, sys, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_extra
import pou_decode_full
import pou_cpu_full

ROOT = cb.ROOT
L = cb.make_log(u"gen_core_full.log")
L(u"=== ШАГ 3.1: ПОЛНОЕ ядро Intel 8080 (все 78 команд) ===")
L(u"python: %s" % sys.version)

GVL_MEM_TEXT = (u"VAR_GLOBAL\n"
                u"\t(* Общая память эмулятора Intel 8080: 64 КБ *)\n"
                u"\tMemory : ARRAY[0..65535] OF BYTE;\n"
                u"END_VAR\n")

# блоки, собранные ранее (подшаги 3.2-3.4); эти файлы НЕ менялись
DEPENDENCIES = (u"FB_PackByte", u"FB_UnpackByte", u"FB_FullAdder", u"FB_ALU8",
                u"FB_CtrlUnit", u"FB_Mux8x8", u"FB_Mux8x16", u"FB_Memory64K")

POUS = []
for group, makers in ((u"вспомогательные", pou_extra.ALL),
                      (u"декодеры", pou_decode_full.ALL),
                      (u"ядро", pou_cpu_full.ALL)):
    for _m in makers:
        _p = _m()
        POUS.append(_p)
        L(u"[0] %-16s POU собран: %-20s сетей=%2d"
          % (group, _p.name, len(_p.networks)))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/core_full.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"core_full")
cn = fbd_xml.count_elements(src_path)
L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
  % (size, cn[0], cn[3], cn[4]))

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.add_gvl(app, u"GVL_CPU", pou_decode_full.gvl_cpu_text(), L)
    cb.add_gvl(app, u"GVL_MEM", GVL_MEM_TEXT, L)

    for dep in DEPENDENCIES:
        L(u"    импорт зависимости %s ..." % dep)
        app.import_xml(ROOT + u"/src/%s.plcopenxml" % dep)
        L(u"    импорт зависимости %s OK" % dep)

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/core_full_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
