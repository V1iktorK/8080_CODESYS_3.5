# -*- coding: utf-8 -*-
"""Почему CODESYS теряет 2 блока SEL при импорте FB_CPU8080_FULL.

Строит для каждого элемента SEL подпись из описаний его входов (G, IN0, IN1)
и сравнивает мультимножества подписей в сгенерированном XML и в выгрузке.
Так видно, какие именно SEL пропали и чем они отличались.
"""

import io, os, re, sys, collections

HERE = os.path.dirname(os.path.abspath(__file__))


def load(path):
    f = io.open(path, 'r', encoding='utf-8')
    t = f.read()
    f.close()
    return t


def pou_seg(t, name):
    m = re.search(r'<pou name="%s"' % re.escape(name), t)
    e = t.find(u'</pou>', m.end())
    return t[m.start():e]


def elements(seg):
    """localId -> (kind, info) для всех элементов сегмента."""
    els = {}
    for m in re.finditer(r'<(inVariable|outVariable|block)\s+localId="(\d+)"([^>]*)>', seg):
        kind, lid, attrs = m.group(1), int(m.group(2)), m.group(3)
        end = seg.find(u'</%s>' % kind, m.end())
        body = seg[m.end():end]
        if kind == 'block':
            tn = re.search(r'typeName="([^"]+)"', attrs)
            info = tn.group(1) if tn else u'?'
        else:
            ex = re.search(r'<expression>([^<]*)</expression>', body)
            info = ex.group(1) if ex else u'?'
        els[lid] = (kind, info)
    return els


def sel_signatures(seg):
    """Подписи всех SEL: (тип/выражение G, IN0, IN1)."""
    els = elements(seg)
    sigs = []
    for m in re.finditer(r'<block\s+localId="(\d+)"\s+typeName="SEL"', seg):
        lid = int(m.group(1))
        end = seg.find(u'</block>', m.end())
        body = seg[m.end():end]
        refs = [int(x) for x in re.findall(r'<connection refLocalId="(\d+)"', body)]
        ins = []
        for r in refs[:3]:
            k, i = els.get(r, (u'?', u'?'))
            ins.append(u'%s:%s' % (k, i))
        sigs.append((lid, tuple(ins)))
    return sigs


def main():
    g = pou_seg(load(os.path.join(HERE, u'..', u'src', u'core_full.plcopenxml')),
                u'FB_CPU8080_FULL')
    r = pou_seg(load(os.path.join(HERE, u'..', u'src', u'core_full_reexport.xml')),
                u'FB_CPU8080_FULL')
    sg, sr = sel_signatures(g), sel_signatures(r)
    cg = collections.Counter(s for _l, s in sg)
    cr = collections.Counter(s for _l, s in sr)
    print(u"SEL сгенерировано=%d импортировано=%d" % (len(sg), len(sr)))
    only_gen = cg - cr
    print(u"\nПодписи, которых НЕТ после импорта:")
    for sig, n in only_gen.items():
        print(u"  x%d  G=%-26s IN0=%-26s IN1=%s" % (n, sig[0], sig[1], sig[2]))
    only_imp = cr - cg
    print(u"\nПодписи, появившиеся после импорта:")
    for sig, n in only_imp.items():
        print(u"  x%d  G=%-26s IN0=%-26s IN1=%s" % (n, sig[0], sig[1], sig[2]))
    # дубликаты подписей в сгенерированном XML (кандидаты на слияние)
    print(u"\nПовторяющиеся подписи SEL в сгенерированном XML:")
    for sig, n in cg.items():
        if n > 1:
            print(u"  x%d  G=%-26s IN0=%-26s IN1=%s" % (n, sig[0], sig[1], sig[2]))


if __name__ == '__main__':
    main()
