# -*- coding: utf-8 -*-
u"""ЛОКАЛЬНЫЙ АНАЛИЗ ВЫГРУЗКИ CODESYS (без запуска CODESYS).

Ищет в XML (выгрузка проекта или сгенерированный файл) ровно те дефекты,
которые видит только кодогенератор:

  1. C80  - вызов пользовательского FB БЕЗ instanceName (block typeName="FB_..."
            без атрибута instanceName) -> "Функциональный блок ... должен иметь
            экземпляр";
  2. C48  - обращение к ДВУМЕРНОМУ массиву одним индексом: Disk[7];
  3. C32  - то же самое, но в позиции приёмника (Disk[7] := BYTE).

Запуск (CPython 3):
    python tools\\scan_defects.py <файл.xml> [<файл2.xml> ...]
"""
import io
import re
import sys
import os

RE_POU = re.compile(r'<pou name="([^"]+)"')
RE_BLOCK = re.compile(r'<block localId="(\d+)" typeName="([^"]+)"([^>]*)>')
RE_INVAR = re.compile(r'<inVariable localId="(\d+)"[^>]*>.*?<expression>(.*?)</expression>',
                      re.S)
RE_OUTVAR = re.compile(r'<outVariable localId="(\d+)"[^>]*>.*?<expression>(.*?)</expression>',
                       re.S)
# обращение к двумерному массиву одним индексом: Disk[7]  (но не Disk[7, 8])
RE_ONE_IDX = re.compile(r'(\w+)\s*\[\s*([^,\[\]]+?)\s*\]')

# известные двумерные массивы проекта
ARR2D = (u"Disk",)


def unesc(s):
    return (s.replace(u"&lt;", u"<").replace(u"&gt;", u">")
             .replace(u"&quot;", u'"').replace(u"&amp;", u"&"))


def split_pous(text):
    u"""Разбить текст выгрузки на куски по POU: [(имя, текст_куска)]."""
    out = []
    ms = list(RE_POU.finditer(text))
    for i, m in enumerate(ms):
        end = ms[i + 1].start() if i + 1 < len(ms) else len(text)
        out.append((m.group(1), text[m.start():end]))
    return out


def scan_blocks(pou, body):
    u"""C80: вызов FB-типа без экземпляра."""
    bad = []
    for m in RE_BLOCK.finditer(body):
        lid, tname, rest = m.group(1), m.group(2), m.group(3)
        if tname.startswith(u"FB_") and u"instanceName" not in rest:
            bad.append((lid, tname))
    return bad


def scan_one_index(exprs):
    u"""C48/C32: двумерный массив с одним индексом."""
    bad = []
    for lid, expr in exprs:
        e = unesc(expr)
        for m in RE_ONE_IDX.finditer(e):
            if m.group(1) in ARR2D:
                bad.append((lid, e))
                break
    return bad


def main():
    files = sys.argv[1:]
    if not files:
        files = [r"C:\dsh8080\work\emu_s4\src\stage4_full_reexport.xml"]
    for path in files:
        if not os.path.isfile(path):
            print(u"нет файла: %s" % path)
            continue
        text = io.open(path, "r", encoding="utf-8", errors="replace").read()
        print(u"")
        print(u"================ %s (%d символов) ================" % (path, len(text)))
        tot_c80 = tot_c48 = 0
        for name, body in split_pous(text):
            b80 = scan_blocks(name, body)
            exprs = [(m.group(1), m.group(2)) for m in RE_INVAR.finditer(body)]
            exprs += [(m.group(1), m.group(2)) for m in RE_OUTVAR.finditer(body)]
            b48 = scan_one_index(exprs)
            if b80 or b48:
                print(u"")
                print(u"--- POU %s : C80=%d C48/C32=%d" % (name, len(b80), len(b48)))
                for lid, t in b80[:20]:
                    print(u"    C80  localId=%s typeName=%s (нет instanceName)" % (lid, t))
                for lid, e in b48[:20]:
                    print(u"    C48  localId=%s expr=%s" % (lid, e))
                if len(b48) > 20:
                    print(u"    ... всего C48/C32 в POU: %d" % len(b48))
            tot_c80 += len(b80)
            tot_c48 += len(b48)
        print(u"")
        print(u"ИТОГО: C80=%d  C48/C32(одномерный доступ к Disk)=%d  POU=%d"
              % (tot_c80, tot_c48, len(split_pous(text))))


main()
