# -*- coding: utf-8 -*-
u"""Строгий разбор выгрузки CODESYS: блоки AND/OR с числом входов < 2."""
import sys
import xml.etree.ElementTree as ET

P = sys.argv[1] if len(sys.argv) > 1 else \
    r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"

NS = u"{http://www.plcopen.org/xml/tc6_0200}"


def local(tag):
    return tag.split(u"}")[-1]


tree = ET.parse(P)
root = tree.getroot()
print(u"корень: %s" % local(root.tag))

bad = 0
n_and = 0
for pou in root.iter():
    if local(pou.tag) != u"pou":
        continue
    name = pou.get(u"name")
    for blk in pou.iter():
        if local(blk.tag) != u"block":
            continue
        tn = blk.get(u"typeName")
        if tn not in (u"AND", u"OR", u"XOR"):
            continue
        n_and += 1
        ins = []
        for iv in blk:
            if local(iv.tag) == u"inputVariables":
                ins = list(iv)
        conns = 0
        for v in ins:
            for cp in v:
                if local(cp.tag) == u"connectionPointIn":
                    if len(list(cp)) > 0:
                        conns += 1
        if len(ins) < 2 or conns < 2:
            bad += 1
            print(u"  %s: %s localId=%s входов=%d связей=%d"
                  % (name, tn, blk.get(u"localId"), len(ins), conns))
print(u"блоков AND/OR/XOR всего: %d, проблемных: %d" % (n_and, bad))
