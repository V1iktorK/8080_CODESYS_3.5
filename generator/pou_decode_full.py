# -*- coding: utf-8 -*-
u"""Подшаг 3.1: ПОЛНЫЙ декодер Intel 8080 (все документированные опкоды).

Схемы вынесены в отдельный модуль: загрузчик скриптов CODESYS не выполняет
файлы больше ~25 КБ (процесс стартует и молча висит), а импортируемые модули
читаются обычным загрузчиком IronPython и этого ограничения не имеют.

СОСТАВ (10 блоков-декодеров, как в плане 04_ПЛАН_CPM.md, раздел 6):
  FB_DecodeFull_MOV   01 DDD SSS (кроме 76h)          -> класс MOV
  FB_DecodeFull_MVI   00 DDD 110                      -> класс MVI
  FB_DecodeFull_ALU   10 xxx SSS                      -> класс ALU
  FB_DecodeFull_ALUI  11 xxx 110                      -> класс ALUI
  FB_DecodeFull_DATA  группа 00h (LXI/DAD/INX/DCX/INR/DCR/сдвиги/DAA/CMA/
                      STC/CMC/LDAX/STAX/LDA/STA/LHLD/SHLD)
  FB_DecodeFull_JMP   JMP/Jcc/CALL/Ccc/RET/Rcc        -> классы JMP/CALL/RET
  FB_DecodeFull_STACK PUSH rp/PSW, POP rp/PSW         -> классы PUSH/POP
  FB_DecodeFull_SPEC  XCHG/XTHL/SPHL/PCHL/EI/DI/RST/IN/OUT
  FB_DecodeFull_HLT   HLT (76h)
  FB_Decoder_Full     сводный: 9 распознавателей -> управляющее слово GVL_CPU

КАК ЧИТАЕТСЯ КОД 8080 (структура кодировки, на ней всё и построено):
  биты 7..6 - группа:  00 расширенная, 01 MOV, 10 АЛУ, 11 управление/стек;
  биты 5..3 - поле xxx (операция АЛУ или код условия или код вектора RST);
  биты 2..0 - поле SSS (источник);
  биты 5..4 - код регистровой пары rp: 0=BC 1=DE 2=HL 3=SP (или PSW).

Строки класса FB_Decoder_Full:
  сеть 1 - вызов девяти распознавателей и защёлкивание их выходов
           (выход вызова FB нельзя ни разветвлять, ни читать из другой сети);
  сеть 2 - поля f3 = (IR SHR 3) AND 7, src = IR AND 7, rp = (IR SHR 4) AND 3;
  сеть 3 - C_Class по приоритету распознавателей;
  сети 4-11 - остальные поля управляющего слова;
  сеть 12 - запись управляющего слова в GVL_CPU.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

# ======================================================================
# КЛАССЫ ОПЕРАЦИЙ (поле GVL_CPU.C_Class). Единственное место, где они заданы:
# отсюда же генерируется текст комментариев для GVL_CPU, чтобы коды в схеме
# и в объявлениях не разъезжались.
# ======================================================================
C_NOP, C_MOV, C_MVI, C_ALU, C_ALUI = 0, 1, 2, 3, 4
C_INR, C_DCR, C_INX, C_DCX, C_DAD = 5, 6, 7, 8, 9
C_LDAX, C_STAX, C_LDA, C_STA, C_LHLD, C_SHLD, C_LXI = 10, 11, 12, 13, 14, 15, 16
C_XCHG, C_XTHL, C_SPHL, C_PCHL = 17, 18, 19, 20
C_ROT, C_FLAG, C_DAA = 21, 22, 23
C_EI, C_DI = 24, 25
C_JMP, C_CALL, C_RET, C_PUSH, C_POP, C_RST, C_HLT = 26, 27, 28, 29, 30, 31, 32
C_IN, C_OUT, C_INT = 33, 34, 35

CLASSES = (
    (C_NOP,  u"NOP",  u"нет операции (NOP; сюда же недокументированные 08,10,18,20,28,30,38,CB,D9,DD,ED,FD)"),
    (C_MOV,  u"MOV",  u"MOV r1,r2 / MOV r,M / MOV M,r - 01 DDD SSS (кроме 76h)"),
    (C_MVI,  u"MVI",  u"MVI r,d8 - 00 DDD 110, байт по PC+1"),
    (C_ALU,  u"ALU",  u"ADD/ADC/SUB/SBB/ANA/XRA/ORA/CMP r/M - 10 xxx SSS"),
    (C_ALUI, u"ALUI", u"ADI/ACI/SUI/SBI/ANI/XRI/ORI/CPI d8 - 11 xxx 110"),
    (C_INR,  u"INR",  u"INR r/M - 00 DDD 100 и 0Ch/1Ch/2Ch/3Ch (CY не меняется)"),
    (C_DCR,  u"DCR",  u"DCR r/M - 00 DDD 101 и 0Dh/1Dh/2Dh/3Dh (CY не меняется)"),
    (C_INX,  u"INX",  u"INX rp - 03h/13h/23h/33h (флаги не меняются)"),
    (C_DCX,  u"DCX",  u"DCX rp - 0Bh/1Bh/2Bh/3Bh (флаги не меняются)"),
    (C_DAD,  u"DAD",  u"DAD rp - 09h/19h/29h/39h, HL := HL + rp (меняется ТОЛЬКО CY)"),
    (C_LDAX, u"LDAX", u"LDAX rp - 0Ah/1Ah, A := Memory[rp], rp = BC или DE"),
    (C_STAX, u"STAX", u"STAX rp - 02h/12h, Memory[rp] := A"),
    (C_LDA,  u"LDA",  u"LDA a16 - 3Ah, A := Memory[a16]"),
    (C_STA,  u"STA",  u"STA a16 - 32h, Memory[a16] := A"),
    (C_LHLD, u"LHLD", u"LHLD a16 - 2Ah, L := Memory[a16], H := Memory[a16+1]"),
    (C_SHLD, u"SHLD", u"SHLD a16 - 22h, Memory[a16] := L, Memory[a16+1] := H"),
    (C_LXI,  u"LXI",  u"LXI rp,d16 - 01h/11h/21h/31h, пара := байты PC+1/PC+2"),
    (C_XCHG, u"XCHG", u"XCHG - EBh, обмен DE <-> HL (пишутся 4 регистра)"),
    (C_XTHL, u"XTHL", u"XTHL - E3h, обмен HL с вершиной стека"),
    (C_SPHL, u"SPHL", u"SPHL - F9h, SP := HL"),
    (C_PCHL, u"PCHL", u"PCHL - E9h, PC := HL"),
    (C_ROT,  u"ROT",  u"RLC/RRC/RAL/RAR - 07h/0Fh/17h/1Fh (меняется ТОЛЬКО CY)"),
    (C_FLAG, u"FLAG", u"CMA/STC/CMC - 2Fh/37h/3Fh (CMA флагов не меняет)"),
    (C_DAA,  u"DAA",  u"DAA - 27h, десятичная коррекция аккумулятора"),
    (C_EI,   u"EI",   u"EI - FBh, разрешить прерывания (IFF := 1)"),
    (C_DI,   u"DI",   u"DI - F3h, запретить прерывания (IFF := 0)"),
    (C_JMP,  u"JMP",  u"JMP C3h и Jcc (C2h+условие)"),
    (C_CALL, u"CALL", u"CALL CDh и Ccc (C4h+условие): PC в стек, затем переход"),
    (C_RET,  u"RET",  u"RET C9h и Rcc (C0h+условие): адрес со стека; при Busy ставит IFF"),
    (C_PUSH, u"PUSH", u"PUSH rp (C5h/D5h/E5h) и PUSH PSW (F5h)"),
    (C_POP,  u"POP",  u"POP rp (C1h/D1h/E1h) и POP PSW (F1h)"),
    (C_RST,  u"RST",  u"RST 0..7 (C7h..FFh, вектор в битах 5..3): PC в стек, PC := вектор*8"),
    (C_HLT,  u"HLT",  u"HLT - 76h, останов процессора"),
    (C_IN,   u"IN",   u"IN d8 - DBh: ЗАРЕЗЕРВИРОВАНО (аппаратный ввод-вывод, этап 3.6)"),
    (C_OUT,  u"OUT",  u"OUT d8 - D3h: ЗАРЕЗЕРВИРОВАНО (аппаратный ввод-вывод, этап 3.6)"),
    (C_INT,  u"INT",  u"внутренний класс: приём прерывания (не опкод, ставит FB_Interrupt)"),
)

# Коды условий (C_Cond) - поле битов 5..3 для Jcc/Ccc/Rcc
CONDS = ((0, u"NZ"), (1, u"Z"), (2, u"NC"), (3, u"C"),
         (4, u"PO"), (5, u"PE"), (6, u"P"), (7, u"M"))

# Поля управляющего слова: (имя, тип, комментарий) - отсюда генерируется GVL_CPU
FIELDS = (
    (u"C_Class",  u"BYTE", u"класс операции (см. таблицу ниже)"),
    (u"C_Dst1",   u"BYTE", u"код регистра-приёмника, порт записи 1 (0..7)"),
    (u"C_Dst2",   u"BYTE", u"код регистра-приёмника, порт записи 2 (0..7)"),
    (u"C_Src",    u"BYTE", u"код регистра-источника (6 = память по адресу HL)"),
    (u"C_RP",     u"BYTE", u"код регистровой пары: 0=BC 1=DE 2=HL 3=SP (для PUSH/POP - PSW)"),
    (u"C_ALU_Op", u"BYTE", u"код операции АЛУ: 0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=ORA 6=XRA"),
    (u"C_Cond",   u"BYTE", u"код условия перехода: 0=NZ 1=Z 2=NC 3=C 4=PO 5=PE 6=P 7=M"),
    (u"C_Vec",    u"BYTE", u"вектор RST 0..7 (адрес обработчика = C_Vec * 8)"),
    (u"C_Rot",    u"BYTE", u"вид сдвига: 0=RLC 1=RRC 2=RAL 3=RAR"),
    (u"C_Flag",   u"BYTE", u"операция над флагами: 0=CMA 1=STC 2=CMC"),
    (u"C_Len",    u"BYTE", u"длина команды в байтах: 1, 2 или 3"),
    (u"C_RdSel",  u"BYTE", u"адрес чтения памяти: 0=не нужно 1=a16 2=BC 3=DE 4=SP"),
    (u"C_Uncond", u"BOOL", u"переход/вызов/возврат безусловный"),
    (u"C_IsCmp",  u"BOOL", u"CMP/CPI: флаги обновить, результат не записывать"),
    (u"C_Halt",   u"BOOL", u"команда HLT"),
    (u"C_EI",     u"BOOL", u"EI - разрешить прерывания"),
    (u"C_DI",     u"BOOL", u"DI - запретить прерывания"),
    (u"C_IsPSW",  u"BOOL", u"PUSH PSW / POP PSW (пара с кодом 3 - не SP, а PSW)"),
    (u"C_WReg1",  u"BOOL", u"разрешить запись в регистр, порт 1"),
    (u"C_WReg2",  u"BOOL", u"разрешить запись в регистр, порт 2"),
    (u"C_WReg3",  u"BOOL", u"разрешить запись в регистр H (только XCHG)"),
    (u"C_WReg4",  u"BOOL", u"разрешить запись в регистр L (только XCHG)"),
    (u"C_SZP_En", u"BOOL", u"обновлять флаги S, Z, P"),
    (u"C_AC_En",  u"BOOL", u"обновлять флаг AC"),
    (u"C_CY_En",  u"BOOL", u"обновлять флаг CY"),
    (u"C_LdPSW",  u"BOOL", u"POP PSW: загрузить флаги из байта по адресу SP"),
)

BUSES = (
    (u"Bus_Data", u"BYTE", u"шина данных, 8 бит"),
    (u"Bus_Addr", u"WORD", u"шина адреса, 16 бит"),
    (u"Bus_IR",   u"BYTE", u"регистр команды, прочитанный из памяти по PC"),
)

STATE = (
    (u"Enable",     u"BOOL", u"разрешение выполнения такта"),
    (u"Step_Cnt",   u"WORD", u"номер выполненного такта"),
    (u"Halted",     u"BOOL", u"процессор остановлен командой HLT"),
    (u"Int_Req",    u"BOOL", u"запрос прерывания (вход FB_Interrupt)"),
    (u"Int_Vector", u"BYTE", u"номер вектора прерывания 0..7 (адрес = вектор * 8)"),
    (u"IFF",        u"BOOL", u"триггер разрешения прерываний (EI/DI/RET)"),
    (u"Int_Busy",   u"BOOL", u"прерывание обслуживается (снимается командой RET)"),
)


def gvl_cpu_text():
    u"""Текст объявления GVL_CPU: шины, управляющее слово, состояние.

    Генерируется из таблиц этого модуля, поэтому комментарии с кодами классов
    физически не могут разойтись со схемой декодера.
    """
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ==== ШИНЫ ЭМУЛЯТОРА Intel 8080 ==== *)")
    for n, t, c in BUSES:
        L.append(u"\t%-12s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== УПРАВЛЯЮЩЕЕ СЛОВО ДЕКОДЕРА (заполняет FB_Decoder_Full) ==== *)")
    for n, t, c in FIELDS:
        L.append(u"\t%-12s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== КЛАССЫ ОПЕРАЦИЙ: C_Class -> что значит ==== *)")
    for code, name, doc in CLASSES:
        L.append(u"\t(* %2d = %-5s %s *)" % (code, name, doc))
    L.append(u"")
    L.append(u"\t(* ==== КОДЫ УСЛОВИЙ: C_Cond -> мнемоника ==== *)")
    for code, name in CONDS:
        L.append(u"\t(* %d = %s *)" % (code, name))
    L.append(u"")
    L.append(u"\t(* ==== КОДЫ РЕГИСТРОВ (C_Dst1/C_Dst2/C_Src) ==== *)")
    L.append(u"\t(* 0=B 1=C 2=D 3=E 4=H 5=L 6=M (память по HL) 7=A *)")
    L.append(u"")
    L.append(u"\t(* ==== СОСТОЯНИЕ, ОТЛАДКА И ПРЕРЫВАНИЯ ==== *)")
    for n, t, c in STATE:
        L.append(u"\t%-12s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


# ======================================================================
# ВСПОМОГАТЕЛЬНОЕ: цепочка SEL по приоритету
# ======================================================================
def _chain(n, acc, steps, x0=None, dx=120, y=None):
    u"""steps: [(условие, значение, x)] -> SEL(G:=условие, IN0:=acc, IN1:=значение).

    Возвращает последний элемент цепочки. Каждый шаг - отдельный блок SEL,
    поэтому fan-out исключён: предыдущий результат используется один раз.
    """
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    for k, st in enumerate(steps):
        cond, val = st[0], st[1]
        xx = st[2] if len(st) > 2 else x0 + dx * k
        acc = n.block(u"SEL", [(u"G", cond), (u"IN0", acc), (u"IN1", val)],
                      [u"OUT"], xx, y)
    return acc


def _or_chain(n, conds, x0=None, dx=110, y=None):
    u"""Дерево OR по списку условий (все - Src)."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    lvl = list(conds)
    xx = x0
    while len(lvl) > 1:
        nxt = []
        for k in range(0, len(lvl), 2):
            if k + 1 < len(lvl):
                nxt.append(n.block(u"OR", [(u"IN1", lvl[k]), (u"IN2", lvl[k + 1])],
                                   [u"OUT"], xx, y))
            else:
                nxt.append(lvl[k])
        lvl = nxt
        xx += dx
    return lvl[0]


# ======================================================================
def make_decode_mov():
    p = Pou(u"FB_DecodeFull_MOV", u"functionBlock",
            doc=u"Распознавание MOV: группа 01xxxxxx, то есть (IR AND C0h) = 40h.\n"
                u"\tКод 0111 0110 (76h) исключён - это HLT, а не MOV M,M.\n"
                u"\tКласс операции: 1 = MOV.\n"
                u"\tПриёмник берётся из поля DDD = (IR SHR 3) AND 7, источник -\n"
                u"\tиз поля SSS = IR AND 7 (код 6 = память по адресу HL).\n"
                u"\tДлина команды 1 байт.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это MOV")
    p.var_out(u"Cls", u"BYTE", u"класс операции C_Class = 1 (MOV)")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C0h)=40h AND IR<>76h ; Cls := 1")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C0"))], [u"OUT"])
    e = n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#40"))], [u"OUT"],
                fbd_xml.COL_BLK2)
    e76 = n.block(u"EQ", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#76"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 120)
    nb = n.block(u"NOT", [(u"IN", e76)], [u"OUT"], fbd_xml.COL_BLK2 + 240)
    n.outvar(u"Hit", n.block(u"AND", [(u"IN1", e), (u"IN2", nb)], [u"OUT"],
                             fbd_xml.COL_BLK2 + 360))
    n.outvar(u"Cls", n.invar(u"BYTE#%d" % C_MOV))
    return p


# ======================================================================
def make_decode_mvi():
    p = Pou(u"FB_DecodeFull_MVI", u"functionBlock",
            doc=u"Распознавание MVI: (IR AND C7h) = 06h (форма 00 DDD 110).\n"
                u"\tКласс операции: 2 = MVI. Приёмник - поле DDD, данные - байт\n"
                u"\tпо адресу PC+1. Длина команды 2 байта.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это MVI")
    p.var_out(u"Cls", u"BYTE", u"класс операции C_Class = 2 (MVI)")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C7h) = 06h ; Cls := 2")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C7"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#6"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"Cls", n.invar(u"BYTE#%d" % C_MVI))
    return p


# ======================================================================
def make_decode_alu():
    p = Pou(u"FB_DecodeFull_ALU", u"functionBlock",
            doc=u"Распознавание АЛУ-команд с регистром/памятью: группа 10xxxxxx,\n"
                u"\tто есть (IR AND C0h) = 80h. Класс операции 3 = ALU.\n"
                u"\tПоле xxx = биты 5..3 задаёт операцию в кодировке 8080:\n"
                u"\t  0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=XRA 6=ORA 7=CMP\n"
                u"\tКоды АЛУ нашего FB_ALU8: 0=ADD 1=ADC 2=SUB 3=SBB 4=ANA 5=ORA 6=XRA,\n"
                u"\tпоэтому в FB_Decoder_Full 5 и 6 меняются местами, а 7 (CMP)\n"
                u"\tпревращается в 2 (SUB) с признаком C_IsCmp.\n"
                u"\tИсточник - поле SSS (6 = память по адресу HL). Длина 1 байт.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это АЛУ-команда с регистром")
    p.var_out(u"Cls", u"BYTE", u"класс операции C_Class = 3 (ALU)")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C0h) = 80h ; Cls := 3")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C0"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#80"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"Cls", n.invar(u"BYTE#%d" % C_ALU))
    return p


# ======================================================================
def make_decode_alui():
    p = Pou(u"FB_DecodeFull_ALUI", u"functionBlock",
            doc=u"Распознавание АЛУ-команд с непосредственным операндом:\n"
                u"\t(IR AND C7h) = C6h (форма 11 xxx 110). Класс операции 4 = ALUI.\n"
                u"\tПоле xxx - та же кодировка, что у группы 10:\n"
                u"\t  0=ADI 1=ACI 2=SUI 3=SBI 4=ANI 5=XRI 6=ORI 7=CPI\n"
                u"\tОперанд - байт по адресу PC+1, длина команды 2 байта.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это АЛУ-команда с непосредственным операндом")
    p.var_out(u"Cls", u"BYTE", u"класс операции C_Class = 4 (ALUI)")

    n = p.network(u"СЕТЬ 1. Hit := (IR AND C7h) = C6h ; Cls := 4")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C7"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#16#C6"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"Cls", n.invar(u"BYTE#%d" % C_ALUI))
    return p


# ======================================================================
def make_decode_hlt():
    p = Pou(u"FB_DecodeFull_HLT", u"functionBlock",
            doc=u"Распознавание HLT (0111 0110 = 76h). Класс операции 32 = HLT.\n"
                u"\tОстанов: PC и регистры перестают меняться, такты не выполняются.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это HLT")
    p.var_out(u"Cls", u"BYTE", u"класс операции C_Class = 32 (HLT)")

    n = p.network(u"СЕТЬ 1. Hit := IR = 76h ; Cls := 32")
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", n.invar(u"IR")),
                                     (u"IN2", n.invar(u"BYTE#16#76"))], [u"OUT"]))
    n.outvar(u"Cls", n.invar(u"BYTE#%d" % C_HLT))
    return p


# ======================================================================
def make_decode_data():
    p = Pou(u"FB_DecodeFull_DATA", u"functionBlock",
            doc=u"Распознавание команд группы 00h (старшие два бита равны 00).\n"
                u"\tЗдесь собраны все команды с младшей тетрадой lo = IR AND 0Fh;\n"
                u"\tстаршая половина байта hi2 = (IR SHR 4) AND 3 выбирает пару\n"
                u"\tрегистров и исключения. Таблица (lo -> класс операции):\n"
                u"\t  lo=0,8 : NOP (коды 08h,10h,18h,20h,28h,30h,38h недокументированы)\n"
                u"\t  lo=1   : LXI rp,d16            (класс 16)\n"
                u"\t  lo=2   : STAX (hi2=0,1), SHLD (hi2=2), STA (hi2=3)  (11 / 15 / 13)\n"
                u"\t  lo=3   : INX rp                (класс 7)\n"
                u"\t  lo=4,C : INR r/M               (класс 5)\n"
                u"\t  lo=5,D : DCR r/M               (класс 6)\n"
                u"\t  lo=6,E : MVI r,d8              (класс 2)\n"
                u"\t  lo=7   : RLC (hi2=0), RAL (hi2=1), DAA (hi2=2), STC (hi2=3) (21/21/23/22)\n"
                u"\t  lo=9   : DAD rp                (класс 9)\n"
                u"\t  lo=A   : LDAX (hi2=0,1), LHLD (hi2=2), LDA (hi2=3)  (10 / 14 / 12)\n"
                u"\t  lo=B   : DCX rp                (класс 8)\n"
                u"\t  lo=F   : RRC (hi2=0), RAR (hi2=1), CMA (hi2=2), CMC (hi2=3) (21/21/22/22)\n"
                u"\tДополнительно блок выдаёт:\n"
                u"\t  Rot  - вид сдвига для FB_Rotate8: 0=RLC 1=RRC 2=RAL 3=RAR;\n"
                u"\t  Flag - операция над флагами: 0=CMA 1=STC 2=CMC.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"команда группы 00h")
    p.var_out(u"Cls", u"BYTE", u"класс операции (0..23)")
    p.var_out(u"Rot", u"BYTE", u"вид сдвига 0..3")
    p.var_out(u"Flag", u"BYTE", u"0=CMA 1=STC 2=CMC")
    p.var(u"lo", u"BYTE", u"младшая тетрада IR")
    p.var(u"hi2", u"BYTE", u"биты 5..4: код пары или признак исключения")
    for k, cname in enumerate((u"c1", u"c2", u"c3", u"c4", u"c5", u"c6", u"c7",
                               u"c9", u"cA", u"cB", u"cC", u"cD", u"cE", u"cF"), 1):
        p.var(cname, u"BOOL", u"признак lo = %s" % cname[1:])
    p.var(u"h1", u"BOOL", u"hi2 = 1")
    p.var(u"h2", u"BOOL", u"hi2 = 2")
    p.var(u"h3", u"BOOL", u"hi2 = 3")
    p.var(u"v_stax", u"BYTE", u"класс для lo=2: STAX / SHLD / STA")
    p.var(u"v_rot", u"BYTE", u"класс для lo=7: ROT / DAA / FLAG")
    p.var(u"v_ldax", u"BYTE", u"класс для lo=A: LDAX / LHLD / LDA")
    p.var(u"v_cmc", u"BYTE", u"класс для lo=F: ROT / FLAG")

    n = p.network(u"СЕТЬ 1. Поля: lo := IR AND 0Fh, hi2 := (IR SHR 4) AND 3")
    n.outvar(u"lo", n.block(u"AND", [(u"IN1", n.invar(u"IR")),
                                     (u"IN2", n.invar(u"BYTE#16#0F"))], [u"OUT"]))
    sh = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#4"))],
                 [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"hi2", n.block(u"AND", [(u"IN1", sh), (u"IN2", n.invar(u"BYTE#3"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 140))

    n = p.network(u"СЕТЬ 2. Hit := (IR AND C0h) = 0")
    a = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C0"))], [u"OUT"])
    n.outvar(u"Hit", n.block(u"EQ", [(u"IN1", a), (u"IN2", n.invar(u"BYTE#0"))],
                             [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 3. Признаки младшей тетрады lo и полей hi2")
    for k, hexv in enumerate((1, 2, 3, 4, 5, 6, 7, 9, 0xA, 0xB, 0xC, 0xD, 0xE, 0xF)):
        n.outvar(u"c%s" % (u"%X" % hexv),
                 n.block(u"EQ", [(u"IN1", n.invar(u"lo")),
                                 (u"IN2", n.invar(u"BYTE#%d" % hexv))], [u"OUT"],
                         fbd_xml.COL_BLK + 120 * k))
    n.outvar(u"h1", n.block(u"EQ", [(u"IN1", n.invar(u"hi2")), (u"IN2", n.invar(u"BYTE#1"))],
                            [u"OUT"], fbd_xml.COL_BLK + 120 * 13))
    n.outvar(u"h2", n.block(u"EQ", [(u"IN1", n.invar(u"hi2")), (u"IN2", n.invar(u"BYTE#2"))],
                            [u"OUT"], fbd_xml.COL_BLK + 120 * 14))
    n.outvar(u"h3", n.block(u"EQ", [(u"IN1", n.invar(u"hi2")), (u"IN2", n.invar(u"BYTE#3"))],
                            [u"OUT"], fbd_xml.COL_BLK + 120 * 15))

    n = p.network(u"СЕТЬ 4. Исключения по hi2: STAX/SHLD/STA, LDAX/LHLD/LDA, "
                  u"ROT/DAA/FLAG, ROT/FLAG")
    n.outvar(u"v_stax", _chain(n, n.invar(u"BYTE#%d" % C_STAX), [
        (n.invar(u"h2"), n.invar(u"BYTE#%d" % C_SHLD)),
        (n.invar(u"h3"), n.invar(u"BYTE#%d" % C_STA))]))
    n.outvar(u"v_ldax", _chain(n, n.invar(u"BYTE#%d" % C_LDAX), [
        (n.invar(u"h2"), n.invar(u"BYTE#%d" % C_LHLD)),
        (n.invar(u"h3"), n.invar(u"BYTE#%d" % C_LDA))], x0=fbd_xml.COL_BLK2 + 200))
    n.outvar(u"v_rot", _chain(n, n.invar(u"BYTE#%d" % C_ROT), [
        (n.invar(u"h2"), n.invar(u"BYTE#%d" % C_DAA)),
        (n.invar(u"h3"), n.invar(u"BYTE#%d" % C_FLAG))], x0=fbd_xml.COL_BLK2 + 500))
    n.outvar(u"v_cmc", _chain(n, n.invar(u"BYTE#%d" % C_ROT), [
        (n.invar(u"h2"), n.invar(u"BYTE#%d" % C_FLAG)),
        (n.invar(u"h3"), n.invar(u"BYTE#%d" % C_FLAG))], x0=fbd_xml.COL_BLK2 + 800))

    n = p.network(u"СЕТЬ 5. Rot := вид сдвига (lo=7: RLC/RAL, lo=F: RRC/RAR)")
    one = n.invar(u"h1")
    lin = _chain(n, n.invar(u"BYTE#0"), [(one, n.invar(u"BYTE#2"))], x0=fbd_xml.COL_BLK)
    rin = _chain(n, n.invar(u"BYTE#1"), [(one, n.invar(u"BYTE#3"))], x0=fbd_xml.COL_BLK + 200)
    n.outvar(u"Rot", n.block(u"SEL", [(u"G", n.invar(u"cF")), (u"IN0", lin), (u"IN1", rin)],
                             [u"OUT"], fbd_xml.COL_BLK2 + 400))

    n = p.network(u"СЕТЬ 6. Flag := 0=CMA (lo=F,hi2=2), 1=STC (lo=7,hi2=3), 2=CMC (lo=F,hi2=3)")
    oth = n.block(u"SEL", [(u"G", n.invar(u"h2")), (u"IN0", n.invar(u"BYTE#2")),
                           (u"IN1", n.invar(u"BYTE#0"))], [u"OUT"], fbd_xml.COL_BLK)
    n.outvar(u"Flag", n.block(u"SEL", [(u"G", n.invar(u"cF")), (u"IN0", n.invar(u"BYTE#1")),
                                       (u"IN1", oth)], [u"OUT"], fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 7. Сводный класс операции по младшей тетраде lo")
    st = [
        (n.invar(u"c1"), n.invar(u"BYTE#%d" % C_LXI)),
        (n.invar(u"c2"), n.invar(u"v_stax")),
        (n.invar(u"c3"), n.invar(u"BYTE#%d" % C_INX)),
        (n.invar(u"c4"), n.invar(u"BYTE#%d" % C_INR)),
        (n.invar(u"c5"), n.invar(u"BYTE#%d" % C_DCR)),
        (n.invar(u"c6"), n.invar(u"BYTE#%d" % C_MVI)),
        (n.invar(u"c7"), n.invar(u"v_rot")),
        (n.invar(u"c9"), n.invar(u"BYTE#%d" % C_DAD)),
        (n.invar(u"cA"), n.invar(u"v_ldax")),
        (n.invar(u"cB"), n.invar(u"BYTE#%d" % C_DCX)),
        (n.invar(u"cC"), n.invar(u"BYTE#%d" % C_INR)),
        (n.invar(u"cD"), n.invar(u"BYTE#%d" % C_DCR)),
        (n.invar(u"cE"), n.invar(u"BYTE#%d" % C_MVI)),
        (n.invar(u"cF"), n.invar(u"v_cmc")),
    ]
    n.outvar(u"Cls", _chain(n, n.invar(u"BYTE#%d" % C_NOP), st, dx=115))
    return p


# ======================================================================
def make_decode_jmp():
    p = Pou(u"FB_DecodeFull_JMP", u"functionBlock",
            doc=u"Распознавание переходов, вызовов и возвратов (группа C0h).\n"
                u"\tКодировка: поле битов 5..3 задаёт код условия, поле битов 5..4\n"
                u"\t(старшие два бита кода условия) выбирает пару Jcc/JMP и т.д.\n"
                u"\t  (IR AND C7h)=C2h : Jcc  (C2h JNZ, CAh JZ, D2h JNC, DAh JC,\n"
                u"\t                            E2h JPO, EAh JPE, F2h JP, FAh JM)\n"
                u"\t  (IR AND C7h)=C4h : Ccc  (CALL по условию, 8 кодов)\n"
                u"\t  (IR AND C7h)=C0h : Rcc  (RET по условию, 8 кодов)\n"
                u"\t  C3h = JMP, CDh = CALL, C9h = RET (безусловные формы).\n"
                u"\tКлассы операции: 26=JMP, 27=CALL, 28=RET.\n"
                u"\tВыход Uncond = 1 для безусловных форм C3h/CDh/C9h:\n"
                u"\tусловие проверять не нужно, переход выполняется всегда.\n"
                u"\tКод условия (C_Cond) берётся декодером прямо из битов 5..3\n"
                u"\tрегистра команды: 0=NZ 1=Z 2=NC 3=C 4=PO 5=PE 6=P 7=M.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это переход/вызов/возврат")
    p.var_out(u"Cls", u"BYTE", u"26=JMP 27=CALL 28=RET")
    p.var_out(u"Uncond", u"BOOL", u"безусловная форма")
    for nm, txt in ((u"isj", u"признак Jcc (C2h + условие)"),
                    (u"isc", u"признак Ccc (C4h + условие)"),
                    (u"isr", u"признак Rcc (C0h + условие)"),
                    (u"jmpu", u"признак JMP (C3h)"),
                    (u"callu", u"признак CALL (CDh)"),
                    (u"retu", u"признак RET (C9h)")):
        p.var(nm, u"BOOL", txt)

    n = p.network(u"СЕТЬ 1. Маска группы и признаки шести форм")
    m = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C7"))], [u"OUT"])
    for k, (name, val) in enumerate(((u"isj", 0xC2), (u"isc", 0xC4), (u"isr", 0xC0))):
        n.outvar(name, n.block(u"EQ", [(u"IN1", m), (u"IN2", n.invar(u"BYTE#16#%02X" % val))],
                               [u"OUT"], fbd_xml.COL_BLK2 + 140 * k))
    for k, (name, val) in enumerate(((u"jmpu", 0xC3), (u"callu", 0xCD), (u"retu", 0xC9))):
        n.outvar(name, n.block(u"EQ", [(u"IN1", n.invar(u"IR")),
                                       (u"IN2", n.invar(u"BYTE#16#%02X" % val))], [u"OUT"],
                               fbd_xml.COL_BLK + 140 * k))

    n = p.network(u"СЕТЬ 2. Hit и Uncond")
    n.outvar(u"Hit", _or_chain(n, [n.invar(x) for x in
                                   (u"isj", u"isc", u"isr", u"jmpu", u"callu", u"retu")],
                               x0=fbd_xml.COL_BLK))
    n.outvar(u"Uncond", _or_chain(n, [n.invar(x) for x in (u"jmpu", u"callu", u"retu")],
                                  x0=fbd_xml.COL_BLK2))

    n = p.network(u"СЕТЬ 3. Класс: 26=JMP, 27=CALL, 28=RET")
    acc = _chain(n, n.invar(u"BYTE#%d" % C_NOP), [
        (n.invar(u"isj"), n.invar(u"BYTE#%d" % C_JMP)),
        (n.invar(u"jmpu"), n.invar(u"BYTE#%d" % C_JMP)),
        (n.invar(u"isc"), n.invar(u"BYTE#%d" % C_CALL)),
        (n.invar(u"callu"), n.invar(u"BYTE#%d" % C_CALL)),
        (n.invar(u"isr"), n.invar(u"BYTE#%d" % C_RET)),
        (n.invar(u"retu"), n.invar(u"BYTE#%d" % C_RET))])
    n.outvar(u"Cls", acc)
    return p


# ======================================================================
def make_decode_stack():
    p = Pou(u"FB_DecodeFull_STACK", u"functionBlock",
            doc=u"Распознавание команд стека (группа C0h).\n"
                u"\tМаска - CFh (биты 5..4 = код пары, бит 3 всегда 0):\n"
                u"\t  (IR AND CFh)=C5h : PUSH rp - C5h BC, D5h DE, E5h HL, F5h PSW;\n"
                u"\t  (IR AND CFh)=C1h : POP  rp - C1h BC, D1h DE, E1h HL, F1h PSW.\n"
                u"\tИменно CFh, а не C7h: с маской C7h код E9h (PCHL) даёт C1h и\n"
                u"\tложно распознаётся как POP H.\n"
                u"\tКласс операции: 29=PUSH, 30=POP.\n"
                u"\tПара берётся из битов 5..4 (C_RP): 0=BC 1=DE 2=HL 3=PSW\n"
                u"\t(для PUSH/POP код 3 означает не SP, а байт состояния PSW -\n"
                u"\tпоэтому признак C_IsPSW формируется по C_RP = 3).\n"
                u"\tPUSH: SP := SP-2, Memory[SP-1] := старший байт, Memory[SP-2] := младший.\n"
                u"\tPOP : младший байт := Memory[SP], старший := Memory[SP+1], SP := SP+2.")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"это PUSH или POP")
    p.var_out(u"Cls", u"BYTE", u"29=PUSH 30=POP")
    p.var(u"isp", u"BOOL", u"признак PUSH (IR AND CFh = C5h)")
    p.var(u"ispo", u"BOOL", u"признак POP (IR AND CFh = C1h)")

    n = p.network(u"СЕТЬ 1. Признаки PUSH и POP (маска CFh)")
    m = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#CF"))], [u"OUT"])
    n.outvar(u"isp", n.block(u"EQ", [(u"IN1", m), (u"IN2", n.invar(u"BYTE#16#C5"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"ispo", n.block(u"EQ", [(u"IN1", m), (u"IN2", n.invar(u"BYTE#16#C1"))],
                              [u"OUT"], fbd_xml.COL_BLK2 + 140))

    n = p.network(u"СЕТЬ 2. Hit := PUSH OR POP ; Cls := PUSH ? 29 : 30")
    n.outvar(u"Hit", n.block(u"OR", [(u"IN1", n.invar(u"isp")), (u"IN2", n.invar(u"ispo"))],
                             [u"OUT"]))
    n.outvar(u"Cls", n.block(u"SEL", [(u"G", n.invar(u"isp")),
                                      (u"IN0", n.invar(u"BYTE#%d" % C_POP)),
                                      (u"IN1", n.invar(u"BYTE#%d" % C_PUSH))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    return p


# ======================================================================
def make_decode_spec():
    p = Pou(u"FB_DecodeFull_SPEC", u"functionBlock",
            doc=u"Распознавание отдельных команд (это не группа, а список кодов):\n"
                u"\t  EBh XCHG (17)  - обмен DE <-> HL\n"
                u"\t  E3h XTHL (18)  - обмен HL с вершиной стека\n"
                u"\t  F9h SPHL (19)  - SP := HL\n"
                u"\t  E9h PCHL (20)  - PC := HL\n"
                u"\t  FBh EI   (24)  - разрешить прерывания\n"
                u"\t  F3h DI   (25)  - запретить прерывания\n"
                u"\t  (IR AND C7h)=C7h - RST 0..7 (класс 31), вектор = биты 5..3:\n"
                u"\t      C7h RST0, CFh RST1, D7h RST2, DFh RST3,\n"
                u"\t      E7h RST4, EFh RST5, F7h RST6, FFh RST7. Адрес = вектор * 8.\n"
                u"\t  DBh IN  d8 (33) - ЗАРЕЗЕРВИРОВАНО: аппаратный ввод, этап 3.6;\n"
                u"\t  D3h OUT d8 (34) - ЗАРЕЗЕРВИРОВАНО: аппаратный вывод, этап 3.6.\n"
                u"\t    (для IN/OUT длина команды 2 байта, сам обмен с портом ядро\n"
                u"\t     пока не выполняет - PC просто проходит дальше)")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    p.var_out(u"Hit", u"BOOL", u"код из списка")
    p.var_out(u"Cls", u"BYTE", u"класс операции")
    p.var(u"isrst", u"BOOL", u"признак RST")
    for nm, txt in ((u"xchg", u"признак XCHG"), (u"xthl", u"признак XTHL"),
                    (u"sphl", u"признак SPHL"), (u"pchl", u"признак PCHL"),
                    (u"ei", u"признак EI"), (u"di", u"признак DI"),
                    (u"inp", u"признак IN (зарезервировано)"),
                    (u"outp", u"признак OUT (зарезервировано)")):
        p.var(nm, u"BOOL", txt)

    codes = ((u"xchg", 0xEB, C_XCHG, u"XCHG"), (u"xthl", 0xE3, C_XTHL, u"XTHL"),
             (u"sphl", 0xF9, C_SPHL, u"SPHL"), (u"pchl", 0xE9, C_PCHL, u"PCHL"),
             (u"ei", 0xFB, C_EI, u"EI"), (u"di", 0xF3, C_DI, u"DI"),
             (u"inp", 0xDB, C_IN, u"IN"), (u"outp", 0xD3, C_OUT, u"OUT"))

    n = p.network(u"СЕТЬ 1. Признаки отдельных кодов и RST по маске C7h")
    for k, (nm, val, _cls, _txt) in enumerate(codes):
        n.outvar(nm, n.block(u"EQ", [(u"IN1", n.invar(u"IR")),
                                     (u"IN2", n.invar(u"BYTE#16#%02X" % val))], [u"OUT"],
                            fbd_xml.COL_BLK + 120 * k))
    m = n.block(u"AND", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#16#C7"))],
                [u"OUT"], fbd_xml.COL_BLK + 120 * 8)
    n.outvar(u"isrst", n.block(u"EQ", [(u"IN1", m), (u"IN2", n.invar(u"BYTE#16#C7"))],
                               [u"OUT"], fbd_xml.COL_BLK + 120 * 9))

    n = p.network(u"СЕТЬ 2. Hit := OR всех признаков")
    n.outvar(u"Hit", _or_chain(n, [n.invar(x) for x in
                                   (u"xchg", u"xthl", u"sphl", u"pchl",
                                    u"ei", u"di", u"inp", u"outp", u"isrst")]))

    n = p.network(u"СЕТЬ 3. Класс операции по приоритету")
    st = [(n.invar(nm), n.invar(u"BYTE#%d" % cl)) for nm, _v, cl, _t in codes]
    st.append((n.invar(u"isrst"), n.invar(u"BYTE#%d" % C_RST)))
    n.outvar(u"Cls", _chain(n, n.invar(u"BYTE#%d" % C_NOP), st, dx=115))
    return p


# ======================================================================
def make_decoder_full():
    p = Pou(u"FB_Decoder_Full", u"functionBlock",
            doc=u"Сводный декодер 8080: регистр команды -> управляющее слово GVL_CPU.\n"
                u"\tВход: IR - код команды.\n"
                u"\tВыход: набор полей прямо в GVL_CPU (см. таблицу классов там же):\n"
                u"\t  C_Class  - класс операции 0..35;\n"
                u"\t  C_Dst1/C_Dst2 - коды регистров-приёмников (портов записи два,\n"
                u"\t             потому что LHLD, POP и XCHG пишут несколько регистров);\n"
                u"\t  C_Src    - код источника (6 = память по HL);\n"
                u"\t  C_RP     - код пары (0=BC 1=DE 2=HL 3=SP, для PUSH/POP - PSW);\n"
                u"\t  C_ALU_Op - операция АЛУ в кодировке FB_ALU8 (0=ADD 1=ADC 2=SUB\n"
                u"\t             3=SBB 4=ANA 5=ORA 6=XRA); поле xxx кодировки 8080\n"
                u"\t             перекодируется: 5(XRA)<->6(ORA), 7(CMP)->2(SUB)+IsCmp;\n"
                u"\t  C_Cond   - код условия 0=NZ..7=M (для Jcc/Ccc/Rcc);\n"
                u"\t  C_Vec    - вектор RST 0..7 (адрес = вектор * 8);\n"
                u"\t  C_Rot    - вид сдвига 0=RLC 1=RRC 2=RAL 3=RAR;\n"
                u"\t  C_Flag   - 0=CMA 1=STC 2=CMC;\n"
                u"\t  C_Len    - длина команды (1, 2 или 3 байта);\n"
                u"\t  C_RdSel  - какой адрес читать из памяти: 0=не надо 1=a16 2=BC\n"
                u"\t             3=DE 4=SP (по нему читаются LDA/LHLD/LDAX, POP/RET/XTHL);\n"
                u"\t  C_Uncond, C_IsCmp, C_Halt, C_EI, C_DI, C_IsPSW - признаки команд;\n"
                u"\t  C_WReg1..C_WReg4 - разрешения записи в регистры по портам;\n"
                u"\t  C_SZP_En, C_AC_En, C_CY_En - какие флаги обновлять:\n"
                u"\t             ALU/ALUI/DAA меняют все пять флагов, INR/DCR - все\n"
                u"\t             кроме CY, DAD и сдвиги - только CY, CMA - ничего;\n"
                u"\t  C_LdPSW  - POP PSW: загрузить флаги из байта по адресу SP.\n"
                u"\tВыходы вызовов девяти распознавателей сразу защёлкиваются в\n"
                u"\tлокальные переменные: выход FB нельзя ни разветвлять, ни читать\n"
                u"\tиз другой сети (CODESYS молча выбрасывает такой POU / вешает импорт).")
    p.var_in(u"IR", u"BYTE", u"регистр команды")
    for nm, txt in ((u"h_mov", u"признак MOV"), (u"h_mvi", u"признак MVI"),
                    (u"h_alu", u"признак ALU"), (u"h_alui", u"признак ALUI"),
                    (u"h_data", u"признак группы 00h"), (u"h_jmp", u"признак переходов"),
                    (u"h_stk", u"признак PUSH/POP"), (u"h_spec", u"признак отдельных команд"),
                    (u"h_hlt", u"признак HLT")):
        p.var(nm, u"BOOL", txt)
    p.var(u"cls_data", u"BYTE", u"класс от декодера группы 00h")
    p.var(u"rot_data", u"BYTE", u"вид сдвига")
    p.var(u"flag_data", u"BYTE", u"операция над флагами")
    p.var(u"cls_jmp", u"BYTE", u"класс от декодера переходов")
    p.var(u"uncond_jmp", u"BOOL", u"безусловная форма перехода")
    p.var(u"cls_stk", u"BYTE", u"класс от декодера стека")
    p.var(u"cls_spec", u"BYTE", u"класс от декодера отдельных команд")
    p.var(u"cls", u"BYTE", u"итоговый класс операции")
    p.var(u"f3", u"BYTE", u"поле битов 5..3")
    p.var(u"src", u"BYTE", u"поле битов 2..0")
    p.var(u"rp", u"BYTE", u"код пары (биты 5..4)")
    p.var(u"lxi_reg", u"BOOL", u"LXI с записью пары (не SP)")
    p.var(u"rp3", u"BOOL", u"код пары = 3 (SP или PSW)")
    p.var(u"rp2", u"BYTE", u"код пары * 2")
    p.var(u"rp2p1", u"BYTE", u"код пары * 2 + 1")
    p.var(u"mdst", u"BOOL", u"поле DDD = 6 (приёмник - память)")
    p.var(u"aop", u"BYTE", u"перекодированная операция АЛУ")
    for nm, txt in ((u"a_mov", u"класс MOV"), (u"a_mvi", u"класс MVI"),
                    (u"a_alu", u"класс ALU"), (u"a_alui", u"класс ALUI"),
                    (u"a_inr", u"класс INR"), (u"a_dcr", u"класс DCR"),
                    (u"a_ldax", u"класс LDAX"), (u"a_stax", u"класс STAX"),
                    (u"a_lda", u"класс LDA"), (u"a_sta", u"класс STA"),
                    (u"a_lhld", u"класс LHLD"), (u"a_shld", u"класс SHLD"),
                    (u"a_lxi", u"класс LXI"), (u"a_xchg", u"класс XCHG"),
                    (u"a_xthl", u"класс XTHL"), (u"a_rot", u"класс ROT"),
                    (u"a_flag", u"класс FLAG"), (u"a_daa", u"класс DAA"),
                    (u"a_inx", u"класс INX"), (u"a_dcx", u"класс DCX"),
                    (u"a_dad", u"класс DAD"),
                    (u"a_ei", u"класс EI"), (u"a_di", u"класс DI"),
                    (u"a_jmp", u"класс JMP"), (u"a_call", u"класс CALL"),
                    (u"a_ret", u"класс RET"), (u"a_push", u"класс PUSH"),
                    (u"a_pop", u"класс POP"), (u"a_in", u"класс IN"),
                    (u"a_out", u"класс OUT")):
        p.var(nm, u"BOOL", txt)
    p.var(u"grp_mm", u"BOOL", u"приёмник - регистр (MOV/MVI/INR/DCR с DDD<>6)")
    p.var(u"grp_am", u"BOOL", u"ALU с источником в памяти (SSS=6)")
    p.var(u"grp_psw", u"BOOL", u"PUSH/POP PSW")
    p.var(u"grp_lh", u"BOOL", u"приёмник - пара H/L (LHLD/SHLD/XTHL)")
    p.var(u"grp_a", u"BOOL", u"приёмник - аккумулятор A")
    p.var(u"grp_incdec", u"BOOL", u"INR или DCR")
    p.var(u"grp_step_reg", u"BOOL", u"INX/DCX над парой (не SP): пишутся два регистра")
    p.var(u"grp_szp", u"BOOL", u"S, Z, P обновляются")
    p.var(u"grp_cy", u"BOOL", u"CY обновляется")
    p.var(u"dst1", u"BYTE", u"код приёмника порта 1")
    p.var(u"dst2", u"BYTE", u"код приёмника порта 2")
    p.var(u"wr1a", u"BOOL", u"запись регистра портом 1 (по классу)")
    p.var(u"flagcy", u"BOOL", u"FLAG со сменой CY (STC/CMC)")
    for nm, typ, txt in ((u"d_mov", u"FB_DecodeFull_MOV", u"декодер MOV"),
                         (u"d_mvi", u"FB_DecodeFull_MVI", u"декодер MVI"),
                         (u"d_alu", u"FB_DecodeFull_ALU", u"декодер ALU"),
                         (u"d_alui", u"FB_DecodeFull_ALUI", u"декодер ALUI"),
                         (u"d_data", u"FB_DecodeFull_DATA", u"декодер группы 00h"),
                         (u"d_jmp", u"FB_DecodeFull_JMP", u"декодер переходов"),
                         (u"d_stk", u"FB_DecodeFull_STACK", u"декодер стека"),
                         (u"d_spec", u"FB_DecodeFull_SPEC", u"декодер отдельных команд"),
                         (u"d_hlt", u"FB_DecodeFull_HLT", u"декодер HLT")):
        p.var(nm, typ, txt)

    # --- сеть 1: вызов девяти распознавателей и защёлкивание выходов ---
    n = p.network(u"СЕТЬ 1. Распознавание всех групп команд 8080")
    ir = n.invar(u"IR")
    d1 = n.block(u"FB_DecodeFull_MOV", [(u"IR", ir)], [u"Hit", u"Cls"], instance=u"d_mov")
    n.outvar(u"h_mov", d1.out(u"Hit"))
    d2 = n.block(u"FB_DecodeFull_MVI", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_mvi", x=fbd_xml.COL_BLK)
    n.outvar(u"h_mvi", d2.out(u"Hit"))
    d3 = n.block(u"FB_DecodeFull_ALU", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_alu", x=fbd_xml.COL_BLK2)
    n.outvar(u"h_alu", d3.out(u"Hit"))
    d4 = n.block(u"FB_DecodeFull_ALUI", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_alui", x=fbd_xml.COL_BLK2)
    n.outvar(u"h_alui", d4.out(u"Hit"))
    d5 = n.block(u"FB_DecodeFull_DATA", [(u"IR", n.invar(u"IR"))],
                 [u"Hit", u"Cls", u"Rot", u"Flag"], instance=u"d_data", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"h_data", d5.out(u"Hit"))
    n.outvar(u"cls_data", d5.out(u"Cls"))
    n.outvar(u"rot_data", d5.out(u"Rot"))
    n.outvar(u"flag_data", d5.out(u"Flag"))
    d6 = n.block(u"FB_DecodeFull_JMP", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls", u"Uncond"],
                 instance=u"d_jmp", x=fbd_xml.COL_BLK2)
    n.outvar(u"h_jmp", d6.out(u"Hit"))
    n.outvar(u"cls_jmp", d6.out(u"Cls"))
    n.outvar(u"uncond_jmp", d6.out(u"Uncond"))
    d7 = n.block(u"FB_DecodeFull_STACK", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_stk", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"h_stk", d7.out(u"Hit"))
    n.outvar(u"cls_stk", d7.out(u"Cls"))
    d8 = n.block(u"FB_DecodeFull_SPEC", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_spec", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"h_spec", d8.out(u"Hit"))
    n.outvar(u"cls_spec", d8.out(u"Cls"))
    d9 = n.block(u"FB_DecodeFull_HLT", [(u"IR", n.invar(u"IR"))], [u"Hit", u"Cls"],
                 instance=u"d_hlt", x=fbd_xml.COL_BLK + 600)
    n.outvar(u"h_hlt", d9.out(u"Hit"))

    # --- сеть 2: поля команды ---
    n = p.network(u"СЕТЬ 2. Поля команды: f3 = (IR SHR 3) AND 7, src = IR AND 7, "
                  u"rp = (IR SHR 4) AND 3")
    sh4 = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#4"))], [u"OUT"])
    n.outvar(u"rp", n.block(u"AND", [(u"IN1", sh4), (u"IN2", n.invar(u"BYTE#3"))],
                            [u"OUT"], fbd_xml.COL_BLK2))
    sh3 = n.block(u"SHR", [(u"IN1", n.invar(u"IR")), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"],
                  fbd_xml.COL_BLK2 + 200)
    n.outvar(u"f3", n.block(u"AND", [(u"IN1", sh3), (u"IN2", n.invar(u"BYTE#7"))],
                            [u"OUT"], fbd_xml.COL_BLK2 + 340))
    n.outvar(u"src", n.block(u"AND", [(u"IN1", n.invar(u"IR")),
                                      (u"IN2", n.invar(u"BYTE#7"))], [u"OUT"],
                             fbd_xml.COL_BLK2 + 480))
    sh1 = n.block(u"SHL", [(u"IN1", n.invar(u"rp")), (u"IN2", n.invar(u"BYTE#1"))], [u"OUT"],
                  fbd_xml.COL_BLK2 + 620)
    n.outvar(u"rp2", sh1)
    n.outvar(u"rp2p1", n.block(u"ADD", [(u"IN1", n.invar(u"rp2")),
                                        (u"IN2", n.invar(u"BYTE#1"))], [u"OUT"],
                               fbd_xml.COL_BLK2 + 760))
    n.outvar(u"rp3", n.block(u"EQ", [(u"IN1", n.invar(u"rp")), (u"IN2", n.invar(u"BYTE#3"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 900))

    # --- сеть 3: класс операции ---
    n = p.network(u"СЕТЬ 3. Класс операции C_Class по приоритету распознавателей")
    n.outvar(u"cls", _chain(n, n.invar(u"BYTE#%d" % C_NOP), [
        (n.invar(u"h_mov"), n.invar(u"BYTE#%d" % C_MOV)),
        (n.invar(u"h_mvi"), n.invar(u"BYTE#%d" % C_MVI)),
        (n.invar(u"h_alu"), n.invar(u"BYTE#%d" % C_ALU)),
        (n.invar(u"h_alui"), n.invar(u"BYTE#%d" % C_ALUI)),
        (n.invar(u"h_data"), n.invar(u"cls_data")),
        (n.invar(u"h_jmp"), n.invar(u"cls_jmp")),
        (n.invar(u"h_stk"), n.invar(u"cls_stk")),
        (n.invar(u"h_spec"), n.invar(u"cls_spec")),
        (n.invar(u"h_hlt"), n.invar(u"BYTE#%d" % C_HLT))], dx=115))

    # --- сеть 4: признаки классов, нужные дальше ---
    n = p.network(u"СЕТЬ 4. Признаки классов для расчёта полей")
    cls = n.invar(u"cls")
    for k, (nm, code) in enumerate(((u"a_mov", C_MOV), (u"a_mvi", C_MVI), (u"a_alu", C_ALU),
                                    (u"a_alui", C_ALUI), (u"a_inr", C_INR), (u"a_dcr", C_DCR),
                                    (u"a_ldax", C_LDAX), (u"a_stax", C_STAX), (u"a_lda", C_LDA),
                                    (u"a_sta", C_STA), (u"a_lhld", C_LHLD), (u"a_shld", C_SHLD),
                                    (u"a_lxi", C_LXI), (u"a_xchg", C_XCHG), (u"a_xthl", C_XTHL),
                                    (u"a_rot", C_ROT), (u"a_flag", C_FLAG), (u"a_daa", C_DAA),
                                    (u"a_inx", C_INX), (u"a_dcx", C_DCX), (u"a_dad", C_DAD),
                                    (u"a_ei", C_EI), (u"a_di", C_DI), (u"a_jmp", C_JMP),
                                    (u"a_call", C_CALL), (u"a_ret", C_RET), (u"a_push", C_PUSH),
                                    (u"a_pop", C_POP), (u"a_in", C_IN), (u"a_out", C_OUT))):
        n.outvar(nm, n.block(u"EQ", [(u"IN1", cls), (u"IN2", n.invar(u"BYTE#%d" % code))],
                             [u"OUT"], fbd_xml.COL_BLK + 110 * (k % 9),
                             fbd_xml.ROW0 + 40 * (k // 9)))

    # --- сеть 5: группы признаков ---
    n = p.network(u"СЕТЬ 5. Групповые признаки (что писать и какие флаги обновлять)")
    n.outvar(u"grp_incdec", _or_chain(n, [n.invar(u"a_inr"), n.invar(u"a_dcr")],
                                      x0=fbd_xml.COL_BLK))
    n.outvar(u"mdst", n.block(u"EQ", [(u"IN1", n.invar(u"f3")), (u"IN2", n.invar(u"BYTE#6"))],
                              [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"grp_mm", n.block(u"AND", [
        (u"IN1", n.invar(u"mdst")),
        (u"IN2", _or_chain(n, [n.invar(u"a_mov"), n.invar(u"a_mvi"),
                               n.invar(u"a_inr"), n.invar(u"a_dcr")],
                           x0=fbd_xml.COL_BLK2 + 160))],
        [u"OUT"], fbd_xml.COL_BLK2 + 320))
    n.outvar(u"grp_am", n.block(u"AND", [
        (u"IN1", n.invar(u"a_alu")),
        (u"IN2", n.block(u"EQ", [(u"IN1", n.invar(u"src")), (u"IN2", n.invar(u"BYTE#6"))],
                         [u"OUT"], fbd_xml.COL_BLK2 + 320))],
        [u"OUT"], fbd_xml.COL_BLK2 + 480))
    n.outvar(u"grp_psw", n.block(u"AND", [
        (u"IN1", _or_chain(n, [n.invar(u"a_push"), n.invar(u"a_pop")],
                           x0=fbd_xml.COL_BLK + 700)),
        (u"IN2", n.invar(u"rp3"))], [u"OUT"], fbd_xml.COL_BLK + 860))
    n.outvar(u"grp_lh", _or_chain(n, [n.invar(u"a_lhld"), n.invar(u"a_shld"),
                                       n.invar(u"a_xthl"), n.invar(u"a_dad")],
                                  x0=fbd_xml.COL_BLK2 + 700))
    n.outvar(u"grp_a", _or_chain(n, [n.invar(u"a_alu"), n.invar(u"a_alui"), n.invar(u"a_lda"),
                                      n.invar(u"a_ldax"), n.invar(u"a_stax"), n.invar(u"a_rot"),
                                      n.invar(u"a_flag"), n.invar(u"a_daa")],
                                 x0=fbd_xml.COL_BLK2 + 900))
    n.outvar(u"grp_szp", _or_chain(n, [n.invar(u"a_alu"), n.invar(u"a_alui"),
                                        n.invar(u"a_inr"), n.invar(u"a_dcr"), n.invar(u"a_daa")],
                                   x0=fbd_xml.COL_BLK2 + 1100))
    n.outvar(u"flagcy", n.block(u"NE", [(u"IN1", n.invar(u"flag_data")),
                                        (u"IN2", n.invar(u"BYTE#0"))], [u"OUT"],
                               fbd_xml.COL_BLK2 + 1300))
    n.outvar(u"grp_cy", _or_chain(n, [n.invar(u"a_alu"), n.invar(u"a_alui"), n.invar(u"a_daa"),
                                       n.invar(u"a_rot"), n.invar(u"a_dad"),
                                       n.block(u"AND", [(u"IN1", n.invar(u"a_flag")),
                                                        (u"IN2", n.invar(u"flagcy"))],
                                               [u"OUT"], fbd_xml.COL_BLK2 + 1500)],
                                  x0=fbd_xml.COL_BLK2 + 1600))

    # --- сеть 6: C_ALU_Op ---
    n = p.network(u"СЕТЬ 6. C_ALU_Op: перекодировка поля xxx в коды FB_ALU8")
    f3 = n.invar(u"f3")
    e5 = n.block(u"EQ", [(u"IN1", f3), (u"IN2", n.invar(u"BYTE#5"))], [u"OUT"])
    e6 = n.block(u"EQ", [(u"IN1", n.invar(u"f3")), (u"IN2", n.invar(u"BYTE#6"))], [u"OUT"],
                 fbd_xml.COL_BLK2)
    e7 = n.block(u"EQ", [(u"IN1", n.invar(u"f3")), (u"IN2", n.invar(u"BYTE#7"))], [u"OUT"],
                 fbd_xml.COL_BLK2 + 120)
    acc = _chain(n, n.invar(u"f3"), [
        (e5, n.invar(u"BYTE#6")),        # XRA -> код 6
        (e6, n.invar(u"BYTE#5")),        # ORA -> код 5
        (e7, n.invar(u"BYTE#2"))])       # CMP -> SUB
    n.outvar(u"aop", acc)
    n.outvar(u"GVL_CPU.C_ALU_Op", _chain(n, n.invar(u"aop"), [
        (n.invar(u"a_dcr"), n.invar(u"BYTE#2")),
        (n.invar(u"a_inr"), n.invar(u"BYTE#0"))], x0=fbd_xml.COL_BLK2 + 400))

    # --- сеть 7: приёмники ---
    n = p.network(u"СЕТЬ 7. C_Dst1 и C_Dst2 (два порта записи регистров)")
    n.outvar(u"grp_step_reg", n.block(u"AND", [
        (u"IN1", _or_chain(n, [n.invar(u"a_inx"), n.invar(u"a_dcx")], x0=fbd_xml.COL_BLK)),
        (u"IN2", n.block(u"NOT", [(u"IN", n.invar(u"rp3"))], [u"OUT"], fbd_xml.COL_BLK + 240))],
        [u"OUT"], fbd_xml.COL_BLK + 380))
    n.outvar(u"dst1", _chain(n, n.invar(u"f3"), [
        (n.invar(u"grp_a"), n.invar(u"BYTE#7")),                       # A
        (n.invar(u"grp_lh"), n.invar(u"BYTE#5")),                      # L
        (n.invar(u"a_xchg"), n.invar(u"BYTE#2")),                      # D
        (n.invar(u"a_pop"), n.block(u"SEL", [
            (u"G", n.invar(u"grp_psw")), (u"IN0", n.invar(u"rp2p1")),
            (u"IN1", n.invar(u"BYTE#7"))], [u"OUT"], fbd_xml.COL_BLK2)),
        (n.invar(u"a_lxi"), n.invar(u"rp2p1")),
        (n.invar(u"grp_step_reg"), n.invar(u"rp2p1"))]))
    n.outvar(u"dst2", _chain(n, n.invar(u"BYTE#0"), [
        (n.invar(u"grp_lh"), n.invar(u"BYTE#4")),                      # H
        (n.invar(u"a_pop"), n.invar(u"rp2")),
        (n.invar(u"a_xchg"), n.invar(u"BYTE#3")),                      # E
        (n.invar(u"a_lxi"), n.invar(u"rp2")),
        (n.invar(u"grp_step_reg"), n.invar(u"rp2"))], x0=fbd_xml.COL_BLK2 + 300))

    # --- сеть 8: длина команды и адрес чтения ---
    n = p.network(u"СЕТЬ 8. C_Len (1/2/3 байта) и C_RdSel (какой адрес читать)")
    e2 = _or_chain(n, [n.invar(u"a_mvi"), n.invar(u"a_alui"),
                       n.invar(u"a_in"), n.invar(u"a_out")], x0=fbd_xml.COL_BLK)
    e3 = _or_chain(n, [n.invar(u"a_lxi"), n.invar(u"a_lda"), n.invar(u"a_sta"),
                       n.invar(u"a_lhld"), n.invar(u"a_shld"),
                       n.invar(u"a_jmp"), n.invar(u"a_call")], x0=fbd_xml.COL_BLK + 200)
    n.outvar(u"GVL_CPU.C_Len", _chain(n, n.invar(u"BYTE#1"), [
        (e2, n.invar(u"BYTE#2")), (e3, n.invar(u"BYTE#3"))], x0=fbd_xml.COL_BLK2 + 400))
    a16 = _or_chain(n, [n.invar(u"a_lda"), n.invar(u"a_sta"),
                        n.invar(u"a_lhld"), n.invar(u"a_shld")], x0=fbd_xml.COL_BLK + 700)
    # ВНИМАНИЕ (фаза B): признак BC был ИНВЕРТИРОВАН - стояло
    # NOT(rp = 0) вместо (rp = 0). Для LDAX B / STAX B (это rp = 0) адрес
    # чтения не выбирался, C_RdSel оставался 0, и память читалась по адресу
    # НОЛЬ. Именно поэтому LDAX B читал 00h вместо значения, положенного тестом
    # по адресу BC = 0100h. У DE условие было записано правильно, поэтому
    # расхождение касалось только BC.
    bc = n.block(u"AND", [(u"IN1", _or_chain(n, [n.invar(u"a_ldax"), n.invar(u"a_stax")],
                                             x0=fbd_xml.COL_BLK + 900)),
                          (u"IN2", n.block(u"EQ", [(u"IN1", n.invar(u"rp")),
                                                   (u"IN2", n.invar(u"BYTE#0"))],
                                           [u"OUT"], fbd_xml.COL_BLK + 1240))],
                 [u"OUT"], fbd_xml.COL_BLK + 1380)
    de = n.block(u"AND", [(u"IN1", _or_chain(n, [n.invar(u"a_ldax"), n.invar(u"a_stax")],
                                             x0=fbd_xml.COL_BLK + 1520)),
                          (u"IN2", n.block(u"EQ", [(u"IN1", n.invar(u"rp")),
                                                   (u"IN2", n.invar(u"BYTE#1"))],
                                           [u"OUT"], fbd_xml.COL_BLK + 1660))],
                 [u"OUT"], fbd_xml.COL_BLK + 1800)
    sp = _or_chain(n, [n.invar(u"a_ret"), n.invar(u"a_pop"), n.invar(u"a_xthl")],
                   x0=fbd_xml.COL_BLK + 1940)
    # ФАЗА B: операнд M (источник по HL) читается через ТОТ ЖЕ путь, что LDA и
    # LDAX, - он проверен и работает. Отдельный блок чтения по HL значения не
    # давал: адрес верный (HL=0600h), память ненулевая, а операнд приходил нулевой.
    msrc = n.block(u"AND", [
        (u"IN1", n.block(u"EQ", [(u"IN1", n.invar(u"src")),
                                 (u"IN2", n.invar(u"BYTE#6"))], [u"OUT"],
                        fbd_xml.COL_BLK + 2100)),
        (u"IN2", _or_chain(n, [n.invar(u"a_mov"), n.invar(u"a_alu"),
                               n.invar(u"a_inr"), n.invar(u"a_dcr")],
                           x0=fbd_xml.COL_BLK + 2200))],
        [u"OUT"], fbd_xml.COL_BLK + 2400)
    n.outvar(u"GVL_CPU.C_RdSel", _chain(n, n.invar(u"BYTE#0"), [
        (a16, n.invar(u"BYTE#1")), (bc, n.invar(u"BYTE#2")),
        (de, n.invar(u"BYTE#3")), (sp, n.invar(u"BYTE#4")),
        (msrc, n.invar(u"BYTE#5"))],
        x0=fbd_xml.COL_BLK2 + 700))

    # --- сеть 9: признаки и разрешения ---
    n = p.network(u"СЕТЬ 9. Признаки команд, разрешения записи и флаги")
    # ВНИМАНИЕ (фаза B): в списке НЕ БЫЛО a_lxi. Из-за этого для LXI порт 1
    # записи регистров оставался выключенным, и МЛАДШИЙ байт пары не писался:
    # из LXI BC,1234h записывался только B := 12h, а C оставался прежним (33h).
    # Проверено поскайсовой диагностикой: IR=01h/11h/21h, класс 16, пара 0/1/2 -
    # декодирование верное, не хватало только разрешения записи.
    # LXI добавлен в wr1a: без него порт 1 не писал, и младший байт пары терялся.
    # Случай LXI SP закрыт в процессоре (порты регистров гасятся по is_lxi_sp):
    # гейт здесь, через rp3, проверен и ОТКЛОНЕН - он ломал обычные LXI.
    n.outvar(u"wr1a", _or_chain(n, [n.invar(u"a_mov"), n.invar(u"a_mvi"), n.invar(u"a_inr"),
                                    n.invar(u"a_dcr"), n.invar(u"a_lda"), n.invar(u"a_ldax"),
                                    n.invar(u"a_lhld"), n.invar(u"a_pop"), n.invar(u"a_xthl"),
                                    n.invar(u"a_xchg"), n.invar(u"a_rot"), n.invar(u"a_daa"),
                                    n.invar(u"a_dad"), n.invar(u"a_lxi")],
                                x0=fbd_xml.COL_BLK))
    # C_WReg1: регистровая запись портом 1 (кроме случая "приёмник - память")
    n.outvar(u"GVL_CPU.C_WReg1", n.block(u"AND", [
        (u"IN1", n.block(u"OR", [
            (u"IN1", n.block(u"OR", [
                (u"IN1", n.invar(u"wr1a")),
                (u"IN2", n.invar(u"grp_step_reg"))], [u"OUT"], fbd_xml.COL_BLK2)),
            (u"IN2", n.block(u"OR", [
                (u"IN1", n.block(u"AND", [
                    (u"IN1", _or_chain(n, [n.invar(u"a_alu"), n.invar(u"a_alui")],
                                       x0=fbd_xml.COL_BLK2)),
                    (u"IN2", n.block(u"NOT", [
                        (u"IN", n.block(u"EQ", [(u"IN1", n.invar(u"f3")),
                                                (u"IN2", n.invar(u"BYTE#7"))],
                                        [u"OUT"], fbd_xml.COL_BLK2 + 300))],
                        [u"OUT"], fbd_xml.COL_BLK2 + 440))],
                    [u"OUT"], fbd_xml.COL_BLK2 + 580)),
                (u"IN2", n.block(u"AND", [          # CMA пишет A
                    (u"IN1", n.invar(u"a_flag")),
                    (u"IN2", n.block(u"NOT", [
                        (u"IN", n.block(u"NE", [(u"IN1", n.invar(u"flag_data")),
                                                (u"IN2", n.invar(u"BYTE#0"))],
                                        [u"OUT"], fbd_xml.COL_BLK2 + 860))],
                        [u"OUT"], fbd_xml.COL_BLK2 + 1000))],
                    [u"OUT"], fbd_xml.COL_BLK2 + 1140))],
                [u"OUT"], fbd_xml.COL_BLK2 + 1280))],
            [u"OUT"], fbd_xml.COL_BLK2 + 1420)),
        # ФАЗА B. Здесь стояло NOT(grp_mm OR grp_am), то есть запись в регистр
        # гасилась ещё и при "у АЛУ источник в памяти". Но ADD M / SUB M / ORA M
        # и вся группа ALU с операндом M пишут результат именно в A - из-за этого
        # A не менялся вовсе (наблюдалось: ADD M при A=0Fh и M=01h оставлял A=0Fh,
        # хотя память получала правильный результат 10h).
        # Гасить регистровую запись нужно ТОЛЬКО когда приёмник - память (grp_mm).
        (u"IN2", n.block(u"NOT", [
            (u"IN", n.invar(u"grp_mm"))],
            [u"OUT"], fbd_xml.COL_BLK2 + 1840))],
        [u"OUT"], fbd_xml.COL_BLK2 + 1980))
    n.outvar(u"GVL_CPU.C_WReg2", n.block(u"OR", [
        (u"IN1", _or_chain(n, [n.invar(u"a_lhld"), n.invar(u"a_xthl"), n.invar(u"a_xchg"),
                               n.invar(u"a_dad"), n.invar(u"grp_step_reg")],
                           x0=fbd_xml.COL_BLK + 600)),
        (u"IN2", n.block(u"OR", [
            (u"IN1", n.block(u"AND", [                 # POP без PSW
                (u"IN1", n.invar(u"a_pop")),
                (u"IN2", n.block(u"NOT", [(u"IN", n.invar(u"grp_psw"))], [u"OUT"],
                                 fbd_xml.COL_BLK + 900))],
                [u"OUT"], fbd_xml.COL_BLK + 1040)),
            (u"IN2", n.block(u"AND", [                 # LXI кроме SP
                (u"IN1", n.invar(u"a_lxi")),
                (u"IN2", n.block(u"NOT", [(u"IN", n.invar(u"rp3"))], [u"OUT"],
                                 fbd_xml.COL_BLK + 1320))],
                [u"OUT"], fbd_xml.COL_BLK + 1460))],
            [u"OUT"], fbd_xml.COL_BLK + 1600))],
        [u"OUT"], fbd_xml.COL_BLK + 1740))
    n.outvar(u"GVL_CPU.C_WReg3", n.invar(u"a_xchg"))
    n.outvar(u"GVL_CPU.C_WReg4", n.invar(u"a_xchg"))
    n.outvar(u"GVL_CPU.C_SZP_En", n.invar(u"grp_szp"))
    n.outvar(u"GVL_CPU.C_AC_En", n.invar(u"grp_szp"))
    n.outvar(u"GVL_CPU.C_CY_En", n.invar(u"grp_cy"))
    n.outvar(u"GVL_CPU.C_LdPSW", n.block(u"AND", [
        (u"IN1", n.invar(u"a_pop")), (u"IN2", n.invar(u"grp_psw"))], [u"OUT"],
        fbd_xml.COL_BLK + 1900))
    n.outvar(u"GVL_CPU.C_IsPSW", n.invar(u"grp_psw"))
    n.outvar(u"GVL_CPU.C_Uncond", n.invar(u"uncond_jmp"))
    n.outvar(u"GVL_CPU.C_IsCmp", n.block(u"AND", [
        (u"IN1", _or_chain(n, [n.invar(u"a_alu"), n.invar(u"a_alui")],
                           x0=fbd_xml.COL_BLK + 2100)),
        (u"IN2", n.block(u"EQ", [(u"IN1", n.invar(u"f3")), (u"IN2", n.invar(u"BYTE#7"))],
                         [u"OUT"], fbd_xml.COL_BLK + 2400))],
        [u"OUT"], fbd_xml.COL_BLK + 2540))
    n.outvar(u"GVL_CPU.C_Halt", n.invar(u"h_hlt"))
    n.outvar(u"GVL_CPU.C_EI", n.invar(u"a_ei"))
    n.outvar(u"GVL_CPU.C_DI", n.invar(u"a_di"))

    # --- сеть 10: прямое копирование простых полей ---
    n = p.network(u"СЕТЬ 10. Поля, которые берутся из регистра команды напрямую")
    n.outvar(u"GVL_CPU.C_Class", n.invar(u"cls"))
    n.outvar(u"GVL_CPU.C_Dst1", n.invar(u"dst1"))
    n.outvar(u"GVL_CPU.C_Dst2", n.invar(u"dst2"))
    # у INR/DCR поле SSS в команде не используется: операндом служит тот самый
    # регистр, который записан в поле DDD. Поэтому источник берётся из f3 -
    # иначе INR B сложил бы единицу с аккумулятором.
    n.outvar(u"GVL_CPU.C_Src", n.block(u"SEL", [
        (u"G", n.invar(u"grp_incdec")), (u"IN0", n.invar(u"src")),
        (u"IN1", n.invar(u"f3"))], [u"OUT"]))
    n.outvar(u"GVL_CPU.C_RP", n.invar(u"rp"))
    n.outvar(u"GVL_CPU.C_Cond", n.invar(u"f3"))
    n.outvar(u"GVL_CPU.C_Vec", n.invar(u"f3"))
    n.outvar(u"GVL_CPU.C_Rot", n.invar(u"rot_data"))
    n.outvar(u"GVL_CPU.C_Flag", n.invar(u"flag_data"))
    return p


ALL = (make_decode_mov, make_decode_mvi, make_decode_alu, make_decode_alui,
       make_decode_hlt, make_decode_data, make_decode_jmp, make_decode_stack,
       make_decode_spec, make_decoder_full)
