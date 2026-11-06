# -*- coding: utf-8 -*-
u"""ЛОКАЛЬНЫЙ ПРОГОН ГЕНЕРАЦИИ ЭТАПА 4 (обычный Python 3, БЕЗ CODESYS).

Зачем: сборка в CODESYS стоит минуты, а ошибка в имени переменной видна там
только как ошибка компиляции. Здесь те же модули генерации собираются в память,
считаются блоки и проверяется, что каждая ссылка вида I(n, "имя") на ПЛОСКИЙ
идентификатор объявлена в этом POU (правило из docs/03, п. 13.6).

Запуск:  python dryrun_stage4.py
"""
import io, os, re, sys

# fbd_xml написан под IronPython 2 (unicode()); для локальной пробы под Python 3
# подставляем совместимые имена, чтобы гонять ТУ ЖЕ логику генерации.
try:
    import builtins
    builtins.unicode = str
    builtins.unichr = chr
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import fbd_xml
import pou_test_defs as TD
import pou_test8080
import pou_testcpm
import pou_testio

GLOBALS = (u"GVL_CPU", u"GVL_MEM", u"GVL_CPM", u"GVL_DISK", u"GVL_IO", u"GVL_IO_Map",
           u"GVL_IO_HW", u"GVL_HMI", u"GVL_TEST")


def flat_id(e):
    u"""Плоский идентификатор ссылки (без индексов/полей/констант)."""
    if not isinstance(e, (str, bytes)):
        return None
    if not isinstance(e, str):
        e = e.decode("utf-8")
    s = e.strip()
    if s.startswith(u"BYTE#") or s.startswith(u"WORD#") or s.startswith(u"INT#") \
            or s.startswith(u"UDINT#") or s.startswith(u"DWORD#") \
            or s.startswith(u"T#") or s in (u"TRUE", u"FALSE"):
        return None
    if s.startswith(u"(") or u" " in s:
        return None
    head = re.split(r"[\[\.]", s)[0]
    if not re.match(r"^[A-Za-z_][A-Za-z0-9_]*$", head):
        return None
    return head


def check(p, declared):
    bad = []
    nblocks = 0
    for net in p.networks:
        for it in net._items:
            if it[0] == u"block":
                nblocks += 1
                for _, s in it[3]:
                    pass
            elif it[0] == u"invar":
                nm = flat_id(it[2])
                if nm and nm not in declared:
                    bad.append((net.title[:40], it[2], nm))
    return nblocks, bad


def main():
    print(u"=== ЛОКАЛЬНЫЙ ПРОГОН ГЕНЕРАЦИИ ЭТАПА 4 ===")
    cs = TD.build_all()
    print(u"кейсов 8080: %d  по группам: %s" % (len(cs), TD.summary()))
    gvl = TD.gvl_test_text()
    print(u"GVL_TEST: %d символов" % len(gvl))

    bad_all = []
    for mk in (pou_test8080.ALL + pou_testcpm.ALL + pou_testio.ALL):
        p = mk()
        declared = set([v.name for v in p.locals] + [v.name for v in p.inputs] +
                       [v.name for v in p.outputs])
        declared |= set(GLOBALS)
        nblocks, bad = check(p, declared)
        print(u"POU %-12s сетей=%2d блоков=%3d  неизвестных ссылок: %d"
              % (p.name, len(p.networks), nblocks, len(bad)))
        for t, e, nm in bad[:20]:
            print(u"    ?? %-12s <- %s   (в сети: %s)" % (nm, e, t))
        bad_all.extend(bad)
        # предупреждение о пустом интерфейсе
        try:
            p.interface_xml()
        except Exception as exc:
            print(u"    !! %s" % exc)

    print(u"\nИТОГ: неизвестных ссылок %d" % len(bad_all))
    # заодно проверим, что XML пишется
    path = os.path.join(HERE, u"_dryrun_stage4.plcopenxml")
    size = fbd_xml.write_project(path, [mk() for mk in
                                        (pou_test8080.ALL + pou_testcpm.ALL +
                                         pou_testio.ALL)], u"dryrun_stage4")
    print(u"PLCopenXML: %d символов" % size)
    print(u"элементы: %s" % (fbd_xml.count_elements(path),))


try:
    main()
except Exception:
    import traceback
    print(traceback.format_exc())
