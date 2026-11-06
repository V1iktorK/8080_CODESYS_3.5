# -*- coding: utf-8 -*-
u"""Этап 4: убрать столкновение регистра IO_Busy / io_busy в FB_CPU8080_FULL.

CODESYS не различает регистр, поэтому выход `IO_Busy` и локальная `io_busy`
в одном POU - это одна и та же переменная (ошибка C142 при кодогенерации,
которая включается только вместе с конфигурацией задач).

Локальная переменная переименована в `tact_busy_l`; выход IO_Busy не
переименовывается - на него ссылаются другие схемы слоя 3.6.
"""
import io, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(HERE, u"pou_cpu_io.py")

EDITS = (
    (u'(u"io_busy", u"BOOL", u"такт начался и не завершён (вход watchdog)"),',
     u'(u"tact_busy_l", u"BOOL", u"такт начался и не завершён (вход watchdog); '
     u'имя не должно совпадать с выходом IO_Busy"),'),
    (u'n.outvar(u"io_busy", AND(n, I(n, u"run"),',
     u'n.outvar(u"tact_busy_l", AND(n, I(n, u"run"),'),
    (u'n.outvar(u"GVL_IO.Tact_Busy", I(n, u"io_busy"))',
     u'n.outvar(u"GVL_IO.Tact_Busy", I(n, u"tact_busy_l"))'),
)


def main():
    t = io.open(P, encoding=u"utf-8").read()
    miss = []
    for old, new in EDITS:
        if old not in t:
            miss.append(old[:70])
            continue
        t = t.replace(old, new)
    io.open(P, "w", encoding=u"utf-8").write(t)
    print(u"правок применено: %d из %d" % (len(EDITS) - len(miss), len(EDITS)))
    for m in miss:
        print(u"  НЕ НАЙДЕНО: %s" % m)


if __name__ == u"__main__":
    main()
