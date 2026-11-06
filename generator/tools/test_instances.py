# -*- coding: utf-8 -*-
u"""Проверка: у диспетчеров BIOS/BDOS все экземпляры функций объявлены."""
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
import pou_bdos, pou_bios, pou_ccp, pou_io, pou_io_hw, pou_cpu_io

D = os.path.join(HERE, u"_renametest")
if not os.path.isdir(D):
    os.makedirs(D)

CASES = [pou_bdos.make_bdos_dispatch(), pou_bios.make_bios_dispatch(),
         pou_ccp.make_ccp(), pou_io.make_io_dispatch(),
         pou_cpu_io.ALL[0]()]

for p in CASES:
    f = os.path.join(D, p.name + u".plcopenxml")
    fbd_xml.write_project(f, [p], p.name)
    t = io.open(f, encoding=u"utf-8").read()
    decl = set(re.findall(u'<variable name="([^"]+)">', t))
    miss = [m.group(2) for m in
            re.finditer(u'<block [^>]*typeName="(FB_[^"]+)" instanceName="([^"]+)"', t)
            if m.group(2) not in decl]
    print(u"%-18s объявлений=%3d  необъявленных экземпляров=%d %s"
          % (p.name, len(decl), len(miss), u", ".join(miss[:5])))
