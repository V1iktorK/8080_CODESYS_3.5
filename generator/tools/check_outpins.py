# -*- coding: utf-8 -*-
u"""ПРОВЕРКА ПОРЯДКА/СОСТАВА ЧИТАЕМЫХ ВЫВОДОВ ВЫЗОВА FB (этап A5).

ЗАЧЕМ. Найдена ошибка, стоившая этапа: единственный в проекте вызов, который
читал ПОДМНОЖЕСТВО выводов FB, давал
    C32: Невозможно конвертировать тип 'BYTE' в тип 'BOOL'.

Причина. Импортёр PLCopenXML сопоставляет выводы вызова ПОЗИЦИОННО: первый
прочитанный вывод привязывается к ПЕРВОМУ объявленному в <outputVariables>.
Вызов FB_ALU8 в сети "Флаги S/Z/P результата DAA" объявлял все шесть выводов
    [R, CY, AC, S, Z, P]
а читал только три - S, Z, P. Позиционно они попадали на R (BYTE), CY, AC,
то есть daa_s (BOOL) получал выход Rx типа BYTE - отсюда C32.

Все остальные вызовы FB в проекте читают ВСЕ свои выводы и в порядке
объявления, поэтому дефект проявлялся ровно один раз и маскировался тем, что
тело вызывающего POU при проверках опустошалось (мёртвый вызов не генерируется).

ПРАВИЛО, КОТОРОЕ ПРОВЕРЯЕТ ЭТОТ СКРИПТ:
    последовательность ЧИТАЕМЫХ выводов блока должна быть ПРЕФИКСОМ списка
    ОБЪЯВЛЕННЫХ выводов (в том же порядке).
Тогда и позиционное, и именованное сопоставление дают верный результат.

Запуск:  python tools\\check_outpins.py
Отчёт:   C:\\dsh8080\\work\\emu_s4\\outpins.txt
"""
import builtins
import io
import os
import sys

builtins.unicode = str

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GEN)
sys.path.insert(0, os.path.join(GEN, u"tools"))

import check_types as CT   # noqa: E402
import pou_deps            # noqa: E402

OUT = u"C:/dsh8080/work/emu_s4/outpins.txt"
BAD = []


def scan(p, ifaces, f):
    # ВАЖНО: проверяем ОТРИСОВАННУЮ схему, а не исходные объекты генератора.
    # fbd_xml.Pou.render() СНАЧАЛА применяет _prune_outputs() (оставляет в вызове
    # только читаемые выводы, в порядке чтения) и только потом _expand_fanout().
    # Если проверять объекты ДО render(), правило будет выглядеть нарушенным
    # всегда - и проверка станет бесполезной.
    p.render()
    items = []
    for net_i, net in enumerate(p.networks):
        for it in net._items:
            items.append((net_i, it))

    # в каком порядке читаются выводы каждого блока (по всему POU, документный порядок)
    used = {}
    for net_i, it in items:
        srcs = []
        if it[0] == u"outvar":
            srcs = [it[3]]
        elif it[0] == u"block":
            srcs = [s for _, s in it[3]]
        for s in srcs:
            if s is None or not s.pin:
                continue
            used.setdefault(s.eid, []).append(s.pin)

    for net_i, it in items:
        if it[0] != u"block":
            continue
        _, lid, tname, ins, outs, _x, _y = it
        b = tname.upper()
        if b not in ifaces:
            continue
        got = used.get(lid, [])
        if not got:
            continue
        # уникализируем, сохраняя порядок
        seq = []
        for g in got:
            if g not in seq:
                seq.append(g)
        if seq == list(outs)[:len(seq)]:
            continue
        BAD.append((p.name, net_i, lid, tname, outs, seq))
        f.write(u"%-22s сеть %2d localId=%-5d %-18s\n"
                % (p.name, net_i, lid, tname))
        f.write(u"      объявлено: %s\n" % u", ".join(outs))
        f.write(u"      читается : %s   <-- НЕ префикс объявленного\n"
                % u", ".join(seq))


def main():
    ifaces = CT.collect_fb_interfaces()
    f = io.open(OUT, u"w", encoding=u"utf-8")
    f.write(u"ВЫЗОВЫ FB, ЧИТАЮЩИЕ ВЫВОДЫ НЕ В ПОРЯДКЕ ОБЪЯВЛЕНИЯ\n\n")
    for grp, makers in CT.GROUPS:
        for mk in makers:
            scan(mk(), ifaces, f)
    for nm in pou_deps.all_names():
        p = pou_deps.make(nm)
        if p is not None:
            scan(p, ifaces, f)
    f.write(u"\nВСЕГО мест: %d\n" % len(BAD))
    f.close()
    print(u"ВСЕГО мест: %d -> %s" % (len(BAD), OUT))
    for x in BAD[:25]:
        print(u"   %s сеть %d %s: объявлено %s, читается %s"
              % (x[0], x[1], x[3], x[4], x[5]))


main()
