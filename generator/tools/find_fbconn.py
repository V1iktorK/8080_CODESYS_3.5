# -*- coding: utf-8 -*-
u"""Поиск в СГЕНЕРИРОВАННОМ XML связей "вывод блока -> вход блока".

Правило журнала (docs/03, п. 11.2): связь вида
    <connection refLocalId="N" formalParameter="OUT" />
во ВХОДЕ блока CODESYS при импорте МОЛЧА теряет вместе со всей ветвью.
Именно так в FB_IO_Dispatch пропал вход блока AND (выгрузка показала
входов=1 вместо 2), и кодогенерация упала с
    C23: Для 'AND' необходимо как минимум '2' операндов.
"""
import io, os, re, sys

PATHS = sys.argv[1:]
if not PATHS:
    PATHS = [r"C:\dsh8080\work\emu_s4\src\s4_pous"]

n = 0
for p in PATHS:
    files = [p] if os.path.isfile(p) else \
        [os.path.join(p, f) for f in sorted(os.listdir(p)) if f.endswith(u".plcopenxml")]
    for f in files:
        t = io.open(f, encoding=u"utf-8").read()
        # все блоки с их localId и typeName
        ids = {}
        for m in re.finditer(u'<block localId="(\\d+)" typeName="([^"]+)"', t):
            ids[m.group(1)] = m.group(2)
        # связи во входах блоков, у которых указан вывод источника
        for m in re.finditer(
                u'<variable formalParameter="[^"]*">\\s*<connectionPointIn>\\s*'
                u'<connection refLocalId="(\\d+)" formalParameter="([^"]+)"',
                t):
            src = ids.get(m.group(1), u"?")
            if src != u"?":
                n += 1
                print(u"%s: вход <- вывод %s.%s (refLocalId=%s)"
                      % (os.path.basename(f), src, m.group(2), m.group(1)))
print(u"\nвсего связей 'вывод FB -> вход блока': %d" % n)
