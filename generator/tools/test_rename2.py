# -*- coding: utf-8 -*-
u"""Проверка: ссылки на переименованные имена в СГЕНЕРИРОВАННЫХ POU."""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
try:
    import builtins
    builtins.unicode = str
    builtins.unichr = chr
except Exception:
    pass

import fbd_xml
import pou_rename
import pou_cpu_io
import pou_io
import pou_prg_io
import pou_test8080
import pou_testio

OUT = os.path.join(HERE, u"_renametest")
if not os.path.isdir(OUT):
    os.makedirs(OUT)

CASES = ((u"FB_CPU8080_FULL", pou_cpu_io.ALL[0]()),
         (u"FB_IO_Dispatch", pou_io.make_io_dispatch()),
         (u"PLC_PRG_CPM", pou_prg_io.make_plc_prg_io()),
         (u"TEST_8080", pou_test8080.make_test_8080()),
         (u"TEST_IO", pou_testio.make_test_io()))

for nm, p in CASES:
    path = os.path.join(OUT, nm + u".plcopenxml")
    fbd_xml.write_project(path, [p], nm)
    t = io.open(path, encoding=u"utf-8").read()
    t2 = pou_rename.xml_text(t)
    io.open(path, "w", encoding=u"utf-8").write(t2)
    print(u"==== %s ==== изменено: %s" % (nm, t != t2))
    # ссылки вида .S .R .LD .DO
    for pat in (u"\\.S(?![A-Za-z0-9_])", u"\\.R(?![A-Za-z0-9_])",
                u"\\.LD(?![A-Za-z0-9_])", u"\\.DO(?![A-Za-z0-9_])"):
        a = len(re.findall(pat, t))
        b = len(re.findall(pat, t2))
        if a or b:
            print(u"   %-26s было %3d -> стало %3d" % (pat, a, b))
    # остались ли зарезервированные имена в выражениях
    left = set()
    for m in re.finditer(u"<expression>([^<]*)</expression>", t2):
        e = m.group(1)
        if re.search(u"(?<![A-Za-z0-9_])(LD|DO)(?![A-Za-z0-9_])", e) or \
           re.search(u"\\.(S|R)(?![A-Za-z0-9_])", e):
            left.add(e)
    if left:
        print(u"   !! остались: %s" % u", ".join(sorted(left)[:10]))
print(u"\nфайлы в %s" % OUT)
