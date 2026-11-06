# -*- coding: utf-8 -*-
u"""Проверка: после переименования в ЗАВИСИМОСТЯХ не остаётся ключевых имён."""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
import pou_rename
import tools.scan_keywords as SK

DEP = u"C:/dsh8080/work/dep_ccp"
OUT = os.path.join(HERE, u"_renametest_dep")

try:
    import gen_stage4 as _g
except Exception:
    _g = None

DEPENDENCIES = (u"FB_PackByte", u"FB_UnpackByte", u"FB_FullAdder", u"FB_ALU8",
                u"FB_CtrlUnit", u"FB_Mux8x8", u"FB_Mux8x16", u"FB_Memory64K",
                u"FB_Reg8", u"FB_Reg16", u"FB_Reg8Q", u"FB_RegFileQ",
                u"FB_FlagsReg2", u"FB_Rotate8", u"FB_DAA", u"FB_Interrupt",
                u"FB_UnpackWord",
                u"FB_DecodeFull_ALU", u"FB_DecodeFull_ALUI", u"FB_DecodeFull_DATA",
                u"FB_DecodeFull_HLT", u"FB_DecodeFull_JMP", u"FB_DecodeFull_MOV",
                u"FB_DecodeFull_MVI", u"FB_DecodeFull_SPEC", u"FB_DecodeFull_STACK",
                u"FB_Decoder_Full")

if __name__ == u"__main__":
    if not os.path.isdir(DEP):
        print(u"dep_ccp не найден")
        sys.exit(0)
    if _g is not None:
        DEPENDENCIES = _g.DEPENDENCIES
    names = set(DEPENDENCIES)
    n_all, n_fix = pou_rename.fix_dir(DEP, OUT, names=names)
    print(u"файлов %d, изменено %d" % (n_all, n_fix))
    bad = []
    for fn in sorted(os.listdir(OUT)):
        if not fn.endswith(u".plcopenxml"):
            continue
        t = io.open(os.path.join(OUT, fn), encoding=u"utf-8").read()
        m = re.search(u"<InterfaceAsPlainText>\\s*<xhtml[^>]*>(.*?)</xhtml>", t, re.S)
        if m:
            d = m.group(1).replace(u"&lt;", u"<").replace(u"&gt;", u">").replace(u"&amp;", u"&")
            SK.decl_names(d, fn[:-len(u".plcopenxml")], bad)
        for mm in re.finditer(u'<variable name="([^"]+)">', t):
            if mm.group(1).upper() in SK.KEYWORDS:
                bad.append((fn, mm.group(1)))
    print(u"осталось ключевых имён: %d" % len(bad))
    for tag, nm in bad:
        print(u"   %-24s %s" % (tag, nm))
