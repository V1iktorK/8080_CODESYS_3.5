# -*- coding: utf-8 -*-
u"""РАЗБОР «СЛЕПЫХ ЗОН» (этап A5): кто и куда подаёт пин, которого нет в интерфейсе.

tools/check_types.py находит связи, которые НЕ проверяются, потому что имени пина
нет в интерфейсе вызываемого блока. Их оказалось ровно 5, и все - на именах,
которые правит переименование (LD->LDx, Sel->SELx, S->Sx). Это подозрительно:
значит, ПОТРЕБИТЕЛЬ и ОПРЕДЕЛЕНИЕ разошлись по имени пина.

Скрипт печатает для каждой такой пары:
  * объявленные пины блока (имя : тип) - как их видит определение;
  * все места вызова (POU, сеть, localId, тип блока, переданные пины).

Запуск:  python tools\\check_pins.py
"""
import builtins
import collections
import io
import os
import sys

builtins.unicode = str

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GEN)

import pou_deps

TARGETS = (u"FB_REG16", u"FB_MUX8X8", u"FB_MUX8X16", u"FB_CTRLUNIT")
WANT = {u"FB_REG16": u"LD", u"FB_MUX8X8": u"SEL", u"FB_MUX8X16": u"SEL",
        u"FB_CTRLUNIT": u"S"}

import check_types as CT   # noqa: E402  (нужен его GROUPS и структуры)

out = io.open(u"C:/dsh8080/work/emu_s4/check_pins.txt", u"w", encoding=u"utf-8")


def W(s):
    out.write(s + u"\n")
    print(s)


def main():
    W(u"=== 1. ОБЪЯВЛЕННЫЕ ПИНЫ ЦЕЛЕВЫХ БЛОКОВ (из первоисточника) ===")
    ifaces = {}
    for nm in pou_deps.all_names():
        p = pou_deps.make(nm)
        if p is None:
            continue
        ifaces[p.name.upper()] = (p, p.inputs, p.outputs)
    for t in TARGETS:
        ent = ifaces.get(t)
        if ent is None:
            W(u"%s: НЕ НАЙДЕН в pou_deps" % t)
            continue
        p, ins, outs = ent
        W(u"")
        W(u"%s (POU %r)" % (t, p.name))
        W(u"    входы : %s" % u", ".join([u"%s:%s" % (v.name, v.type) for v in ins]))
        W(u"    выходы: %s" % u", ".join([u"%s:%s" % (v.name, v.type) for v in outs]))
        if WANT[t].upper() not in [v.name.upper() for v in ins]:
            W(u"    !! пина %r В ВХОДАХ НЕТ" % WANT[t])

    W(u"")
    W(u"=== 2. ВЫЗОВЫ С «ЧУЖИМ» ПИНОМ ===")
    W(u"(POU, сеть, localId, блок, пины-входы и их имена)")

    hits = collections.Counter()
    for grp, makers in CT.GROUPS:
        for mk in makers:
            p = mk()
            for net_i, net in enumerate(p.networks):
                for it in net._items:
                    if it[0] != u"block":
                        continue
                    _, lid, tname, ins, outs, _x, _y = it
                    tu = tname.upper()
                    if tu not in WANT:
                        continue
                    names = [pin for pin, _src in ins]
                    have = ifaces.get(tu)
                    decl = [v.name.upper() for v in have[1]] if have else []
                    bad = [n for n in names if n and n.upper() not in decl
                           and n.upper() not in (u"EN", u"ENO")]
                    if not bad:
                        continue
                    hits[u"%s <- %s" % (p.name, tu)] += 1
                    W(u"")
                    W(u"  POU=%s  сеть=%d  localId=%d  блок=%s"
                      % (p.name, net_i, lid, tname))
                    W(u"    объявленные входы: %s" % u", ".join(decl))
                    W(u"    переданы пины    : %s" % u", ".join([n for n in names if n]))
                    W(u"    ЛИШНИЕ пины      : %s" % u", ".join(bad))
    W(u"")
    W(u"ИТОГО мест: %s" % hits.most_common())

    # то же для 27 зависимостей - они тоже вызывают друг друга
    W(u"")
    W(u"=== 3. ТО ЖЕ ВНУТРИ 27 ЗАВИСИМОСТЕЙ ===")
    hits2 = collections.Counter()
    for nm in pou_deps.all_names():
        p = pou_deps.make(nm)
        if p is None:
            continue
        for net_i, net in enumerate(p.networks):
            for it in net._items:
                if it[0] != u"block":
                    continue
                _, lid, tname, ins, outs, _x, _y = it
                tu = tname.upper()
                if tu not in WANT:
                    continue
                names = [pin for pin, _src in ins]
                have = ifaces.get(tu)
                decl = [v.name.upper() for v in have[1]] if have else []
                bad = [n for n in names if n and n.upper() not in decl
                       and n.upper() not in (u"EN", u"ENO")]
                if not bad:
                    continue
                hits2[u"%s <- %s" % (p.name, tu)] += 1
                W(u"  POU=%s сеть=%d localId=%d блок=%s ЛИШНИЕ=%s"
                  % (p.name, net_i, lid, tname, u",".join(bad)))
    W(u"ИТОГО: %s" % hits2.most_common())


main()
out.close()
