# -*- coding: utf-8 -*-
u"""Поиск AND/OR с недостатком СВЯЗЕЙ в ВЫГРУЗКЕ из CODESYS (reexport)."""
import io, os, re, sys

PATHS = sys.argv[1:] or [r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"]

n = 0
for p in PATHS:
    if not os.path.isfile(p):
        print(u"нет файла %s" % p)
        continue
    t = io.open(p, encoding=u"utf-8").read()
    print(u"%s: %d символов" % (os.path.basename(p), len(t)))
    for m in re.finditer(u"<block ([^>]*)>(.*?)</block>", t, re.S):
        tn = re.search(u'typeName="([^"]+)"', m.group(1))
        tn = tn.group(1) if tn else u"?"
        if tn not in (u"AND", u"OR"):
            continue
        body = m.group(2)
        kv = len(re.findall(u"<connectionPointIn>", body))
        kc = len(re.findall(u"<connection ", body))
        if kc < 2:
            n += 1
            lid = re.search(u'localId="([^"]+)"', m.group(1))
            print(u"  %s localId=%s входов=%d связей=%d"
                  % (tn, lid.group(1) if lid else u"?", kv, kc))
    # вообще: входы без связи
    empty = len(re.findall(u"<connectionPointIn\\s*/>", t))
    print(u"  пустых входов (<connectionPointIn/>): %d" % empty)
print(u"итого блоков AND/OR со <2 связями: %d" % n)
