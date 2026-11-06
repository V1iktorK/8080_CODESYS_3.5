# -*- coding: utf-8 -*-
u"""Утилита: убрать третий аргумент у I(n, имя, позиция).

I(n, e) в pou_cpm_defs.py принимает ТОЛЬКО два аргумента (имя/выражение);
координаты передаются блокам, а не входным переменным. Утилита чинит
вызовы вида I(n, u"X", fbd_xml.COL_BLK + 200) -> I(n, u"X").
"""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PAT = re.compile(r'I\(n,\s*(u"[^"]*")\s*,\s*[fA-Za-z0-9_.\s+*()\-]*\)')


def fix(path):
    t = io.open(path, encoding="utf-8").read()
    n = len(PAT.findall(t))
    t2 = PAT.sub(lambda m: u'I(n, %s)' % m.group(1), t)
    if t2 != t:
        io.open(path, "w", encoding="utf-8").write(t2)
    print(u"%s: исправлено %d" % (os.path.basename(path), n))


if __name__ == "__main__":
    for f in ("pou_test8080.py", "pou_testcpm.py", "pou_testio.py"):
        fix(os.path.join(HERE, f))
