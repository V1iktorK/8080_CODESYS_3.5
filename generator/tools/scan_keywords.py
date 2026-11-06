# -*- coding: utf-8 -*-
u"""Поиск ВСЕХ имён, совпадающих с ключевыми словами IEC/CODESYS.

Причина: кодогенерация (появляется только вместе с конфигурацией задач) не
принимает имена, которые в языке зарезервированы. Разбор объявлений их
пропускает, поэтому ошибка видна только на сборке ПЛК:
    C9: Обнаружен недопустимый символ 'st' / 'to' / 'Bit' / 'Sel' / 'exp'

Скрипт печатает список (файл, имя), чтобы разом дополнить таблицу
переименования pou_rename.RESERVED, а не искать имена по одному прогону.
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

# ключевые слова IEC 61131-3, операторы IL, имена стандартных функций/типов
KEYWORDS = set(u"""
ACTION END_ACTION ARRAY AT BY CASE END_CASE CONFIGURATION END_CONFIGURATION
CONSTANT CONTINUE DATA END_DATA DO ELSE ELSIF EXIT F_EDGE R_EDGE FALSE FOR TO
FUNCTION END_FUNCTION FUNCTION_BLOCK END_FUNCTION_BLOCK IF THEN END_IF
INITIAL_STEP END_INITIAL_STEP LABEL END_LABEL NODE END_NODE NON_RETAIN NOT OF
PROGRAM END_PROGRAM RETAIN REPEAT UNTIL END_REPEAT RESOURCE END_RESOURCE RETURN
STEP END_STEP STRUCT END_STRUCT TRANSITION END_TRANSITION TRUE TYPE END_TYPE
VAR END_VAR VAR_INPUT VAR_OUTPUT VAR_IN_OUT VAR_EXTERNAL VAR_GLOBAL VAR_ACCESS
VAR_CONFIG VAR_TEMP WHILE END_WHILE WITH
AND OR XOR MOD AND_THEN OR_ELSE
LT GT LE GE EQ NE ADD SUB MUL DIV MOVE SHL SHR ROL ROR SEL MUX LIMIT MAX MIN
ABS SQRT LN LOG EXP EXPT SIN COS TAN ASIN ACOS ATAN TRUNC ROUND
LD LDN ST STN S R JMP CAL RET
TON TOF TP RS SR R_TRIG F_TRIG CTU CTD CTUD
BIT BOOL BYTE WORD DWORD LWORD SINT USINT INT UINT DINT UDINT LINT ULINT
REAL LREAL TIME LTIME DATE DT TOD TIME_OF_DAY DATE_AND_TIME STRING WSTRING
POINTER REFERENCE REF ANY VOID __NEW __DELETE THIS SUPER
""".split())


def decl_names(text, tag, out):
    sec = None
    for line in text.split(u"\n"):
        s = line.strip()
        if not s or s.startswith(u"(*") or s.startswith(u"//"):
            continue
        if s.startswith(u"VAR"):
            sec = s.split()[0]
            continue
        if s.startswith(u"END_VAR"):
            sec = None
            continue
        m = re.match(u"^([A-Za-z_][A-Za-z0-9_]*)\\s*(AT\\s+\\S+)?\\s*:(.*)$", s)
        if m and sec and m.group(1).upper() in KEYWORDS:
            out.append((tag, m.group(1)))


def scan_generated(out):
    import pou_decode_full, pou_cpm_defs, pou_io_defs, pou_io_hw, pou_test_defs
    import pou_cpu_io, pou_cpm_trap, pou_bios, pou_bdos, pou_ccp
    import pou_com_loader, pou_io, pou_prg_io, pou_test8080, pou_testcpm, pou_testio

    groups = (pou_cpu_io.ALL + pou_cpm_trap.ALL + pou_bios.ALL + pou_bdos.ALL +
              pou_ccp.ALL + pou_com_loader.ALL + pou_io.ALL + pou_io_hw.ALL +
              pou_prg_io.ALL + pou_test8080.ALL + pou_testcpm.ALL +
              pou_testio.ALL)
    n = 0
    for mk in groups:
        p = mk()
        n += 1
        decl_names(p.declaration(), p.name, out)
    print(u"POU проверено: %d" % n)

    gvls = [(u"GVL_CPU", pou_decode_full.gvl_cpu_text()),
            (u"GVL_MEM", u"VAR_GLOBAL\n\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n"),
            (u"GVL_CPM", pou_cpm_defs.gvl_cpm_text()),
            (u"GVL_DISK", pou_cpm_defs.gvl_disk_text()),
            (u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text()),
            (u"GVL_TEST", pou_test_defs.gvl_test_text())]
    for nm, fn in pou_io_defs.GVL_ALL:
        gvls.append((nm, fn()))
    for nm, text in gvls:
        decl_names(text, nm, out)
    for nm, text in (pou_cpm_defs.DUT_ALL + pou_io_defs.DUT_ALL +
                     pou_test_defs.DUT_ALL):
        decl_names(text, nm, out)
    print(u"GVL/DUT проверено: %d" % len(gvls))


def scan_deps(out, dep=u"C:/dsh8080/work/dep_ccp"):
    n = 0
    if not os.path.isdir(dep):
        print(u"dep_ccp не найден")
        return
    for fn in sorted(os.listdir(dep)):
        if not fn.endswith(u".plcopenxml"):
            continue
        t = io.open(os.path.join(dep, fn), encoding=u"utf-8").read()
        m = re.search(u"<InterfaceAsPlainText>\\s*<xhtml[^>]*>(.*?)</xhtml>", t, re.S)
        if not m:
            continue
        n += 1
        d = m.group(1).replace(u"&lt;", u"<").replace(u"&gt;", u">").replace(u"&amp;", u"&")
        decl_names(d, fn[:-len(u".plcopenxml")], out)
    print(u"зависимостей проверено: %d" % n)


def main():
    out = []
    scan_generated(out)
    scan_deps(out)
    print(u"\n=== НАЙДЕНО КЛЮЧЕВЫХ ИМЁН: %d ===" % len(out))
    seen = {}
    for tag, nm in out:
        seen.setdefault(nm.upper(), []).append(tag)
    for nm in sorted(seen):
        print(u"  %-10s : %s" % (nm, u", ".join(sorted(set(seen[nm]))[:8])))
    return out


if __name__ == u"__main__":
    main()
