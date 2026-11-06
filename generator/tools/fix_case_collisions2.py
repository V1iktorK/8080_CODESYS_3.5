# -*- coding: utf-8 -*-
u"""Дочистка столкновений регистра в pou_io.py (продолжение fix_case_collisions)."""
import io, os

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
P = os.path.join(HERE, u"pou_io.py")

EDITS = (
    (u'LIMIT(n, I(n, u"INT#0"), I(n, u"raw"), I(n, u"den_e"),',
     u'LIMIT(n, I(n, u"INT#0"), I(n, u"raw_in"), I(n, u"den_e"),'),
    (u'        EQ(n, I(n, u"kind"), I(n, H % K_DI)),',
     u'        EQ(n, I(n, u"kind_l"), I(n, H % K_DI)),'),
    (u'        EQ(n, I(n, u"kind"), I(n, H % K_DO), fbd_xml.COL_BLK + 140),',
     u'        EQ(n, I(n, u"kind_l"), I(n, H % K_DO), fbd_xml.COL_BLK + 140),'),
    (u'        EQ(n, I(n, u"kind"), I(n, H % K_AI), fbd_xml.COL_BLK + 280),',
     u'        EQ(n, I(n, u"kind_l"), I(n, H % K_AI), fbd_xml.COL_BLK + 280),'),
    (u'        EQ(n, I(n, u"kind"), I(n, H % K_AO), fbd_xml.COL_BLK + 420)],',
     u'        EQ(n, I(n, u"kind_l"), I(n, H % K_AO), fbd_xml.COL_BLK + 420)],'),
)


def main():
    t = io.open(P, encoding=u"utf-8").read()
    miss = []
    for old, new in EDITS:
        if old not in t:
            miss.append(old[:60])
            continue
        t = t.replace(old, new)
    io.open(P, "w", encoding=u"utf-8").write(t)
    print(u"доправок применено: %d из %d" % (len(EDITS) - len(miss), len(EDITS)))
    for m in miss:
        print(u"  НЕ НАЙДЕНО: %s" % m)


if __name__ == u"__main__":
    main()
