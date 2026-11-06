# -*- coding: utf-8 -*-
"""ЛОКАЛЬНАЯ ПРОВЕРКА схем подшага 3.1 (обычный Python 3, БЕЗ CODESYS).

Проверяет то, что дорого ловить медленной сборкой:
  * модули вообще импортируются и POU собираются;
  * каждая входная переменная схемы (inVariable) - либо литерал, либо
    объявленная переменная POU, либо обращение к GVL/экземпляру;
  * каждая цель записи (outVariable) - объявленная переменная POU или GVL;
  * каждый экземпляр FB (instanceName) объявлен и имеет нужный тип;
  * разветвление выхода вызова FB отсутствует (иначе генератор бросит ошибку);
  * статистика: блоков/связей на POU.

Запуск:  python generator/check_full.py
"""

import io
import os
import re
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import builtins
builtins.unicode = str          # fbd_xml написан под IronPython 2.7

import fbd_xml
import pou_decode_full as pd
import pou_extra as pe
import pou_cpu_full as pc

LIT = re.compile(r'^(TRUE|FALSE|BYTE#|WORD#|DWORD#|SINT#|USINT#|INT#|UINT#|DINT#|16#|\d)')
SIMPLE = re.compile(r'^[A-Za-z_][A-Za-z0-9_]*$')


def read_text(path):
    f = io.open(path, 'r', encoding='utf-8')
    t = f.read()
    f.close()
    return t


def check_pou(p, src, errors):
    names = set(v.name for v in p.inputs) | set(v.name for v in p.outputs) \
        | set(v.name for v in p.locals)
    types = {}
    for v in p.locals:
        types[v.name] = v.type

    def chk_in(expr, where):
        if LIT.match(expr):
            return
        head = re.split(r'[.\[]', expr)[0]
        if head in names or head in (u'GVL_CPU', u'GVL_MEM'):
            return
        errors.append(u"%s: в схеме используется необъявленная переменная '%s' (%s)"
                      % (p.name, expr, where))

    seen = set()          # localId, определённые ДО текущего элемента
    for net in p.networks:
        for it in net._items:
            if it[0] == u'invar':
                chk_in(it[2], u"сеть %d" % net.number)
                seen.add(it[1])
            elif it[0] == u'outvar':
                tgt = it[2]
                if SIMPLE.match(tgt):
                    if tgt not in names:
                        errors.append(u"%s: запись в необъявленную переменную '%s'"
                                      % (p.name, tgt))
                else:
                    head = re.split(r'[.\[]', tgt)[0]
                    if head not in names and head not in (u'GVL_CPU', u'GVL_MEM'):
                        errors.append(u"%s: запись в неизвестный объект '%s'" % (p.name, tgt))
                if it[3].eid not in seen:
                    errors.append(u"%s: связь в outVariable '%s' ссылается на "
                                  u"несуществующий/будущий элемент %s"
                                  % (p.name, tgt, it[3].eid))
                seen.add(it[1])
            else:
                _kind, eid, tname, ins, outs, x, y = it
                inst = p._inst.get(eid)
                if inst:
                    if inst not in types:
                        errors.append(u"%s: экземпляр '%s' не объявлен" % (p.name, inst))
                    elif types[inst].strip().upper() != tname.strip().upper():
                        errors.append(u"%s: экземпляр '%s' объявлен как %s, а вызывается %s"
                                      % (p.name, inst, types[inst], tname))
                for pin, s in ins:
                    if s.eid not in seen:
                        errors.append(u"%s: вход %s блока %s ссылается на "
                                      u"несуществующий/будущий элемент %s"
                                      % (p.name, pin, tname, s.eid))
                seen.add(eid)
    # объявленные, но не используемые локальные переменные
    used = set()
    for net in p.networks:
        for it in net._items:
            if it[0] == u'invar':
                for m in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', it[2]):
                    used.add(m)
            elif it[0] == u'outvar':
                for m in re.findall(r'[A-Za-z_][A-Za-z0-9_]*', it[2]):
                    used.add(m)
            else:
                inst = p._inst.get(it[1])
                if inst:
                    used.add(inst)      # вызов FB по имени экземпляра
    unused = [n for n in names if n not in used and n not in
              set(v.name for v in p.inputs)]
    return unused

def main():
    errors = []
    allp = []
    for maker in (pe.ALL + pd.ALL + pc.ALL):
        p = maker()
        allp.append(p)

    total_blocks = total_conn = total_empty = 0
    for p in allp:
        unused = check_pou(p, None, errors)
        try:
            p._expand_fanout()
        except Exception as e:
            errors.append(u"%s: fan-out выхода вызова FB: %s" % (p.name, e))
        nb = sum(1 for net in p.networks for it in net._items if it[0] == u'block')
        ni = sum(1 for net in p.networks for it in net._items if it[0] == u'invar')
        no = sum(1 for net in p.networks for it in net._items if it[0] == u'outvar')
        nc = sum(len(it[3]) if it[0] != u'invar' and it[0] != u'outvar' else 1
                 for net in p.networks for it in net._items)
        total_blocks += nb
        total_conn += nc
        print(u"%-20s сетей=%2d блоков=%4d вход.перем=%4d выход.перем=%3d"
              % (p.name, len(p.networks), nb, ni, no))
        if unused:
            print(u"    неиспользуемые локальные: %s" % u", ".join(unused))

    # запись XML (здесь же проверяется fan-out вызовов FB)
    out = os.path.join(HERE, u"_check_full.plcopenxml")
    size = fbd_xml.write_project(out, allp, u"check_full")
    cnt = fbd_xml.count_elements(out)
    print(u"\nPOU всего: %d" % len(allp))
    print(u"XML: %d символов -> %s" % (size, out))
    print(u"блоков=%d вход.перем=%d выход.перем=%d связей=%d пустых.входов=%d" % cnt)
    print(u"GVL_CPU: %d символов объявления" % len(pd.gvl_cpu_text()))

    if errors:
        print(u"\n=== ОШИБКИ (%d) ===" % len(errors))
        for e in errors:
            print(u"  " + e)
        return 1
    print(u"\nПРОВЕРКА ПРОЙДЕНА: ошибок нет")
    return 0


if __name__ == '__main__':
    sys.exit(main())
