# -*- coding: utf-8 -*-
u"""Поиск связей, которые ссылаются на ВЫХОДНУЮ переменную (outVariable).

У outVariable НЕТ выходной точки, поэтому такая связь при импорте теряется
вместе с ветвью (проявление бага журнала п. 11.2), а блок остаётся с одним
входом - кодогенерация падает:
    C23: Для 'AND' необходимо как минимум '2' операндов
"""
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
        out_ids = set(re.findall(u'<outVariable localId="(\\d+)"', t))
        for m in re.finditer(u'<connection refLocalId="(\\d+)"', t):
            if m.group(1) in out_ids:
                n += 1
                ctx = t[max(0, m.start() - 400):m.start()]
                expr = re.findall(u"<expression>([^<]*)</expression>", ctx)
                print(u"%s: связь на outVariable id=%s (выражение: %s)"
                      % (fn, m.group(1), expr[-1] if expr else u"?"))
print(u"найдено связей на outVariable: %d" % n)
