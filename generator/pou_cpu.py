# -*- coding: utf-8 -*-
u"""Описание машины (подшаг 3.4): регистровый файл и FB_CPU8080.

Вынесено в отдельный модуль: загрузчик скриптов CODESYS не берёт файлы больше
примерно 25 КБ (процесс стартует и молча висит).

ПРАВИЛА СТИЛЯ, ВЫТЕКШИЕ ИЗ ОГРАНИЧЕНИЙ CODESYS (см. docs/03_ЖУРНАЛ_СБОРКИ.md):
  * один выход = одна связь (иначе POU молча выбрасывается);
  * выход вызова FB нельзя читать из другой сети - защёлкиваем в переменную;
  * сигналы между фазами такта идут через GVL_CPU, а не проводами через лист;
  * для 16-разрядных операций байт сначала переносится в переменную WORD
    (иначе SHL работает в разрядности BYTE и старший байт теряется).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

# Коды регистров 8080: 0=B 1=C 2=D 3=E 4=H 5=L 6=M 7=A
# Классы операций (GVL_CPU.C_Class): 0=NOP 1=MOV 2=MVI 3=ALU 4=JMP 5=CALL 6=RET 9=HLT


def make_reg_file():
    p = Pou(u"FB_RegFile", u"functionBlock",
            doc=u"Регистровый файл: семь 8-разрядных регистров общего назначения.\n"
                u"\tКоды регистров (как в 8080): 0=B 1=C 2=D 3=E 4=H 5=L 6=M 7=A.\n"
                u"\tКод 6 (M) в файле отсутствует - это память по адресу HL,\n"
                u"\tзапись в неё выполняет FB_CPU8080.\n"
                u"\tВходы:  Data - общая шина данных для записи,\n"
                u"\t        LD_B..LD_A - разрешение записи в конкретный регистр\n"
                u"\tВыходы: A, B, C, D, E, H, L - текущие значения.\n"
                u"\tРегистры обновляются в конце вызова, поэтому чтение выходов даёт\n"
                u"\tзначения, записанные в предыдущем такте.")
    p.var_in(u"Data", u"BYTE", u"общая шина данных записи")
    p.var_in(u"LD_B", u"BOOL", u"записать в регистр B")
    p.var_in(u"LD_C", u"BOOL", u"записать в регистр C")
    p.var_in(u"LD_D", u"BOOL", u"записать в регистр D")
    p.var_in(u"LD_E", u"BOOL", u"записать в регистр E")
    p.var_in(u"LD_H", u"BOOL", u"записать в регистр H")
    p.var_in(u"LD_L", u"BOOL", u"записать в регистр L")
    p.var_in(u"LD_A", u"BOOL", u"записать в аккумулятор A")
    p.var_out(u"A", u"BYTE", u"аккумулятор")
    p.var_out(u"B", u"BYTE", u"регистр B")
    p.var_out(u"C", u"BYTE", u"регистр C")
    p.var_out(u"D", u"BYTE", u"регистр D")
    p.var_out(u"E", u"BYTE", u"регистр E")
    p.var_out(u"H", u"BYTE", u"регистр H (старший байт адреса)")
    p.var_out(u"L", u"BYTE", u"регистр L (младший байт адреса)")
    for r in (u"B", u"C", u"D", u"E", u"H", u"L", u"A"):
        p.var(u"r%s" % r, u"FB_Reg8", u"регистр %s" % r)

    n = p.network(u"СЕТЬ 1. Семь регистров: каждый защёлкивается своим сигналом LD")
    data = n.invar(u"Data")
    zero = n.invar(u"FALSE")
    for r in (u"B", u"C", u"D", u"E", u"H", u"L", u"A"):
        blk = n.block(u"FB_Reg8",
                      [(u"D", data), (u"LD", n.invar(u"LD_%s" % r)), (u"CLR", zero)],
                      [u"Q"], instance=u"r%s" % r)
        n.outvar(r, blk.out(u"Q"))
    return p


def make_cpu():
    p = Pou(u"FB_CPU8080", u"functionBlock",
            doc=u"Процессор Intel 8080: один вызов = один такт = один скан PLC.\n"
                u"\tВнутренних T-состояний нет: весь такт укладывается в один скан,\n"
                u"\tфазы разнесены по сетям сверху вниз.\n"
                u"\tФАЗЫ ТАКТА:\n"
                u"\t  1 FETCH          - адрес из PC на шину, чтение команды в IR\n"
                u"\t  2 DECODE         - IR -> управляющее слово на шине GVL_CPU\n"
                u"\t  3 АДРЕСА         - PC+1, PC+2 и пара HL\n"
                u"\t  4 ЧТЕНИЕ         - операнд по HL и два байта по PC+1 / PC+2\n"
                u"\t  5 ОПЕРАНДЫ       - выбор источника через MUX по коду регистра\n"
                u"\t  6 АЛУ            - арифметика/логика и новые флаги\n"
                u"\t  7 ЗАПИСЬ         - регистры и флаги (единственный писатель)\n"
                u"\t  8 PC/ПАМЯТЬ/HLT  - адрес следующей команды, запись в память, стоп\n"
                u"\tВход:  Enable - разрешение работы (0 = процессор стоит)\n"
                u"\tВыходы: Halted - остановлен командой HLT, Step - счётчик тактов.\n"
                u"\tПамять одна (GVL_MEM), но к ней обращаются ПЯТЬ экземпляров\n"
                u"\tFB_Memory64K: выборка команды, операнд по HL, младший и старший\n"
                u"\tбайты по PC+1/PC+2, запись. Вызов FB выполняется один раз за скан,\n"
                u"\tпоэтому адреса обязаны быть разными экземплярами.")
    p.var_in(u"Enable", u"BOOL", u"разрешение выполнения такта")
    p.var_out(u"Halted", u"BOOL", u"процессор остановлен")
    p.var_out(u"Step", u"WORD", u"номер выполненного такта")

    # --- локальные защёлки (BYTE/BOOL) ---
    for v, t, c in (
            (u"run", u"BOOL", u"такт выполняется"),
            (u"pcv", u"WORD", u"текущий PC"),
            (u"spv", u"WORD", u"текущий SP"),
            (u"ir", u"BYTE", u"регистр команды"),
            (u"pc1", u"WORD", u"PC+1"),
            (u"pc2", u"WORD", u"PC+2"),
            (u"hl", u"WORD", u"пара HL - адрес операнда M"),
            (u"op_m", u"BYTE", u"операнд из памяти по HL"),
            (u"op_lo", u"BYTE", u"младший байт по PC+1"),
            (u"op_hi", u"BYTE", u"старший байт по PC+2"),
            (u"msel", u"BYTE", u"регистр-источник с MUX"),
            (u"srcval", u"BYTE", u"значение источника"),
            (u"bval", u"BYTE", u"операнд B для АЛУ"),
            (u"wrval", u"BYTE", u"значение для записи"),
            (u"alu_r", u"BYTE", u"результат АЛУ"),
            (u"target", u"WORD", u"адрес перехода"),
            (u"pcnext", u"WORD", u"адрес следующей команды"),
            (u"is_mov", u"BOOL", u"класс MOV"),
            (u"is_mvi", u"BOOL", u"класс MVI"),
            (u"is_alu", u"BOOL", u"класс АЛУ"),
            (u"is_srcm", u"BOOL", u"источник - память M"),
            (u"is_dstm", u"BOOL", u"приёмник - память M"),
            (u"is_cmp", u"BOOL", u"операция CMP"),
            (u"notcmp", u"BOOL", u"не CMP"),
            (u"wr_en", u"BOOL", u"разрешение записи результата"),
            (u"halt_now", u"BOOL", u"пришла команда HLT"),
            (u"halted_l", u"BOOL", u"защёлка признака остановки"),
            (u"alu_cy", u"BOOL", u"АЛУ: перенос"),
            (u"alu_ac", u"BOOL", u"АЛУ: дополнительный перенос"),
            (u"alu_s", u"BOOL", u"АЛУ: знак"),
            (u"alu_z", u"BOOL", u"АЛУ: ноль"),
            (u"alu_p", u"BOOL", u"АЛУ: чётность"),
            (u"h_w", u"WORD", u"H, расширенный до слова"),
            (u"l_w", u"WORD", u"L, расширенный до слова"),
            (u"ophi_w", u"WORD", u"старший байт адреса, расширенный до слова"),
            (u"oplo_w", u"WORD", u"младший байт адреса, расширенный до слова"),
            (u"ldb", u"BOOL", u"запись в B"), (u"ldc", u"BOOL", u"запись в C"),
            (u"ldd", u"BOOL", u"запись в D"), (u"lde", u"BOOL", u"запись в E"),
            (u"ldh", u"BOOL", u"запись в H"), (u"ldl", u"BOOL", u"запись в L"),
            (u"lda", u"BOOL", u"запись в A")):
        p.var(v, t, c)

    # --- экземпляры ---
    p.var(u"regs", u"FB_RegFile", u"регистровый файл")
    p.var(u"pc", u"FB_Reg16", u"счётчик команд")
    p.var(u"sp", u"FB_Reg16", u"указатель стека")
    p.var(u"flags", u"FB_FlagsReg", u"регистр флагов")
    p.var(u"dec", u"FB_Decoder", u"декодер команд")
    p.var(u"ctrl", u"FB_CtrlUnit", u"блок управления")
    p.var(u"alu", u"FB_ALU8", u"арифметико-логическое устройство")
    p.var(u"msrc", u"FB_Mux8x8", u"MUX выбора регистра-источника")
    p.var(u"m_ir", u"FB_Memory64K", u"память: выборка команды")
    p.var(u"m_op", u"FB_Memory64K", u"память: операнд по HL")
    p.var(u"m_lo", u"FB_Memory64K", u"память: младший байт по PC+1")
    p.var(u"m_hi", u"FB_Memory64K", u"память: старший байт по PC+2")
    p.var(u"m_wr", u"FB_Memory64K", u"память: запись результата")

    # ==================================================================
    # ФАЗА 1. FETCH
    # ==================================================================
    n = p.network(u"СЕТЬ 1 (ФАЗА 1). Разрешение работы и защёлкивание PC / SP")
    en = n.invar(u"Enable")
    halt = n.invar(u"GVL_CPU.Halted")
    n.outvar(u"run", n.block(u"AND", [(u"IN1", en), (u"IN2", n.block(
        u"NOT", [(u"IN", halt)], [u"OUT"], fbd_xml.COL_BLK + 200))],
        [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"pcv", n.invar(u"pc.Q"))
    n.outvar(u"spv", n.invar(u"sp.Q"))

    n = p.network(u"СЕТЬ 2 (ФАЗА 1). Адрес из PC на шину и чтение команды в IR")
    n.outvar(u"GVL_CPU.Bus_Addr", n.invar(u"pcv"))
    m = n.block(u"FB_Memory64K",
                [(u"Addr", n.invar(u"pcv")), (u"Wr", n.invar(u"FALSE")),
                 (u"DataIn", n.invar(u"BYTE#0"))],
                [u"DataOut"], instance=u"m_ir", x=fbd_xml.COL_BLK2)
    n.outvar(u"ir", m.out(u"DataOut"))

    n = p.network(u"СЕТЬ 3 (ФАЗА 1). Регистр команды на шину данных")
    n.outvar(u"GVL_CPU.Bus_IR", n.invar(u"ir"))

    # ==================================================================
    # ФАЗА 2. DECODE
    # ==================================================================
    n = p.network(u"СЕТЬ 4 (ФАЗА 2). DECODE: IR -> управляющее слово на шине GVL_CPU")
    n.block(u"FB_Decoder", [(u"IR", n.invar(u"ir"))], [], instance=u"dec")

    # ==================================================================
    # ФАЗА 3. АДРЕСА
    # ==================================================================
    n = p.network(u"СЕТЬ 5 (ФАЗА 3). Адреса: PC+1, PC+2 и пара HL")
    n.outvar(u"pc1", n.block(u"ADD", [(u"IN1", n.invar(u"pcv")), (u"IN2", n.invar(u"WORD#1"))],
                             [u"OUT"]))
    n.outvar(u"pc2", n.block(u"ADD", [(u"IN1", n.invar(u"pcv")), (u"IN2", n.invar(u"WORD#2"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"h_w", n.invar(u"regs.H"))          # BYTE -> WORD (расширение)
    n.outvar(u"l_w", n.invar(u"regs.L"))
    sh = n.block(u"SHL", [(u"IN1", n.invar(u"h_w")), (u"IN2", n.invar(u"WORD#8"))], [u"OUT"],
                 fbd_xml.COL_BLK + 260)
    n.outvar(u"hl", n.block(u"OR", [(u"IN1", sh), (u"IN2", n.invar(u"l_w"))],
                            [u"OUT"], fbd_xml.COL_BLK2 + 260))

    # ==================================================================
    # ФАЗА 4. ЧТЕНИЕ ОПЕРАНДОВ
    # ==================================================================
    n = p.network(u"СЕТЬ 6 (ФАЗА 4). Чтение: операнд по HL и два байта по PC+1 / PC+2")
    zero_b = n.invar(u"BYTE#0")
    ff = n.invar(u"FALSE")
    a1 = n.block(u"FB_Memory64K", [(u"Addr", n.invar(u"hl")), (u"Wr", ff), (u"DataIn", zero_b)],
                 [u"DataOut"], instance=u"m_op")
    a2 = n.block(u"FB_Memory64K", [(u"Addr", n.invar(u"pc1")), (u"Wr", ff), (u"DataIn", zero_b)],
                 [u"DataOut"], instance=u"m_lo", x=fbd_xml.COL_BLK2)
    a3 = n.block(u"FB_Memory64K", [(u"Addr", n.invar(u"pc2")), (u"Wr", ff), (u"DataIn", zero_b)],
                 [u"DataOut"], instance=u"m_hi", x=fbd_xml.COL_BLK2 + 160)
    n.outvar(u"op_m", a1.out(u"DataOut"))
    n.outvar(u"op_lo", a2.out(u"DataOut"))
    n.outvar(u"op_hi", a3.out(u"DataOut"))

    # ==================================================================
    # ФАЗА 5. ВЫБОР ОПЕРАНДОВ
    # ==================================================================
    n = p.network(u"СЕТЬ 7 (ФАЗА 5). MUX регистра-источника по коду C_Src")
    sel = n.invar(u"GVL_CPU.C_Src")
    ins = [n.invar(u"regs.%s" % r) for r in (u"B", u"C", u"D", u"E", u"H", u"L", u"B", u"A")]
    mx = n.block(u"FB_Mux8x8", [(u"Sel", sel)] + [(u"I%d" % k, ins[k]) for k in range(8)],
                 [u"Q"], instance=u"msrc")
    n.outvar(u"msel", mx.out(u"Q"))

    n = p.network(u"СЕТЬ 8 (ФАЗА 5). Источник: память M или регистр; для MVI - байт по PC+1")
    srcm = n.block(u"EQ", [(u"IN1", n.invar(u"GVL_CPU.C_Src")), (u"IN2", n.invar(u"BYTE#6"))],
                   [u"OUT"])
    n.outvar(u"is_srcm", srcm)
    n.outvar(u"srcval", n.block(u"SEL", [(u"G", srcm), (u"IN0", n.invar(u"msel")),
                                         (u"IN1", n.invar(u"op_m"))],
                                [u"OUT"], fbd_xml.COL_BLK2))
    imm = n.block(u"EQ", [(u"IN1", n.invar(u"GVL_CPU.C_Class")), (u"IN2", n.invar(u"BYTE#2"))],
                  [u"OUT"], fbd_xml.COL_BLK2 + 160)
    n.outvar(u"is_mvi", imm)
    n.outvar(u"bval", n.block(u"SEL", [(u"G", imm), (u"IN0", n.invar(u"srcval")),
                                       (u"IN1", n.invar(u"op_lo"))],
                              [u"OUT"], fbd_xml.COL_BLK2 + 300))

    # ==================================================================
    # ФАЗА 6. АЛУ
    # ==================================================================
    n = p.network(u"СЕТЬ 9 (ФАЗА 6). АЛУ: операция над A и операндом B")
    al = n.block(u"FB_ALU8",
                 [(u"OP", n.invar(u"GVL_CPU.C_ALU_Op")), (u"A", n.invar(u"regs.A")),
                  (u"B", n.invar(u"bval")), (u"Cin", n.invar(u"flags.CY"))],
                 [u"R", u"CY", u"AC", u"S", u"Z", u"P"], instance=u"alu")
    n.outvar(u"alu_r", al.out(u"R"))
    n.outvar(u"alu_cy", al.out(u"CY"))
    n.outvar(u"alu_ac", al.out(u"AC"))
    n.outvar(u"alu_s", al.out(u"S"))
    n.outvar(u"alu_z", al.out(u"Z"))
    n.outvar(u"alu_p", al.out(u"P"))

    # ==================================================================
    # ФАЗА 7. ЗАПИСЬ РЕГИСТРОВ И ФЛАГОВ
    # ==================================================================
    n = p.network(u"СЕТЬ 10 (ФАЗА 7). Класс операции, разрешение записи и значение результата")
    cc = n.invar(u"GVL_CPU.C_Class")
    e1 = n.block(u"EQ", [(u"IN1", cc), (u"IN2", n.invar(u"BYTE#1"))], [u"OUT"])
    e3 = n.block(u"EQ", [(u"IN1", cc), (u"IN2", n.invar(u"BYTE#3"))], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"is_mov", e1)
    n.outvar(u"is_alu", e3)
    n.outvar(u"is_cmp", n.invar(u"GVL_CPU.C_IsCmp"))
    n.outvar(u"notcmp", n.block(u"NOT", [(u"IN", n.invar(u"is_cmp"))], [u"OUT"],
                                fbd_xml.COL_BLK2 + 160))
    n.outvar(u"wr_en", n.block(u"AND", [
        (u"IN1", n.block(u"OR", [
            (u"IN1", n.block(u"OR", [(u"IN1", n.invar(u"is_mov")), (u"IN2", n.invar(u"is_mvi"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 160)),
            (u"IN2", n.block(u"AND", [(u"IN1", n.invar(u"is_alu")),
                                      (u"IN2", n.invar(u"notcmp"))],
                             [u"OUT"], fbd_xml.COL_BLK2 + 280))],
            [u"OUT"], fbd_xml.COL_BLK2 + 400)),
        (u"IN2", n.invar(u"run"))], [u"OUT"], fbd_xml.COL_BLK2 + 520))
    n.outvar(u"wrval", n.block(u"SEL", [(u"G", n.invar(u"is_alu")), (u"IN0", n.invar(u"bval")),
                                        (u"IN1", n.invar(u"alu_r"))],
                               [u"OUT"], fbd_xml.COL_BLK2 + 660))

    n = p.network(u"СЕТЬ 11 (ФАЗА 7). Запись в регистр-приёмник по коду C_Dst")
    dst = n.invar(u"GVL_CPU.C_Dst")
    wen = n.invar(u"wr_en")
    for code, name in ((0, u"ldb"), (1, u"ldc"), (2, u"ldd"), (3, u"lde"),
                       (4, u"ldh"), (5, u"ldl"), (7, u"lda")):
        eq = n.block(u"EQ", [(u"IN1", dst), (u"IN2", n.invar(u"BYTE#%d" % code))], [u"OUT"])
        n.outvar(name, n.block(u"AND", [(u"IN1", eq), (u"IN2", wen)], [u"OUT"],
                               fbd_xml.COL_BLK2))
    n.block(u"FB_RegFile", [
        (u"Data", n.invar(u"wrval")),
        (u"LD_B", n.invar(u"ldb")), (u"LD_C", n.invar(u"ldc")), (u"LD_D", n.invar(u"ldd")),
        (u"LD_E", n.invar(u"lde")), (u"LD_H", n.invar(u"ldh")), (u"LD_L", n.invar(u"ldl")),
        (u"LD_A", n.invar(u"lda")),
    ], [u"A", u"B", u"C", u"D", u"E", u"H", u"L"], instance=u"regs")

    n = p.network(u"СЕТЬ 12 (ФАЗА 7). Флаги обновляются только АЛУ-командами")
    n.block(u"FB_FlagsReg", [
        (u"S_In", n.invar(u"alu_s")), (u"Z_In", n.invar(u"alu_z")),
        (u"AC_In", n.invar(u"alu_ac")), (u"P_In", n.invar(u"alu_p")),
        (u"CY_In", n.invar(u"alu_cy")),
        (u"LD", n.block(u"AND", [(u"IN1", n.invar(u"is_alu")), (u"IN2", n.invar(u"run"))],
                        [u"OUT"], fbd_xml.COL_BLK + 220)),
        (u"PSW_In", n.invar(u"BYTE#0")), (u"LD_PSW", n.invar(u"FALSE")),
    ], [u"S", u"Z", u"AC", u"P", u"CY", u"PSW"], instance=u"flags")

    # ==================================================================
    # ФАЗА 8. СЛЕДУЮЩИЙ PC, ПАМЯТЬ, ОСТАНОВ
    # ==================================================================
    n = p.network(u"СЕТЬ 13 (ФАЗА 8). Адрес перехода и адрес следующей команды")
    n.outvar(u"ophi_w", n.invar(u"op_hi"))        # BYTE -> WORD
    n.outvar(u"oplo_w", n.invar(u"op_lo"))
    sh = n.block(u"SHL", [(u"IN1", n.invar(u"ophi_w")), (u"IN2", n.invar(u"WORD#8"))], [u"OUT"])
    n.outvar(u"target", n.block(u"OR", [(u"IN1", sh), (u"IN2", n.invar(u"oplo_w"))],
                                [u"OUT"], fbd_xml.COL_BLK2))
    ct = n.block(u"FB_CtrlUnit", [
        (u"Cond", n.invar(u"GVL_CPU.C_Cond")),
        (u"S", n.invar(u"flags.S")), (u"Z", n.invar(u"flags.Z")),
        (u"P", n.invar(u"flags.P")), (u"CY", n.invar(u"flags.CY")),
        (u"Uncond", n.invar(u"GVL_CPU.C_Uncond")),
        (u"PC", n.invar(u"pcv")), (u"Target", n.invar(u"target")),
        (u"Len", n.invar(u"GVL_CPU.C_Len")),
    ], [u"CondMet", u"Take", u"PC_Next"], instance=u"ctrl", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"pcnext", ct.out(u"PC_Next"))
    n.block(u"FB_Reg16", [(u"D", n.invar(u"pcnext")), (u"LD", n.invar(u"run")),
                          (u"CLR", n.invar(u"FALSE"))], [u"Q"], instance=u"pc",
            x=fbd_xml.COL_BLK2 + 440)
    n.block(u"FB_Reg16", [(u"D", n.invar(u"spv")), (u"LD", n.invar(u"FALSE")),
                          (u"CLR", n.invar(u"FALSE"))], [u"Q"], instance=u"sp",
            x=fbd_xml.COL_BLK2 + 440)

    n = p.network(u"СЕТЬ 14 (ФАЗА 8). Запись в память, останов HLT, счётчик тактов")
    dstm = n.block(u"EQ", [(u"IN1", n.invar(u"GVL_CPU.C_Dst")), (u"IN2", n.invar(u"BYTE#6"))],
                   [u"OUT"])
    n.outvar(u"is_dstm", dstm)
    n.outvar(u"GVL_CPU.Bus_Data", n.invar(u"wrval"))
    wrbit = n.block(u"AND", [(u"IN1", n.block(u"AND", [(u"IN1", n.invar(u"is_mov")),
                                                       (u"IN2", n.invar(u"is_dstm"))],
                                              [u"OUT"], fbd_xml.COL_BLK + 220)),
                             (u"IN2", n.invar(u"run"))], [u"OUT"], fbd_xml.COL_BLK + 360)
    n.block(u"FB_Memory64K", [(u"Addr", n.invar(u"hl")), (u"Wr", wrbit),
                              (u"DataIn", n.invar(u"wrval"))],
            [u"DataOut"], instance=u"m_wr", x=fbd_xml.COL_BLK + 500)
    hlt_cls = n.block(u"EQ", [(u"IN1", n.invar(u"GVL_CPU.C_Class")),
                              (u"IN2", n.invar(u"BYTE#9"))], [u"OUT"],
                      x=fbd_xml.COL_BLK + 640)
    n.outvar(u"halt_now", n.block(u"AND", [(u"IN1", hlt_cls), (u"IN2", n.invar(u"run"))],
                                  [u"OUT"], x=fbd_xml.COL_BLK + 780))
    n.outvar(u"halted_l", n.block(u"SEL", [(u"G", n.invar(u"halt_now")),
                                           (u"IN0", n.invar(u"GVL_CPU.Halted")),
                                           (u"IN1", n.invar(u"TRUE"))],
                                  [u"OUT"], x=fbd_xml.COL_BLK + 920))
    n.outvar(u"GVL_CPU.Halted", n.invar(u"halted_l"))
    n.outvar(u"Halted", n.invar(u"halted_l"))
    inc = n.block(u"ADD", [(u"IN1", n.invar(u"GVL_CPU.Step_Cnt")), (u"IN2", n.invar(u"WORD#1"))],
                  [u"OUT"])
    nxt = n.block(u"SEL", [(u"G", n.invar(u"run")), (u"IN0", n.invar(u"GVL_CPU.Step_Cnt")),
                           (u"IN1", inc)], [u"OUT"], fbd_xml.COL_BLK2)
    n.outvar(u"GVL_CPU.Step_Cnt", nxt)
    n.outvar(u"Step", nxt)
    return p


def make_plc_prg():
    p = Pou(u"PLC_PRG", u"program",
            doc=u"Главная программа проекта: инициализация памяти при старте и вызов\n"
                u"\tпроцессора. Один скан PLC = один такт процессора.")
    p.var(u"cpu", u"FB_CPU8080", u"экземпляр процессора")
    p.var(u"init_done", u"BOOL", u"память инициализирована")
    p.var(u"i", u"WORD", u"счётчик инициализации")

    n = p.network(u"СЕТЬ 1. Программа теста: LDA 0100h; MOV B,A; LDA 0101h; ADD B; "
                  u"STA 0102h; HLT - загрузка в память при старте")
    # Байты программы кладём в память обычными присваиваниями по фиксированным адресам.
    prog = [(u"WORD#16#0000", u"BYTE#16#3A"),   # LDA 0100h
            (u"WORD#16#0001", u"BYTE#16#00"),
            (u"WORD#16#0002", u"BYTE#16#01"),
            (u"WORD#16#0003", u"BYTE#16#47"),   # MOV B,A
            (u"WORD#16#0004", u"BYTE#16#3A"),   # LDA 0101h
            (u"WORD#16#0005", u"BYTE#16#01"),
            (u"WORD#16#0006", u"BYTE#16#01"),
            (u"WORD#16#0007", u"BYTE#16#80"),   # ADD B
            (u"WORD#16#0008", u"BYTE#16#32"),   # STA 0102h
            (u"WORD#16#0009", u"BYTE#16#02"),
            (u"WORD#16#000A", u"BYTE#16#01"),
            (u"WORD#16#000B", u"BYTE#16#76"),   # HLT
            (u"WORD#16#0100", u"BYTE#16#25"),   # слагаемое 1
            (u"WORD#16#0101", u"BYTE#16#17")]   # слагаемое 2
    notdone = n.block(u"NOT", [(u"IN", n.invar(u"init_done"))], [u"OUT"])
    for addr, val in prog:
        n.outvar(u"GVL_MEM.Memory[%s]" % addr,
                 n.block(u"SEL", [(u"G", notdone), (u"IN0", n.invar(u"GVL_MEM.Memory[%s]" % addr)),
                                  (u"IN1", n.invar(val))], [u"OUT"],
                         x=fbd_xml.COL_BLK))
    n.outvar(u"init_done", n.invar(u"TRUE"))

    n = p.network(u"СЕТЬ 2. Вызов процессора: один такт за скан")
    n.block(u"FB_CPU8080", [(u"Enable", n.invar(u"GVL_CPU.Enable"))],
            [u"Halted", u"Step"], instance=u"cpu")
    return p
