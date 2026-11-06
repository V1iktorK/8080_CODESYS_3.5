# -*- coding: utf-8 -*-
u"""Найти, в каком POU находится блок с указанным localId (в выгрузке CODESYS)."""
import io, re, sys

P = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"
LID = sys.argv[2] if len(sys.argv) > 2 else u"360000000004"

t = io.open(P, encoding=u"utf-8").read()
pos = t.find(u'localId="%s"' % LID)
print(u"позиция: %d" % pos)
if pos > 0:
    pou = None
    for m in re.finditer(u'<pou name="([^"]+)"', t[:pos]):
        pou = m.group(1)
    print(u"POU: %s" % pou)
    print(t[max(0, pos - 1500):pos + 900])
