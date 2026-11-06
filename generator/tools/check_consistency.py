# -*- coding: utf-8 -*-
u"""Проверка СОГЛАСОВАННОСТИ ИМЁН между определениями POU и их потребителями.

Зачем: переименование зарезервированных имён (R->Rx, S->Sx, SEL->SELx)
применяется к PLCopenXML. Если применить его не ко всем POU сразу, определения
получают новые имена, а вызовы остаются со старыми - компиляция даёт каскад
C0007/C0009/C0046/C0004/C0037/C0022. Эта проверка ловит такой рассинхрон
БЕЗ CODESYS, за секунды.

Проверяются три вида расхождений:
  1. вызов блока обращается к выводу, которого нет в интерфейсе этого FB;
  2. вызов блока передаёт на вход, которого нет в интерфейсе этого FB;
  3. обращение вида <экземпляр>.<вывод> к выводу, которого нет у типа экземпляра.

Запуск:  python check_consistency.py <папка_с_plcopenxml>
"""

import io
import os
import re
import sys


def read(path):
    return io.open(path, u"r", encoding=u"utf-8").read()


def iface_of(text):
    u"""Интерфейс POU: имена и типы входов/выходов/локалов."""
    ins, outs, locs = {}, {}, {}
    for tag, dst in ((u"inputVars", ins), (u"outputVars", outs), (u"localVars", locs)):
        m = re.search(u"<%s>(.*?)</%s>" % (tag, tag), text, re.S)
        if not m:
            continue
        for v in re.finditer(
                u'<variable name="([A-Za-z_][A-Za-z0-9_]*)"><type>(?:<([A-Za-z_0-9]+) />'
                u'|<derived name="([^"]+)" />)', m.group(1)):
            name = v.group(1)
            dst[name] = v.group(2) or (u"INST:" + v.group(3))
    return ins, outs, locs


def scan(src_dir, verbose=False):
    files = {}
    for fn in sorted(os.listdir(src_dir)):
        if fn.endswith(u".plcopenxml"):
            files[fn[:-len(u".plcopenxml")]] = read(os.path.join(src_dir, fn))

    types = {}
    for name, text in files.items():
        ins, outs, locs = iface_of(text)
        types[name] = (ins, outs, locs)

    problems = []
    for name, text in files.items():
        ins, outs, locs = types[name]
        # экземпляры внутри этого POU
        inst_type = {}
        for vn, vt in locs.items():
            if vt.startswith(u"INST:"):
                inst_type[vn] = vt[5:]
        for other in types.values():
            for vn, vt in other[0].items():
                if vt.startswith(u"INST:"):
                    inst_type.setdefault(vn, vt[5:])
            for vn, vt in other[1].items():
                if vt.startswith(u"INST:"):
                    inst_type.setdefault(vn, vt[5:])

        # 1-2. вызовы блоков: сверяем formalParameter с интерфейсом
        for m in re.finditer(
                u'(?s)<block localId="(\\d+)" typeName="([^"]+)"(?: instanceName="([^"]*)")?'
                u'(.*?)</block>', text):
            lid, btype, inst, body = m.group(1), m.group(2), m.group(3), m.group(4)
            if btype not in types:
                continue                      # стандартный оператор или внешний тип
            bi, bo, _ = types[btype]
            for pm in re.finditer(u'formalParameter="([A-Za-z_][A-Za-z0-9_]*)"', body):
                pin = pm.group(1)
                if pin not in bi and pin not in bo:
                    problems.append((name, u"block %s (%s)" % (lid, btype),
                                     u"вывод/вход '%s' отсутствует у %s" % (pin, btype)))

        # 3. обращения вида inst.Pin
        for m in re.finditer(u'<expression>([^<]*)</expression>', text):
            e = m.group(1)
            for im in re.finditer(u'\\b([A-Za-z_][A-Za-z0-9_]*)\\.([A-Za-z_][A-Za-z0-9_]*)', e):
                iv, pin = im.group(1), im.group(2)
                if iv not in inst_type:
                    continue
                it = inst_type[iv]
                if it not in types:
                    continue
                ii, oo, _ = types[it]
                if pin not in oo and pin not in ii:
                    problems.append((name, u"%s.%s" % (iv, pin),
                                     u"нет вывода '%s' у типа %s" % (pin, it)))
    return problems, sorted(types.keys())


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else u"."
    problems, names = scan(src)
    print(u"POU проверено: %d" % len(names))
    if not problems:
        print(u"РАССИНХРОНА ИМЁН НЕ НАЙДЕНО: OK")
        return 0
    seen = set()
    for p in problems:
        if p in seen:
            continue
        seen.add(p)
        print(u"  %-18s %-26s %s" % p)
    print(u"ПРОБЛЕМ: %d" % len(seen))
    return 1


if __name__ == u"__main__":
    sys.exit(main())
