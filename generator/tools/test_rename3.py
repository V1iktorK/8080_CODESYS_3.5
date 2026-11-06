# -*- coding: utf-8 -*-
u"""Проверка: после переименования в POU НЕ остаётся ключевых имён.

Гоняет тот же конвейер, что и сборка: генерирует POU -> пишет PLCopenXML ->
применяет pou_rename -> заново разбирает объявление и ищет ключевые слова.
"""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, HERE)
try:
    import builtins
    builtins.unicode = str
    builtins.unichr = chr
except Exception:
    pass

import fbd_xml
import pou_rename
import tools.scan_keywords as SK

import pou_cpu_io, pou_cpm_trap, pou_bios, pou_bdos, pou_ccp
import pou_com_loader, pou_io, pou_io_hw, pou_prg_io
import pou_test8080, pou_testcpm, pou_testio

OUT = os.path.join(HERE, u"_renametest")
if not os.path.isdir(OUT):
    os.makedirs(OUT)

GROUPS = (pou_cpu_io.ALL + pou_cpm_trap.ALL + pou_bios.ALL + pou_bdos.ALL +
          pou_ccp.ALL + pou_com_loader.ALL + pou_io.ALL + pou_io_hw.ALL +
          pou_prg_io.ALL + pou_test8080.ALL + pou_testcpm.ALL + pou_testio.ALL)


def main():
    bad = []
    for mk in GROUPS:
        p = mk()
        path = os.path.join(OUT, p.name + u".plcopenxml")
        fbd_xml.write_project(path, [p], p.name)
        pou_rename.fix_file(path)
        t = io.open(path, encoding=u"utf-8").read()
        m = re.search(u"<InterfaceAsPlainText>\\s*<xhtml[^>]*>(.*?)</xhtml>", t, re.S)
        if m:
            d = m.group(1).replace(u"&lt;", u"<").replace(u"&gt;", u">").replace(u"&amp;", u"&")
            before = len(bad)
            SK.decl_names(d, p.name, bad)
        # заодно: имена переменных прямо в структурном интерфейсе
        for mm in re.finditer(u'<variable name="([^"]+)">', t):
            if mm.group(1).upper() in SK.KEYWORDS:
                bad.append((p.name, mm.group(1)))
    print(u"POU проверено: %d" % len(GROUPS))
    print(u"осталось ключевых имён: %d" % len(bad))
    for tag, nm in bad:
        print(u"   %-22s %s" % (tag, nm))


if __name__ == u"__main__":
    main()
