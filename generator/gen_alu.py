# -*- coding: utf-8 -*-
u"""ШАГ 3, подшаг 3.2 — АЛУ, коммутация, память, стек.

Состав:
  FB_DecodeRegSel — разбор 3-битного поля регистра (IsMem / IsPair / IsLow)
  FB_Mux8x8       — выбор одного из 8 байт по коду (дерево SEL 8->4->2->1)
  FB_Mux8x16      — то же для 16-разрядных (PC, SP)
  FB_ALU8         — 8-разрядное АЛУ на 8 экземплярах FB_FullAdder + флаги
  FB_Memory64K    — чтение/запись общей памяти 64 КБ с индексной адресацией
  FB_Stack16      — стек: PUSH/POP через ту же память по указателю SP

Коды операций АЛУ (вход OP):
  0 = ADD, 1 = ADC, 2 = SUB (для CMP тоже 2, без записи результата),
  3 = SBB, 4 = ANA, 5 = ORA, 6 = XRA.
"""

import os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
from fbd_xml import Pou

ROOT = cb.ROOT
L = cb.make_log(u"gen_alu.log")
L(u"=== ШАГ 3.2: АЛУ, коммутация, память, стек ===")


# ======================================================================
def make_decode_regsel():
    p = Pou(u"FB_DecodeRegSel", u"functionBlock",
            doc=u"Разбор 3-битного поля регистра (SSS или DDD) кода команды.\n"
                u"\tВход:  RegCode - код 0..7 (0=B,1=C,2=D,3=E,4=H,5=L,6=M,7=A)\n"
                u"\tВыходы:\n"
                u"\t  IsMem  - код 6: операнд берётся из памяти по адресу HL\n"
                u"\t  IsPair - код >= 4: регистр входит в пару (BC/DE/HL/SP)\n"
                u"\t  IsLow  - младший разряд кода = 1: это C, E или L\n"
                u"\t  Sel    - код без изменений, идёт на адресные входы MUX")
    p.var_in(u"RegCode", u"BYTE", u"поле регистра из кода команды")
    p.var_out(u"IsMem", u"BOOL", u"операнд в памяти (код 6 = M)")
    p.var_out(u"IsPair", u"BOOL", u"регистр из пары (код >= 4)")
    p.var_out(u"IsLow", u"BOOL", u"младший регистр пары (код нечётен)")
    p.var_out(u"Sel", u"BYTE", u"код для MUX")

    n = p.network(u"СЕТЬ 1. IsMem := RegCode = 6")
    rc = n.invar(u"RegCode")
    six = n.invar(u"BYTE#6")
    n.outvar(u"IsMem", n.block(u"EQ", [(u"IN1", rc), (u"IN2", six)], [u"OUT"]))

    n = p.network(u"СЕТЬ 2. IsPair := RegCode >= 4")
    rc = n.invar(u"RegCode")
    four = n.invar(u"BYTE#4")
    n.outvar(u"IsPair", n.block(u"GE", [(u"IN1", rc), (u"IN2", four)], [u"OUT"]))

    n = p.network(u"СЕТЬ 3. IsLow: младший бит кода (маска и сдвиг)")
    rc = n.invar(u"RegCode")
    one = n.invar(u"BYTE#1")
    zero = n.invar(u"BYTE#0")
    a = n.block(u"AND", [(u"IN1", rc), (u"IN2", one)], [u"OUT"])
    n.outvar(u"IsLow", n.block(u"NE", [(u"IN1", a), (u"IN2", zero)], [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 4. Sel := RegCode (сквозная передача на MUX)")
    rc = n.invar(u"RegCode")
    n.outvar(u"Sel", rc)
    return p


# ======================================================================
def make_mux8x8():
    p = Pou(u"FB_Mux8x8", u"functionBlock",
            doc=u"Выбор одного из восьми байт по 3-битному коду.\n"
                u"\tДерево SEL: 8 -> 4 -> 2 -> 1, разряды кода 0, 1, 2.\n"
                u"\tПрименяется для выбора регистра-источника (A..L) и приёмника.")
    p.var_in(u"Sel", u"BYTE", u"код 0..7")
    for i in range(8):
        p.var_in(u"I%d" % i, u"BYTE", u"вход %d" % i)
    p.var_out(u"Q", u"BYTE", u"выбранное значение")

    n = p.network(u"СЕТЬ 1. Разряды кода: s0 = Sel.0, s1 = Sel.1, s2 = Sel.2")
    sel = n.invar(u"Sel")
    zero = n.invar(u"BYTE#0")
    s = []
    for k, mask in enumerate((u"BYTE#1", u"BYTE#2", u"BYTE#4")):
        m = n.invar(mask)
        a = n.block(u"AND", [(u"IN1", sel), (u"IN2", m)], [u"OUT"])
        s.append(n.block(u"NE", [(u"IN1", a), (u"IN2", zero)], [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 2. Дерево SEL: 8 -> 4 -> 2 -> 1")
    ins = [n.invar(u"I%d" % i) for i in range(8)]
    lvl1 = []
    for k in range(0, 8, 2):
        lvl1.append(n.block(u"SEL", [(u"G", s[0]), (u"IN0", ins[k]), (u"IN1", ins[k + 1])],
                            [u"OUT"], fbd_xml.COL_BLK))
    lvl2 = []
    for k in range(0, 4, 2):
        lvl2.append(n.block(u"SEL", [(u"G", s[1]), (u"IN0", lvl1[k]), (u"IN1", lvl1[k + 1])],
                            [u"OUT"], fbd_xml.COL_BLK2))
    q = n.block(u"SEL", [(u"G", s[2]), (u"IN0", lvl2[0]), (u"IN1", lvl2[1])],
                [u"OUT"], fbd_xml.COL_BLK2 + 140)
    n.outvar(u"Q", q)
    return p


# ======================================================================
def make_mux8x16():
    p = Pou(u"FB_Mux8x16", u"functionBlock",
            doc=u"То же, что FB_Mux8x8, но для 16-разрядных значений.\n"
                u"\tПрименяется для выбора регистровой пары (BC/DE/HL/SP)\n"
                u"\tи адреса следующей команды PC.")
    p.var_in(u"Sel", u"BYTE", u"код 0..7")
    for i in range(8):
        p.var_in(u"I%d" % i, u"WORD", u"вход %d" % i)
    p.var_out(u"Q", u"WORD", u"выбранное значение")

    n = p.network(u"СЕТЬ 1. Разряды кода 0, 1, 2")
    sel = n.invar(u"Sel")
    zero = n.invar(u"BYTE#0")
    s = []
    for mask in (u"BYTE#1", u"BYTE#2", u"BYTE#4"):
        m = n.invar(mask)
        a = n.block(u"AND", [(u"IN1", sel), (u"IN2", m)], [u"OUT"])
        s.append(n.block(u"NE", [(u"IN1", a), (u"IN2", zero)], [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 2. Дерево SEL: 8 -> 4 -> 2 -> 1")
    ins = [n.invar(u"I%d" % i) for i in range(8)]
    lvl1 = []
    for k in range(0, 8, 2):
        lvl1.append(n.block(u"SEL", [(u"G", s[0]), (u"IN0", ins[k]), (u"IN1", ins[k + 1])],
                            [u"OUT"], fbd_xml.COL_BLK))
    lvl2 = []
    for k in range(0, 4, 2):
        lvl2.append(n.block(u"SEL", [(u"G", s[1]), (u"IN0", lvl1[k]), (u"IN1", lvl1[k + 1])],
                            [u"OUT"], fbd_xml.COL_BLK2))
    q = n.block(u"SEL", [(u"G", s[2]), (u"IN0", lvl2[0]), (u"IN1", lvl2[1])],
                [u"OUT"], fbd_xml.COL_BLK2 + 140)
    n.outvar(u"Q", q)
    return p


# ======================================================================
def make_alu8():
    p = Pou(u"FB_ALU8", u"functionBlock",
            doc=u"8-разрядное арифметико-логическое устройство.\n"
                u"\tВходы:  OP - код операции, A и B - операнды, Cin - входной перенос\n"
                u"\tВыходы: R - результат, CY - перенос/заём, AC - перенос из разряда 3,\n"
                u"\t        S - знак, Z - ноль, P - чётность\n"
                u"\tКоды OP: 0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=ORA 6=XRA\n"
                u"\t(CMP выполняется кодом 2, результат просто не записывается.)\n"
                u"\tЯдро - 8 экземпляров FB_FullAdder, соединённых цепью переносов\n"
                u"\tc0..c8. Переносы вынесены в отдельные переменные: во-первых так\n"
                u"\tсхема читается как настоящий сумматор, во-вторых выход вызова FB\n"
                u"\tнельзя разветвлять (CODESYS выбрасывает такой POU).\n"
                u"\tВычитание: A + NOT(B) + 1 (дополнительный код).\n"
                u"\tЛогические операции: CY := 0, AC := 0 (у ANA AC := 1).")
    p.var_in(u"OP", u"BYTE", u"код операции 0..6")
    p.var_in(u"A", u"BYTE", u"операнд A (обычно аккумулятор)")
    p.var_in(u"B", u"BYTE", u"операнд B")
    p.var_in(u"Cin", u"BOOL", u"входной перенос для ADC/SBB")
    p.var_out(u"R", u"BYTE", u"результат")
    p.var_out(u"CY", u"BOOL", u"перенос из старшего разряда")
    p.var_out(u"AC", u"BOOL", u"перенос из разряда 3")
    p.var_out(u"S", u"BOOL", u"знак: R.7")
    p.var_out(u"Z", u"BOOL", u"ноль: R = 0")
    p.var_out(u"P", u"BOOL", u"чётность: чётное число единиц в R")
    for i in range(8):
        p.var(u"a%d" % i, u"BOOL", u"разряд %d операнда A" % i)
        p.var(u"b%d" % i, u"BOOL", u"разряд %d операнда B'" % i)
        p.var(u"s%d" % i, u"BOOL", u"сумма разряда %d" % i)
    for i in range(9):
        p.var(u"c%d" % i, u"BOOL", u"перенос в разряд %d" % i)
    for i in range(8):
        p.var(u"fa%d" % i, u"FB_FullAdder", u"сумматор разряда %d" % i)
    p.var(u"ua", u"FB_UnpackByte", u"распаковка A")
    p.var(u"ub", u"FB_UnpackByte", u"распаковка B после инверсии")
    p.var(u"up", u"FB_PackByte", u"упаковка суммы")

    # --- сеть 1: признаки операции -------------------------------------
    n = p.network(u"СЕТЬ 1. Признаки операции: IsSub(2,3), Logic(4..6), IsAna(4)")
    op = n.invar(u"OP")
    c2 = n.invar(u"BYTE#2"); c3 = n.invar(u"BYTE#3")
    c4 = n.invar(u"BYTE#4"); c6 = n.invar(u"BYTE#6")
    e2 = n.block(u"EQ", [(u"IN1", op), (u"IN2", c2)], [u"OUT"])
    e3 = n.block(u"EQ", [(u"IN1", op), (u"IN2", c3)], [u"OUT"])
    issub = n.block(u"OR", [(u"IN1", e2), (u"IN2", e3)], [u"OUT"], fbd_xml.COL_BLK2)
    ge4 = n.block(u"GE", [(u"IN1", op), (u"IN2", c4)], [u"OUT"], fbd_xml.COL_BLK2 + 60)
    le6 = n.block(u"LE", [(u"IN1", op), (u"IN2", c6)], [u"OUT"], fbd_xml.COL_BLK2 + 60)
    islogic = n.block(u"AND", [(u"IN1", ge4), (u"IN2", le6)], [u"OUT"], fbd_xml.COL_BLK2 + 200)
    isana = n.block(u"EQ", [(u"IN1", op), (u"IN2", c4)], [u"OUT"], fbd_xml.COL_BLK2 + 200)

    # --- сеть 2: B' и входной перенос ----------------------------------
    n = p.network(u"СЕТЬ 2. B' := IsSub ? NOT B : B ;  Cin' := IsSub ? (SBB ? NOT CY : 1) : Cin")
    b = n.invar(u"B")
    notb = n.block(u"NOT", [(u"IN", b)], [u"OUT"])
    beff = n.block(u"SEL", [(u"G", issub), (u"IN0", b), (u"IN1", notb)], [u"OUT"], fbd_xml.COL_BLK2)
    cin = n.invar(u"Cin")
    true1 = n.invar(u"TRUE")
    # ФАЗА B. Раньше здесь для ЛЮБОГО вычитания принудительно ставился перенос 1:
    #     Cin' := IsSub ? 1 : Cin
    # Из-за этого SBB (вычитание с заёмом) НЕ УЧИТЫВАЛ входной перенос, и
    # результат получался ровно на 1 больше правильного.
    # ВАЖНО: это единственная правка, которая не ломает остальное. Инверсия
    # флагов CY/AC для вычитания проверена и ОТКЛОНЕНА - она ломает CMP и DCR.
    is_sbb = n.block(u"EQ", [(u"IN1", op), (u"IN2", c3)], [u"OUT"], fbd_xml.COL_BLK2 + 60)
    notcy = n.block(u"NOT", [(u"IN", cin)], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    sub_cin = n.block(u"SEL", [(u"G", is_sbb), (u"IN0", true1), (u"IN1", notcy)],
                      [u"OUT"], fbd_xml.COL_BLK2 + 220)
    cineff = n.block(u"SEL", [(u"G", issub), (u"IN0", cin), (u"IN1", sub_cin)],
                     [u"OUT"], fbd_xml.COL_BLK2 + 320)
    n2 = p.network(u"СЕТЬ 3. c0 := Cin' (перенос в младший разряд)")
    n2.outvar(u"c0", cineff)

    # --- сеть 3: распаковка операндов ----------------------------------
    n = p.network(u"СЕТЬ 4. Распаковка A и B' в разряды (маски и сдвиги)")
    a = n.invar(u"A")
    ua = n.block(u"FB_UnpackByte", [(u"B", a)],
                 [u"B%d" % i for i in range(8)], instance=u"ua")
    ub = n.block(u"FB_UnpackByte", [(u"B", beff)],
                 [u"B%d" % i for i in range(8)], instance=u"ub", x=fbd_xml.COL_BLK2)
    for i in range(8):
        n.outvar(u"a%d" % i, ua.out(u"B%d" % i))
        n.outvar(u"b%d" % i, ub.out(u"B%d" % i))

    # --- сети 5..12: цепь сумматоров -----------------------------------
    for i in range(8):
        n = p.network(u"СЕТЬ %d. Разряд %d: сумматор, перенос c%d -> c%d"
                      % (5 + i, i, i, i + 1))
        ai = n.invar(u"a%d" % i)
        bi = n.invar(u"b%d" % i)
        ci = n.invar(u"c%d" % i)
        fa = n.block(u"FB_FullAdder",
                     [(u"A", ai), (u"B", bi), (u"Cin", ci)],
                     [u"Sum", u"Cout"], instance=u"fa%d" % i)
        n.outvar(u"s%d" % i, fa.out(u"Sum"))
        n.outvar(u"c%d" % (i + 1), fa.out(u"Cout"))

    # --- сеть 13: упаковка ---------------------------------------------
    n = p.network(u"СЕТЬ 13. Упаковка разрядов суммы в байт")
    up = n.block(u"FB_PackByte", [(u"B%d" % i, n.invar(u"s%d" % i)) for i in range(8)],
                 [u"B"], instance=u"up")

    # --- сеть 14: логика и выбор результата ----------------------------
    n = p.network(u"СЕТЬ 14. Логические результаты ANA/ORA/XRA и выбор R")
    a = n.invar(u"A"); b = n.invar(u"B")
    rand = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
    ror = n.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], fbd_xml.COL_BLK2)
    rxor = n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], fbd_xml.COL_BLK2 + 120)
    rlog = n.block(u"SEL", [(u"G", isana), (u"IN0", rxor), (u"IN1", rand)],
                   [u"OUT"], fbd_xml.COL_BLK2 + 240)
    rr = n.block(u"SEL", [(u"G", islogic), (u"IN0", up.out(u"B")), (u"IN1", rlog)],
                 [u"OUT"], fbd_xml.COL_BLK2 + 360)
    n.outvar(u"R", rr)

    # --- сеть 15: Z и S -------------------------------------------------
    n = p.network(u"СЕТЬ 15. Флаги Z и S (из результата R)")
    rv = n.invar(u"R")
    zero8 = n.invar(u"BYTE#0")
    n.outvar(u"Z", n.block(u"EQ", [(u"IN1", rv), (u"IN2", zero8)], [u"OUT"]))
    seven = n.invar(u"BYTE#128")
    aand = n.block(u"AND", [(u"IN1", rv), (u"IN2", seven)], [u"OUT"])
    n.outvar(u"S", n.block(u"NE", [(u"IN1", aand), (u"IN2", n.invar(u"BYTE#0"))],
                           [u"OUT"], fbd_xml.COL_BLK2))

    # --- сеть 16: чётность ---------------------------------------------
    n = p.network(u"СЕТЬ 16. Чётность P: XOR всех разрядов результата")
    rv = n.invar(u"R")
    bits = []
    for i in range(8):
        m = n.invar(u"BYTE#%d" % (1 << i))
        a_ = n.block(u"AND", [(u"IN1", rv), (u"IN2", m)], [u"OUT"])
        z_ = n.invar(u"BYTE#0")
        bits.append(n.block(u"NE", [(u"IN1", a_), (u"IN2", z_)], [u"OUT"], fbd_xml.COL_BLK2))
    lvl = bits
    while len(lvl) > 1:
        nxt = []
        for k in range(0, len(lvl), 2):
            nxt.append(n.block(u"XOR", [(u"IN1", lvl[k]), (u"IN2", lvl[k + 1])],
                               [u"OUT"], fbd_xml.COL_BLK2 + 140))
        lvl = nxt
    # ВАЖНО: P в 8080 равен 1 при ЧЁТНОМ числе единичных битов результата.
    # XOR всех разрядов даёт 1 при НЕЧЁТНОМ числе, поэтому нужна инверсия.
    # Без неё флаг был инвертирован, и часть арифметических и логических
    # кейсов не могла пройти.
    n.outvar(u"P", n.block(u"NOT", [(u"IN", lvl[0])], [u"OUT"],
                           fbd_xml.COL_BLK2 + 200))

    # --- сеть 17: CY и AC ----------------------------------------------
    n = p.network(u"СЕТЬ 17. CY := Logic ? 0 : c8 ;  AC := IsAna ? 1 : (Logic ? 0 : c4)")
    c8 = n.invar(u"c8")
    c4v = n.invar(u"c4")
    false1 = n.invar(u"FALSE")
    true2 = n.invar(u"TRUE")
    # ПРОВЕРЕНО (фаза B): инвертировать CY/AC для вычитания НЕЛЬЗЯ.
    # Попытка "CY := NOT(c8) при вычитании" сломала CMP и DCR (они проходили
    # до неё), то есть в этой схеме флаги переноса уже согласованы с проверками.
    # Оставлена только правка входного переноса для SBB (см. сеть 2).
    n.outvar(u"CY", n.block(u"SEL", [(u"G", islogic), (u"IN0", c8), (u"IN1", false1)],
                            [u"OUT"]))
    ac0 = n.block(u"SEL", [(u"G", islogic), (u"IN0", c4v), (u"IN1", false1)],
                  [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"AC", n.block(u"SEL", [(u"G", isana), (u"IN0", ac0), (u"IN1", true2)],
                            [u"OUT"], fbd_xml.COL_BLK2 + 120))
    return p


# ======================================================================
def make_memory():
    p = Pou(u"FB_Memory64K", u"functionBlock",
            doc=u"Доступ к общей памяти эмулятора (64 КБ) по 16-разрядному адресу.\n"
                u"\tПамять лежит в GVL_MEM.Memory : ARRAY[0..65535] OF BYTE.\n"
                u"\tВходы:  Addr - адрес (шина адреса), Wr - разрешение записи,\n"
                u"\t        DataIn - данные для записи (шина данных)\n"
                u"\tВыход:  DataOut - прочитанный байт (шина данных)\n"
                u"\tПорядок сетей важен: сначала ЧТЕНИЕ, потом ЗАПИСЬ.\n"
                u"\tЗа скан читается старое значение, запись происходит после -\n"
                u"\tименно это нужно такту процессора (сначала выбрать операнды,\n"
                u"\tпотом записать результат).\n"
                u"\tУсловная запись выполнена через SEL: при Wr=FALSE в память\n"
                u"\tзаписывается её же текущее значение.")
    p.var_in(u"Addr", u"WORD", u"адрес ячейки (шина адреса)")
    p.var_in(u"Wr", u"BOOL", u"1 = записать DataIn")
    p.var_in(u"DataIn", u"BYTE", u"данные для записи (шина данных)")
    p.var_out(u"DataOut", u"BYTE", u"прочитанные данные (шина данных)")

    n = p.network(u"СЕТЬ 1. ЧТЕНИЕ: DataOut := GVL_MEM.Memory[Addr]")
    adr = n.invar(u"Addr")
    rd = n.invar(u"GVL_MEM.Memory[Addr]")
    n.outvar(u"DataOut", rd)

    n = p.network(u"СЕТЬ 2. ЗАПИСЬ: Memory[Addr] := Wr ? DataIn : Memory[Addr]")
    adr = n.invar(u"Addr")
    wr = n.invar(u"Wr")
    din = n.invar(u"DataIn")
    old = n.invar(u"GVL_MEM.Memory[Addr]")
    val = n.block(u"SEL", [(u"G", wr), (u"IN0", old), (u"IN1", din)], [u"OUT"])
    n.outvar(u"GVL_MEM.Memory[Addr]", val)
    return p


# ======================================================================
def make_stack():
    p = Pou(u"FB_Stack16", u"functionBlock",
            doc=u"Стек процессора. Использует ту же память, что и FB_Memory64K,\n"
                u"\tпо указателю SP (стек растёт ВНИЗ, как в реальном 8080).\n"
                u"\tВходы:  Push, Pop - команды работы со стеком, SP_In - текущий SP,\n"
                u"\t        DataIn - что положить (для PUSH)\n"
                u"\tВыходы: SP_Out - новый указатель, DataOut - что сняли (для POP)\n"
                u"\tPUSH: SP := SP-1; Memory[SP] := DataIn\n"
                u"\tPOP : DataOut := Memory[SP]; SP := SP+1")
    p.var_in(u"Push", u"BOOL", u"положить на стек")
    p.var_in(u"Pop", u"BOOL", u"снять со стека")
    p.var_in(u"SP_In", u"WORD", u"текущий указатель стека")
    p.var_in(u"DataIn", u"BYTE", u"данные для PUSH")
    p.var_out(u"SP_Out", u"WORD", u"новый указатель стека")
    p.var_out(u"DataOut", u"BYTE", u"данные при POP")

    n = p.network(u"СЕТЬ 1. Новый указатель: PUSH -> SP-1, POP -> SP+1, иначе SP")
    sp = n.invar(u"SP_In")
    one = n.invar(u"WORD#1")
    push = n.invar(u"Push")
    pop = n.invar(u"Pop")
    sp_dec = n.block(u"SUB", [(u"IN1", sp), (u"IN2", one)], [u"OUT"])
    t1 = n.block(u"SEL", [(u"G", push), (u"IN0", sp), (u"IN1", sp_dec)], [u"OUT"], fbd_xml.COL_BLK2)
    sp_inc = n.block(u"ADD", [(u"IN1", sp), (u"IN2", one)], [u"OUT"], fbd_xml.COL_BLK2)
    t2 = n.block(u"SEL", [(u"G", pop), (u"IN0", t1), (u"IN1", sp_inc)], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    n.outvar(u"SP_Out", t2)

    n = p.network(u"СЕТЬ 2. ЧТЕНИЕ вершины: DataOut := Memory[SP_In]")
    sp = n.invar(u"SP_In")
    rd = n.invar(u"GVL_MEM.Memory[SP_In]")
    n.outvar(u"DataOut", rd)

    n = p.network(u"СЕТЬ 3. ЗАПИСЬ при PUSH: Memory[SP_In-1] := Push ? DataIn : старое")
    push = n.invar(u"Push")
    din = n.invar(u"DataIn")
    old = n.invar(u"GVL_MEM.Memory[SP_In-1]")
    n.outvar(u"GVL_MEM.Memory[SP_In-1]", n.block(
        u"SEL", [(u"G", push), (u"IN0", old), (u"IN1", din)], [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
GVL_MEM_TEXT = u"""VAR_GLOBAL
\t(* Общая память эмулятора Intel 8080: 64 КБ *)
\tMemory : ARRAY[0..65535] OF BYTE;
END_VAR
"""

POUS = [make_decode_regsel(), make_mux8x8(), make_mux8x16(),
        make_alu8(), make_memory(), make_stack()]
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/alu_mem.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"alu_mem")
L(u"[1] PLCopenXML записан: %d символов" % size)
L(u"    POU: %s" % u", ".join(NAMES))

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    # базовые FB, на которые ссылаются новые
    cb.add_gvl(app, u"GVL_MEM", GVL_MEM_TEXT, L)
    for dep in (u"FB_Reg8", u"FB_Reg16", u"FB_UnpackByte", u"FB_PackByte", u"FB_FullAdder"):
        app.import_xml(ROOT + u"/src/%s.plcopenxml" % dep)
    L(u"    базовые FB импортированы")

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/alu_mem_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
