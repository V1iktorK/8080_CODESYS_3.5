# -*- coding: utf-8 -*-
u"""Поиск блока AND/OR с МЕНЬШЕ чем двумя входами (это и есть ошибка C23)."""
import io, os, re, sys

DIRS = sys.argv[1:] or [r"C:\dsh8080\work\emu_s4\src\s4_pous",
                        r"C:\dsh8080\work\emu_s4\src\dep_fix"]

n = 0
for d in DIRS:
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(u".plcopenxml"):
            continue
        t = io.open(os.path.join(d, fn), encoding=u"utf-8").read()
        for m in re.finditer(u"<block ([^>]*)>(.*?)</block>", t, re.S):
            tn = re.search(u'typeName="([^"]+)"', m.group(1))
            tn = tn.group(1) if tn else u"?"
            if tn not in (u"AND", u"OR"):
                continue
            body = m.group(2)
            k = len(re.findall(u"<variable formalParameter=", body)) + \
                len(re.findall(u"<variable>", body))
            if k < 2:
                n += 1
                lid = re.search(u'localId="([^"]+)"', m.group(1))
                print(u"%s: %s localId=%s входов=%d"
                      % (fn, tn, lid.group(1) if lid else u"?", k))
print(u"найдено блоков с <2 входами: %d" % n)
