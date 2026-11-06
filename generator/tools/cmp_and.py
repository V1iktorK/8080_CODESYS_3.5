# -*- coding: utf-8 -*-
u"""Сравнение блоков AND/OR в сгенерированном XML и в выгрузке CODESYS."""
import io, re, sys
import xml.etree.ElementTree as ET

GEN = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\dsh8080\work\emu_s4\src\s4_pous\FB_IO_Dispatch.plcopenxml"
REX = sys.argv[2] if len(sys.argv) > 2 else \
    r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"


def local(t):
    return t.split(u"}")[-1]


def blocks(path, only_pou=None):
    root = ET.parse(path).getroot()
    out = []
    pous = [p for p in root.iter() if local(p.tag) == u"pou"]
    for pou in pous:
        if only_pou and pou.get(u"name") != only_pou:
            continue
        for blk in pou.iter():
            if local(blk.tag) != u"block":
                continue
            ins = []
            for iv in blk:
                if local(iv.tag) == u"inputVariables":
                    ins = list(iv)
            out.append((blk.get(u"typeName"), len(ins), blk.get(u"localId")))
    return out


g = blocks(GEN)
print(u"СГЕНЕРИРОВАНО (%s): блоков %d" % (GEN.split(u"\\")[-1], len(g)))
for tn, k, lid in g:
    if tn in (u"AND", u"OR") and k != 2:
        print(u"   %s входов=%d localId=%s" % (tn, k, lid))

r = blocks(REX, u"FB_IO_Dispatch")
print(u"ВЫГРУЗКА FB_IO_Dispatch: блоков %d" % len(r))
for tn, k, lid in r:
    if tn in (u"AND", u"OR") and k < 2:
        print(u"   %s входов=%d localId=%s" % (tn, k, lid))
