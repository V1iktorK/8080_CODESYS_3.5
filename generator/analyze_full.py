# -*- coding: utf-8 -*-
"""Разбор расхождения «блоков после импорта» для подшага 3.1.

Сравнивает число <block> по каждому POU в сгенерированном XML и в выгрузке
из CODESYS, и ищет в схемах «висячие» блоки (выход никуда не подключён) -
именно их CODESYS может выбросить при импорте.
"""

import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import builtins
builtins.unicode = str

import fbd_xml
import pou_extra as pe
import pou_decode_full as pd
import pou_cpu_full as pc


def count_per_pou(path):
    if not os.path.exists(path):
        return None
    f = io.open(path, 'r', encoding='utf-8')
    t = f.read()
    f.close()
    out = {}
    for m in re.finditer(r'<pou name="([^"]+)"', t):
        name = m.group(1)
        end = t.find(u'</pou>', m.end())
        seg = t[m.start():end]
        out[name] = seg.count(u'<block ')
    return out


def dangling(p):
    """Блоки, чей выход не читает никто."""
    used = set()
    for net in p.networks:
        for it in net._items:
            if it[0] == u'invar':
                continue
            if it[0] == u'outvar':
                used.add(it[3].eid)
            else:
                for _pin, s in it[3]:
                    used.add(s.eid)
    res = []
    for net in p.networks:
        for it in net._items:
            if it[0] == u'block' and it[1] not in used:
                res.append((net.number, it[2], it[1]))
    return res


def main():
    gens = {}
    for maker in (pe.ALL + pd.ALL + pc.ALL):
        p = maker()
        p._expand_fanout()
        gens[p.name] = sum(1 for net in p.networks for it in net._items if it[0] == u'block')
        d = dangling(p)
        if d:
            print(u"%-22s ВИСЯЧИЕ БЛОКИ: %s" % (p.name, d))
    rex = count_per_pou(os.path.join(HERE, u'..', u'src', u'core_full_reexport.xml'))
    print(u"\n%-22s %6s %6s %s" % (u"POU", u"ген", u"импорт", u"разница"))
    tot_g = tot_r = 0
    for name in sorted(gens):
        g = gens[name]
        r = None if rex is None else rex.get(name)
        tot_g += g
        tot_r += (r or 0)
        flag = u'' if r == g else u'   <-- РАСХОЖДЕНИЕ'
        print(u"%-22s %6d %6s%s" % (name, g, r, flag))
    print(u"%-22s %6d %6d" % (u"ИТОГО", tot_g, tot_r))


if __name__ == '__main__':
    main()
