# -*- coding: utf-8 -*-
u"""Этап 4: убрать СТОЛКНОВЕНИЯ ИМЁН, РАЗЛИЧАЮЩИХСЯ ТОЛЬКО РЕГИСТРОМ.

CODESYS не различает регистр в именах, поэтому в одном POU нельзя иметь
выход `Raw` и локальную `raw`, выход `AOut` и локальную `aout`, выход `Kind`
и локальную `kind`. Кодогенерация (включилась только после появления
конфигурации задач) сообщает об этом:

    C142: Локальная переменная с именем 'raw'  уже задана в 'FB_IO_AnalogIn'
    C142: Локальная переменная с именем 'aout' уже задана в 'FB_IO_AnalogOut'
    C142: Локальная переменная с именем 'kind' уже задана в 'FB_IO_Dispatch'

Правка затрагивает ТОЛЬКО имена ВНУТРЕННИХ (локальных) переменных этих трёх
блоков: выходы не переименовываются (на них ссылаются вызывающие схемы).
Схема при этом не меняется: связи идут по localId.
"""
import io, os, re, sys

HERE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PATH = os.path.join(HERE, u"pou_io.py")

# (строка-образец, замена) - правки строго внутри указанных функций
EDITS = (
    # ---- FB_IO_AnalogIn (локальная raw -> raw_in) ----
    (u'    p.var(u"raw", u"INT", u"сырое значение входа")',
     u'    p.var(u"raw_in", u"INT", u"сырое значение входа (не путать с выходом Raw)")'),
    (u'n.outvar(u"raw", I(n, u"GVL_IO.AI[idx]"))',
     u'n.outvar(u"raw_in", I(n, u"GVL_IO.AI[idx]"))'),
    (u'n.outvar(u"Raw", I(n, u"raw"))',
     u'n.outvar(u"Raw", I(n, u"raw_in"))'),
    (u'DIV(n, MUL(n, I2D(n, LIMIT(n, I(n, u"INT#0"), I(n, u"raw"), I(n, u"den_e"),',
     u'DIV(n, MUL(n, I2D(n, LIMIT(n, I(n, u"INT#0"), I(n, u"raw_in"), I(n, u"den_e"),'),
    (u'n.outvar(u"over_in", ORL(n, [GT(n, I(n, u"raw"), I(n, u"den_e")),',
     u'n.outvar(u"over_in", ORL(n, [GT(n, I(n, u"raw_in"), I(n, u"den_e")),'),
    (u'LT(n, I(n, u"raw"), I(n, u"INT#0"),',
     u'LT(n, I(n, u"raw_in"), I(n, u"INT#0"),'),
    # ---- FB_IO_AnalogOut (локальная aout -> ao_calc) ----
    (u'    p.var(u"aout", u"INT", u"значение выхода")',
     u'    p.var(u"ao_calc", u"INT", u"значение выхода (не путать с выходом AOut)")'),
    (u'n.outvar(u"aout", D2I(n, I(n, u"d3"), fbd_xml.COL_BLK + 940))',
     u'n.outvar(u"ao_calc", D2I(n, I(n, u"d3"), fbd_xml.COL_BLK + 940))'),
    (u'n.outvar(u"AOut", I(n, u"aout"))',
     u'n.outvar(u"AOut", I(n, u"ao_calc"))'),
    (u'n.outvar(tgt, IF(n, I(n, u"ok"), I(n, u"aout"), I(n, tgt),',
     u'n.outvar(tgt, IF(n, I(n, u"ok"), I(n, u"ao_calc"), I(n, tgt),'),
    # ---- FB_IO_Dispatch (локальная kind -> kind_l) ----
    (u'    p.var(u"kind", u"BYTE", u"вид канала из дескриптора")',
     u'    p.var(u"kind_l", u"BYTE", u"вид канала из дескриптора (не путать с выходом Kind)")'),
    (u'n.outvar(u"kind", I(n, u"GVL_IO_Map.Map[Port].Kind"))',
     u'n.outvar(u"kind_l", I(n, u"GVL_IO_Map.Map[Port].Kind"))'),
    (u'n.outvar(u"is_none", EQ(n, I(n, u"kind"), I(n, H % K_NONE)))',
     u'n.outvar(u"is_none", EQ(n, I(n, u"kind_l"), I(n, H % K_NONE)))'),
    (u'n.outvar(u"is_cons", EQ(n, I(n, u"kind"), I(n, H % K_CONSOLE),',
     u'n.outvar(u"is_cons", EQ(n, I(n, u"kind_l"), I(n, H % K_CONSOLE),'),
    (u'            EQ(n, I(n, u"kind"), I(n, H % K_DI)),',
     u'            EQ(n, I(n, u"kind_l"), I(n, H % K_DI)),'),
    (u'            EQ(n, I(n, u"kind"), I(n, H % K_DO), fbd_xml.COL_BLK + 140),',
     u'            EQ(n, I(n, u"kind_l"), I(n, H % K_DO), fbd_xml.COL_BLK + 140),'),
    (u'            EQ(n, I(n, u"kind"), I(n, H % K_AI), fbd_xml.COL_BLK + 280),',
     u'            EQ(n, I(n, u"kind_l"), I(n, H % K_AI), fbd_xml.COL_BLK + 280),'),
    (u'            EQ(n, I(n, u"kind"), I(n, H % K_AO), fbd_xml.COL_BLK + 420)],',
     u'            EQ(n, I(n, u"kind_l"), I(n, H % K_AO), fbd_xml.COL_BLK + 420)],'),
    (u'        (u"En", I(n, u"ad_en")), (u"RW", I(n, u"RW")), (u"Kind", I(n, u"kind")),',
     u'        (u"En", I(n, u"ad_en")), (u"RW", I(n, u"RW")), (u"Kind", I(n, u"kind_l")),'),
    (u'n.outvar(u"GVL_IO.Diag.Last_Kind", IF(n, I(n, u"ready"), I(n, u"kind"),',
     u'n.outvar(u"GVL_IO.Diag.Last_Kind", IF(n, I(n, u"ready"), I(n, u"kind_l"),'),
    (u'    n.outvar(u"Kind", I(n, u"kind"))',
     u'    n.outvar(u"Kind", I(n, u"kind_l"))'),
    (u'n.outvar(u"is_kind", EQ(n, I(n, u"kind"), I(n, H % kind)))',
     u'n.outvar(u"is_kind", EQ(n, I(n, u"kind_l"), I(n, H % kind)))'),
)


def main():
    t = io.open(PATH, encoding="utf-8").read()
    miss = []
    for old, new in EDITS:
        if old not in t:
            miss.append(old[:70])
            continue
        t = t.replace(old, new)
    io.open(PATH, "w", encoding="utf-8").write(t)
    print(u"правок применено: %d из %d" % (len(EDITS) - len(miss), len(EDITS)))
    for m in miss:
        print(u"  НЕ НАЙДЕНО: %s" % m)
    # контроль: не осталось ли локальных объявлений, конфликтующих с выходами
    bad = []
    for m in re.finditer(r'p\.var\(u"(\w+)"', t):
        nm = m.group(1)
        if u'p.var_out(u"%s"' % nm.lower() in t.lower() or \
           u'p.var_out(u"%s"' % nm in t:
            bad.append(nm)
    print(u"возможные конфликты регистра (локальная против выхода): %s"
          % (u", ".join(bad) if bad else u"нет"))


if __name__ == u"__main__":
    main()
