# -*- coding: utf-8 -*-
u"""Описание блоков подшага 3.3 на языке схем (библиотека для драйвера gen_decode.py).

Вынесено в отдельный модуль: загрузчик скриптов CODESYS не берёт файлы больше
примерно 25 КБ - процесс стартует и молча висит, не выполнив ни одной строки.
Импортируемые модули читаются обычным загрузчиком IronPython и этого ограничения
не имеют.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

def make_flags_reg():
    p = Pou(u"FB_FlagsReg", u"functionBlock",
            doc=u"Регистр флагов процессора 8080.\n"
                u"\tВходы:  S_In, Z_In, AC_In, P_In, CY_In - новые значения флагов,\n"
                u"\t        LD - защёлкнуть их;\n"
                u"\t        PSW_In - байт состояния (для команды POP PSW),\n"
                u"\t        LD_PSW - загрузить флаги из PSW_In (приоритетнее LD)\n"
                u"\tВыходы: S, Z, AC, P, CY - текущие флаги, PSW - упакованный байт\n"
                u"\tРаскладка PSW: 7=S 6=Z 5=0 4=AC 3=0 2=P 1=1 0=CY\n"
                u"\tРаспаковка PSW_In и упаковка PSW выполняются блоками\n"
                u"\tFB_UnpackByte / FB_PackByte (маски, сдвиги и взвешивание).")
    p.var_in(u"S_In", u"BOOL", u"новый флаг знака")
    p.var_in(u"Z_In", u"BOOL", u"новый флаг нуля")
    p.var_in(u"AC_In", u"BOOL", u"новый флаг дополнительного переноса")
    p.var_in(u"P_In", u"BOOL", u"новый флаг чётности")
    p.var_in(u"CY_In", u"BOOL", u"новый флаг переноса")
    p.var_in(u"LD", u"BOOL", u"защёлкнуть новые флаги")
    p.var_in(u"PSW_In", u"BYTE", u"байт состояния для POP PSW")
    p.var_in(u"LD_PSW", u"BOOL", u"загрузить флаги из PSW_In")
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

    # --- сеть 1: распаковка входного PSW + защёлкивание битов в переменные ---
    # Выходы вызова FB сразу переносим в переменные: читать их напрямую из
    # последующих сетей нельзя - импортёр CODESYS на такой схеме зависает
    # (проверено: FB_FlagsReg с прямым чтением up.B7 вешал импорт намертво).
    n = p.network(u"СЕТЬ 1. Распаковка PSW_In в отдельные биты")
    psw = n.invar(u"PSW_In")
    up = n.block(u"FB_UnpackByte", [(u"B", psw)],
                 [u"B%d" % i for i in range(8)], instance=u"upsw")
    for i in range(8):
        n.outvar(u"pb%d" % i, up.out(u"B%d" % i))

    # --- сети 2..6: по одному флагу ---
    for i, (bit, iname, oname) in enumerate((
            (7, u"S_In", u"S"), (6, u"Z_In", u"Z"), (4, u"AC_In", u"AC"),
            (2, u"P_In", u"P"), (0, u"CY_In", u"CY"))):
        n = p.network(u"СЕТЬ %d. Флаг %s: LD_PSW ? PSW.bit%d : (LD ? %s : %s)"
                      % (i + 2, oname, bit, iname, oname))
        ld = n.invar(u"LD")
        ldpsw = n.invar(u"LD_PSW")
        newv = n.invar(iname)
        old = n.invar(oname)
        pb = n.invar(u"pb%d" % bit)
        t1 = n.block(u"SEL", [(u"G", ld), (u"IN0", old), (u"IN1", newv)], [u"OUT"])
        t2 = n.block(u"SEL", [(u"G", ldpsw), (u"IN0", t1), (u"IN1", pb)],
                     [u"OUT"], fbd_xml.COL_BLK2)
        n.outvar(oname, t2)

    # --- сеть 7: упаковка PSW ---
    n = p.network(u"СЕТЬ 7. Упаковка PSW: 7=S 6=Z 5=0 4=AC 3=0 2=P 1=1 0=CY")
    n.outvar(u"PSW", n.block(u"FB_PackByte", [
        (u"B0", n.invar(u"CY")),
        (u"B1", n.invar(u"TRUE")),
        (u"B2", n.invar(u"P")),
        (u"B3", n.invar(u"FALSE")),
        (u"B4", n.invar(u"AC")),
        (u"B5", n.invar(u"FALSE")),
        (u"B6", n.invar(u"Z")),
        (u"B7", n.invar(u"S")),
    ], [u"B"], instance=u"ppsw"))
    return p


# ======================================================================
def make_decode_mov():
    p = Pou(u"FB_Decode_MOV", u"functionBlock",
            doc=u"Распознавание команды MOV r1,r2.\n"
                u"\tФормат: 01 DDD SSS. Признак - старшие два бита равны 01.\n"
                u"\tИсключение: код 0111 0110 (DDD=6, SSS=6) - это HLT, а не MOV M,M.\n"
                u"\tВыходы: Hit - команда распознана, DDD - код приёмника,\n"
                u"\t        SSS - код источника (6 = память по адресу HL).")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это MOV")
    p.var_out(u"DDD", u"BYTE", u"код регистра-приёмника 0..7")
    p.var_out(u"SSS", u"BYTE", u"код регистра-источника 0..7")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C0h) = 40h  И  IR <> 76h")
    ir = n.invar(u"IR")
    m = n.invar(u"BYTE#16#C0")
    a = n.block(u"AND", [(u"IN1", ir), (u"IN2", m)], [u"OUT"])
    e = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#40"))], [u"OUT"], fbd_xml.COL_BLK2)
    e76 = n.block(u"EQ", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#76"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 140)
    n.outvar(u"Hit", n.block(u"AND", [(u"IN1", e), (u"IN2", n.block(
        u"NOT", [(u"IN", e76)], [u"OUT"], fbd_xml.COL_BLK2 + 260))],
        [u"OUT"], fbd_xml.COL_BLK2 + 380))

    n = p.network(u"СЕТЬ 2. DDD := (IR SHR 3) AND 7")
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"])
    n.outvar(u"DDD", n.block(u"AND", [(u"IN1", sh), (u"IN2", n.invar(u"BYTE#7"))],
                             [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 3. SSS := IR AND 7")
    n.outvar(u"SSS", n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#7"))],
                             [u"OUT"]))
    return p


# ======================================================================
def make_decode_mvi():
    p = Pou(u"FB_Decode_MVI", u"functionBlock",
            doc=u"Распознавание команды MVI r,data.\n"
                u"\tФормат: 00 DDD 110, то есть (IR AND C7h) = 06h.\n"
                u"\tВыходы: Hit - команда распознана, DDD - код приёмника.\n"
                u"\tДанные берутся из памяти по адресу PC+1, длина команды 2 байта.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это MVI")
    p.var_out(u"DDD", u"BYTE", u"код регистра-приёмника 0..7")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C7h) = 06h")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C7"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#6"))],
                             [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 2. DDD := (IR SHR 3) AND 7")
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"])
    n.outvar(u"DDD", n.block(u"AND", [(u"IN1", sh), (u"IN2", n.invar(u"BYTE#7"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
def make_decode_alu():
    p = Pou(u"FB_Decode_ALU", u"functionBlock",
            doc=u"Распознавание арифметико-логических команд вида 10 xxx yyy.\n"
                u"\tЭто ADD/ADC/SUB/SBB/ANA/XRA/ORA/CMP (коды 80h..BFh).\n"
                u"\tПоле xxx (биты 5..3) задаёт операцию:\n"
                u"\t  0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=XRA 6=ORA 7=CMP\n"
                u"\tКоды АЛУ нашего блока: 0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=ORA 6=XRA,\n"
                u"\tпоэтому 5 и 6 меняются местами, а CMP выполняется как SUB (код 2)\n"
                u"\tс запретом записи результата.\n"
                u"\tВыходы: Hit, Op - код операции для FB_ALU8, SSS - код источника,\n"
                u"\t        IsCmp - признак CMP (результат не записывать).")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это АЛУ-команда")
    p.var_out(u"Op", u"BYTE", u"код операции для FB_ALU8")
    p.var_out(u"SSS", u"BYTE", u"код регистра-источника 0..7")
    p.var_out(u"IsCmp", u"BOOL", u"это CMP: флаги обновить, результат не писать")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C0h) = 80h")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C0"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#80"))],
                             [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 2. Группа операции: grp := (IR SHR 3) AND 7")
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"])
    grp = n.block(u"AND", [(u"IN1", sh), (u"IN2", n.invar(u"BYTE#7"))], [u"OUT"], fbd_xml.COL_BLK2)
    e4 = n.block(u"EQ", [(u"IN1", grp), (u"IN2", n.invar(u"BYTE#4"))], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    e5 = n.block(u"EQ", [(u"IN1", grp), (u"IN2", n.invar(u"BYTE#5"))], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    e6 = n.block(u"EQ", [(u"IN1", grp), (u"IN2", n.invar(u"BYTE#6"))], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    e7 = n.block(u"EQ", [(u"IN1", grp), (u"IN2", n.invar(u"BYTE#7"))], [u"OUT"], fbd_xml.COL_BLK2 + 140)
    t1 = n.block(u"SEL", [(u"G", e7), (u"IN0", grp), (u"IN1", n.invar(u"BYTE#2"))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 280)
    t2 = n.block(u"SEL", [(u"G", e6), (u"IN0", t1), (u"IN1", n.invar(u"BYTE#5"))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 400)
    t3 = n.block(u"SEL", [(u"G", e5), (u"IN0", t2), (u"IN1", n.invar(u"BYTE#6"))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 520)
    n.outvar(u"Op", n.block(u"SEL", [(u"G", e4), (u"IN0", t3), (u"IN1", n.invar(u"BYTE#4"))],
                            [u"OUT"], fbd_xml.COL_BLK2 + 640))
    n.outvar(u"IsCmp", e7)

    n = p.network(u"СЕТЬ 3. SSS := IR AND 7")
    n.outvar(u"SSS", n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#7"))],
                             [u"OUT"]))
    return p


# ======================================================================
def make_decode_jmp():
    p = Pou(u"FB_Decode_JMP", u"functionBlock",
            doc=u"Распознавание переходов, вызовов и возвратов.\n"
                u"\tБезусловные: JMP=C3h, CALL=CDh, RET=C9h.\n"
                u"\tУсловные:    Jcc=C2h, Ccc=C4h, Rcc=C0h + код условия в битах 5..3.\n"
                u"\tКоды условий: 0=NZ 1=Z 2=NC 3=C 4=PO 5=PE 6=P 7=M\n"
                u"\tВыходы: Hit - это команда перехода/вызова/возврата,\n"
                u"\t        Kind - класс: 4=JMP, 5=CALL, 6=RET,\n"
                u"\t        Cond - код условия, Uncond - переход безусловный.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"команда перехода/вызова/возврата")
    p.var_out(u"Kind", u"BYTE", u"4=JMP 5=CALL 6=RET")
    p.var_out(u"Cond", u"BYTE", u"код условия 0..7")
    p.var_out(u"Uncond", u"BOOL", u"безусловная форма")

    n = p.network(u"СЕТЬ 1. Признаки JMP / CALL / RET (по маске C7h)")
    ir = n.invar(u"IR")
    m = n.invar(u"BYTE#16#C7")
    a = n.block(u"AND", [(u"IN1", ir), (u"IN2", m)], [u"OUT"])
    j = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C2"))], [u"OUT"])
    c = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C4"))], [u"OUT"], fbd_xml.COL_BLK2)
    r = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C0"))], [u"OUT"], fbd_xml.COL_BLK2 + 120)
    jc = n.block(u"OR", [(u"IN1", j), (u"IN2", c)], [u"OUT"], fbd_xml.COL_BLK2 + 240)
    n.outvar(u"Hit", n.block(u"OR", [(u"IN1", jc), (u"IN2", r)], [u"OUT"], fbd_xml.COL_BLK2 + 360))

    n = p.network(u"СЕТЬ 2. Kind: 4=JMP, 5=CALL, 6=RET (приоритет RET > CALL > JMP)")
    inner = n.block(u"SEL", [(u"G", j), (u"IN0", n.invar(u"BYTE#0")), (u"IN1", n.invar(u"BYTE#4"))],
                    [u"OUT"], fbd_xml.COL_BLK2)
    t = n.block(u"SEL", [(u"G", c), (u"IN0", inner), (u"IN1", n.invar(u"BYTE#5"))],
                [u"OUT"], fbd_xml.COL_BLK2 + 160)
    n.outvar(u"Kind", n.block(u"SEL", [(u"G", r), (u"IN0", t), (u"IN1", n.invar(u"BYTE#6"))],
                              [u"OUT"], fbd_xml.COL_BLK2 + 320))

    n = p.network(u"СЕТЬ 3. Cond := (IR SHR 3) AND 7 ; Uncond := (IR AND C7h) = C3h/CDh/C9h")
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"])
    n.outvar(u"Cond", n.block(u"AND", [(u"IN1", sh), (u"IN2", n.invar(u"BYTE#7"))],
                              [u"OUT"], fbd_xml.COL_BLK2))
    ir = n.invar(u"IR")
    a = n.block(u"AND", [(u"IN1", ir), (u"IN2", n.invar(u"BYTE#16#C7"))], [u"OUT"])
    u1 = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C3"))], [u"OUT"], fbd_xml.COL_BLK2)
    u2 = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#CD"))], [u"OUT"], fbd_xml.COL_BLK2 + 120)
    u3 = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C9"))], [u"OUT"], fbd_xml.COL_BLK2 + 240)
    uu = n.block(u"OR", [(u"IN1", u1), (u"IN2", u2)], [u"OUT"], fbd_xml.COL_BLK2 + 360)
    n.outvar(u"Uncond", n.block(u"OR", [(u"IN1", uu), (u"IN2", u3)], [u"OUT"], fbd_xml.COL_BLK2 + 480))
    return p


# ======================================================================
def make_decode_hlt():
    p = Pou(u"FB_Decode_HLT", u"functionBlock",
            doc=u"Распознавание команды HLT (0111 0110 = 76h).\n"
                u"\tВыход Hit = 1 останавливает процессор: PC и регистры перестают\n"
                u"\tменяться, такты больше не выполняются.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это HLT")
    n = p.network(u"СЕТЬ 1. Hit := IR = 76h")
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", n.invar(u"IR")),
                                     (u"IN2", n.invar(u"BYTE#16#76"))], [u"OUT"]))
    return p


# ======================================================================
def make_decoder():
    p = Pou(u"FB_Decoder", u"functionBlock",
            doc=u"Сводный декодер команд: IR -> управляющее слово на шине GVL_CPU.\n"
                u"\tВход:  IR - регистр команды (байт, прочитанный из памяти по PC)\n"
                u"\tВыход: управляющие сигналы пишутся прямо в GVL_CPU:\n"
                u"\t  C_Class  - класс операции (0=NOP 1=MOV 2=MVI 3=ALU 4=JMP 5=CALL\n"
                u"\t             6=RET 7=PUSH 8=POP 9=HLT 10=SPECIAL)\n"
                u"\t  C_Dst    - код регистра-приёмника\n"
                u"\t  C_Src    - код регистра-источника\n"
                u"\t  C_ALU_Op - код операции для FB_ALU8\n"
                u"\t  C_Cond   - код условия перехода, C_Uncond - безусловная форма\n"
                u"\t  C_Len    - длина команды в байтах (1/2/3)\n"
                u"\t  C_IsCmp  - CMP: результат не записывать\n"
                u"\t  C_Halt   - останов\n"
                u"\tПризнаки команд сначала защёлкиваются в локальные переменные:\n"
                u"\tвыход вызова FB нельзя разветвлять, а нужен он в нескольких сетях.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    for v, t, c in ((u"h_mov", u"BOOL", u"признак MOV"), (u"h_mvi", u"BOOL", u"признак MVI"),
                    (u"h_alu", u"BOOL", u"признак АЛУ-команды"), (u"h_jmp", u"BOOL", u"признак перехода"),
                    (u"h_hlt", u"BOOL", u"признак HLT"),
                    (u"d_mov", u"BYTE", u"DDD команды MOV"), (u"s_mov", u"BYTE", u"SSS команды MOV"),
                    (u"d_mvi", u"BYTE", u"DDD команды MVI"),
                    (u"op_alu", u"BYTE", u"код операции АЛУ"), (u"s_alu", u"BYTE", u"SSS АЛУ-команды"),
                    (u"is_cmp", u"BOOL", u"признак CMP"),
                    (u"k_jmp", u"BYTE", u"класс перехода"), (u"c_jmp", u"BYTE", u"код условия"),
                    (u"u_jmp", u"BOOL", u"безусловная форма")):
        p.var(v, t, c)
    p.var(u"dmov", u"FB_Decode_MOV", u"декодер MOV")
    p.var(u"dmvi", u"FB_Decode_MVI", u"декодер MVI")
    p.var(u"dalu", u"FB_Decode_ALU", u"декодер АЛУ")
    p.var(u"djmp", u"FB_Decode_JMP", u"декодер переходов")
    p.var(u"dhlt", u"FB_Decode_HLT", u"декодер HLT")

    # --- сеть 1: запустить все декодеры и защёлкнуть их выходы ---
    n = p.network(u"СЕТЬ 1. Распознавание всех групп команд")
    ir = n.invar(u"IR")
    dmov = n.block(u"FB_Decode_MOV", [(u"IR", ir)], [u"Hit", u"DDD", u"SSS"], instance=u"dmov")
    dmvi = n.block(u"FB_Decode_MVI", [(u"IR", ir)], [u"Hit", u"DDD"], instance=u"dmvi")
    dalu = n.block(u"FB_Decode_ALU", [(u"IR", ir)], [u"Hit", u"Op", u"SSS", u"IsCmp"], instance=u"dalu")
    djmp = n.block(u"FB_Decode_JMP", [(u"IR", ir)], [u"Hit", u"Kind", u"Cond", u"Uncond"], instance=u"djmp")
    dhlt = n.block(u"FB_Decode_HLT", [(u"IR", ir)], [u"Hit"], instance=u"dhlt")
    n.outvar(u"h_mov", dmov.out(u"Hit"))
    n.outvar(u"d_mov", dmov.out(u"DDD"))
    n.outvar(u"s_mov", dmov.out(u"SSS"))
    n.outvar(u"h_mvi", dmvi.out(u"Hit"))
    n.outvar(u"d_mvi", dmvi.out(u"DDD"))
    n.outvar(u"h_alu", dalu.out(u"Hit"))
    n.outvar(u"op_alu", dalu.out(u"Op"))
    n.outvar(u"s_alu", dalu.out(u"SSS"))
    n.outvar(u"is_cmp", dalu.out(u"IsCmp"))
    n.outvar(u"h_jmp", djmp.out(u"Hit"))
    n.outvar(u"k_jmp", djmp.out(u"Kind"))
    n.outvar(u"c_jmp", djmp.out(u"Cond"))
    n.outvar(u"u_jmp", djmp.out(u"Uncond"))
    n.outvar(u"h_hlt", dhlt.out(u"Hit"))

    # --- сеть 2: класс операции (приоритет сверху вниз) ---
    n = p.network(u"СЕТЬ 2. Класс операции C_Class (приоритет снизу вверх)")
    acc = n.invar(u"BYTE#0")                      # NOP по умолчанию
    acc = n.block(u"SEL", [(u"G", n.invar(u"h_mov")), (u"IN0", acc), (u"IN1", n.invar(u"BYTE#1"))],
                  [u"OUT"], fbd_xml.COL_BLK)
    acc = n.block(u"SEL", [(u"G", n.invar(u"h_mvi")), (u"IN0", acc), (u"IN1", n.invar(u"BYTE#2"))],
                  [u"OUT"], fbd_xml.COL_BLK2)
    acc = n.block(u"SEL", [(u"G", n.invar(u"h_alu")), (u"IN0", acc), (u"IN1", n.invar(u"BYTE#3"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 120)
    acc = n.block(u"SEL", [(u"G", n.invar(u"h_jmp")), (u"IN0", acc), (u"IN1", n.invar(u"k_jmp"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 240)
    acc = n.block(u"SEL", [(u"G", n.invar(u"h_hlt")), (u"IN0", acc), (u"IN1", n.invar(u"BYTE#9"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 360)
    n.outvar(u"GVL_CPU.C_Class", acc)

    # --- сеть 3: приёмник и источник ---
    n = p.network(u"СЕТЬ 3. Приёмник C_Dst и источник C_Src")
    d = n.block(u"SEL", [(u"G", n.invar(u"h_mvi")), (u"IN0", n.invar(u"d_mov")),
                         (u"IN1", n.invar(u"d_mvi"))], [u"OUT"])
    n.outvar(u"GVL_CPU.C_Dst", d)
    s = n.block(u"SEL", [(u"G", n.invar(u"h_alu")), (u"IN0", n.invar(u"s_mov")),
                         (u"IN1", n.invar(u"s_alu"))], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"GVL_CPU.C_Src", s)

    # --- сеть 4: код операции АЛУ и длина команды ---
    n = p.network(u"СЕТЬ 4. C_ALU_Op, C_Cond, C_Uncond, C_IsCmp")
    n.outvar(u"GVL_CPU.C_ALU_Op", n.block(
        u"SEL", [(u"G", n.invar(u"h_alu")), (u"IN0", n.invar(u"BYTE#0")),
                 (u"IN1", n.invar(u"op_alu"))], [u"OUT"]))
    n.outvar(u"GVL_CPU.C_Cond", n.block(
        u"SEL", [(u"G", n.invar(u"h_jmp")), (u"IN0", n.invar(u"BYTE#0")),
                 (u"IN1", n.invar(u"c_jmp"))], [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"GVL_CPU.C_Uncond", n.block(
        u"AND", [(u"IN1", n.invar(u"h_jmp")), (u"IN2", n.invar(u"u_jmp"))],
        [u"OUT"], fbd_xml.COL_BLK2 + 120))
    n.outvar(u"GVL_CPU.C_IsCmp", n.block(
        u"AND", [(u"IN1", n.invar(u"h_alu")), (u"IN2", n.invar(u"is_cmp"))],
        [u"OUT"], fbd_xml.COL_BLK2 + 240))

    n = p.network(u"СЕТЬ 5. Длина команды: переход/вызов 3, MVI 2, остальные 1")
    l3 = n.invar(u"BYTE#3")
    l2 = n.invar(u"BYTE#2")
    l1 = n.invar(u"BYTE#1")
    t1 = n.block(u"SEL", [(u"G", n.invar(u"h_mvi")), (u"IN0", l1), (u"IN1", l2)], [u"OUT"])
    t2 = n.block(u"SEL", [(u"G", n.invar(u"h_jmp")), (u"IN0", t1), (u"IN1", l3)],
                 [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"GVL_CPU.C_Len", n.block(
        u"SEL", [(u"G", n.invar(u"h_hlt")), (u"IN0", t2), (u"IN1", l1)],
        [u"OUT"], fbd_xml.COL_BLK2 + 120))

    n = p.network(u"СЕТЬ 6. Признак остановки C_Halt := h_hlt")
    n.outvar(u"GVL_CPU.C_Halt", n.invar(u"h_hlt"))
    return p


# ======================================================================
def make_ctrl_unit():
    p = Pou(u"FB_CtrlUnit", u"functionBlock",
            doc=u"Блок управления: проверка условия и расчёт адреса следующей команды.\n"
                u"\tВходы:  Cond - код условия, S/Z/P/CY - флаги,\n"
                u"\t        Uncond - переход безусловный, PC - текущий счётчик команд,\n"
                u"\t        Target - адрес перехода (из двух байт команды), Len - длина\n"
                u"\tВыходы: CondMet - условие выполнено,\n"
                u"\t        Take - переход состоялся,\n"
                u"\t        PC_Next - адрес следующей команды\n"
                u"\tКоды условий: 0=NZ 1=Z 2=NC 3=C 4=PO 5=PE 6=P 7=M\n"
                u"\tPC_Next := Take ? Target : PC + Len")
    p.var_in(u"Cond", u"BYTE", u"код условия 0..7")
    p.var_in(u"S", u"BOOL", u"флаг знака")
    p.var_in(u"Z", u"BOOL", u"флаг нуля")
    p.var_in(u"P", u"BOOL", u"флаг чётности")
    p.var_in(u"CY", u"BOOL", u"флаг переноса")
    p.var_in(u"Uncond", u"BOOL", u"безусловная форма команды")
    p.var_in(u"PC", u"WORD", u"текущий счётчик команд")
    p.var_in(u"Target", u"WORD", u"адрес перехода")
    p.var_in(u"Len", u"BYTE", u"длина текущей команды")
    p.var_out(u"CondMet", u"BOOL", u"условие выполнено")
    p.var_out(u"Take", u"BOOL", u"переход/вызов состоялся")
    p.var_out(u"PC_Next", u"WORD", u"адрес следующей команды")

    n = p.network(u"СЕТЬ 1. Проверка условия: 8 последовательных SEL по коду Cond")
    cnd = n.invar(u"Cond")
    z = n.invar(u"Z"); cy = n.invar(u"CY"); pp = n.invar(u"P"); s = n.invar(u"S")
    acc = n.block(u"NOT", [(u"IN", z)], [u"OUT"])                       # cond 0 = NZ
    for k, (name, src) in enumerate(((u"Z", z), (u"NC", None), (u"C", cy),
                                     (u"PO", None), (u"PE", pp), (u"P", None), (u"M", s))):
        if src is None:
            base = {u"NC": cy, u"PO": pp, u"P": s}[name]
            val = n.block(u"NOT", [(u"IN", base)], [u"OUT"], fbd_xml.COL_BLK + 120 * (k + 1))
        else:
            val = src
        eq = n.block(u"EQ", [(u"IN1", cnd), (u"IN2", n.invar(u"BYTE#%d" % (k + 1)))],
                     [u"OUT"], fbd_xml.COL_BLK + 120 * (k + 1))
        acc = n.block(u"SEL", [(u"G", eq), (u"IN0", acc), (u"IN1", val)],
                      [u"OUT"], fbd_xml.COL_BLK2 + 120 * k)
    n.outvar(u"CondMet", acc)

    n = p.network(u"СЕТЬ 2. Take := Uncond OR CondMet")
    n.outvar(u"Take", n.block(u"OR", [(u"IN1", n.invar(u"Uncond")), (u"IN2", n.invar(u"CondMet"))],
                              [u"OUT"]))

    n = p.network(u"СЕТЬ 3. PC_Next := Take ? Target : PC + Len")
    pcp = n.block(u"ADD", [(u"IN1", n.invar(u"PC")), (u"IN2", n.invar(u"Len"))], [u"OUT"])
    n.outvar(u"PC_Next", n.block(u"SEL", [(u"G", n.invar(u"Take")), (u"IN0", pcp),
                                          (u"IN1", n.invar(u"Target"))],
                                 [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
