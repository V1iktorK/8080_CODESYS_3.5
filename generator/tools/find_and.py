# -*- coding: utf-8 -*-
u"""Поиск источника ошибки C23 "Для 'AND' необходимо как минимум '2' операндов"."""
import io, os, re, sys, collections

DIRS = sys.argv[1:] or [r"C:\dsh8080\work\emu_s4\src\s4_pous",
                        r"C:\dsh8080\work\emu_s4\src\dep_fix"]

for d in DIRS:
    if not os.path.isdir(d):
        continue
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(u".plcopenxml"):
            continue
        t = io.open(os.path.join(d, fn), encoding=u"utf-8").read()
        for m in re.finditer(u"<expression>([^<]*)</expression>", t):
            e = m.group(1)
            if u" AND " in e or u" OR " in e:
                print(u"[выражение] %s: %r" % (fn, e))
        for m in re.finditer(u"<block ([^>]*)>(.*?)</block>", t, re.S):
            tn = re.search(u'typeName="([^"]+)"', m.group(1))
            tn = tn.group(1) if tn else u"?"
            if tn not in (u"AND", u"OR"):
                continue
            body = m.group(2)
            k = len(re.findall(u"<variable formalParameter=", body))
            k2 = len(re.findall(u"<variable>", body))
            if k + k2 != 2:
                print(u"[блок] %s: %s входов=%d (+%d без имени)" % (fn, tn, k, k2))
