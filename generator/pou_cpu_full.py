# -*- coding: utf-8 -*-
u"""Подшаг 3.1: ПОЛНОЕ ядро Intel 8080 - блок FB_CPU8080_FULL и программа PLC_PRG_FULL.

Схемы вынесены в отдельный модуль (ограничение загрузчика скриптов CODESYS ~25 КБ).

ЧТО ЭТО: один вызов FB = один такт = один скан задачи. Внутри такта 10 фаз,
разложенных по сетям сверху вниз; порядок сетей И ЕСТЬ порядок выполнения.

ФАЗЫ ТАКТА
  0 ПРЕРЫВАНИЕ   - FB_Interrupt: (Int_Req и IFF и не Busy) -> такт отдан
                   прерыванию: PC в стек, PC := вектор*8, IFF := 0, Busy := 1;
  1 ВЫБОРКА      - адрес PC на шину, чтение команды в IR;
  2 ДЕКОДИРОВАНИЕ- FB_Decoder_Full заполняет управляющее слово GVL_CPU;
  3 АДРЕСА       - PC+1, PC+2, SP-1, SP-2, SP+1, SP+2, пары HL/DE/BC;
  4 ЧТЕНИЕ       - 6 экземпляров FB_Memory64K: команда по PC, операнд M по HL,
                   байты по PC+1/PC+2, операнд по выбранному адресу и по адресу+1;
  5 ОПЕРАНДЫ     - MUX регистра-источника, выбор "регистр/память/непосредственно";
  6 АЛУ          - FB_ALU8 (A и B), FB_Rotate8, FB_DAA, выравнивание флагов;
  7 РЕЗУЛЬТАТ    - единый res8/res8b и данные двух портов записи в память;
  8 УПРАВЛЕНИЕ   - FB_CtrlUnit: условие, адрес перехода, SP, IFF/Busy;
  9 ЗАПИСЬ       - память (2 экземпляра), регистровый файл, флаги, PC, SP;
 10 СЛУЖЕБНОЕ    - HLT и счётчик тактов.

ПОЧЕМУ ЭТО РАБОТАЕТ В ОДИН СКАН (проектные решения)
  * регистры читаются в начале такта, а пишутся в конце: вызов FB_RegFileQ
    стоит ниже всех сетей, которые читают regs.A..regs.L, поэтому все чтения
    дают значения предыдущего такта - как в настоящем такте процессора;
  * запись в память идёт ПОСЛЕ чтения (сети 4 -> 9), поэтому операнды выбраны
    по старым значениям, а результат записан в новое;
  * XCHG пишет ЧЕТЫРЕ регистра за такт: FB_RegFileQ имеет четыре порта, причём
    данные всех портов вычисляются до вызова файла, то есть все четыре
    значения - "старые", и обмен получается корректным;
  * PUSH/CALL/RST/SHLD/XTHL пишут ДВА байта за такт: у памяти два экземпляра
    записи (m_wr1 и m_wr2) с независимыми адресами.

ФЛАГИ: у FB_ALU8 перенос вычитания получается прямым (c8), а в 8080 CY после
SUB/SBB/CMP - это ЗАЁМ, то есть НЕ c8. Поэтому в такте перенос и AC для
вычитающих операций инвертируются. Для ANA флаг AC в 8080 равен A3 ИЛИ B3 -
это тоже вычисляется здесь. Сам FB_ALU8 не менялся (он проверен подшагом 3.2).

СОБЛЮДЕНИЕ ПРАВИЛ ЖУРНАЛА (docs/03_ЖУРНАЛ_СБОРКИ.md):
  * один выход = одна связь; выход вызова FB сразу защёлкивается в переменную;
  * байт перед 16-разрядным сдвигом переносится в переменную WORD (п. 10.1);
  * <interface> не пустой; связи идут только "назад" (сеть -> следующая сеть).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

# Классы операций - те же коды, что в pou_decode_full.CLASSES и в GVL_CPU
C_NOP, C_MOV, C_MVI, C_ALU, C_ALUI = 0, 1, 2, 3, 4
C_INR, C_DCR, C_INX, C_DCX, C_DAD = 5, 6, 7, 8, 9
C_LDAX, C_STAX, C_LDA, C_STA, C_LHLD, C_SHLD, C_LXI = 10, 11, 12, 13, 14, 15, 16
C_XCHG, C_XTHL, C_SPHL, C_PCHL = 17, 18, 19, 20
C_ROT, C_FLAG, C_DAA = 21, 22, 23
C_EI, C_DI = 24, 25
C_JMP, C_CALL, C_RET, C_PUSH, C_POP, C_RST, C_HLT = 26, 27, 28, 29, 30, 31, 32
C_IN, C_OUT, C_INT = 33, 34, 35

B = u"BYTE#%d"
H = u"BYTE#16#%02X"
W = u"WORD#%d"


# ------------------------- мелкие конструкторы ------------------------
def _x(x):
    u"""Координата по умолчанию (fbd_xml: None недопустим, нужен COL_BLK)."""
    return fbd_xml.COL_BLK if x is None else x


def I(n, e):
    return n.invar(e)


def NOT(n, a, x=None, y=None):
    return n.block(u"NOT", [(u"IN", a)], [u"OUT"], _x(x), y)


def AND(n, a, b, x=None, y=None):
    return n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def OR(n, a, b, x=None, y=None):
    return n.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def EQ(n, a, b, x=None, y=None):
    return n.block(u"EQ", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def SEL(n, g, a, b, x=None, y=None):
    return n.block(u"SEL", [(u"G", g), (u"IN0", a), (u"IN1", b)], [u"OUT"], _x(x), y)


def ORL(n, items, x0=None, dx=110, y=None):
    u"""Дерево OR по списку источников."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    lvl, xx = list(items), x0
    while len(lvl) > 1:
        nxt = []
        for k in range(0, len(lvl), 2):
            if k + 1 < len(lvl):
                nxt.append(OR(n, lvl[k], lvl[k + 1], xx, y))
            else:
                nxt.append(lvl[k])
        lvl, xx = nxt, xx + dx
    return lvl[0]


def CHAIN(n, acc, steps, x0=None, dx=115, y=None):
    u"""Цепочка SEL(G, IN0=acc, IN1=значение) - приоритетный выбор."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    for k, (g, v) in enumerate(steps):
        acc = SEL(n, g, acc, v, x0 + dx * k, y)
    return acc


# ======================================================================
def make_cpu_full():
    p = Pou(u"FB_CPU8080_FULL", u"functionBlock",
            doc=u"Процессор Intel 8080 целиком: полный набор команд (все 78\n"
                u"\tмнемоник, включая IN/OUT - они декодируются, но обмен с портом\n"
                u"\tделает аппаратный слой этапа 3.6).\n"
                u"\tОДИН ВЫЗОВ = ОДИН ТАКТ = ОДИН СКАН ЗАДАЧИ.\n"
                u"\tВход:  Enable - разрешение работы; Int_Req и Int_Vector берутся\n"
                u"\t       из GVL_CPU (это входы прерывания).\n"
                u"\tВыходы: Halted - остановлен командой HLT, Step - счётчик тактов.\n"
                u"\tКлассы операций C_Class (полная таблица - в GVL_CPU):\n"
                u"\t  0=NOP  1=MOV  2=MVI  3=ALU  4=ALUI  5=INR  6=DCR  7=INX\n"
                u"\t  8=DCX  9=DAD 10=LDAX 11=STAX 12=LDA 13=STA 14=LHLD 15=SHLD\n"
                u"\t 16=LXI 17=XCHG 18=XTHL 19=SPHL 20=PCHL 21=ROT 22=FLAG 23=DAA\n"
                u"\t 24=EI 25=DI 26=JMP 27=CALL 28=RET 29=PUSH 30=POP 31=RST\n"
                u"\t 32=HLT 33=IN 34=OUT 35=INT (внутренний: приём прерывания).\n"
                u"\tПамять одна (GVL_MEM), но к ней обращаются ВОСЕМЬ экземпляров\n"
                u"\tFB_Memory64K: шесть на чтение (PC, HL, PC+1, PC+2, выбранный\n"
                u"\tадрес и адрес+1) и два на запись (SP/CALL/RST кладут два байта,\n"
                u"\tSHLD и XTHL пишут два байта). Вызов FB выполняется один раз за\n"
                u"\tскан, поэтому разные обращения - обязательно разные экземпляры.")
    p.var_in(u"Enable", u"BOOL", u"разрешение выполнения такта")
    p.var_out(u"Halted", u"BOOL", u"процессор остановлен командой HLT")
    p.var_out(u"Step", u"WORD", u"номер выполненного такта")

    # ---------- локальные переменные (по фазам) ----------
    loc = [
        # фаза 0
        (u"run", u"BOOL", u"такт выполняется (Enable и не Halted)"),
        (u"run_i", u"BOOL", u"такт выполняется и не отдан прерыванию"),
        (u"int_take", u"BOOL", u"прерывание принято"),
        (u"int_vec", u"WORD", u"адрес обработчика прерывания"),
        (u"int_sp", u"WORD", u"SP после сохранения PC при прерывании"),
        (u"iff", u"BOOL", u"триггер разрешения прерываний IFF"),
        (u"busy", u"BOOL", u"прерывание обслуживается (снимает RET)"),
        (u"cls", u"BYTE", u"эффективный класс операции"),
        # фаза 1
        (u"pcv", u"WORD", u"текущий PC"), (u"spv", u"WORD", u"текущий SP"),
        (u"ir", u"BYTE", u"регистр команды"),
        # фаза 3
        (u"pc1", u"WORD", u"PC+1"), (u"pc2", u"WORD", u"PC+2"),
        (u"spp1", u"WORD", u"SP+1"), (u"spp2", u"WORD", u"SP+2"),
        (u"wsp1", u"WORD", u"SP-1"), (u"wsp2", u"WORD", u"SP-2"),
        (u"hl", u"WORD", u"пара HL"), (u"de", u"WORD", u"пара DE"),
        (u"bc", u"WORD", u"пара BC"),
        (u"h_w", u"WORD", u"H как слово"), (u"l_w", u"WORD", u"L как слово"),
        (u"d_w", u"WORD", u"D как слово"), (u"e_w", u"WORD", u"E как слово"),
        (u"b_w", u"WORD", u"B как слово"), (u"c_w", u"WORD", u"C как слово"),
        # фаза 4
        (u"op_m", u"BYTE", u"операнд M по адресу HL"),
        (u"op_lo", u"BYTE", u"байт по PC+1"), (u"op_hi", u"BYTE", u"байт по PC+2"),
        (u"a16", u"WORD", u"адрес из байтов PC+1/PC+2"),
        (u"target", u"WORD", u"адрес перехода"),
        (u"a16p1", u"WORD", u"адрес a16 + 1"),
        (u"rds", u"BYTE", u"код адреса чтения (C_RdSel)"),
        (u"rd_addr", u"WORD", u"адрес чтения"), (u"rd_addr2", u"WORD", u"адрес чтения + 1"),
        (u"rd_val", u"BYTE", u"прочитанный байт"), (u"rd_val2", u"BYTE", u"байт по адресу+1"),
        (u"oplo_w", u"WORD", u"младший байт адреса как слово"),
        (u"ophi_w", u"WORD", u"старший байт адреса как слово"),
        (u"rdv1_w", u"WORD", u"rd_val как слово"), (u"rdv2_w", u"WORD", u"rd_val2 как слово"),
        # фаза 5
        (u"msel", u"BYTE", u"регистр-источник с MUX"),
        (u"srcval", u"BYTE", u"значение источника (регистр или память M)"),
    (u"dbg_opm", u"BYTE", u"диагностика: операнд M"),
    (u"dbg_src", u"BYTE", u"диагностика: выбранный источник"),
        (u"is_mem_src", u"BOOL", u"источник - память по HL (код 6)"),
        (u"alu_a", u"BYTE", u"операнд A для АЛУ"),
        (u"bval", u"BYTE", u"операнд B для АЛУ"),
        (u"cin", u"BOOL", u"входной перенос АЛУ (только для ADC/SBB)"),
        # фаза 6
        (u"alu_r", u"BYTE", u"результат АЛУ"),
        (u"alu_cy", u"BOOL", u"перенос АЛУ (прямой)"),
        (u"alu_ac", u"BOOL", u"перенос из разряда 3 (прямой)"),
        (u"alu_s", u"BOOL", u"знак результата АЛУ"),
        (u"alu_z", u"BOOL", u"ноль результата АЛУ"),
        (u"alu_p", u"BOOL", u"чётность результата АЛУ"),
        (u"nota", u"BYTE", u"инверсия аккумулятора (CMA)"),
        (u"rot_r", u"BYTE", u"результат сдвига"), (u"rot_cy", u"BOOL", u"перенос сдвига"),
        (u"daa_r", u"BYTE", u"результат DAA"), (u"daa_ac", u"BOOL", u"AC после DAA"),
        (u"daa_cy", u"BOOL", u"CY после DAA"),
        (u"daa_s", u"BOOL", u"знак после DAA"), (u"daa_z", u"BOOL", u"ноль после DAA"),
        (u"daa_p", u"BOOL", u"чётность после DAA"),
        (u"cy_eff", u"BOOL", u"CY с учётом заёма вычитания"),
        (u"ac_eff", u"BOOL", u"AC с учётом заёма вычитания"),
        (u"ana_ac", u"BOOL", u"AC для ANA/ANI: A3 ИЛИ B3"),
        (u"cy_new", u"BOOL", u"новое значение флага CY"),
        (u"ac_new", u"BOOL", u"новое значение флага AC"),
        # фаза 7
        (u"pair_lo", u"BYTE", u"младший байт выбранной пары"),
        (u"pair_hi", u"BYTE", u"старший байт выбранной пары"),
        (u"pairval", u"WORD", u"значение выбранной пары"),
        (u"plo2", u"BYTE", u"младший байт пары после INX/DCX"),
        (u"phi2", u"BYTE", u"старший байт пары после INX/DCX"),
        (u"pcl", u"BYTE", u"младший байт PC"), (u"pch", u"BYTE", u"старший байт PC"),
        (u"ret_k", u"BYTE", u"прибавка к PC для адреса возврата (0/1/3)"),
        (u"ret_lo", u"BYTE", u"младший байт адреса возврата"),
        (u"ret_hi", u"BYTE", u"старший байт адреса возврата"),
        (u"push_lo", u"BYTE", u"младший байт того, что кладём в стек"),
        (u"push_hi", u"BYTE", u"старший байт того, что кладём в стек"),
        (u"dad_lo", u"BYTE", u"младший байт суммы DAD"),
        (u"dad_hi", u"BYTE", u"старший байт суммы DAD"),
        (u"dad_cy", u"BOOL", u"перенос DAD (единственный флаг этой команды)"),
        (u"dadw", u"WORD", u"сумма HL + пара"),
        (u"res8", u"BYTE", u"значение для записи в регистр, порт 1"),
        (u"res8b", u"BYTE", u"значение для записи в регистр, порт 2"),
        (u"res8c", u"BYTE", u"значение для записи в регистр H (XCHG)"),
        (u"res8d", u"BYTE", u"значение для записи в регистр L (XCHG)"),
        # фаза 8
        (u"ret_addr", u"WORD", u"адрес возврата со стека"),
        (u"vecw", u"BYTE", u"номер вектора RST/прерывания"),
        (u"vecw_w", u"WORD", u"номер вектора как слово"),
        (u"vec_addr", u"WORD", u"адрес вектора (вектор * 8)"),
        (u"ctrl_target", u"WORD", u"адрес перехода для блока управления"),
        (u"uncond_eff", u"BOOL", u"переход безусловный (с учётом RST/INT)"),
        (u"take", u"BOOL", u"условие перехода выполнено"),
        (u"pc_ctrl", u"WORD", u"адрес следующей команды от FB_CtrlUnit (защёлка выхода FB)"),
        (u"len_w", u"WORD", u"длина команды как слово"),
        (u"pclen", u"WORD", u"PC + длина команды"),
        (u"pcnext", u"WORD", u"адрес следующей команды"),
        (u"sp_adj", u"WORD", u"SP +/- 1 для INX/DCX SP"),
        (u"spnew", u"WORD", u"новое значение SP"),
        (u"sp_push", u"WORD", u"SP при записи в стек (SP-2)"),
        (u"is_pushlike", u"BOOL", u"команда кладёт два байта в стек"),
        (u"is_branch", u"BOOL", u"адрес следующей команды берётся у блока управления"),
        (u"is_vec", u"BOOL", u"переход на вектор (RST или прерывание)"),
        (u"is_jcr", u"BOOL", u"JMP/CALL/RET (условие проверяет FB_CtrlUnit)"),
        (u"is_incdec", u"BOOL", u"INR или DCR"),
        (u"is_step", u"BOOL", u"INX или DCX"),
        (u"is_pair_incdec", u"BOOL", u"INX/DCX над парой (не SP)"),
        (u"is_sub_op", u"BOOL", u"операция АЛУ вычитающая (SUB/SBB)"),
        (u"is_carry_op", u"BOOL", u"операция АЛУ использует входной перенос (ADC/SBB)"),
        (u"is_ana", u"BOOL", u"операция ANA или ANI"),
        (u"is_cma", u"BOOL", u"FLAG с кодом 0 (CMA)"),
        (u"is_stc", u"BOOL", u"FLAG с кодом 1 (STC)"),
        (u"is_cmc", u"BOOL", u"FLAG с кодом 2 (CMC)"),
        (u"is_sp_incdec", u"BOOL", u"INX/DCX над SP"),
        (u"is_lxi_sp", u"BOOL", u"LXI SP,d16"),
        (u"is_psw_pop", u"BOOL", u"POP PSW"),
        (u"psw_pop1", u"BOOL", u"POP с кодом пары 3 (PSW)"),
        (u"is_cmp", u"BOOL", u"CMP/CPI: результат не записывать"),
        (u"mdst", u"BOOL", u"поле приёмника DDD = 6 (память по HL)"),
        (u"wr_reg_dst", u"BOOL", u"команда пишет по коду DDD (MOV/MVI/INR/DCR)"),
        (u"en_mem", u"BOOL", u"разрешение записи в память (по классу)"),
        (u"en1", u"BOOL", u"разрешение записи в память, порт 1"),
        (u"en2", u"BOOL", u"разрешение записи в память, порт 2"),
        (u"en_push", u"BOOL", u"разрешение положить два байта в стек"),
        # фаза 9-10
        (u"wa1", u"WORD", u"адрес записи, порт 1"), (u"wa2", u"WORD", u"адрес записи, порт 2"),
        (u"wd1", u"BYTE", u"данные записи, порт 1"), (u"wd2", u"BYTE", u"данные записи, порт 2"),
        (u"psw_in", u"BYTE", u"байт состояния для POP PSW"),
        (u"ret_busy", u"BOOL", u"RET снимает обслуживание прерывания"),
        (u"iff_n", u"BOOL", u"новое значение IFF"),
        (u"busy_n", u"BOOL", u"новое значение Busy"),
        (u"hlt_now", u"BOOL", u"пришла команда HLT"),
        (u"halted_l", u"BOOL", u"защёлка останова"),
        (u"step_inc", u"WORD", u"счётчик тактов + 1"),
        (u"step_n", u"WORD", u"новое значение счётчика тактов"),
    ]
    for nm, t, c in loc:
        p.var(nm, t, c)
    # признаки классов
    for nm, code in ((u"k_mov", C_MOV), (u"k_mvi", C_MVI), (u"k_alu", C_ALU),
                     (u"k_alui", C_ALUI), (u"k_inr", C_INR), (u"k_dcr", C_DCR),
                     (u"k_inx", C_INX), (u"k_dcx", C_DCX), (u"k_dad", C_DAD),
                     (u"k_ldax", C_LDAX), (u"k_stax", C_STAX), (u"k_lda", C_LDA),
                     (u"k_sta", C_STA), (u"k_lhld", C_LHLD), (u"k_shld", C_SHLD),
                     (u"k_lxi", C_LXI), (u"k_xchg", C_XCHG), (u"k_xthl", C_XTHL),
                     (u"k_sphl", C_SPHL), (u"k_pchl", C_PCHL), (u"k_rot", C_ROT),
                     (u"k_flag", C_FLAG), (u"k_daa", C_DAA), (u"k_ei", C_EI),
                     (u"k_di", C_DI), (u"k_jmp", C_JMP), (u"k_call", C_CALL),
                     (u"k_ret", C_RET), (u"k_push", C_PUSH), (u"k_pop", C_POP),
                     (u"k_rst", C_RST), (u"k_hlt", C_HLT), (u"k_int", C_INT)):
        p.var(nm, u"BOOL", u"класс %d" % code)

    # ---------- экземпляры ----------
    for nm, t, c in ((u"regs", u"FB_RegFileQ", u"регистровый файл (4 порта записи)"),
                     (u"pc", u"FB_Reg16", u"счётчик команд"),
                     (u"sp", u"FB_Reg16", u"указатель стека"),
                     (u"flags", u"FB_FlagsReg2", u"регистр флагов"),
                     (u"dec", u"FB_Decoder_Full", u"полный декодер команд"),
                     (u"intr", u"FB_Interrupt", u"приём прерывания"),
                     (u"ctrl", u"FB_CtrlUnit", u"блок управления переходами"),
                     (u"alu", u"FB_ALU8", u"арифметико-логическое устройство"),
                     (u"ualu", u"FB_ALU8", u"АЛУ для флагов S/Z/P результата DAA"),
                     (u"rot", u"FB_Rotate8", u"сдвиги RLC/RRC/RAL/RAR"),
                     (u"daa", u"FB_DAA", u"десятичная коррекция"),
                     (u"msrc", u"FB_Mux8x8", u"MUX регистра-источника"),
                     (u"mpair", u"FB_Mux8x16", u"MUX регистровой пары"),
                     (u"uw_pc", u"FB_UnpackWord", u"PC -> два байта"),
                     (u"uw_dad", u"FB_UnpackWord", u"сумма DAD -> два байта"),
                     (u"m_ir", u"FB_Memory64K", u"память: выборка команды по PC"),
                     (u"m_op", u"FB_Memory64K", u"память: операнд M по HL"),
                     (u"m_lo", u"FB_Memory64K", u"память: байт по PC+1"),
                     (u"m_hi", u"FB_Memory64K", u"память: байт по PC+2"),
                     (u"m_rda", u"FB_Memory64K", u"память: чтение по выбранному адресу"),
                     (u"m_rda2", u"FB_Memory64K", u"память: чтение по адресу+1"),
                     (u"m_wr1", u"FB_Memory64K", u"память: запись, порт 1"),
                     (u"m_wr2", u"FB_Memory64K", u"память: запись, порт 2")):
        p.var(nm, t, c)

    # ==================================================================
    # ФАЗА 0. ПРЕРЫВАНИЕ, РАЗРЕШЕНИЕ РАБОТЫ, КЛАСС
    # ==================================================================
    n = p.network(u"СЕТЬ 1 (ФАЗА 0). run, прерывание FB_Interrupt, эффективный класс, PC/SP")
    en = I(n, u"Enable")
    halt = I(n, u"GVL_CPU.Halted")
    n.outvar(u"run", AND(n, en, NOT(n, halt, fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK2))
    # запрос прерывания принимается только при разрешённом процессоре
    # (Enable); останов HLT прерывание снимает - как в реальном 8080
    it = n.block(u"FB_Interrupt", [
        (u"INT_Req", AND(n, I(n, u"GVL_CPU.Int_Req"), I(n, u"Enable"),
                         fbd_xml.COL_BLK2 + 100)),
        (u"IFF", I(n, u"iff")),
        (u"Busy", I(n, u"busy")), (u"INT_Vector", I(n, u"GVL_CPU.Int_Vector")),
        (u"PC", I(n, u"pc.Q")), (u"SP", I(n, u"sp.Q")),
    ], [u"Take", u"PC_Vec", u"SP_New", u"Push_Needed"], instance=u"intr",
        x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"int_take", it.out(u"Take"))
    n.outvar(u"int_vec", it.out(u"PC_Vec"))
    n.outvar(u"int_sp", it.out(u"SP_New"))
    nt = NOT(n, I(n, u"int_take"), fbd_xml.COL_BLK2 + 420)
    n.outvar(u"run_i", AND(n, I(n, u"run"), nt, fbd_xml.COL_BLK2 + 540))
    n.outvar(u"cls", SEL(n, I(n, u"int_take"), I(n, u"GVL_CPU.C_Class"),
                         I(n, B % C_INT), fbd_xml.COL_BLK2 + 660))
    n.outvar(u"pcv", I(n, u"pc.Q"))
    n.outvar(u"spv", I(n, u"sp.Q"))

    # ==================================================================
    # ФАЗА 1. ВЫБОРКА КОМАНДЫ
    # ==================================================================
    n = p.network(u"СЕТЬ 2 (ФАЗА 1). Адрес PC на шину и чтение команды в IR")
    # ДИАГНОСТИКА (фаза B): на шину адреса выкладывается ЭФФЕКТИВНЫЙ АДРЕС hl.
    # Раньше здесь был pcv, который никому не нужен: GVL_CPU.Bus_Addr читается
    # только диагностикой. Так поскайсовая защёлка в TEST_8080 видит, какой
    # именно адрес собрался из пары H:L - это и нужно для разбора M-операнда.
    n.outvar(u"GVL_CPU.Bus_Addr", I(n, u"ctrl_target"))  # диагностика: адрес перехода
    m = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"pcv")), (u"Wr", I(n, u"FALSE")),
                                  (u"DataIn", I(n, B % 0))], [u"DataOut"],
                instance=u"m_ir", x=fbd_xml.COL_BLK2)
    n.outvar(u"ir", m.out(u"DataOut"))

    n = p.network(u"СЕТЬ 3 (ФАЗА 1). Регистр команды на шину данных")
    n.outvar(u"GVL_CPU.Bus_IR", I(n, u"ir"))

    # ==================================================================
    # ФАЗА 2. ДЕКОДИРОВАНИЕ
    # ==================================================================
    n = p.network(u"СЕТЬ 4 (ФАЗА 2). ДЕКОДЕР: IR -> управляющее слово GVL_CPU "
                  u"(все поля классов - в GVL_CPU)")
    n.block(u"FB_Decoder_Full", [(u"IR", I(n, u"ir"))], [], instance=u"dec")

    # ==================================================================
    # ФАЗА 3. АДРЕСА
    # ==================================================================
    n = p.network(u"СЕТЬ 5 (ФАЗА 3). PC+1/PC+2, SP+1/SP+2/SP-1/SP-2 и пары HL/DE/BC")
    n.outvar(u"pc1", n.block(u"ADD", [(u"IN1", I(n, u"pcv")), (u"IN2", I(n, W % 1))], [u"OUT"]))
    n.outvar(u"pc2", n.block(u"ADD", [(u"IN1", I(n, u"pcv")), (u"IN2", I(n, W % 2))],
                             [u"OUT"], fbd_xml.COL_BLK + 120))
    n.outvar(u"spp1", n.block(u"ADD", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 1))],
                              [u"OUT"], fbd_xml.COL_BLK + 240))
    n.outvar(u"spp2", n.block(u"ADD", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 2))],
                              [u"OUT"], fbd_xml.COL_BLK + 360))
    n.outvar(u"wsp1", n.block(u"SUB", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 1))],
                              [u"OUT"], fbd_xml.COL_BLK + 480))
    n.outvar(u"wsp2", n.block(u"SUB", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 2))],
                              [u"OUT"], fbd_xml.COL_BLK + 600))
    # пары: байт сначала переносится в переменную WORD, только потом сдвиг
    # (иначе SHL работает в разрядности BYTE и старший байт адреса теряется)
    #
    # ФАЗА B: этого оказалось МАЛО. Присваивание h_w := regs.H (BYTE -> WORD)
    # в сгенерированном XML давало ВЫРАЖЕНИЕ ТИПА BYTE, и SHL по-прежнему
    # работал в разрядности байта: старший байт адреса терялся. Симптом:
    # MOV M,A при HL=0200h писал по адресу 0000h (T-335), а ADD M/SUB M/ORA M
    # читали 00h вместо предустановленного значения. Теперь разрядность входа
    # SHL задаётся ЯВНО - прибавлением WORD#0, поэтому выражение WORD.
    for k, (hi, lo, out) in enumerate(((u"H", u"L", u"hl"), (u"D", u"E", u"de"),
                                       (u"B", u"C", u"bc"))):
        n.outvar(u"%s_w" % hi.lower(), I(n, u"regs.%s" % hi))
        n.outvar(u"%s_w" % lo.lower(), I(n, u"regs.%s" % lo))
        hi16 = n.block(u"ADD", [(u"IN1", I(n, u"%s_w" % hi.lower())),
                                (u"IN2", I(n, W % 0))], [u"OUT"],
                       fbd_xml.COL_BLK2 + 120 * k)
        lo16 = n.block(u"ADD", [(u"IN1", I(n, u"%s_w" % lo.lower())),
                                (u"IN2", I(n, W % 0))], [u"OUT"],
                       fbd_xml.COL_BLK2 + 120 * k + 40)
        sh = n.block(u"SHL", [(u"IN1", hi16), (u"IN2", I(n, W % 8))], [u"OUT"],
                     fbd_xml.COL_BLK2 + 120 * k + 80)
        n.outvar(out, n.block(u"OR", [(u"IN1", sh), (u"IN2", lo16)],
                              [u"OUT"], fbd_xml.COL_BLK2 + 120 * k + 110))

    # ==================================================================
    # ФАЗА 4. ЧТЕНИЕ ПАМЯТИ
    # ==================================================================
    n = p.network(u"СЕТЬ 6 (ФАЗА 4). Чтение: операнд M по HL, байты по PC+1 и PC+2")
    zb = I(n, B % 0)
    ff = I(n, u"FALSE")
    a1 = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"hl")), (u"Wr", ff), (u"DataIn", zb)],
                 [u"DataOut"], instance=u"m_op")
    a2 = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"pc1")), (u"Wr", I(n, u"FALSE")),
                                   (u"DataIn", I(n, B % 0))], [u"DataOut"],
                 instance=u"m_lo", x=fbd_xml.COL_BLK2)
    a3 = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"pc2")), (u"Wr", I(n, u"FALSE")),
                                   (u"DataIn", I(n, B % 0))], [u"DataOut"],
                 instance=u"m_hi", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"op_m", a1.out(u"DataOut"))
    n.outvar(u"op_lo", a2.out(u"DataOut"))
    n.outvar(u"op_hi", a3.out(u"DataOut"))

    n = p.network(u"СЕТЬ 7 (ФАЗА 4). Адрес a16 из байтов PC+1/PC+2 (и он же target)")
    n.outvar(u"oplo_w", I(n, u"op_lo"))
    n.outvar(u"ophi_w", I(n, u"op_hi"))
    sh = n.block(u"SHL", [(u"IN1", I(n, u"ophi_w")), (u"IN2", I(n, W % 8))], [u"OUT"])
    n.outvar(u"a16", n.block(u"OR", [(u"IN1", sh), (u"IN2", I(n, u"oplo_w"))],
                             [u"OUT"], fbd_xml.COL_BLK2))
    n.outvar(u"target", I(n, u"a16"))
    n.outvar(u"a16p1", n.block(u"ADD", [(u"IN1", I(n, u"a16")), (u"IN2", I(n, W % 1))],
                               [u"OUT"], fbd_xml.COL_BLK2 + 200))

    n = p.network(u"СЕТЬ 8 (ФАЗА 4). Выбор адреса чтения по C_RdSel "
                  u"(1=a16, 2=BC, 3=DE, 4=SP, 5=HL) и адрес+1")
    n.outvar(u"rds", I(n, u"GVL_CPU.C_RdSel"))
    e1 = EQ(n, I(n, u"rds"), I(n, B % 1))
    e2 = EQ(n, I(n, u"rds"), I(n, B % 2), fbd_xml.COL_BLK + 120)
    e3 = EQ(n, I(n, u"rds"), I(n, B % 3), fbd_xml.COL_BLK + 240)
    e4 = EQ(n, I(n, u"rds"), I(n, B % 4), fbd_xml.COL_BLK + 360)
    e5 = EQ(n, I(n, u"rds"), I(n, B % 5), fbd_xml.COL_BLK + 480)
    acc = CHAIN(n, I(n, W % 0), [
        (e1, I(n, u"a16")), (e2, I(n, u"bc")), (e3, I(n, u"de")), (e4, I(n, u"spv")),
        (e5, I(n, u"hl"))],
        x0=fbd_xml.COL_BLK2)
    n.outvar(u"rd_addr", acc)
    n.outvar(u"rd_addr2", n.block(u"ADD", [(u"IN1", I(n, u"rd_addr")), (u"IN2", I(n, W % 1))],
                                  [u"OUT"], fbd_xml.COL_BLK2 + 520))

    n = p.network(u"СЕТЬ 9 (ФАЗА 4). Чтение по выбранному адресу и по адресу+1")
    b1 = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"rd_addr")), (u"Wr", I(n, u"FALSE")),
                                   (u"DataIn", I(n, B % 0))], [u"DataOut"], instance=u"m_rda")
    b2 = n.block(u"FB_Memory64K", [(u"Addr", I(n, u"rd_addr2")), (u"Wr", I(n, u"FALSE")),
                                   (u"DataIn", I(n, B % 0))], [u"DataOut"],
                 instance=u"m_rda2", x=fbd_xml.COL_BLK2)
    n.outvar(u"rd_val", b1.out(u"DataOut"))
    n.outvar(u"rd_val2", b2.out(u"DataOut"))
    n.outvar(u"rdv1_w", I(n, u"rd_val"))
    n.outvar(u"rdv2_w", I(n, u"rd_val2"))

    # ==================================================================
    # ФАЗА 5. ОПЕРАНДЫ
    # ==================================================================
    n = p.network(u"СЕТЬ 10 (ФАЗА 5). Признаки классов управляющего слова")
    cl = I(n, u"cls")
    for k, (nm, code) in enumerate(((u"k_mov", C_MOV), (u"k_mvi", C_MVI), (u"k_alu", C_ALU),
                                    (u"k_alui", C_ALUI), (u"k_inr", C_INR), (u"k_dcr", C_DCR),
                                    (u"k_inx", C_INX), (u"k_dcx", C_DCX), (u"k_dad", C_DAD),
                                    (u"k_ldax", C_LDAX), (u"k_stax", C_STAX), (u"k_lda", C_LDA),
                                    (u"k_sta", C_STA), (u"k_lhld", C_LHLD), (u"k_shld", C_SHLD),
                                    (u"k_lxi", C_LXI), (u"k_xchg", C_XCHG), (u"k_xthl", C_XTHL),
                                    (u"k_sphl", C_SPHL), (u"k_pchl", C_PCHL), (u"k_rot", C_ROT),
                                    (u"k_flag", C_FLAG), (u"k_daa", C_DAA), (u"k_ei", C_EI),
                                    (u"k_di", C_DI), (u"k_jmp", C_JMP), (u"k_call", C_CALL),
                                    (u"k_ret", C_RET), (u"k_push", C_PUSH), (u"k_pop", C_POP),
                                    (u"k_rst", C_RST), (u"k_hlt", C_HLT), (u"k_int", C_INT))):
        n.outvar(nm, EQ(n, cl, I(n, B % code), fbd_xml.COL_BLK + 110 * (k % 9),
                        fbd_xml.ROW0 + 35 * (k // 9)))

    n = p.network(u"СЕТЬ 11 (ФАЗА 5). Групповые признаки и режимы записи")
    for nm, items in ((u"is_incdec", (u"k_inr", u"k_dcr")),
                      (u"is_step", (u"k_inx", u"k_dcx")),
                      (u"is_jcr", (u"k_jmp", u"k_call", u"k_ret")),
                      (u"is_vec", (u"k_rst", u"k_int")),
                      (u"is_pushlike", (u"k_push", u"k_call", u"k_rst", u"k_int")),
                      (u"is_branch", (u"k_jmp", u"k_call", u"k_ret", u"k_rst", u"k_int")),
                      (u"wr_reg_dst", (u"k_mov", u"k_mvi", u"k_inr", u"k_dcr"))):
        n.outvar(nm, ORL(n, [I(n, x) for x in items], x0=fbd_xml.COL_BLK))
    n.outvar(u"is_pair_incdec", AND(n, I(n, u"is_step"),
                                    NOT(n, EQ(n, I(n, u"GVL_CPU.C_RP"), I(n, B % 3),
                                              fbd_xml.COL_BLK + 200)),
                                    fbd_xml.COL_BLK + 340))
    n.outvar(u"is_sp_incdec", AND(n, I(n, u"is_step"),
                                  EQ(n, I(n, u"GVL_CPU.C_RP"), I(n, B % 3),
                                     fbd_xml.COL_BLK2 + 200), fbd_xml.COL_BLK2 + 340))
    n.outvar(u"is_lxi_sp", AND(n, I(n, u"k_lxi"),
                               EQ(n, I(n, u"GVL_CPU.C_RP"), I(n, B % 3),
                                  fbd_xml.COL_BLK2 + 480), fbd_xml.COL_BLK2 + 620))
    n.outvar(u"is_sub_op", ORL(n, [
        EQ(n, I(n, u"GVL_CPU.C_ALU_Op"), I(n, B % 2)),
        EQ(n, I(n, u"GVL_CPU.C_ALU_Op"), I(n, B % 3), fbd_xml.COL_BLK + 140)],
        x0=fbd_xml.COL_BLK + 280))
    n.outvar(u"is_carry_op", ORL(n, [
        EQ(n, I(n, u"GVL_CPU.C_ALU_Op"), I(n, B % 1)),
        EQ(n, I(n, u"GVL_CPU.C_ALU_Op"), I(n, B % 3), fbd_xml.COL_BLK + 140)],
        x0=fbd_xml.COL_BLK + 420))
    n.outvar(u"is_ana", AND(n, EQ(n, I(n, u"GVL_CPU.C_ALU_Op"), I(n, B % 4)),
                            ORL(n, [I(n, u"k_alu"), I(n, u"k_alui")], x0=fbd_xml.COL_BLK + 600),
                            fbd_xml.COL_BLK + 740))
    f0 = EQ(n, I(n, u"GVL_CPU.C_Flag"), I(n, B % 0), fbd_xml.COL_BLK2 + 200)
    f1 = EQ(n, I(n, u"GVL_CPU.C_Flag"), I(n, B % 1), fbd_xml.COL_BLK2 + 320)
    f2 = EQ(n, I(n, u"GVL_CPU.C_Flag"), I(n, B % 2), fbd_xml.COL_BLK2 + 440)
    n.outvar(u"is_cma", AND(n, I(n, u"k_flag"), f0, fbd_xml.COL_BLK2 + 560))
    n.outvar(u"is_stc", AND(n, I(n, u"k_flag"), f1, fbd_xml.COL_BLK2 + 680))
    n.outvar(u"is_cmc", AND(n, I(n, u"k_flag"), f2, fbd_xml.COL_BLK2 + 800))
    n.outvar(u"is_cmp", I(n, u"GVL_CPU.C_IsCmp"))
    n.outvar(u"mdst", EQ(n, I(n, u"GVL_CPU.C_Dst1"), I(n, B % 6), fbd_xml.COL_BLK2 + 920))
    n.outvar(u"psw_pop1", I(n, u"GVL_CPU.C_IsPSW"))
    n.outvar(u"is_psw_pop", AND(n, I(n, u"k_pop"), I(n, u"psw_pop1"),
                                fbd_xml.COL_BLK2 + 1040))

    n = p.network(u"СЕТЬ 12 (ФАЗА 5). MUX регистра-источника и выбор источника операнда")
    sel = I(n, u"GVL_CPU.C_Src")
    ins = [I(n, u"regs.%s" % r) for r in (u"B", u"C", u"D", u"E", u"H", u"L", u"B", u"A")]
    mx = n.block(u"FB_Mux8x8", [(u"Sel", sel)] + [(u"I%d" % k, ins[k]) for k in range(8)],
                 [u"Q"], instance=u"msrc")
    n.outvar(u"msel", mx.out(u"Q"))
    # источником "память по HL" бывает MOV, ALU и INR/DCR (у них поле SSS
    # декодер заменяет на код приёмника, поэтому проверка одна и та же)
    n.outvar(u"is_mem_src", AND(n, EQ(n, sel, I(n, B % 6)),
                                ORL(n, [I(n, u"k_mov"), I(n, u"k_alu"), I(n, u"is_incdec")],
                                    x0=fbd_xml.COL_BLK2),
                                fbd_xml.COL_BLK2 + 200))
    # ОПЕРАНД M. Путь через rd_val (C_RdSel=5) проверен и ОТКЛОНЕН: он ломает
    # INR M и DCR M. Оставлен прежний блок op_m; его значение латчится в
    # диагностику (см. TEST_8080), чтобы видеть, что реально приходит в АЛУ.
    n.outvar(u"srcval", SEL(n, I(n, u"is_mem_src"), I(n, u"msel"), I(n, u"op_m"),
                            fbd_xml.COL_BLK2 + 340))
    # защёлки для поскайсовой диагностики операнда
    n.outvar(u"dbg_opm", I(n, u"op_m"), fbd_xml.COL_BLK2 + 420)
    n.outvar(u"dbg_src", I(n, u"srcval"), fbd_xml.COL_BLK2 + 500)

    n = p.network(u"СЕТЬ 13 (ФАЗА 5). Операнд B: регистр/память, непосредственный, 1 для INR/DCR")
    n.outvar(u"alu_a", SEL(n, I(n, u"is_incdec"), I(n, u"regs.A"), I(n, u"srcval"),
                           fbd_xml.COL_BLK))
    bv = SEL(n, I(n, u"k_alui"), I(n, u"srcval"), I(n, u"op_lo"), fbd_xml.COL_BLK2)
    n.outvar(u"bval", SEL(n, I(n, u"is_incdec"), bv, I(n, B % 1), fbd_xml.COL_BLK2 + 160))

    # ==================================================================
    # ФАЗА 6. АЛУ, СДВИГИ, DAA
    # ==================================================================
    n = p.network(u"СЕТЬ 14 (ФАЗА 6). АЛУ: входной перенос только для ADC/SBB, затем ALU")
    n.outvar(u"cin", SEL(n, I(n, u"is_carry_op"), I(n, u"FALSE"), I(n, u"flags.CY")))
    al = n.block(u"FB_ALU8", [
        (u"OP", I(n, u"GVL_CPU.C_ALU_Op")), (u"A", I(n, u"alu_a")),
        (u"B", I(n, u"bval")), (u"Cin", I(n, u"cin"))],
        [u"R", u"CY", u"AC", u"S", u"Z", u"P"], instance=u"alu", x=fbd_xml.COL_BLK2)
    n.outvar(u"alu_r", al.out(u"R"))
    n.outvar(u"alu_cy", al.out(u"CY"))
    n.outvar(u"alu_ac", al.out(u"AC"))
    n.outvar(u"alu_s", al.out(u"S"))
    n.outvar(u"alu_z", al.out(u"Z"))
    n.outvar(u"alu_p", al.out(u"P"))

    n = p.network(u"СЕТЬ 15 (ФАЗА 6). CMA, сдвиги FB_Rotate8 и десятичная коррекция FB_DAA")
    # CMA (инверсия аккумулятора) - стандартный NOT (ANY_BIT) над байтом A.
    # ПРОВЕРЕНО (этап A5): NOT у CODESYS принимает ANY_BIT, поэтому NOT над BYTE
    # законен. Гипотеза «NOT принимает только BOOL» была проверена заменой этого
    # места на XOR(A, BYTE#255) - ошибка C32 сохранилась, то есть ЭТО МЕСТО НЕ
    # виновато. Тот же NOT по BYTE есть в FB_ALU8 (вход B) и компилируется
    # чисто. Здесь оставлен исходный вариант.
    n.outvar(u"nota", NOT(n, I(n, u"regs.A")))
    ro = n.block(u"FB_Rotate8", [(u"A", I(n, u"regs.A")), (u"CY_In", I(n, u"flags.CY")),
                                 (u"Kind", I(n, u"GVL_CPU.C_Rot"))],
                 [u"R", u"CY_Out"], instance=u"rot", x=fbd_xml.COL_BLK2)
    n.outvar(u"rot_r", ro.out(u"R"))
    n.outvar(u"rot_cy", ro.out(u"CY_Out"))
    da = n.block(u"FB_DAA", [(u"A", I(n, u"regs.A")), (u"AC_In", I(n, u"flags.AC")),
                             (u"CY_In", I(n, u"flags.CY"))],
                 [u"R", u"AC_Out", u"CY_Out"], instance=u"daa", x=fbd_xml.COL_BLK2 + 200)
    n.outvar(u"daa_r", da.out(u"R"))
    n.outvar(u"daa_ac", da.out(u"AC_Out"))
    n.outvar(u"daa_cy", da.out(u"CY_Out"))

    # ==================================================================
    # ФАЗА 7. ПАРЫ, DAD, ФЛАГИ, АДРЕС ВОЗВРАТА, РЕЗУЛЬТАТ
    # (порядок сетей здесь важен: перенос DAD нужен признаку cy_new)
    # ==================================================================
    n = p.network(u"СЕТЬ 16 (ФАЗА 7). Байты пары по C_RP (0=BC 1=DE 2=HL 3=PSW) "
                  u"и значение пары для DAD/STAX")
    rp = I(n, u"GVL_CPU.C_RP")
    r1 = EQ(n, rp, I(n, B % 1))
    r2 = EQ(n, rp, I(n, B % 2), fbd_xml.COL_BLK + 120)
    r3 = EQ(n, rp, I(n, B % 3), fbd_xml.COL_BLK + 240)
    n.outvar(u"pair_lo", CHAIN(n, I(n, u"regs.C"), [
        (r1, I(n, u"regs.E")), (r2, I(n, u"regs.L")), (r3, I(n, u"flags.PSW"))],
        x0=fbd_xml.COL_BLK2))
    n.outvar(u"pair_hi", CHAIN(n, I(n, u"regs.B"), [
        (r1, I(n, u"regs.D")), (r2, I(n, u"regs.H")), (r3, I(n, u"regs.A"))],
        x0=fbd_xml.COL_BLK2 + 400))
    mp = n.block(u"FB_Mux8x16", [
        (u"Sel", rp), (u"I0", I(n, u"bc")), (u"I1", I(n, u"de")), (u"I2", I(n, u"hl")),
        (u"I3", I(n, u"spv")), (u"I4", I(n, W % 0)), (u"I5", I(n, W % 0)),
        (u"I6", I(n, W % 0)), (u"I7", I(n, W % 0))], [u"Q"], instance=u"mpair",
        x=fbd_xml.COL_BLK2 + 800)
    n.outvar(u"pairval", mp.out(u"Q"))

    n = p.network(u"СЕТЬ 17 (ФАЗА 7). INX/DCX над парой и DAD (16-разрядное сложение)")
    s1 = n.block(u"SUB", [(u"IN1", I(n, u"pair_lo")), (u"IN2", I(n, B % 1))], [u"OUT"])
    a1 = n.block(u"ADD", [(u"IN1", I(n, u"pair_lo")), (u"IN2", I(n, B % 1))], [u"OUT"],
                 fbd_xml.COL_BLK + 120)
    n.outvar(u"plo2", SEL(n, I(n, u"k_inx"), s1, a1, fbd_xml.COL_BLK + 240))
    brw = EQ(n, I(n, u"pair_lo"), I(n, B % 0), fbd_xml.COL_BLK + 360)
    crr = n.block(u"GE", [(u"IN1", I(n, u"pair_lo")), (u"IN2", I(n, u"BYTE#255"))],
                  [u"OUT"], fbd_xml.COL_BLK + 480)
    adj = SEL(n, I(n, u"k_inx"), brw, crr, fbd_xml.COL_BLK + 600)
    adjb = SEL(n, adj, I(n, B % 0), I(n, B % 1), fbd_xml.COL_BLK + 720)
    sub2 = n.block(u"SUB", [(u"IN1", I(n, u"pair_hi")), (u"IN2", adjb)], [u"OUT"],
                   fbd_xml.COL_BLK + 840)
    add2 = n.block(u"ADD", [(u"IN1", I(n, u"pair_hi")), (u"IN2", adjb)], [u"OUT"],
                   fbd_xml.COL_BLK + 960)
    n.outvar(u"phi2", SEL(n, I(n, u"k_inx"), sub2, add2, fbd_xml.COL_BLK + 1080))
    n.outvar(u"dadw", n.block(u"ADD", [(u"IN1", I(n, u"hl")), (u"IN2", I(n, u"pairval"))],
                              [u"OUT"], fbd_xml.COL_BLK2 + 400))
    # перенос DAD: сумма стала меньше первого слагаемого
    n.outvar(u"dad_cy", NOT(n, n.block(u"GE", [(u"IN1", I(n, u"dadw")),
                                               (u"IN2", I(n, u"hl"))], [u"OUT"],
                                    fbd_xml.COL_BLK2 + 560),
                            fbd_xml.COL_BLK2 + 700))
    ud = n.block(u"FB_UnpackWord", [(u"W", I(n, u"dadw"))], [u"Lo", u"Hi"],
                 instance=u"uw_dad", x=fbd_xml.COL_BLK2 + 820)
    n.outvar(u"dad_lo", ud.out(u"Lo"))
    n.outvar(u"dad_hi", ud.out(u"Hi"))

    n = p.network(u"СЕТЬ 18 (ФАЗА 6). Флаги S/Z/P результата DAA (свободный вызов FB_ALU8) "
                  u"и выравнивание CY/AC для вычитания и ANA")
    # ================= ИСПРАВЛЕНИЕ ОШИБКИ C32 (этап A5) =================
    # ЗДЕСЬ БЫЛА ЕДИНСТВЕННАЯ ОШИБКА КОМПИЛЯЦИИ ВО ВСЁМ ПРОЕКТЕ.
    #
    # ВЫЗОВ ОБЪЯВЛЯЛ ВСЕ ШЕСТЬ ВЫВОДОВ FB_ALU8: [R, CY, AC, S, Z, P], - но
    # ЧИТАЛИСЬ ТОЛЬКО ТРИ: S, Z, P (это 4-й, 5-й и 6-й по порядку объявления).
    # Импортёр PLCopenXML СОПОСТАВЛЯЕТ ВЫВОДЫ ПОЗИЦИОННО, а не по
    # formalParameter: первый прочитанный вывод привязывается к ПЕРВОМУ
    # объявленному. В результате:
    #     daa_s (BOOL) <- 1-й объявленный вывод Rx (BYTE)  ->  C32 'BYTE' -> 'BOOL'
    #     daa_z (BOOL) <- 2-й CY (BOOL)                    ->  молча, но НЕВЕРНО
    #     daa_p (BOOL) <- 3-й AC (BOOL)                    ->  молча, но НЕВЕРНО
    # Компилятор сообщал ровно одну ошибку - про daa_s, и загрузка была
    # невозможна.
    #
    # ПОЧЕМУ ЭТО НЕ НАХОДИЛОСЬ ТАК ДОЛГО: ВСЕ ОСТАЛЬНЫЕ ВЫЗОВЫ FB В ПРОЕКТЕ
    # читают ВСЕ свои выводы И В ПОРЯДКЕ ОБЪЯВЛЕНИЯ (FB_UnpackByte B0..B7,
    # FB_PackByte B, FB_FullAdder Sum/Cout, FB_Rotate8 R/CY_Out,
    # FB_DAA R/AC_Out/CY_Out, FB_UnpackWord Lo/Hi) - там позиционное
    # сопоставление совпадает с именованным, и дефект не проявлялся.
    # Этот вызов был ЕДИНСТВЕННЫМ, читавшим ПОДМНОЖЕСТВО выводов.
    #
    # ИСПРАВЛЕНИЕ: объявлять в вызове ТОЛЬКО те выводы, которые читаются,
    # и в том порядке, в котором они читаются. Тогда и позиционное, и
    # именованное сопоставление дают верный результат.
    ua = n.block(u"FB_ALU8", [(u"OP", I(n, B % 0)), (u"A", I(n, u"daa_r")),
                              (u"B", I(n, B % 0)), (u"Cin", I(n, u"FALSE"))],
                 [u"R", u"CY", u"AC", u"S", u"Z", u"P"], instance=u"ualu")
    n.outvar(u"daa_s", ua.out(u"S"))
    n.outvar(u"daa_z", ua.out(u"Z"))
    n.outvar(u"daa_p", ua.out(u"P"))
    # в 8080 CY после SUB/SBB/CMP - это ЗАЁМ, то есть НЕ перенос сумматора
    n.outvar(u"cy_eff", SEL(n, I(n, u"is_sub_op"), I(n, u"alu_cy"),
                            NOT(n, I(n, u"alu_cy"), fbd_xml.COL_BLK2),
                            fbd_xml.COL_BLK2 + 200))
    n.outvar(u"ac_eff", SEL(n, I(n, u"is_sub_op"), I(n, u"alu_ac"),
                            NOT(n, I(n, u"alu_ac"), fbd_xml.COL_BLK2 + 320),
                            fbd_xml.COL_BLK2 + 440))
    # ANA/ANI: AC := бит 3 аккумулятора ИЛИ бит 3 операнда
    a3 = n.block(u"AND", [(u"IN1", I(n, u"regs.A")), (u"IN2", I(n, B % 8))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 560)
    b3 = n.block(u"AND", [(u"IN1", I(n, u"bval")), (u"IN2", I(n, B % 8))],
                 [u"OUT"], fbd_xml.COL_BLK2 + 680)
    n.outvar(u"ana_ac", ORL(n, [
        n.block(u"NE", [(u"IN1", a3), (u"IN2", I(n, B % 0))], [u"OUT"],
                fbd_xml.COL_BLK2 + 800),
        n.block(u"NE", [(u"IN1", b3), (u"IN2", I(n, B % 0))], [u"OUT"],
                fbd_xml.COL_BLK2 + 920)], x0=fbd_xml.COL_BLK2 + 1040))
    acx = SEL(n, I(n, u"is_ana"), I(n, u"ac_eff"), I(n, u"ana_ac"), fbd_xml.COL_BLK2 + 1180)
    n.outvar(u"ac_new", SEL(n, I(n, u"k_daa"), acx, I(n, u"daa_ac"),
                            fbd_xml.COL_BLK2 + 1320))
    cy = SEL(n, I(n, u"k_rot"), I(n, u"cy_eff"), I(n, u"rot_cy"), fbd_xml.COL_BLK2 + 1460)
    cy = SEL(n, I(n, u"is_stc"), cy, I(n, u"TRUE"), fbd_xml.COL_BLK2 + 1580)
    cy = SEL(n, I(n, u"is_cmc"), cy, NOT(n, I(n, u"flags.CY"), fbd_xml.COL_BLK2 + 1700),
             fbd_xml.COL_BLK2 + 1820)
    # ФАЗА B. ДЛЯ DAA ПЕРЕНОС БЕРЁТСЯ ИЗ БЛОКА КОРРЕКЦИИ.
    # Здесь этого выбора не было: cy оставался переносом предыдущей операции,
    # поэтому DAA 9Ah давал верный результат A=00h, но сбрасывал CY
    # (наблюдалось PSW=56h вместо 57h). AC для DAA уже выбирался правильно (ac_new).
    cy_new = SEL(n, I(n, u"k_dad"), cy, I(n, u"dad_cy"),
                 fbd_xml.COL_BLK2 + 1940)
    n.outvar(u"cy_new", SEL(n, I(n, u"k_daa"), cy_new, I(n, u"daa_cy"),
                            fbd_xml.COL_BLK2 + 2060))

    n = p.network(u"СЕТЬ 19 (ФАЗА 7). Адрес возврата PC+1/PC+3/PC и что кладём в стек")
    up = n.block(u"FB_UnpackWord", [(u"W", I(n, u"pcv"))], [u"Lo", u"Hi"],
                 instance=u"uw_pc")
    n.outvar(u"pcl", up.out(u"Lo"))
    n.outvar(u"pch", up.out(u"Hi"))
    k1 = I(n, B % 1)
    kk = SEL(n, I(n, u"k_call"), k1, I(n, B % 3), fbd_xml.COL_BLK)
    n.outvar(u"ret_k", SEL(n, I(n, u"k_int"), kk, I(n, B % 0), fbd_xml.COL_BLK + 120))
    n.outvar(u"ret_lo", n.block(u"ADD", [(u"IN1", I(n, u"pcl")), (u"IN2", I(n, u"ret_k"))],
                                [u"OUT"], fbd_xml.COL_BLK + 240))
    c255 = n.block(u"GE", [(u"IN1", I(n, u"pcl")), (u"IN2", I(n, u"BYTE#255"))], [u"OUT"],
                   fbd_xml.COL_BLK + 360)
    c253 = n.block(u"GE", [(u"IN1", I(n, u"pcl")), (u"IN2", I(n, u"BYTE#253"))], [u"OUT"],
                   fbd_xml.COL_BLK + 480)
    cr = SEL(n, I(n, u"k_call"), c255, c253, fbd_xml.COL_BLK + 600)
    cr = SEL(n, I(n, u"k_int"), cr, I(n, u"FALSE"), fbd_xml.COL_BLK + 720)
    crb = SEL(n, cr, I(n, B % 0), I(n, B % 1), fbd_xml.COL_BLK + 840)
    n.outvar(u"ret_hi", n.block(u"ADD", [(u"IN1", I(n, u"pch")), (u"IN2", crb)], [u"OUT"],
                                fbd_xml.COL_BLK + 960))
    # ФАЗА B. ЗЕРКАЛЬНАЯ ПОЛЯРНОСТЬ SEL.
    # Здесь стояло SEL(is_pushlike, pair_*, ret_*) = is_pushlike ? ret_* : pair_*
    # - для PUSH в стек писались БАЙТЫ АДРЕСА ВОЗВРАТА вместо пары:
    # наблюдалось PUSH B -> в 06FFh попадало 02h (PSW) вместо 12h (B).
    # Но и обратное неверно: CALL/RST/прерывание кладут ИМЕННО адрес возврата.
    # Поэтому выбор делается не по is_pushlike, а по is_ret_addr.
    is_ret_addr = ORL(n, [I(n, u"k_call"), I(n, u"k_rst"), I(n, u"k_int")],
                      x0=fbd_xml.COL_BLK2 + 300)
    n.outvar(u"push_lo", SEL(n, is_ret_addr, I(n, u"pair_lo"), I(n, u"ret_lo"),
                             fbd_xml.COL_BLK2 + 400))
    n.outvar(u"push_hi", SEL(n, is_ret_addr, I(n, u"pair_hi"), I(n, u"ret_hi"),
                             fbd_xml.COL_BLK2 + 540))

    n = p.network(u"СЕТЬ 20 (ФАЗА 7). Единое значение результата для обоих портов регистров")
    c_mov = I(n, u"k_mov")
    c_imm = ORL(n, [I(n, u"k_mvi"), I(n, u"k_lxi")], x0=fbd_xml.COL_BLK)
    c_rd = ORL(n, [I(n, u"k_lda"), I(n, u"k_ldax"), I(n, u"k_lhld"), I(n, u"k_xthl"),
                   AND(n, I(n, u"k_pop"), NOT(n, I(n, u"is_psw_pop"), fbd_xml.COL_BLK + 200),
                       fbd_xml.COL_BLK + 340)], x0=fbd_xml.COL_BLK + 140)
    c_psw = I(n, u"is_psw_pop")
    rr = CHAIN(n, I(n, u"alu_r"), [
        (c_mov, I(n, u"srcval")), (c_imm, I(n, u"op_lo")), (c_rd, I(n, u"rd_val")),
        (I(n, u"k_rot"), I(n, u"rot_r")), (I(n, u"k_daa"), I(n, u"daa_r")),
        (I(n, u"is_cma"), I(n, u"nota")), (I(n, u"k_xchg"), I(n, u"regs.H")),
        (I(n, u"is_pair_incdec"), I(n, u"plo2")), (I(n, u"k_dad"), I(n, u"dad_lo")),
        (c_psw, I(n, u"rd_val2"))], x0=fbd_xml.COL_BLK2 + 600)
    n.outvar(u"res8", rr)
    rb = I(n, u"rd_val2")
    rb = SEL(n, I(n, u"k_xchg"), rb, I(n, u"regs.L"), fbd_xml.COL_BLK2 + 1200)
    rb = SEL(n, I(n, u"is_pair_incdec"), rb, I(n, u"phi2"), fbd_xml.COL_BLK2 + 1320)
    rb = SEL(n, I(n, u"k_lxi"), rb, I(n, u"op_hi"), fbd_xml.COL_BLK2 + 1440)
    n.outvar(u"res8b", SEL(n, I(n, u"k_dad"), rb, I(n, u"dad_hi"), fbd_xml.COL_BLK2 + 1560))
    n.outvar(u"res8c", SEL(n, I(n, u"k_xchg"), I(n, u"res8"), I(n, u"regs.D"),
                           fbd_xml.COL_BLK2 + 1680))
    n.outvar(u"res8d", SEL(n, I(n, u"k_xchg"), I(n, u"res8"), I(n, u"regs.E"),
                           fbd_xml.COL_BLK2 + 1800))

    # ==================================================================
    # ФАЗА 8. УПРАВЛЕНИЕ
    # ==================================================================
    n = p.network(u"СЕТЬ 21 (ФАЗА 8). Блок управления: условие, адрес перехода, "
                  u"адрес следующей команды")
    ra = n.block(u"OR", [(u"IN1", n.block(u"SHL", [(u"IN1", I(n, u"rdv2_w")),
                                                   (u"IN2", I(n, W % 8))], [u"OUT"])),
                         (u"IN2", I(n, u"rdv1_w"))], [u"OUT"])
    n.outvar(u"ret_addr", ra)
    ct = I(n, u"target")
    ct = SEL(n, I(n, u"k_ret"), ct, I(n, u"ret_addr"), fbd_xml.COL_BLK + 200)
    n.outvar(u"vecw", SEL(n, I(n, u"int_take"), I(n, u"GVL_CPU.C_Vec"),
                          I(n, u"GVL_CPU.Int_Vector"), fbd_xml.COL_BLK + 320))
    n.outvar(u"vecw_w", I(n, u"vecw"))
    n.outvar(u"vec_addr", n.block(u"SHL", [(u"IN1", I(n, u"vecw_w")), (u"IN2", I(n, W % 3))],
                                  [u"OUT"], fbd_xml.COL_BLK + 440))
    ct = SEL(n, I(n, u"is_vec"), ct, I(n, u"vec_addr"), fbd_xml.COL_BLK + 560)
    n.outvar(u"ctrl_target", ct)
    n.outvar(u"uncond_eff", ORL(n, [
        AND(n, I(n, u"GVL_CPU.C_Uncond"), I(n, u"is_jcr"), fbd_xml.COL_BLK + 680),
        I(n, u"is_vec")], x0=fbd_xml.COL_BLK + 820))
    ctl = n.block(u"FB_CtrlUnit", [
        (u"Cond", I(n, u"GVL_CPU.C_Cond")), (u"S", I(n, u"flags.S")), (u"Z", I(n, u"flags.Z")),
        (u"P", I(n, u"flags.P")), (u"CY", I(n, u"flags.CY")),
        (u"Uncond", I(n, u"uncond_eff")), (u"PC", I(n, u"pcv")),
        (u"Target", I(n, u"ctrl_target")), (u"Len", I(n, u"GVL_CPU.C_Len"))],
        [u"CondMet", u"Take", u"PC_Next"], instance=u"ctrl", x=fbd_xml.COL_BLK + 960)
    n.outvar(u"take", ctl.out(u"Take"))
    # ВАЖНО: выход вызова FB защёлкивается в переменную POU прямо в этой сети.
    # Связь "вывод FB -> вход блока" (formalParameter="PC_Next") CODESYS при
    # импорте молча теряет вместе со всей цепочкой ниже по схеме: в прогоне
    # от 3.1 так пропали два блока SEL (697 вместо 699). Через переменную
    # pc_ctrl всё импортируется.
    n.outvar(u"pc_ctrl", ctl.out(u"PC_Next"))
    n.outvar(u"len_w", I(n, u"GVL_CPU.C_Len"))
    n.outvar(u"pclen", n.block(u"ADD", [(u"IN1", I(n, u"pcv")), (u"IN2", I(n, u"len_w"))],
                               [u"OUT"], fbd_xml.COL_BLK + 1100))

    n = p.network(u"СЕТЬ 22 (ФАЗА 8). Адрес следующей команды и указатель стека: "
                  u"PUSH/CALL/RST/INT, POP/RET, SPHL, INX/DCX SP")
    pn = SEL(n, I(n, u"is_branch"), I(n, u"pclen"), I(n, u"pc_ctrl"),
             x=fbd_xml.COL_BLK)
    n.outvar(u"pcnext", SEL(n, I(n, u"k_pchl"), pn, I(n, u"hl"), fbd_xml.COL_BLK + 140))
    n.outvar(u"sp_push", SEL(n, I(n, u"int_take"), I(n, u"wsp2"), I(n, u"int_sp")))
    n.outvar(u"sp_adj", SEL(n, I(n, u"k_inx"),
                            n.block(u"SUB", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 1))],
                                    [u"OUT"], fbd_xml.COL_BLK + 120),
                            n.block(u"ADD", [(u"IN1", I(n, u"spv")), (u"IN2", I(n, W % 1))],
                                    [u"OUT"], fbd_xml.COL_BLK + 240),
                            fbd_xml.COL_BLK + 360))
    sp = I(n, u"spv")
    # ФАЗА B. УСЛОВНЫЙ CALL не должен трогать стек, если условие ложно.
    # Раньше здесь стояло OR(AND(is_pushlike, run_i), int_take): признак
    # is_pushlike включает k_call, поэтому SP уменьшался ВСЕГДА, даже когда
    # CALL не выполнялся (наблюдалось: CNZ при Z=1 давал SP=06FE вместо 0700,
    # хотя PC оставался прежним). Для PUSH/RST гейт не нужен - они безусловны.
    sp_gate = AND(n, AND(n, I(n, u"is_pushlike"), I(n, u"run_i"),
                         fbd_xml.COL_BLK + 1240),
                  OR(n, NOT(n, I(n, u"k_call"), fbd_xml.COL_BLK + 1000),
                     I(n, u"take"), fbd_xml.COL_BLK + 1120),
                  fbd_xml.COL_BLK + 1360)
    sp = SEL(n, ORL(n, [sp_gate, I(n, u"int_take")], x0=fbd_xml.COL_BLK + 620),
             sp, I(n, u"sp_push"), fbd_xml.COL_BLK + 760)
    sp = SEL(n, ORL(n, [AND(n, I(n, u"k_pop"), I(n, u"run_i"), fbd_xml.COL_BLK + 900),
                        AND(n, I(n, u"k_ret"), AND(n, I(n, u"take"), I(n, u"run_i"),
                                                   fbd_xml.COL_BLK + 1040),
                            fbd_xml.COL_BLK + 1180)], x0=fbd_xml.COL_BLK + 1320),
             sp, I(n, u"spp2"), fbd_xml.COL_BLK + 1460)
    sp = SEL(n, I(n, u"k_sphl"), sp, I(n, u"hl"), fbd_xml.COL_BLK + 1580)
    sp = SEL(n, I(n, u"is_sp_incdec"), sp, I(n, u"sp_adj"), fbd_xml.COL_BLK + 1700)
    sp = SEL(n, I(n, u"is_lxi_sp"), sp, I(n, u"a16"), fbd_xml.COL_BLK + 1820)
    n.outvar(u"spnew", sp)

    # ==================================================================
    # ФАЗА 9. ЗАПИСЬ
    # ==================================================================
    n = p.network(u"СЕТЬ 23 (ФАЗА 9). Адрес и данные двух портов записи в память")
    # en_push - единственный гейт записи двух байт в стек: у CALL он зависит от
    # условия перехода (Ccc при невыполненном условии в стек ничего не кладёт).
    gate = ORL(n, [
        AND(n, I(n, u"k_push"), I(n, u"run_i")),
        AND(n, I(n, u"k_call"), AND(n, I(n, u"take"), I(n, u"run_i"), fbd_xml.COL_BLK + 140),
            fbd_xml.COL_BLK + 280),
        AND(n, I(n, u"k_rst"), I(n, u"run_i"), fbd_xml.COL_BLK + 420)],
        x0=fbd_xml.COL_BLK + 560)
    n.outvar(u"en_push", gate)
    # ФАЗА B. АЛУ НИКОГДА НЕ ПИШЕТ В ПАМЯТЬ.
    # Здесь стояло лишнее слагаемое
    #     AND(k_alu, EQ(C_Src, 6), NOT(is_cmp))
    # то есть "если операнд-источник взят из памяти, записать результат в память".
    # Из-за него ADD M / SUB M / ORA M затирали ячейку по HL результатом: в
    # памяти по адресу 0600h после ADD M оказывалось 10h (результат сложения),
    # а не предустановленное значение. Проверено замером памяти в такте.
    # В память пишут только: приёмник-память у MOV/INR/DCR (wr_reg_dst+mdst),
    # STA/STAX/SHLD/XTHL и стек.
    en_mem = ORL(n, [
        AND(n, I(n, u"wr_reg_dst"), I(n, u"mdst")),
        I(n, u"k_sta"), I(n, u"k_stax"), I(n, u"k_shld"), I(n, u"k_xthl")],
        x0=fbd_xml.COL_BLK + 560)
    n.outvar(u"en_mem", en_mem)
    n.outvar(u"en1", ORL(n, [
        AND(n, en_mem, I(n, u"run_i")), AND(n, gate, I(n, u"run_i")),
        I(n, u"int_take")], x0=fbd_xml.COL_BLK2 + 400))
    n.outvar(u"en2", ORL(n, [
        AND(n, ORL(n, [I(n, u"k_shld"), I(n, u"k_xthl")], x0=fbd_xml.COL_BLK2 + 600),
            I(n, u"run_i")),
        AND(n, gate, I(n, u"run_i")), I(n, u"int_take")],
        x0=fbd_xml.COL_BLK2 + 740))
    w1 = I(n, u"res8")
    w1 = SEL(n, I(n, u"k_sta"), w1, I(n, u"regs.A"), fbd_xml.COL_BLK2 + 880)
    w1 = SEL(n, I(n, u"k_stax"), w1, I(n, u"regs.A"), fbd_xml.COL_BLK2 + 1000)
    w1 = SEL(n, I(n, u"k_shld"), w1, I(n, u"regs.L"), fbd_xml.COL_BLK2 + 1120)
    w1 = SEL(n, I(n, u"is_pushlike"), w1, I(n, u"push_hi"), fbd_xml.COL_BLK2 + 1240)
    n.outvar(u"wd1", SEL(n, I(n, u"k_xthl"), w1, I(n, u"regs.L"), fbd_xml.COL_BLK2 + 1360))
    w2 = I(n, u"push_lo")
    w2 = SEL(n, I(n, u"k_shld"), w2, I(n, u"regs.H"), fbd_xml.COL_BLK2 + 1480)
    n.outvar(u"wd2", SEL(n, I(n, u"k_xthl"), w2, I(n, u"regs.H"), fbd_xml.COL_BLK2 + 1600))
    wa = I(n, u"hl")
    wa = SEL(n, I(n, u"k_sta"), wa, I(n, u"a16"), fbd_xml.COL_BLK2 + 1720)
    wa = SEL(n, I(n, u"k_shld"), wa, I(n, u"a16"), fbd_xml.COL_BLK2 + 1840)
    wa = SEL(n, I(n, u"k_stax"), wa, I(n, u"pairval"), fbd_xml.COL_BLK2 + 1960)
    wa = SEL(n, I(n, u"is_pushlike"), wa, I(n, u"wsp1"), fbd_xml.COL_BLK2 + 2080)
    n.outvar(u"wa1", SEL(n, I(n, u"k_xthl"), wa, I(n, u"spv"), fbd_xml.COL_BLK2 + 2200))
    wb = I(n, u"hl")
    wb = SEL(n, I(n, u"k_shld"), wb, I(n, u"a16p1"), fbd_xml.COL_BLK2 + 2320)
    wb = SEL(n, I(n, u"is_pushlike"), wb, I(n, u"wsp2"), fbd_xml.COL_BLK2 + 2440)
    n.outvar(u"wa2", SEL(n, I(n, u"k_xthl"), wb, I(n, u"spp1"), fbd_xml.COL_BLK2 + 2560))

    n = p.network(u"СЕТЬ 24 (ФАЗА 9). Запись в память: два независимых экземпляра")
    n.outvar(u"GVL_CPU.Bus_Data", I(n, u"dbg_opm"))  # диагностика: операнд M
    n.block(u"FB_Memory64K", [(u"Addr", I(n, u"wa1")), (u"Wr", I(n, u"en1")),
                              (u"DataIn", I(n, u"wd1"))], [u"DataOut"], instance=u"m_wr1")
    n.block(u"FB_Memory64K", [(u"Addr", I(n, u"wa2")), (u"Wr", I(n, u"en2")),
                              (u"DataIn", I(n, u"wd2"))], [u"DataOut"], instance=u"m_wr2",
            x=fbd_xml.COL_BLK2)

    n = p.network(u"СЕТЬ 25 (ФАЗА 9). Регистровый файл: два адресуемых порта и два порта XCHG")
    # ФАЗА B: при LXI SP порты регистров НЕ пишут. Иначе младший байт пары идёт
    # в регистр с кодом rp*2+1 = 7, а это A: наблюдалось LXI SP,1234h -> A=34h.
    # Сам SP пишется отдельным путём (spnew = SEL(is_lxi_sp, sp, a16)).
    no_lxi_sp = NOT(n, I(n, u"is_lxi_sp"), fbd_xml.COL_BLK + 60)
    wr1_en = AND(n, AND(n, I(n, u"GVL_CPU.C_WReg1"), I(n, u"run_i"),
                       fbd_xml.COL_BLK + 120), no_lxi_sp, fbd_xml.COL_BLK + 180)
    wr2_en = AND(n, AND(n, I(n, u"GVL_CPU.C_WReg2"), I(n, u"run_i"),
                       fbd_xml.COL_BLK + 240), no_lxi_sp, fbd_xml.COL_BLK + 300)
    n.block(u"FB_RegFileQ", [
        (u"Data1", I(n, u"res8")), (u"Dst1", I(n, u"GVL_CPU.C_Dst1")),
        (u"Wr1", wr1_en),
        (u"Data2", I(n, u"res8b")), (u"Dst2", I(n, u"GVL_CPU.C_Dst2")),
        (u"Wr2", wr2_en),
        (u"Data3", I(n, u"res8c")),
        (u"Wr3", AND(n, I(n, u"GVL_CPU.C_WReg3"), I(n, u"run_i"), fbd_xml.COL_BLK + 280)),
        (u"Data4", I(n, u"res8d")),
        (u"Wr4", AND(n, I(n, u"GVL_CPU.C_WReg4"), I(n, u"run_i"), fbd_xml.COL_BLK + 420)),
    ], [u"A", u"B", u"C", u"D", u"E", u"H", u"L"], instance=u"regs",
        x=fbd_xml.COL_BLK2 + 200)

    n = p.network(u"СЕТЬ 26 (ФАЗА 9). Флаги: раздельные LD по каждому флагу")
    n.outvar(u"psw_in", SEL(n, I(n, u"is_psw_pop"), I(n, B % 0), I(n, u"rd_val")))
    fl = n.block(u"FB_FlagsReg2", [
        (u"S_In", SEL(n, I(n, u"k_daa"), I(n, u"alu_s"), I(n, u"daa_s"),
                      fbd_xml.COL_BLK2)),
        (u"Z_In", SEL(n, I(n, u"k_daa"), I(n, u"alu_z"), I(n, u"daa_z"),
                      fbd_xml.COL_BLK2 + 120)),
        (u"AC_In", I(n, u"ac_new")),
        (u"P_In", SEL(n, I(n, u"k_daa"), I(n, u"alu_p"), I(n, u"daa_p"),
                      fbd_xml.COL_BLK2 + 240)),
        (u"CY_In", I(n, u"cy_new")),
        (u"LD_S", AND(n, I(n, u"GVL_CPU.C_SZP_En"), I(n, u"run_i"),
                      fbd_xml.COL_BLK2 + 360)),
        (u"LD_Z", AND(n, I(n, u"GVL_CPU.C_SZP_En"), I(n, u"run_i"),
                      fbd_xml.COL_BLK2 + 480)),
        (u"LD_AC", AND(n, I(n, u"GVL_CPU.C_AC_En"), I(n, u"run_i"),
                       fbd_xml.COL_BLK2 + 600)),
        (u"LD_P", AND(n, I(n, u"GVL_CPU.C_SZP_En"), I(n, u"run_i"),
                      fbd_xml.COL_BLK2 + 720)),
        (u"LD_CY", AND(n, I(n, u"GVL_CPU.C_CY_En"), I(n, u"run_i"),
                       fbd_xml.COL_BLK2 + 840)),
        (u"PSW_In", I(n, u"psw_in")),
        (u"LD_PSW", AND(n, I(n, u"is_psw_pop"), I(n, u"run_i"), fbd_xml.COL_BLK2 + 960)),
    ], [u"S", u"Z", u"AC", u"P", u"CY", u"PSW"], instance=u"flags",
        x=fbd_xml.COL_BLK2 + 1100)

    n = p.network(u"СЕТЬ 27 (ФАЗА 9). Запись PC и SP")
    # прерывание обязано записать PC (адрес обработчика) и SP, поэтому
    # разрешение записи - run_i ИЛИ int_take, а не просто run_i
    pc_ld = OR(n, I(n, u"run_i"), I(n, u"int_take"))
    n.block(u"FB_Reg16", [(u"D", I(n, u"pcnext")), (u"LD", pc_ld),
                          (u"CLR", I(n, u"FALSE"))], [u"Q"], instance=u"pc")
    n.block(u"FB_Reg16", [(u"D", I(n, u"spnew")),
                          (u"LD", OR(n, I(n, u"run_i"), I(n, u"int_take"),
                                     fbd_xml.COL_BLK + 140)),
                          (u"CLR", I(n, u"FALSE"))], [u"Q"], instance=u"sp",
            x=fbd_xml.COL_BLK2)

    # ==================================================================
    # ФАЗА 10. ПРЕРЫВАНИЯ, ОСТАНОВ, СЧЁТЧИК ТАКТОВ
    # ==================================================================
    n = p.network(u"СЕТЬ 28 (ФАЗА 10). Триггер IFF и признак Busy: EI/DI/INT/RET")
    n.outvar(u"ret_busy", AND(n, I(n, u"k_ret"),
                              AND(n, I(n, u"busy"), I(n, u"run_i"), fbd_xml.COL_BLK + 120),
                              fbd_xml.COL_BLK + 260))
    iff = I(n, u"iff")
    iff = SEL(n, AND(n, I(n, u"k_ei"), I(n, u"run_i"), fbd_xml.COL_BLK + 380),
              iff, I(n, u"TRUE"), fbd_xml.COL_BLK + 520)
    iff = SEL(n, AND(n, I(n, u"k_di"), I(n, u"run_i"), fbd_xml.COL_BLK + 640),
              iff, I(n, u"FALSE"), fbd_xml.COL_BLK + 780)
    iff = SEL(n, I(n, u"int_take"), iff, I(n, u"FALSE"), fbd_xml.COL_BLK + 900)
    n.outvar(u"iff_n", SEL(n, I(n, u"ret_busy"), iff, I(n, u"TRUE"), fbd_xml.COL_BLK + 1020))
    n.outvar(u"iff", I(n, u"iff_n"))
    n.outvar(u"GVL_CPU.IFF", I(n, u"iff_n"))
    bs = I(n, u"busy")
    bs = SEL(n, I(n, u"int_take"), bs, I(n, u"TRUE"), fbd_xml.COL_BLK2 + 400)
    n.outvar(u"busy_n", SEL(n, I(n, u"ret_busy"), bs, I(n, u"FALSE"),
                            fbd_xml.COL_BLK2 + 520))
    n.outvar(u"busy", I(n, u"busy_n"))
    n.outvar(u"GVL_CPU.Int_Busy", I(n, u"busy_n"))

    n = p.network(u"СЕТЬ 29 (ФАЗА 10). Останов HLT и счётчик тактов")
    n.outvar(u"hlt_now", AND(n, I(n, u"k_hlt"), I(n, u"run_i")))
    hl = SEL(n, I(n, u"hlt_now"), I(n, u"GVL_CPU.Halted"), I(n, u"TRUE"))
    # принятое прерывание снимает останов HLT - так ведёт себя реальный 8080
    n.outvar(u"halted_l", SEL(n, I(n, u"int_take"), hl, I(n, u"FALSE"),
                              fbd_xml.COL_BLK2 + 140))
    n.outvar(u"GVL_CPU.Halted", I(n, u"halted_l"))
    n.outvar(u"Halted", I(n, u"halted_l"))
    n.outvar(u"step_inc", n.block(u"ADD", [(u"IN1", I(n, u"GVL_CPU.Step_Cnt")),
                                           (u"IN2", I(n, W % 1))], [u"OUT"],
                                  fbd_xml.COL_BLK + 400))
    n.outvar(u"step_n", SEL(n, I(n, u"run"), I(n, u"GVL_CPU.Step_Cnt"),
                            I(n, u"step_inc"), fbd_xml.COL_BLK + 520))
    n.outvar(u"GVL_CPU.Step_Cnt", I(n, u"step_n"))
    n.outvar(u"Step", I(n, u"step_n"))
    return p


# ======================================================================
def make_plc_prg_full():
    p = Pou(u"PLC_PRG_FULL", u"program",
            doc=u"Главная программа полного ядра: один скан PLC = один такт 8080.\n"
                u"\tСеть 1 - загрузка тестовой программы в память при первом скане:\n"
                u"\t  0000 31 00 30  LXI SP,3000h    - стек\n"
                u"\t  0003 3E 25     MVI A,25h\n"
                u"\t  0005 06 17     MVI B,17h\n"
                u"\t  0007 80        ADD B           - A = 3Ch\n"
                u"\t  0008 32 02 01  STA 0102h       - запись результата в память\n"
                u"\t  000B 09        DAD B           - HL := HL + BC\n"
                u"\t  000C E5        PUSH H\n"
                u"\t  000D E1        POP  H\n"
                u"\t  000E 07        RLC\n"
                u"\t  000F 3C        INR A\n"
                u"\t  0010 27        DAA\n"
                u"\t  0011 C3 20 00  JMP 0020h\n"
                u"\t  0020 F5        PUSH PSW\n"
                u"\t  0021 F1        POP  PSW\n"
                u"\t  0022 76        HLT\n"
                u"\tСеть 2 - вызов процессора (Enable берётся из GVL_CPU).")
    p.var(u"cpu", u"FB_CPU8080_FULL", u"экземпляр процессора")
    p.var(u"init_done", u"BOOL", u"память инициализирована")
    p.var(u"notdone", u"BOOL", u"инициализация ещё не выполнена")

    PROG = (
        (0x0000, 0x31), (0x0001, 0x00), (0x0002, 0x30),   # LXI SP,3000h
        (0x0003, 0x3E), (0x0004, 0x25),                   # MVI A,25h
        (0x0005, 0x06), (0x0006, 0x17),                   # MVI B,17h
        (0x0007, 0x80),                                   # ADD B
        (0x0008, 0x32), (0x0009, 0x02), (0x000A, 0x01),   # STA 0102h
        (0x000B, 0x09),                                   # DAD B
        (0x000C, 0xE5),                                   # PUSH H
        (0x000D, 0xE1),                                   # POP H
        (0x000E, 0x07),                                   # RLC
        (0x000F, 0x3C),                                   # INR A
        (0x0010, 0x27),                                   # DAA
        (0x0011, 0xC3), (0x0012, 0x20), (0x0013, 0x00),   # JMP 0020h
        (0x0014, 0x76),                                   # HLT (если перехода не было)
        (0x0020, 0xF5),                                   # PUSH PSW
        (0x0021, 0xF1),                                   # POP PSW
        (0x0022, 0x76),                                   # HLT
        (0x0100, 0x01), (0x0101, 0x02),                   # операнды для LDA/STA
    )
    n = p.network(u"СЕТЬ 1. Загрузка тестовой программы в память при первом скане")
    n.outvar(u"notdone", NOT(n, I(n, u"init_done")))
    for addr, val in PROG:
        tgt = u"GVL_MEM.Memory[WORD#16#%04X]" % addr
        n.outvar(tgt, SEL(n, I(n, u"notdone"), I(n, tgt), I(n, H % val), fbd_xml.COL_BLK))
    n.outvar(u"init_done", I(n, u"TRUE"))

    n = p.network(u"СЕТЬ 2. Вызов процессора: один такт 8080 за скан")
    n.block(u"FB_CPU8080_FULL", [(u"Enable", I(n, u"GVL_CPU.Enable"))],
            [u"Halted", u"Step"], instance=u"cpu")
    return p


ALL = (make_cpu_full, make_plc_prg_full)
