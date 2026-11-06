# -*- coding: utf-8 -*-
u"""ПРОБА этапа 3.6: конструкции аппаратного слоя ввода-вывода в диалекте FBD.

В этом диалекте всё непроверенное МОЛЧА теряется (журнал сборки, пункты 4.3,
8.2, 9.1, 11.2), поэтому новые конструкции проверяются отдельной маленькой
сборкой (build/PROBE_IO.project) до большой сборки на 4000+ блоков.

ЧТО ПРОВЕРЯЕТСЯ (чего в проекте ещё НЕ БЫЛО):
  P_IO_MAP     - поле структуры, ЛЕЖАЩЕЙ В МАССИВЕ, по ВЫЧИСЛЯЕМОМУ индексу:
                 GVL_IO_Map.Map[Port].Kind (чтение) и Map[Port].Fault := ...
                 (запись). На этом построен весь маппинг портов;
  P_IO_ARR     - обращение к массивам каналов по индексу, ОГРАНИЧЕННОМУ блоком
                 LIMIT (защита от выхода за границу массива), запись в BOOL- и
                 INT-массивы, а также блоки BYTE_TO_INT / INT_TO_BYTE;
  P_IO_MATH    - масштабирование аналога: INT_TO_DINT / MUL / DIV / LIMIT /
                 DINT_TO_BYTE (шкала 27648 x 255 не влезает в INT), XOR для
                 инверсии логики, счётчики UDINT, маска INT AND 255;
  P_IO_MAPINIT - заливка карты портов так, как это делает FB_IO_MapInit
                 (десятки полей с ПОСТОЯННЫМ индексом и гейтом "первый скан");
  P_IO_HW      - НЕ входит в эту пробу: AT %IB0/%QB0/%IW0/%QW0 проверяются
                 отдельной пробой (gen_probe_hw.py), потому что в этой установке
                 нет устройства с физическими модулями ввода-вывода.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, K, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, SEL, IF,
                          ADD, SUB, MUL, SHL, SHR, W2B, ORL, CHAIN, B, H, W)
import pou_io_defs as D
from pou_io_defs import DIV, LIMIT, XOR, B2I, I2B, I2D, D2I, D2B, PORT_MAX

U1 = u"UDINT#1"


def make_map():
    u"""Чтение и запись полей дескриптора порта по ВЫЧИСЛЯЕМОМУ индексу."""
    p = Pou(u"P_IO_MAP", u"functionBlock",
            doc=u"Проба: GVL_IO_Map.Map[Port].поле - структура в массиве по\n"
                u"\tвычисляемому индексу (Port : BYTE). Проверяются ЧТЕНИЕ всех\n"
                u"\tполей и ЗАПИСЬ поля Fault (её делает FB_IO_Dispatch, когда\n"
                u"\tадаптер сообщает о неисправности канала), а также обращение\n"
                u"\tпо ПОСТОЯННОМУ индексу (так карту заливает FB_IO_MapInit).")
    p.var_in(u"Port", u"BYTE", u"номер порта 0..255")
    p.var_in(u"Fl", u"BOOL", u"новое значение поля Fault")
    p.var_in(u"Idx", u"INT", u"номер канала")
    p.var_out(u"Kind", u"BYTE", u"прочитанный вид канала")
    p.var_out(u"Index", u"INT", u"прочитанный номер канала")
    p.var_out(u"Num", u"INT", u"числитель масштаба")
    p.var_out(u"Den", u"INT", u"знаменатель масштаба")
    p.var_out(u"Inv", u"BOOL", u"инверсия")
    p.var_out(u"Flt", u"BOOL", u"неисправность")
    p.var_out(u"K16", u"BYTE", u"вид канала порта 10h (постоянный индекс)")

    n = p.network(u"СЕТЬ 1. Чтение всех полей дескриптора по индексу Port")
    n.outvar(u"Kind", I(n, u"GVL_IO_Map.Map[Port].Kind"))
    n.outvar(u"Index", I(n, u"GVL_IO_Map.Map[Port].Index"))
    n.outvar(u"Num", I(n, u"GVL_IO_Map.Map[Port].ScaleNum"))
    n.outvar(u"Den", I(n, u"GVL_IO_Map.Map[Port].ScaleDen"))
    n.outvar(u"Inv", I(n, u"GVL_IO_Map.Map[Port].Invert"))
    n.outvar(u"Flt", I(n, u"GVL_IO_Map.Map[Port].Fault"))

    n = p.network(u"СЕТЬ 2. Запись полей дескриптора по индексу Port")
    n.outvar(u"GVL_IO_Map.Map[Port].Fault", I(n, u"Fl"))
    n.outvar(u"GVL_IO_Map.Map[Port].Index", I(n, u"Idx"))
    n.outvar(u"GVL_IO_Map.Map[Port].Kind", I(n, u"GVL_IO_Map.Map[Port].Kind"))

    n = p.network(u"СЕТЬ 3. Обращение по постоянному индексу (заливка карты)")
    n.outvar(u"K16", I(n, u"GVL_IO_Map.Map[16].Kind"))
    n.outvar(u"GVL_IO_Map.Map[16].Index", I(n, u"INT#0"))
    return p


def make_arr():
    u"""Массивы каналов с индексом, ограниченным LIMIT."""
    p = Pou(u"P_IO_ARR", u"functionBlock",
            doc=u"Проба: обращение к массивам каналов по индексу из карты портов.\n"
                u"\tИндекс ВСЕГДА проходит через LIMIT: дескриптор может содержать\n"
                u"\tчто угодно (например -5 или 9999), а выход за границу массива\n"
                u"\tв FBD - это авария ПЛК. Проверяются чтение DI/AI, запись DO/AO\n"
                u"\tи преобразования BYTE_TO_INT / INT_TO_BYTE.")
    p.var_in(u"RawIdx", u"INT", u"номер канала из дескриптора (может быть любым)")
    p.var_in(u"Byte", u"BYTE", u"байт для вывода (бит 0 идёт в DO)")
    p.var_in(u"An", u"INT", u"аналоговое значение")
    p.var_out(u"DIv", u"BOOL", u"прочитанный дискретный вход")
    p.var_out(u"AIv", u"INT", u"прочитанный аналоговый вход")
    p.var_out(u"WIv", u"INT", u"байт как INT (BYTE_TO_INT)")
    p.var_out(u"BOv", u"BYTE", u"аналог как BYTE (INT_TO_BYTE)")
    p.var_out(u"Dbit", u"BOOL", u"бит 0 байта вывода (для DO)")
    p.var(u"di", u"INT", u"ограниченный индекс дискретного канала")
    p.var(u"ai", u"INT", u"ограниченный индекс аналогового канала")

    n = p.network(u"СЕТЬ 1. Индексы каналов через LIMIT (0..63 и 0..15)")
    n.outvar(u"di", LIMIT(n, I(n, u"INT#0"), I(n, u"RawIdx"), I(n, u"INT#63")))
    n.outvar(u"ai", LIMIT(n, I(n, u"INT#0"), I(n, u"RawIdx"), I(n, u"INT#15"),
                          fbd_xml.COL_BLK + 200))

    n = p.network(u"СЕТЬ 2. Чтение дискретного и аналогового входа")
    n.outvar(u"DIv", I(n, u"GVL_IO.DI[di]"))
    n.outvar(u"AIv", I(n, u"GVL_IO.AI[ai]"))
    n.outvar(u"WIv", B2I(n, I(n, u"Byte"), fbd_xml.COL_BLK + 200))
    n.outvar(u"BOv", I2B(n, I(n, u"AIv"), fbd_xml.COL_BLK + 320))

    n = p.network(u"СЕТЬ 3. Запись дискретного и аналогового выхода")
    n.outvar(u"Dbit", NE(n, AND(n, I(n, u"Byte"), I(n, u"BYTE#1")), I(n, u"BYTE#0"),
                         fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO.DO[di]", I(n, u"Dbit"))
    n.outvar(u"GVL_IO.AO[ai]", I(n, u"An"))
    n.outvar(u"GVL_IO.AI[ai]", I(n, u"An"))
    return p


def make_math():
    u"""Масштабирование аналога в DINT, XOR, счётчики UDINT."""
    p = Pou(u"P_IO_MATH", u"functionBlock",
            doc=u"Проба: аналоговое масштабирование INT -> BYTE.\n"
                u"\tСырое значение (0..27648) умножается на числитель (255) и\n"
                u"\tделится на знаменатель (27648) - в INT это переполнение, поэтому\n"
                u"\tсчитаем в DINT: INT_TO_DINT -> MUL -> DIV -> LIMIT -> DINT_TO_BYTE.\n"
                u"\tПлюс проверяются XOR для инверсии логики, счётчик UDINT и маска\n"
                u"\tINT AND 255 (её использует журнал консоли).")
    p.var_in(u"Raw", u"INT", u"сырое значение аналогового входа")
    p.var_in(u"Num", u"INT", u"числитель масштаба")
    p.var_in(u"Den", u"INT", u"знаменатель масштаба")
    p.var_in(u"Bit", u"BOOL", u"логический уровень канала")
    p.var_in(u"Inv", u"BOOL", u"инверсия логики")
    p.var_out(u"Byte", u"BYTE", u"результат: 0..255")
    p.var_out(u"Ovf", u"BOOL", u"выход за диапазон шкалы")
    p.var_out(u"InvBit", u"BOOL", u"инвертированный бит")
    p.var_out(u"Cnt", u"UDINT", u"счётчик (UDINT + 1)")
    p.var_out(u"Masked", u"INT", u"INT AND 255")
    p.var_out(u"AnOut", u"INT", u"обратное преобразование BYTE -> INT")
    p.var(u"d1", u"DINT", u"сырое значение в DINT")
    p.var(u"d2", u"DINT", u"произведение в DINT")
    p.var(u"d3", u"DINT", u"частное в DINT")
    p.var(u"d4", u"DINT", u"насыщенное значение")
    p.var(u"b1", u"BYTE", u"результат в BYTE")

    n = p.network(u"СЕТЬ 1. INT -> DINT -> MUL -> DIV -> LIMIT -> BYTE")
    n.outvar(u"d1", I2D(n, I(n, u"Raw")))
    n.outvar(u"d2", MUL(n, I(n, u"d1"), I2D(n, I(n, u"Num"), fbd_xml.COL_BLK + 200),
                        fbd_xml.COL_BLK + 320))
    n.outvar(u"d3", DIV(n, I(n, u"d2"), I2D(n, I(n, u"Den"), fbd_xml.COL_BLK + 440),
                        fbd_xml.COL_BLK + 560))
    n.outvar(u"d4", LIMIT(n, I(n, u"DINT#0"), I(n, u"d3"), I(n, u"DINT#255"),
                          fbd_xml.COL_BLK + 680))
    n.outvar(u"b1", D2B(n, I(n, u"d4"), fbd_xml.COL_BLK + 800))
    n.outvar(u"Byte", I(n, u"b1"))

    n = p.network(u"СЕТЬ 2. Признак выхода за диапазон и инверсия логики")
    n.outvar(u"Ovf", OR(n, GT(n, I(n, u"Raw"), I(n, u"Den")),
                        LT(n, I(n, u"Raw"), I(n, u"INT#0"), fbd_xml.COL_BLK + 200),
                        fbd_xml.COL_BLK + 340))
    n.outvar(u"InvBit", XOR(n, I(n, u"Bit"), I(n, u"Inv")))
    n.outvar(u"Masked", AND(n, I(n, u"GVL_IO.Diag.Last_Index"), I(n, u"INT#255")))

    n = p.network(u"СЕТЬ 3. Обратное преобразование BYTE -> INT и счётчик UDINT")
    n.outvar(u"AnOut", D2I(n, DIV(n, MUL(n, B2I(n, I(n, u"b1")),
                                          I2D(n, I(n, u"Den"), fbd_xml.COL_BLK + 200),
                                          fbd_xml.COL_BLK + 320),
                                   I2D(n, I(n, u"Num"), fbd_xml.COL_BLK + 440),
                                   fbd_xml.COL_BLK + 560),
                             fbd_xml.COL_BLK + 680))
    n.outvar(u"Cnt", ADD(n, I(n, u"GVL_IO.Diag.Read_Cnt"), I(n, U1)))
    n.outvar(u"GVL_IO.Diag.Read_Cnt", I(n, u"Cnt"))
    return p


def make_mapinit():
    u"""Заливка карты портов - так же, как это делает FB_IO_MapInit."""
    p = Pou(u"P_IO_MAPINIT", u"functionBlock",
            doc=u"Проба: инициализация карты портов 'первым сканом'.\n"
                u"\tПроверяются десятки записей в поля структуры по ПОСТОЯННОМУ\n"
                u"\tиндексу под гейтом SEL(notdone) и запись скалярных параметров\n"
                u"\tнастройки (MissingPortMode, лимиты watchdog).")
    p.var_in(u"Enable", u"BOOL", u"выполнять инициализацию")
    p.var(u"notdone", u"BOOL", u"карта ещё не инициализирована")
    p.var_out(u"Done", u"BOOL", u"инициализация выполнена")

    n = p.network(u"СЕТЬ 1. Гейт первого скана")
    n.outvar(u"notdone", AND(n, I(n, u"Enable"), NOT(n, I(n, u"GVL_IO_Map.Map_Ready"),
                                                  fbd_xml.COL_BLK + 200),
                             fbd_xml.COL_BLK + 320))

    n = p.network(u"СЕТЬ 2. Поля дескрипторов демонстрационных портов")
    for port, kind, idx, num, den, inv, _txt in D.MAP_DEMO:
        t = lambda f: u"GVL_IO_Map.Map[%d].%s" % (port, f)
        n.outvar(t(u"Kind"), SEL(n, I(n, u"notdone"), I(n, t(u"Kind")),
                                 I(n, H % kind), fbd_xml.COL_BLK))
        n.outvar(t(u"Index"), SEL(n, I(n, u"notdone"), I(n, t(u"Index")),
                                  I(n, u"INT#%d" % idx), fbd_xml.COL_BLK + 160))
        if num != 1 or den != 1:
            n.outvar(t(u"ScaleNum"), SEL(n, I(n, u"notdone"), I(n, t(u"ScaleNum")),
                                         I(n, u"INT#%d" % num), fbd_xml.COL_BLK + 320))
            n.outvar(t(u"ScaleDen"), SEL(n, I(n, u"notdone"), I(n, t(u"ScaleDen")),
                                         I(n, u"INT#%d" % den), fbd_xml.COL_BLK + 480))
        if inv:
            n.outvar(t(u"Invert"), SEL(n, I(n, u"notdone"), I(n, t(u"Invert")),
                                       I(n, u"TRUE"), fbd_xml.COL_BLK + 640))
        n.outvar(t(u"Fault"), SEL(n, I(n, u"notdone"), I(n, t(u"Fault")),
                                  I(n, u"FALSE"), fbd_xml.COL_BLK + 800))

    n = p.network(u"СЕТЬ 3. Параметры защит и признак готовности карты")
    n.outvar(u"GVL_IO_Map.MissingPortMode",
             IF(n, I(n, u"notdone"), I(n, H % D.MODE_STUB),
                I(n, u"GVL_IO_Map.MissingPortMode")))
    n.outvar(u"GVL_IO_Map.Watchdog_Enable",
             IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                I(n, u"GVL_IO_Map.Watchdog_Enable"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO_Map.Limit_Scans",
             IF(n, I(n, u"notdone"), I(n, u"UDINT#100"),
                I(n, u"GVL_IO_Map.Limit_Scans"), fbd_xml.COL_BLK + 400))
    n.outvar(u"GVL_IO_Map.Map_Ready", I(n, u"TRUE"))
    n.outvar(u"Done", I(n, u"notdone"))
    return p


ALL = (make_map, make_arr, make_math, make_mapinit)
