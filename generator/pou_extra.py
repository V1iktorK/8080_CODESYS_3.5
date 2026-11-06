# -*- coding: utf-8 -*-
u"""Подшаг 3.1: вспомогательные блоки полного ядра Intel 8080.

Состав (все - НОВЫЕ блоки, существующие файлы подшагов 3.2-3.4 не меняются):
  FB_UnpackWord  - WORD -> два байта (младший/старший)
  FB_Reg8Q       - 8-разрядный регистр с ЧЕТЫРЬМЯ портами загрузки
  FB_RegFileQ    - регистровый файл из семи таких регистров (шины + коды приёмника)
  FB_FlagsReg2   - регистр флагов с РАЗДЕЛЬНЫМИ разрешениями записи по каждому флагу
  FB_Rotate8     - сдвиги RLC / RRC / RAL / RAR
  FB_DAA         - десятичная коррекция аккумулятора
  FB_Interrupt   - приём прерывания (INT_Req + IFF -> стек, вектор, сброс IFF)

ПОЧЕМУ ПОНАДОБИЛИСЬ НОВЫЕ БЛОКИ, А НЕ ПРАВКА СТАРЫХ:
  * FB_Reg8/FB_RegFile имеют ОДИН порт загрузки, а команды LHLD/SHLD/POP/XCHG/
    PUSH за один такт пишут ДВА регистра (а XCHG - четыре). Такт у нас один
    скан, поэтому портов должно быть четыре.
  * FB_FlagsReg обновляет все пять флагов одним сигналом LD, а в 8080 запись
    флагов РАЗНАЯ: INR/DCR не трогают CY, DAD и сдвиги трогают ТОЛЬКО CY,
    ANA меняет S/Z/P/AC но не CY. Отсюда раздельные LD_S/LD_Z/LD_AC/LD_P/LD_CY.

ОГРАНИЧЕНИЯ CODESYS, СОБЛЮДЁННЫЕ ЗДЕСЬ (см. docs/03_ЖУРНАЛ_СБОРКИ.md):
  * один выход = одна связь; выход вызова FB сразу защёлкивается в переменную POU;
  * <interface> не пустой (у каждого блока есть входы и выходы).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

# Коды регистров 8080 (поле DDD/SSS): 0=B 1=C 2=D 3=E 4=H 5=L 6=M 7=A
REG_CODES = ((u"B", 0), (u"C", 1), (u"D", 2), (u"E", 3), (u"H", 4), (u"L", 5), (u"A", 7))

# Способ выделения байтов из слова.
#   'bits' - побитный доступ W.0..W.15 (проверено пробой gen_probe_bits)
#   'mask' - маски AND на WORD + NE (запасной вариант)
#   'w2b'  - оператор WORD_TO_BYTE (запасной вариант)
WORD_SPLIT = 'bits'


# ======================================================================
def make_unpack_word():
    p = Pou(u"FB_UnpackWord", u"functionBlock",
            doc=u"Разделение 16-разрядного слова на два байта.\n"
                u"\tВход:  W - слово\n"
                u"\tВыходы: Lo - младший байт (W.0..W.7), Hi - старший (W.8..W.15)\n"
                u"\tНужен там, где 16-разрядный результат надо положить в память\n"
                u"\tпобайтно (PUSH/CALL/RST - адрес возврата, SHLD, DAD - пара HL).\n"
                u"\tСпособ выделения байтов: %s." % WORD_SPLIT)
    p.var_in(u"W", u"WORD", u"исходное слово")
    p.var_out(u"Lo", u"BYTE", u"младший байт")
    p.var_out(u"Hi", u"BYTE", u"старший байт")
    # ЭКЗЕМПЛЯРЫ ВЫЗЫВАЕМОГО FB ОБЯЗАТЕЛЬНЫ (этап 4, ошибки кодогенерации):
    # блок с typeName="FB_PackByte" и БЕЗ instanceName даёт сразу три ошибки -
    #   C80: Функциональный блок 'FB_PackByte' должен иметь экземпляр (дважды),
    #   C32: Невозможно конвертировать тип 'BYTE' в тип 'BOOL'.
    # Разбор объявлений такие вызовы принимает, кодогенерация - нет.
    p.var(u"up_lo", u"FB_PackByte", u"упаковка битов W.0..W.7 в младший байт")
    p.var(u"up_hi", u"FB_PackByte", u"упаковка битов W.8..W.15 в старший байт")

    if WORD_SPLIT == 'bits':
        n = p.network(u"СЕТЬ 1. Lo := упаковка битов W.0..W.7")
        n.outvar(u"Lo", n.block(u"FB_PackByte",
                                [(u"B%d" % i, n.invar(u"W.%d" % i)) for i in range(8)],
                                [u"B"], instance=u"up_lo"))
        n = p.network(u"СЕТЬ 2. Hi := упаковка битов W.8..W.15")
        n.outvar(u"Hi", n.block(u"FB_PackByte",
                                [(u"B%d" % i, n.invar(u"W.%d" % (i + 8))) for i in range(8)],
                                [u"B"], instance=u"up_hi"))
    elif WORD_SPLIT == 'mask':
        for k, (out, rng) in enumerate(((u"Lo", range(8)), (u"Hi", range(8, 16)))):
            n = p.network(u"СЕТЬ %d. %s := (W AND 2^i) <> 0, упаковка" % (k + 1, out))
            ins = []
            for i in rng:
                a = n.block(u"AND", [(u"IN1", n.invar(u"W")),
                                     (u"IN2", n.invar(u"WORD#%d" % (1 << i)))], [u"OUT"])
                ins.append((u"B%d" % (i - rng[0]),
                            n.block(u"NE", [(u"IN1", a), (u"IN2", n.invar(u"WORD#0"))],
                                    [u"OUT"], fbd_xml.COL_BLK2)))
            n.outvar(out, n.block(u"FB_PackByte", ins, [u"B"], fbd_xml.COL_BLK2 + 160,
                                  instance=u"up_%s" % out.lower()))
    else:
        n = p.network(u"СЕТЬ 1. Lo := WORD_TO_BYTE(W)")
        n.outvar(u"Lo", n.block(u"WORD_TO_BYTE", [(u"IN", n.invar(u"W"))], [u"OUT"]))
        n = p.network(u"СЕТЬ 2. Hi := WORD_TO_BYTE(SHR(W,8))")
        sh = n.block(u"SHR", [(u"IN1", n.invar(u"W")), (u"IN2", n.invar(u"WORD#8"))], [u"OUT"])
        n.outvar(u"Hi", n.block(u"WORD_TO_BYTE", [(u"IN", sh)], [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
def make_reg8q():
    p = Pou(u"FB_Reg8Q", u"functionBlock",
            doc=u"8-разрядный регистр с четырьмя портами загрузки.\n"
                u"\tQ := CLR ? 0 : (LD1 ? D1 : (LD2 ? D2 : (LD3 ? D3 : (LD4 ? D4 : Q))))\n"
                u"\tПриоритет: CLR > LD1 > LD2 > LD3 > LD4 > хранение.\n"
                u"\tПорты 3 и 4 нужны команде XCHG (обмен DE <-> HL пишет сразу\n"
                u"\tчетыре регистра), порты 1 и 2 - LHLD, POP, SHLD, INR/DCR.\n"
                u"\tРегистры обновляются в конце вызова: чтение Q в том же скане\n"
                u"\tдаёт значение, записанное предыдущим сканом.")
    p.var_in(u"D1", u"BYTE", u"данные порта 1")
    p.var_in(u"LD1", u"BOOL", u"загрузка порта 1")
    p.var_in(u"D2", u"BYTE", u"данные порта 2")
    p.var_in(u"LD2", u"BOOL", u"загрузка порта 2")
    p.var_in(u"D3", u"BYTE", u"данные порта 3")
    p.var_in(u"LD3", u"BOOL", u"загрузка порта 3")
    p.var_in(u"D4", u"BYTE", u"данные порта 4")
    p.var_in(u"LD4", u"BOOL", u"загрузка порта 4")
    p.var_in(u"CLR", u"BOOL", u"сброс в ноль (приоритетнее загрузки)")
    p.var_out(u"Q", u"BYTE", u"текущее значение регистра")

    n = p.network(u"СЕТЬ 1. Хранение и четыре порта загрузки")
    q = n.invar(u"Q")
    t = n.block(u"SEL", [(u"G", n.invar(u"LD4")), (u"IN0", q), (u"IN1", n.invar(u"D4"))],
                [u"OUT"])
    t = n.block(u"SEL", [(u"G", n.invar(u"LD3")), (u"IN0", t), (u"IN1", n.invar(u"D3"))],
                [u"OUT"], fbd_xml.COL_BLK2)
    t = n.block(u"SEL", [(u"G", n.invar(u"LD2")), (u"IN0", t), (u"IN1", n.invar(u"D2"))],
                [u"OUT"], fbd_xml.COL_BLK2 + 140)
    t = n.block(u"SEL", [(u"G", n.invar(u"LD1")), (u"IN0", t), (u"IN1", n.invar(u"D1"))],
                [u"OUT"], fbd_xml.COL_BLK2 + 280)
    n.outvar(u"Q", n.block(u"SEL", [(u"G", n.invar(u"CLR")), (u"IN0", t),
                                    (u"IN1", n.invar(u"BYTE#0"))],
                           [u"OUT"], fbd_xml.COL_BLK2 + 420))
    return p


# ======================================================================
def make_reg_file_q():
    p = Pou(u"FB_RegFileQ", u"functionBlock",
            doc=u"Регистровый файл процессора 8080 с четырьмя портами записи.\n"
                u"\tКоды регистров: 0=B 1=C 2=D 3=E 4=H 5=L 6=M 7=A\n"
                u"\t(код 6 - не регистр, а память по адресу HL: её пишет FB_CPU8080).\n"
                u"\tВходы: Data1..Data4 - четыре шины данных,\n"
                u"\t        Dst1, Dst2  - коды регистров-приёмников для портов 1 и 2,\n"
                u"\t        Wr1..Wr4    - разрешения записи по портам.\n"
                u"\tПорты 3 и 4 адресуются жёстко: порт 3 - регистр H (код 4),\n"
                u"\tпорт 4 - регистр L (код 5). Так сделано потому, что их использует\n"
                u"\tединственная команда - XCHG (H<-D, L<-E), а экономия на\n"
                u"\tдешифраторе адреса уменьшает схему.\n"
                u"\tВыходы: A, B, C, D, E, H, L - значения регистров (предыдущий такт).")
    p.var_in(u"Data1", u"BYTE", u"шина данных порта 1")
    p.var_in(u"Dst1", u"BYTE", u"код регистра-приёмника порта 1")
    p.var_in(u"Wr1", u"BOOL", u"запись порта 1")
    p.var_in(u"Data2", u"BYTE", u"шина данных порта 2")
    p.var_in(u"Dst2", u"BYTE", u"код регистра-приёмника порта 2")
    p.var_in(u"Wr2", u"BOOL", u"запись порта 2")
    p.var_in(u"Data3", u"BYTE", u"шина данных порта 3 (только H)")
    p.var_in(u"Wr3", u"BOOL", u"запись порта 3 (H <- Data3)")
    p.var_in(u"Data4", u"BYTE", u"шина данных порта 4 (только L)")
    p.var_in(u"Wr4", u"BOOL", u"запись порта 4 (L <- Data4)")
    for r, _c in REG_CODES:
        p.var_out(r, u"BYTE", u"регистр %s" % r)
    for r, _c in REG_CODES:
        p.var(u"r%s" % r, u"FB_Reg8Q", u"регистр %s" % r)

    n = p.network(u"СЕТЬ 1. Дешифрация кодов Dst1/Dst2 и загрузка семи регистров")
    d1 = n.invar(u"Dst1")
    d2 = n.invar(u"Dst2")
    w1 = n.invar(u"Wr1")
    w2 = n.invar(u"Wr2")
    w3 = n.invar(u"Wr3")
    w4 = n.invar(u"Wr4")
    for r, code in REG_CODES:
        e1 = n.block(u"EQ", [(u"IN1", d1), (u"IN2", n.invar(u"BYTE#%d" % code))], [u"OUT"])
        ld1 = n.block(u"AND", [(u"IN1", e1), (u"IN2", w1)], [u"OUT"], fbd_xml.COL_BLK2)
        e2 = n.block(u"EQ", [(u"IN1", d2), (u"IN2", n.invar(u"BYTE#%d" % code))], [u"OUT"])
        ld2 = n.block(u"AND", [(u"IN1", e2), (u"IN2", w2)], [u"OUT"], fbd_xml.COL_BLK2)
        # порт 3 - только H (код 4), порт 4 - только L (код 5)
        ld3 = w3 if code == 4 else n.invar(u"FALSE")
        ld4 = w4 if code == 5 else n.invar(u"FALSE")
        blk = n.block(u"FB_Reg8Q", [
            (u"D1", n.invar(u"Data1")), (u"LD1", ld1),
            (u"D2", n.invar(u"Data2")), (u"LD2", ld2),
            (u"D3", n.invar(u"Data3")), (u"LD3", ld3),
            (u"D4", n.invar(u"Data4")), (u"LD4", ld4),
            (u"CLR", n.invar(u"FALSE")),
        ], [u"Q"], instance=u"r%s" % r, x=fbd_xml.COL_BLK2 + 200)
        n.outvar(r, blk.out(u"Q"))
    return p


# ======================================================================
def make_flags_reg2():
    p = Pou(u"FB_FlagsReg2", u"functionBlock",
            doc=u"Регистр флагов с раздельной записью по каждому флагу.\n"
                u"\tВ 8080 флаги обновляются по-разному:\n"
                u"\t  ADD/ADC/SUB/SBB/ANA/ORA/XRA/CMP и ADI..CPI - S, Z, AC, P, CY;\n"
                u"\t  INR/DCR                                        - S, Z, AC, P (БЕЗ CY);\n"
                u"\t  DAD, RLC/RRC/RAL/RAR, STC/CMC                  - ТОЛЬКО CY;\n"
                u"\t  CMA                                            - ни один флаг;\n"
                u"\t  DAA                                            - S, Z, AC, P, CY.\n"
                u"\tПоэтому у каждого флага свой вход разрешения LD_S..LD_CY.\n"
                u"\tLD_PSW (POP PSW) имеет приоритет над LD_*: флаги берутся из битов\n"
                u"\tвходного байта PSW_In, где 7=S 6=Z 4=AC 2=P 0=CY.\n"
                u"\tВыход PSW - упакованный байт состояния (бит 1 всегда 1).")
    p.var_in(u"S_In", u"BOOL", u"новый флаг знака")
    p.var_in(u"Z_In", u"BOOL", u"новый флаг нуля")
    p.var_in(u"AC_In", u"BOOL", u"новый флаг дополнительного переноса")
    p.var_in(u"P_In", u"BOOL", u"новый флаг чётности")
    p.var_in(u"CY_In", u"BOOL", u"новый флаг переноса")
    p.var_in(u"LD_S", u"BOOL", u"записать S")
    p.var_in(u"LD_Z", u"BOOL", u"записать Z")
    p.var_in(u"LD_AC", u"BOOL", u"записать AC")
    p.var_in(u"LD_P", u"BOOL", u"записать P")
    p.var_in(u"LD_CY", u"BOOL", u"записать CY")
    p.var_in(u"PSW_In", u"BYTE", u"байт состояния для POP PSW")
    p.var_in(u"LD_PSW", u"BOOL", u"загрузить все флаги из PSW_In")
    p.var_out(u"S", u"BOOL", u"знак")
    p.var_out(u"Z", u"BOOL", u"ноль")
    p.var_out(u"AC", u"BOOL", u"дополнительный перенос")
    p.var_out(u"P", u"BOOL", u"чётность")
    p.var_out(u"CY", u"BOOL", u"перенос")
    p.var_out(u"PSW", u"BYTE", u"упакованный байт состояния")
    p.var(u"upsw", u"FB_UnpackByte", u"распаковка PSW_In")
    p.var(u"ppsw", u"FB_PackByte", u"упаковка PSW")
    for i in range(8):
        p.var(u"pb%d" % i, u"BOOL", u"защёлкнутый бит %d байта PSW_In" % i)

    # Выходы вызова FB сразу переносим в переменные: читать их из следующих
    # сетей нельзя - импортёр CODESYS на такой схеме зависает (баг №6 журнала).
    n = p.network(u"СЕТЬ 1. Распаковка PSW_In в отдельные биты")
    up = n.block(u"FB_UnpackByte", [(u"B", n.invar(u"PSW_In"))],
                 [u"B%d" % i for i in range(8)], instance=u"upsw")
    for i in range(8):
        n.outvar(u"pb%d" % i, up.out(u"B%d" % i))

    for k, (bit, iname, oname, lname) in enumerate((
            (7, u"S_In", u"S", u"LD_S"), (6, u"Z_In", u"Z", u"LD_Z"),
            (4, u"AC_In", u"AC", u"LD_AC"), (2, u"P_In", u"P", u"LD_P"),
            (0, u"CY_In", u"CY", u"LD_CY"))):
        n = p.network(u"СЕТЬ %d. Флаг %s := LD_PSW ? PSW.бит%d : (%s ? %s : %s)"
                      % (k + 2, oname, bit, lname, iname, oname))
        t1 = n.block(u"SEL", [(u"G", n.invar(lname)), (u"IN0", n.invar(oname)),
                              (u"IN1", n.invar(iname))], [u"OUT"])
        t2 = n.block(u"SEL", [(u"G", n.invar(u"LD_PSW")), (u"IN0", t1),
                              (u"IN1", n.invar(u"pb%d" % bit))], [u"OUT"], fbd_xml.COL_BLK2)
        n.outvar(oname, t2)

    n = p.network(u"СЕТЬ 7. Упаковка PSW: 7=S 6=Z 5=0 4=AC 3=0 2=P 1=1 0=CY")
    n.outvar(u"PSW", n.block(u"FB_PackByte", [
        (u"B0", n.invar(u"CY")), (u"B1", n.invar(u"TRUE")),
        (u"B2", n.invar(u"P")), (u"B3", n.invar(u"FALSE")),
        (u"B4", n.invar(u"AC")), (u"B5", n.invar(u"FALSE")),
        (u"B6", n.invar(u"Z")), (u"B7", n.invar(u"S")),
    ], [u"B"], instance=u"ppsw"))
    return p


# ======================================================================
def make_rotate8():
    p = Pou(u"FB_Rotate8", u"functionBlock",
            doc=u"Сдвиги аккумулятора: RLC, RRC, RAL, RAR.\n"
                u"\tВходы:  A - аккумулятор, CY_In - текущий перенос, Kind - вид:\n"
                u"\t        0=RLC (влево, бит 7 -> CY и в бит 0),\n"
                u"\t        1=RRC (вправо, бит 0 -> CY и в бит 7),\n"
                u"\t        2=RAL (влево через перенос: CY -> бит 0, бит 7 -> CY),\n"
                u"\t        3=RAR (вправо через перенос: CY -> бит 7, бит 0 -> CY).\n"
                u"\tВыходы: R - результат, CY_Out - новый перенос.\n"
                u"\tФлаги S, Z, AC, P этими командами НЕ меняются.\n"
                u"\tРеализация - на разрядах, а не сдвигами: в FBD сдвиг BYTE\n"
                u"\tработает в разрядности BYTE, и полагаться на вынос бита нельзя.\n"
                u"\tКаждый выходной разряд выбирается из двух входных (сосед слева\n"
                u"\tили справа), а крайние разряды берут бит переноса либо бит\n"
                u"\tс противоположного конца - ровно так работает кольцо.")
    p.var_in(u"A", u"BYTE", u"аккумулятор")
    p.var_in(u"CY_In", u"BOOL", u"текущий перенос")
    p.var_in(u"Kind", u"BYTE", u"вид сдвига 0..3")
    p.var_out(u"R", u"BYTE", u"результат")
    p.var_out(u"CY_Out", u"BOOL", u"новый перенос")
    p.var(u"ua", u"FB_UnpackByte", u"распаковка аккумулятора")
    p.var(u"up", u"FB_PackByte", u"упаковка результата")
    for i in range(8):
        p.var(u"b%d" % i, u"BOOL", u"разряд %d аккумулятора" % i)
    p.var(u"right", u"BOOL", u"сдвиг вправо (RRC или RAR)")
    p.var(u"lin", u"BOOL", u"бит, входящий слева (RLC: b7, RAL: CY)")
    p.var(u"rin", u"BOOL", u"бит, входящий справа (RRC: b0, RAR: CY)")
    for i in range(8):
        p.var(u"o%d" % i, u"BOOL", u"разряд %d результата" % i)

    n = p.network(u"СЕТЬ 1. Распаковка аккумулятора")
    ua = n.block(u"FB_UnpackByte", [(u"B", n.invar(u"A"))],
                 [u"B%d" % i for i in range(8)], instance=u"ua")
    for i in range(8):
        n.outvar(u"b%d" % i, ua.out(u"B%d" % i))

    n = p.network(u"СЕТЬ 2. Признак направления и биты, входящие с краёв")
    k1 = n.block(u"EQ", [(u"IN1", n.invar(u"Kind")), (u"IN2", n.invar(u"BYTE#1"))], [u"OUT"])
    k2 = n.block(u"EQ", [(u"IN1", n.invar(u"Kind")), (u"IN2", n.invar(u"BYTE#2"))],
                 [u"OUT"], fbd_xml.COL_BLK2)
    k3 = n.block(u"EQ", [(u"IN1", n.invar(u"Kind")), (u"IN2", n.invar(u"BYTE#3"))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 120)
    n.outvar(u"right", n.block(u"OR", [(u"IN1", k1), (u"IN2", k3)], [u"OUT"],
                               fbd_xml.COL_BLK2 + 240))
    n.outvar(u"lin", n.block(u"SEL", [(u"G", k2), (u"IN0", n.invar(u"b7")),
                                      (u"IN1", n.invar(u"CY_In"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 360))
    n.outvar(u"rin", n.block(u"SEL", [(u"G", k3), (u"IN0", n.invar(u"b0")),
                                      (u"IN1", n.invar(u"CY_In"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 480))

    n = p.network(u"СЕТЬ 3. Разряды результата: сдвиг влево или вправо")
    bits = [n.invar(u"b%d" % i) for i in range(8)]
    n.outvar(u"o0", n.block(u"SEL", [(u"G", n.invar(u"right")), (u"IN0", n.invar(u"lin")),
                                     (u"IN1", bits[1])], [u"OUT"]))
    for i in range(1, 7):
        n.outvar(u"o%d" % i, n.block(u"SEL", [(u"G", n.invar(u"right")),
                                              (u"IN0", bits[i - 1]), (u"IN1", bits[i + 1])],
                                     [u"OUT"], fbd_xml.COL_BLK + 120 * i))
    n.outvar(u"o7", n.block(u"SEL", [(u"G", n.invar(u"right")), (u"IN0", bits[6]),
                                     (u"IN1", n.invar(u"rin"))],
                            [u"OUT"], fbd_xml.COL_BLK + 120 * 7))

    n = p.network(u"СЕТЬ 4. Упаковка результата и новый перенос")
    n.outvar(u"R", n.block(u"FB_PackByte", [(u"B%d" % i, n.invar(u"o%d" % i))
                                            for i in range(8)], [u"B"], instance=u"up"))
    n.outvar(u"CY_Out", n.block(u"SEL", [(u"G", n.invar(u"right")), (u"IN0", n.invar(u"b7")),
                                         (u"IN1", n.invar(u"b0"))],
                                [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
def make_daa():
    p = Pou(u"FB_DAA", u"functionBlock",
            doc=u"Десятичная коррекция аккумулятора (DAA) для упакованного BCD.\n"
                u"\tПравило 8080:\n"
                u"\t  если (A AND 0Fh) >= 0Ah или AC = 1, то A := A + 06h (старший\n"
                u"\t     полубайт коррекции AC_Out := 1, иначе 0);\n"
                u"\t  если A >= 9Ah или CY = 1, то A := A + 60h, CY_Out := 1, иначе 0.\n"
                u"\tСложение идёт по модулю 256 (BYTE), как в реальном 8080.\n"
                u"\tВходы:  A, AC_In, CY_In\n"
                u"\tВыходы: R - результат, AC_Out, CY_Out - новые флаги AC и CY.\n"
                u"\tФлаги S, Z, P считает вызывающая сторона (в ядре для этого\n"
                u"\tиспользуется свободный вызов FB_ALU8 с операцией ADD и B=0).")
    p.var_in(u"A", u"BYTE", u"аккумулятор")
    p.var_in(u"AC_In", u"BOOL", u"флаг дополнительного переноса")
    p.var_in(u"CY_In", u"BOOL", u"флаг переноса")
    p.var_out(u"R", u"BYTE", u"результат")
    p.var_out(u"AC_Out", u"BOOL", u"новый AC (коррекция младшей тетрады)")
    p.var_out(u"CY_Out", u"BOOL", u"новый CY (коррекция старшей тетрады)")

    n = p.network(u"СЕТЬ 1. Младшая тетрада: (A AND 0Fh) >= 0Ah или AC")
    low = n.block(u"AND", [(u"IN1", n.invar(u"A")), (u"IN2", n.invar(u"BYTE#16#0F"))], [u"OUT"])
    ge = n.block(u"GE", [(u"IN1", low), (u"IN2", n.invar(u"BYTE#16#0A"))], [u"OUT"],
                 fbd_xml.COL_BLK2)
    fix_lo = n.block(u"OR", [(u"IN1", ge), (u"IN2", n.invar(u"AC_In"))], [u"OUT"],
                     fbd_xml.COL_BLK2 + 120)
    n.outvar(u"AC_Out", fix_lo)

    n = p.network(u"СЕТЬ 2. Старшая тетрада: A >= 9Ah или CY")
    ge2 = n.block(u"GE", [(u"IN1", n.invar(u"A")), (u"IN2", n.invar(u"BYTE#16#9A"))], [u"OUT"])
    fix_hi = n.block(u"OR", [(u"IN1", ge2), (u"IN2", n.invar(u"CY_In"))], [u"OUT"],
                     fbd_xml.COL_BLK2)
    n.outvar(u"CY_Out", fix_hi)

    n = p.network(u"СЕТЬ 3. Коррекция: A + 06h, затем + 60h")
    a6 = n.block(u"ADD", [(u"IN1", n.invar(u"A")), (u"IN2", n.invar(u"BYTE#6"))], [u"OUT"])
    t = n.block(u"SEL", [(u"G", n.invar(u"AC_Out")), (u"IN0", n.invar(u"A")), (u"IN1", a6)],
                [u"OUT"], fbd_xml.COL_BLK2)
    a60 = n.block(u"ADD", [(u"IN1", t), (u"IN2", n.invar(u"BYTE#16#60"))], [u"OUT"],
                  fbd_xml.COL_BLK2 + 140)
    n.outvar(u"R", n.block(u"SEL", [(u"G", n.invar(u"CY_Out")), (u"IN0", t), (u"IN1", a60)],
                           [u"OUT"], fbd_xml.COL_BLK2 + 280))
    return p


# ======================================================================
def make_interrupt():
    p = Pou(u"FB_Interrupt", u"functionBlock",
            doc=u"Приём запроса прерывания (вход INT процессора).\n"
                u"\tПрерывание принимается, если: INT_Req = 1, IFF = 1 (прерывания\n"
                u"\tразрешены командой EI и запрещены DI) и Busy = 0 (предыдущее\n"
                u"\tпрерывание уже отработано). Приоритет внутри такта абсолютный:\n"
                u"\tвыборка и выполнение очередной команды заменяются переходом\n"
                u"\tна обработчик.\n"
                u"\tПри приёме: PC <- INT_Vector * 8, SP <- SP - 2 (в стек по SP-1 и\n"
                u"\tSP-2 процессор кладёт текущий PC), IFF <- 0, Busy <- 1.\n"
                u"\tКоманда RET при Busy = 1 снимает Busy и снова ставит IFF = 1 -\n"
                u"\tтак же, как в реальном 8080 (RET восстанавливает разрешение).\n"
                u"\tВыходы: Take - прерывание принято, PC_Vec - адрес обработчика,\n"
                u"\t        SP_New - новый указатель стека, Push_Needed - надо\n"
                u"\t        положить PC в стек (совпадает с Take, отдельным\n"
                u"\t        выходом - чтобы схема читалась как микрооперации).")
    p.var_in(u"INT_Req", u"BOOL", u"запрос прерывания")
    p.var_in(u"IFF", u"BOOL", u"разрешение прерываний (триггер IFF)")
    p.var_in(u"Busy", u"BOOL", u"прерывание уже обслуживается")
    p.var_in(u"INT_Vector", u"BYTE", u"номер вектора 0..7")
    p.var_in(u"PC", u"WORD", u"текущий счётчик команд (кладётся в стек)")
    p.var_in(u"SP", u"WORD", u"текущий указатель стека")
    p.var_out(u"Take", u"BOOL", u"прерывание принято")
    p.var_out(u"PC_Vec", u"WORD", u"адрес обработчика = вектор * 8")
    p.var_out(u"SP_New", u"WORD", u"указатель стека после сохранения PC")
    p.var_out(u"Push_Needed", u"BOOL", u"нужно положить PC в стек")
    p.var(u"vec_w", u"WORD", u"вектор, расширенный до слова (см. журнал 10.1)")

    n = p.network(u"СЕТЬ 1. Take := INT_Req AND IFF AND NOT Busy")
    rq = n.invar(u"INT_Req")
    iff = n.invar(u"IFF")
    nb = n.block(u"NOT", [(u"IN", n.invar(u"Busy"))], [u"OUT"])
    t = n.block(u"AND", [(u"IN1", rq), (u"IN2", iff)], [u"OUT"])
    n.outvar(u"Take", n.block(u"AND", [(u"IN1", t), (u"IN2", nb)], [u"OUT"],
                              fbd_xml.COL_BLK2))
    n.outvar(u"Push_Needed", n.invar(u"Take"))

    n = p.network(u"СЕТЬ 2. Адрес обработчика: вектор * 8 (байт сначала в WORD)")
    n.outvar(u"vec_w", n.invar(u"INT_Vector"))
    sh = n.block(u"SHL", [(u"IN1", n.invar(u"vec_w")), (u"IN2", n.invar(u"WORD#3"))],
                 [u"OUT"])
    n.outvar(u"PC_Vec", sh)

    n = p.network(u"СЕТЬ 3. Указатель стека: SP - 2")
    n.outvar(u"SP_New", n.block(u"SUB", [(u"IN1", n.invar(u"SP")),
                                         (u"IN2", n.invar(u"WORD#2"))], [u"OUT"]))
    return p


ALL = (make_unpack_word, make_reg8q, make_reg_file_q, make_flags_reg2,
       make_rotate8, make_daa, make_interrupt)
