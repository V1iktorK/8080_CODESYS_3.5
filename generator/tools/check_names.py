# -*- coding: utf-8 -*-
u"""Проверка имён: зарезервированные слова и столкновения регистра.

Запускается обычным Python 3, БЕЗ CODESYS. Проверяет:
  1. сгенерированные POU (модули этапов 3.2-3.6 и тестовый слой) - по объектам
     Pou в памяти;
  2. зависимости из dep_ccp/*.plcopenxml - по тексту InterfaceAsPlainText;
  3. GVL/DUT - по тексту объявлений.

Причина появления проверки: кодогенерация (включается только вместе с
конфигурацией задач) не принимает имена LD, S, R, DO и не различает регистр.
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

import pou_rename

RESERVED = set(pou_rename.RESERVED.keys())


def check_decl(text, tag, out):
    u"""Разбор текста объявления: секции, имена, типы."""
    sec = None
    names = {}
    for line in text.split(u"\n"):
        s = line.strip()
        if s.startswith(u"(*") or s.startswith(u"//") or not s:
            continue
        if s.startswith(u"VAR"):
            sec = s.split()[0]
            names.setdefault(sec, [])
            continue
        if s.startswith(u"END_VAR"):
            sec = None
            continue
        m = re.match(u"^([A-Za-z_][A-Za-z0-9_]*)\\s*:(.*)$", s)
        if m and sec:
            nm = m.group(1)
            names[sec].append(nm)
            if nm in RESERVED:
                out.append((tag, u"ЗАРЕЗЕРВИРОВАНО: %s" % nm))
    # столкновения регистра между секциями и внутри одной
    seen = {}
    for sec_name, lst in names.items():
        for nm in lst:
            low = nm.lower()
            if low in seen and seen[low] != nm:
                out.append((tag, u"РЕГИСТР: '%s' и '%s'" % (seen[low], nm)))
            seen[low] = nm
    return names


def main():
    out = []
    # ---- 1. сгенерированные POU ----
    import pou_cpm_defs, pou_io_defs, pou_decode_full
    import pou_cpu_io, pou_cpm_trap, pou_bios, pou_bdos, pou_ccp
    import pou_com_loader, pou_io, pou_io_hw, pou_prg_io
    import pou_test_defs, pou_test8080, pou_testcpm, pou_testio

    groups = (pou_cpu_io.ALL + pou_cpm_trap.ALL + pou_bios.ALL + pou_bdos.ALL +
              pou_ccp.ALL + pou_com_loader.ALL + pou_io.ALL + pou_io_hw.ALL +
              pou_prg_io.ALL + pou_test8080.ALL + pou_testcpm.ALL +
              pou_testio.ALL)
    npou = 0
    for mk in groups:
        p = mk()
        npou += 1
        check_decl(p.declaration(), p.name, out)
    print(u"проверено сгенерированных POU: %d" % npou)

    # ---- 2. GVL / DUT ----
    gvls = [(u"GVL_CPU", pou_decode_full.gvl_cpu_text())]
    gvls.append((u"GVL_MEM", u"VAR_GLOBAL\n\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n"))
    for nm, fn in pou_io_defs.GVL_ALL:
        gvls.append((nm, fn()))
    gvls.append((u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text()))
    gvls.append((u"GVL_CPM", pou_cpm_defs.gvl_cpm_text()))
    gvls.append((u"GVL_DISK", pou_cpm_defs.gvl_disk_text()))
    gvls.append((u"GVL_TEST", pou_test_defs.gvl_test_text()))
    for nm, text in pou_cpm_defs.DUT_ALL + pou_io_defs.DUT_ALL + pou_test_defs.DUT_ALL:
        check_decl(text, nm, out)
    for nm, text in gvls:
        check_decl(text, nm, out)
    print(u"проверено GVL/DUT: %d" % (len(gvls) + 7))

    # ---- 3. зависимости ----
    dep = u"C:/dsh8080/work/dep_ccp"
    if os.path.isdir(dep):
        nd = 0
        for fn in sorted(os.listdir(dep)):
            if not fn.endswith(u".plcopenxml"):
                continue
            t = io.open(os.path.join(dep, fn), encoding=u"utf-8").read()
            m = re.search(u"<InterfaceAsPlainText>\\s*<xhtml[^>]*>(.*?)</xhtml>", t, re.S)
            if not m:
                continue
            nd += 1
            d = m.group(1).replace(u"&lt;", u"<").replace(u"&gt;", u">").replace(u"&amp;", u"&")
            check_decl(d, fn[:-len(u".plcopenxml")], out)
        print(u"проверено зависимостей: %d" % nd)
    else:
        print(u"dep_ccp не найден")

    print(u"\n=== НАЙДЕНО ПРОБЛЕМ: %d ===" % len(out))
    for tag, msg in out:
        print(u"  %-26s %s" % (tag, msg))


if __name__ == u"__main__":
    main()
