# -*- coding: utf-8 -*-
u"""Показать проблемный AND в выгрузке FB_IO_Dispatch и его окружение."""
import sys
import xml.etree.ElementTree as ET

REX = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"


def local(t):
    return t.split(u"}")[-1]


root = ET.parse(REX).getroot()
for pou in root.iter():
    if local(pou.tag) != u"pou" or pou.get(u"name") != u"FB_IO_Dispatch":
        continue
    fbd = None
    for e in pou.iter():
        if local(e.tag) == u"FBD":
            fbd = e
    items = list(fbd)
    by_id = {}
    for it in items:
        by_id[it.get(u"localId")] = it
    print(u"элементов в FBD: %d" % len(items))
    for idx, it in enumerate(items):
        if local(it.tag) != u"block" or it.get(u"typeName") not in (u"AND", u"OR"):
            continue
        ins = []
        for iv in it:
            if local(iv.tag) == u"inputVariables":
                ins = list(iv)
        if len(ins) < 2:
            print(u"\n=== ПРОБЛЕМНЫЙ БЛОК %s localId=%s входов=%d ==="
                  % (it.get(u"typeName"), it.get(u"localId"), len(ins)))
            for j in range(max(0, idx - 6), min(len(items), idx + 3)):
                e = items[j]
                txt = ET.tostring(e, encoding=u"unicode")
                expr = e.find(u".//{http://www.iec.ch/public/PLCopen}expression")
                if expr is None:
                    for sub in e.iter():
                        if local(sub.tag) == u"expression":
                            expr = sub
                print(u"  [%d] %s %s expr=%s" % (
                    j, local(e.tag), e.get(u"localId"),
                    expr.text if expr is not None else u"-"))
            print(ET.tostring(it, encoding=u"unicode")[:1500])
