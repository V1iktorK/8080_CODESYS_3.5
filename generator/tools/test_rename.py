# -*- coding: utf-8 -*-
u"""Локальная проверка переименования имён (обычный Python 3, без CODESYS)."""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pou_rename

SRC = u"C:/dsh8080/work/dep_ccp"


def show(fn):
    p = os.path.join(SRC, fn)
    t = io.open(p, encoding=u"utf-8").read()
    t2 = pou_rename.xml_text(t)
    print(u"==== %s ==== изменено: %s" % (fn, t != t2))
    for pat in (u'name="LD"', u'name="S"', u'name="R"', u'name="DO"',
                u'formalParameter="LD"', u'formalParameter="S"',
                u'formalParameter="R"'):
        a, b = t.count(pat), t2.count(pat)
        if a or b:
            print(u"   %-24s было %3d -> стало %3d" % (pat, a, b))
    m = re.search(u"<InterfaceAsPlainText>.*?</InterfaceAsPlainText>", t2, re.S)
    if m:
        txt = m.group(0)
        lines = [l for l in txt.split(u"\n")
                 if re.match(u"^\\s*(LD|S|R|DO)x?\\s*:", l)]
        print(u"   строки объявления с новыми именами:")
        for l in lines[:8]:
            print(u"      %s" % l.strip())


if __name__ == u"__main__":
    for f in (u"FB_Reg8.plcopenxml", u"FB_ALU8.plcopenxml",
              u"FB_FlagsReg2.plcopenxml"):
        show(f)
