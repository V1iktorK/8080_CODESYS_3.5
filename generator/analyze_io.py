# -*- coding: utf-8 -*-
u"""Сверка «сгенерировано против выгрузки» ПО КАЖДОМУ POU (этап 3.6).

Сборка подтверждает только ИТОГОВОЕ число блоков. Проект уже дважды терял схему
МОЛЧА (пункты 4.3, 8.2, 9.1, 11.2 журнала), поэтому после каждой сборки число
блоков сверяется по каждому POU отдельно - и в сгенерированном PLCopenXML, и в
обратной выгрузке из CODESYS.

Запуск (обычный Python, CODESYS не нужен):
    python analyze_io.py
"""

import io, os, re, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
try:
    unicode
except NameError:
    import builtins
    builtins.unicode = str

SRC = os.path.join(HERE, u"..", u"src")
GEN = os.path.join(SRC, u"cpm_full.plcopenxml")
REX = os.path.join(SRC, u"cpm_full_reexport.xml")


def count_per_pou(path):
    u"""Сколько <block> в каждом POU файла PLCopenXML."""
    if not os.path.exists(path):
        return None
    f = io.open(path, "r", encoding="utf-8")
    t = f.read()
    f.close()
    out = {}
    for m in re.finditer(u'<pou name="([^"]+)"', t):
        name = m.group(1)
        end = t.find(u"</pou>", m.end())
        seg = t[m.start():end]
        out[name] = (seg.count(u"<block "), seg.count(u"<connectionPointIn />"))
    return out


def main():
    gen = count_per_pou(GEN)
    rex = count_per_pou(REX)
    if gen is None or rex is None:
        print(u"нет файлов: %s / %s" % (GEN, REX))
        return
    print(u"%-34s %7s %7s %7s" % (u"POU", u"ген", u"импорт", u"разница"))
    bad = 0
    tg = tr = 0
    for name in sorted(gen):
        g = gen[name][0]
        r = rex.get(name)
        rn = -1 if r is None else r[0]
        tg += g
        tr += max(rn, 0)
        flag = u""
        if r is None:
            flag = u"   <-- POU ПОТЕРЯН"
            bad += 1
        elif rn != g:
            flag = u"   <-- РАСХОЖДЕНИЕ"
            bad += 1
        if flag:
            print(u"%-34s %7d %7d %7d%s" % (name, g, rn, rn - g, flag))
    print(u"%-34s %7d %7d" % (u"ИТОГО", tg, tr))
    print(u"POU с расхождением: %d (в выгрузке %d POU, сгенерировано %d)"
          % (bad, len(rex), len(gen)))
    empty = sum([v[1] for v in rex.values()])
    print(u"пустых входов в выгрузке: %d" % empty)
    if bad == 0 and empty == 0:
        print(u"СВЕРКА ПО КАЖДОМУ POU: OK")
    else:
        print(u"СВЕРКА ПО КАЖДОМУ POU: ЕСТЬ РАСХОЖДЕНИЯ")


if __name__ == "__main__":
    main()
