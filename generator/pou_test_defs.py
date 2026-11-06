# -*- coding: utf-8 -*-
u"""ЭТАП 4: DUT и GVL ТЕСТОВОГО СЛОЯ (данные тестов, не логика).

ЗДЕСЬ ТОЛЬКО ДАННЫЕ. Логика прогона - в FBD: pou_test8080.py, pou_testcpm.py,
pou_testio.py. Это прямо разрешено заданием: «ST - только инициализация и
тестовые данные». Поэтому весь набор тест-кейсов - это ОДИН массив структур
`GVL_TEST.Tests`, а схема прогона одна и та же для всех кейсов.

ЧТО ЛЕЖИТ В ФАЙЛЕ:
  * ST_TestCase  - структура тест-кейса (по плану docs/02, раздел 1.1);
  * ST_CaseResult- снимок факта для отчёта (диагностика FAIL);
  * GVL_TEST     - данные тестов + состояние прогона + результаты;
  * CASES        - сам набор кейсов (генерируется кодом ниже);
  * функции report_rows() / summary() - сводка для отчёта этапа 4.

ОТСТУПЛЕНИЯ ОТ ПЛАНА (docs/02, п. 1.1), внесённые сознательно:
  1. Code : ARRAY[0..15] OF BYTE вместо [0..7]. Программы группы 6 из плана
     (T-371: LDA/MOV/LDA/ADD/STA/HLT) занимают 12 байт и в 8 не влезают.
     Замер: T-371 = 3+1+3+1+3+1 = 12 байт.
  2. Добавлены Pre1..Pre3 (адрес+значение): план даёт ОДНУ ячейку памяти
     (MemAddr/MemVal), а тестам CALL/RET/XTHL/LHLD нужно две-три
     (адрес возврата занимает два байта, LHLD читает два байта подряд).
  3. Поле Name оставлено в структуре (по плану), но не заполняется: имена
     кейсов есть в этом файле и в отчёте, а в ПЛК для учёта хватает Id и Group.

СЕМАНТИКА PSWMask (ключевой механизм плана):
  бит маски = 1 -> флаг обязан стать равным ExpPSW[бит];
  бит маски = 0 -> флаг обязан ОСТАТЬСЯ равным InitPSW[бит].
Значимые биты PSW: 7=S 6=Z 4=AC 2=P 0=CY (биты 5 и 3 всегда 0, бит 1 всегда 1),
поэтому сравнение всегда идёт по маске 0xD7.
"""

# ======================================================================
# АДРЕСА, ОБЩИЕ ДЛЯ ВСЕГО НАБОРА ТЕСТОВ
# ======================================================================
CODE_BASE = 0x0200       # куда грузится код теста (8..16 байт)
D_TARGET = 0x0300        # «пустой» адрес перехода (там нули = NOP)
D_STACK = 0x0700         # вершина стека по умолчанию
D_DATA = 0x0100          # ячейка данных по умолчанию
D_HL = 0x0600            # куда показывает HL по умолчанию

# биты PSW
S_B, Z_B, AC_B, P_B, CY_B = 0x80, 0x40, 0x10, 0x04, 0x01
PSW_MASK_ALL = 0xD7      # S Z AC P CY
PSW_MASK_CY = 0x01       # только перенос
PSW_MASK_SZP = 0xD6      # S Z AC P (CY не проверяется - сравнивается с InitPSW)
PSW_MASK_NONE = 0x00     # PSW должен остаться как был
PSW_BASE = 0x02          # бит 1 в реальном 8080 всегда 1


def par(v):
    u"""Флаг чётности 8080: 1, если число единичных бит чётное."""
    return P_B if (bin(v & 0xFF).count(u"1") % 2 == 0) else 0


def psw(s=0, z=0, ac=0, p=0, cy=0):
    u"""Собрать байт PSW из флагов (бит 1 всегда 1, биты 5 и 3 всегда 0)."""
    return (S_B if s else 0) | (Z_B if z else 0) | (AC_B if ac else 0) | \
           (P_B if p else 0) | (CY_B if cy else 0) | PSW_BASE


# ======================================================================
# ТЕКСТ DUT
# ======================================================================
DUT_TESTCASE = u"""TYPE ST_TestCase :
STRUCT
    (* Один тест-кейс табличного прогона TEST_8080 (план docs/02, п. 1.1).
       Все поля - ДАННЫЕ: схема прогона читает их и не зависит от их числа. *)
    Id        : WORD;                    (* T-001 ... - номер для отчёта *)
    Name      : STRING(24);              (* краткое имя (заполняет отчёт) *)
    Group     : BYTE;                    (* 1..7 - группа плана *)
    (* --- программа, которую кладём в память по адресу 0200h --- *)
    Code      : ARRAY[0..15] OF BYTE;    (* до 16 байт кода *)
    CodeLen   : BYTE;
    (* --- до трёх ячеек памяти, которые надо предустановить --- *)
    Pre1Addr  : WORD;  Pre1Val : BYTE;
    Pre2Addr  : WORD;  Pre2Val : BYTE;
    Pre3Addr  : WORD;  Pre3Val : BYTE;
    (* --- начальное состояние процессора --- *)
    InitA, InitB, InitC, InitD, InitE, InitH, InitL : BYTE;
    InitSP    : WORD;
    InitPC    : WORD;
    InitPSW   : BYTE;
    (* --- ожидаемый результат --- *)
    ExpA, ExpB, ExpC, ExpD, ExpE, ExpH, ExpL : BYTE;
    ExpSP     : WORD;
    ExpPC     : WORD;
    ExpPSW    : BYTE;
    PSWMask   : BYTE;    (* 1 = сверять с ExpPSW, 0 = флаг не должен измениться *)
    CheckMem  : BOOL;    (* проверять ли ячейку памяти *)
    ExpMemAddr: WORD;
    ExpMemVal : BYTE;
    MaxTacts  : WORD;    (* сколько тактов выполняем программу *)
END_STRUCT
END_TYPE
"""

DUT_ALL = ((u"ST_TestCase", DUT_TESTCASE),)


# ======================================================================
# НАБОР ТЕСТ-КЕЙСОВ
# ======================================================================
CASES = []


def T(cid, name, group, code, exp=None, init=None, preload=(),
      psw_mask=PSW_MASK_NONE, tacts=None, mem=None, exp_psw=None):
    u"""Добавить тест-кейс.

    cid     - номер (T-001 ...); цифры после T- образуют поле Id;
    code    - список байтов программы (кладётся по адресу CODE_BASE);
    exp     - словарь ожидаемых значений: A,B,C,D,E,H,L,SP,PC,PSW;
    init    - словарь начальных значений (по умолчанию - стандарт);
    preload - список (адрес, значение) - до трёх ячеек памяти;
    mem     - (адрес, значение) - что проверить в памяти.
    exp_psw - ожидаемый байт флагов (если не задан - берётся из exp/init);
    psw_mask- какие флаги сверять с exp_psw (остальные - с init).
    """
    i = dict(INIT_DEFAULT)
    if init:
        i.update(init)
    e = dict(i)
    e[u"PC"] = CODE_BASE + len(code)
    if exp:
        e.update(exp)
    if tacts is None:
        tacts = 1
    pl = list(preload) + [(0, 0)] * (3 - len(preload))
    c = dict(id=cid, name=name, group=group, code=list(code), init=i, exp=e,
             pre=pl[:3], mask=psw_mask, tacts=tacts,
             check_mem=(mem is not None), mem=(mem if mem else (0, 0)),
             exp_psw=(exp_psw if exp_psw is not None else e[u"PSW"]))
    CASES.append(c)
    return c


INIT_DEFAULT = {
    u"A": 0x11, u"B": 0x22, u"C": 0x33, u"D": 0x44, u"E": 0x55,
    u"H": 0x06, u"L": 0x00, u"SP": D_STACK, u"PC": CODE_BASE,
    u"PSW": PSW_BASE,
}

# имена регистров в порядке кода поля команды: 0=B 1=C 2=D 3=E 4=H 5=L 6=M 7=A
REG_NAMES = [u"B", u"C", u"D", u"E", u"H", u"L", u"M", u"A"]


def _reg_init(reg, val):
    u"""Начальное значение для источника/приёмника с кодом регистра."""
    d = {}
    if reg == 6:
        # M - это память по HL; HL по умолчанию 0600h, туда и кладём значение
        d[u"H"] = 0x06
        d[u"L"] = 0x00
    else:
        d[REG_NAMES[reg]] = val
    return d


def build_mov():
    u"""T-001..T-064: все 64 комбинации MOV DDD,SSS (включая MOV M,M = HLT)."""
    n = 0
    for ddd in range(8):
        for sss in range(8):
            n += 1
            op = 0x40 | (ddd << 3) | sss
            src_val = 0x88 if sss == 6 else INIT_DEFAULT[REG_NAMES[sss]]
            # ПОРЯДОК ВАЖЕН (фаза B). Раньше здесь было наоборот: сначала
            # инициализировался ИСТОЧНИК, затем ПРИЁМНИК обнулялся. Для
            # диагональных кейсов (MOV A,A, MOV B,B, ... MOV L,L) ddd == sss,
            # поэтому обнуление приёмника затирало значение источника:
            # начальное B = 0, а ожидалось B = 22h - кейс не мог пройти НИКОГДА
            # (это и давало 8 гарантированных FAIL из 82).
            # Теперь сначала обнуляется приёмник, затем ставится источник.
            init = {}
            init.update(_reg_init(ddd, 0))
            init.update(_reg_init(sss, src_val))
            exp = {}
            if ddd == 6 and sss == 6:
                # 76h - это HLT, а не MOV M,M: PC уходит на 1 и процессор встаёт
                exp = {}
                name = u"MOV M,M = HLT"
            elif ddd == 6:
                exp = {}
                name = u"MOV M,%s" % REG_NAMES[sss]
                mem = (D_HL, src_val)
            elif sss == 6:
                exp = {REG_NAMES[ddd]: 0x88}
                name = u"MOV %s,M" % REG_NAMES[ddd]
                mem = None
            else:
                exp = {REG_NAMES[ddd]: src_val}
                name = u"MOV %s,%s" % (REG_NAMES[ddd], REG_NAMES[sss])
                mem = None
            if ddd == 6 and sss != 6:
                T(u"T-%03d" % n, name, 1, [op], exp=exp,
                  init=init, preload=[(D_HL, 0x88)], mem=mem)
            else:
                T(u"T-%03d" % n, name, 1, [op], exp=exp,
                  init=init, preload=[(D_HL, 0x88)])


def build_mvi():
    u"""T-065..T-073: MVI r,data - все 8 регистров (код 6 = M)."""
    n = 64
    for r in range(8):
        n += 1
        op = 0x06 | (r << 3)
        init = _reg_init(r, 0)
        if r == 6:
            T(u"T-%03d" % n, u"MVI M,5Ah", 1, [op, 0x5A], init=init,
              preload=[(D_HL, 0x00)], mem=(D_HL, 0x5A))
        else:
            T(u"T-%03d" % n, u"MVI %s,5Ah" % REG_NAMES[r], 1, [op, 0x5A],
              exp={REG_NAMES[r]: 0x5A}, init=init)


def build_group1():
    u"""T-074..T-089: LXI, LDA, STA, LDAX, STAX, LHLD, SHLD, XCHG, SPHL, PCHL, XTHL."""
    # LXI rp,d16 - 4 пары
    pairs = [(0, u"B", u"C"), (1, u"D", u"E"), (2, u"H", u"L"), (3, u"SP", u"SP")]
    for k, (rp, hi, lo) in enumerate(pairs):
        op = 0x01 | (rp << 4)
        exp = {}
        if rp == 3:
            exp[u"SP"] = 0x1234
        else:
            exp[hi] = 0x12
            exp[lo] = 0x34
        T(u"T-%03d" % (74 + k), u"LXI %s,1234h" % (hi if rp == 3 else hi + lo), 1,
          [op, 0x34, 0x12], exp=exp)

    T(u"T-080", u"LDA 0100h", 1, [0x3A, 0x00, 0x01], exp={u"A": 0xAA},
      preload=[(0x0100, 0xAA)])
    T(u"T-081", u"STA 0100h", 1, [0x32, 0x00, 0x01], init={u"A": 0x55},
      mem=(0x0100, 0x55))
    T(u"T-082", u"LDAX B", 1, [0x0A], exp={u"A": 0x99},
      init={u"B": 0x01, u"C": 0x00}, preload=[(0x0100, 0x99)])
    T(u"T-083", u"LDAX D", 1, [0x1A], exp={u"A": 0x77},
      init={u"D": 0x01, u"E": 0x00}, preload=[(0x0100, 0x77)])
    T(u"T-084", u"STAX D", 1, [0x12], init={u"A": 0x66, u"D": 0x01, u"E": 0x00},
      mem=(0x0100, 0x66))
    T(u"T-085", u"LHLD 0100h", 1, [0x2A, 0x00, 0x01], exp={u"H": 0x12, u"L": 0x34},
      preload=[(0x0100, 0x34), (0x0101, 0x12)])
    T(u"T-086", u"SHLD 0100h", 1, [0x22, 0x00, 0x01],
      init={u"H": 0x12, u"L": 0x34}, mem=(0x0100, 0x34))
    T(u"T-087", u"XCHG", 1, [0xEB],
      init={u"D": 0x12, u"E": 0x34, u"H": 0x56, u"L": 0x78},
      exp={u"D": 0x56, u"E": 0x78, u"H": 0x12, u"L": 0x34})
    T(u"T-088", u"SPHL", 1, [0xF9], init={u"H": 0x07, u"L": 0x00},
      exp={u"SP": 0x0700})
    T(u"T-089", u"PCHL", 1, [0xE9], init={u"H": 0x02, u"L": 0x00},
      exp={u"PC": CODE_BASE})
    T(u"T-090", u"XTHL", 1, [0xE3],
      init={u"H": 0x12, u"L": 0x34, u"SP": 0x0700},
      exp={u"H": 0xBC, u"L": 0x9A},
      preload=[(0x0700, 0x9A), (0x0701, 0xBC)], mem=(0x0700, 0x34))


def build_alu():
    u"""Группа 2: ADD/ADC/ADI/ACI/SUB/SBB/SUI/SBI (T-121..T-144)."""
    # ---- ADD r: A=0F, reg=01 -> A=10, AC=1, P=0 (у 10h один бит) ----
    n = 120
    vsrc = 0x01
    for r in range(8):
        n += 1
        op = 0x80 | r
        init = {u"A": 0x0F}
        init.update(_reg_init(r, vsrc))
        pre = [(D_HL, vsrc)] if r == 6 else []
        # ДЛЯ r = 7 (ADD A) ОЖИДАНИЕ ДРУГОЕ: инициализация источника
        # перезаписывает сам аккумулятор (A := 01h), поэтому A + A = 02h,
        # а не 0Fh + 01h = 10h. Раньше здесь стояло общее ожидание 10h, и кейс
        # не мог пройти НИКОГДА (эмулятор считал верно).
        if r == 7:
            T(u"T-%03d" % n, u"ADD %s" % REG_NAMES[r], 2, [op], init=init,
              exp={u"A": 0x02}, preload=pre, psw_mask=PSW_MASK_ALL,
              exp_psw=psw())
        else:
            T(u"T-%03d" % n, u"ADD %s" % REG_NAMES[r], 2, [op], init=init,
              exp={u"A": 0x10}, preload=pre, psw_mask=PSW_MASK_ALL,
              exp_psw=psw(ac=1))

    # ---- ADI/ACI/SUI/SBI d8 ----
    T(u"T-129", u"ADI 01h", 2, [0xC6, 0x01], init={u"A": 0x0F},
      exp={u"A": 0x10}, psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1))
    T(u"T-130", u"ACI 00h при CY=1", 2, [0xCE, 0x00],
      init={u"A": 0x0F, u"PSW": psw(cy=1)}, exp={u"A": 0x10},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1))
    T(u"T-131", u"SUI 01h", 2, [0xD6, 0x01], init={u"A": 0x10},
      exp={u"A": 0x0F}, psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))
    T(u"T-132", u"SBI 00h при CY=1", 2, [0xDE, 0x00],
      init={u"A": 0x10, u"PSW": psw(cy=1)}, exp={u"A": 0x0F},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))

    # ---- ADC r при CY=0 и CY=1 ----
    T(u"T-133", u"ADC B при CY=0", 2, [0x88],
      init={u"A": 0x0F, u"B": 0x00}, exp={u"A": 0x0F},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(p=1))
    T(u"T-134", u"ADC B при CY=1", 2, [0x88],
      init={u"A": 0x0F, u"B": 0x00, u"PSW": psw(cy=1)}, exp={u"A": 0x10},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1))
    T(u"T-135", u"ADC B 0F+01 без переноса", 2, [0x88],
      init={u"A": 0x0F, u"B": 0x01}, exp={u"A": 0x10},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1))
    T(u"T-136", u"ADC B F0+0F+1 = 100h", 2, [0x88],
      init={u"A": 0xF0, u"B": 0x0F, u"PSW": psw(cy=1)}, exp={u"A": 0x00},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, ac=1, p=1, cy=1))

    # ---- SUB r: A=10, reg=01 -> A=0F, CY=0, AC=1, P=1 ----
    T(u"T-137", u"SUB B", 2, [0x90], init={u"A": 0x10, u"B": 0x01},
      exp={u"A": 0x0F}, psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))
    T(u"T-138", u"SUB M", 2, [0x96], init={u"A": 0x10},
      preload=[(D_HL, 0x01)], exp={u"A": 0x0F},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))
    T(u"T-139", u"SUB A,A = 00h", 2, [0x97], init={u"A": 0x55},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))
    T(u"T-140", u"SUB A,B заём 00-01", 2, [0x90], init={u"A": 0x00, u"B": 0x01},
      exp={u"A": 0xFF}, psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, ac=1, cy=1, p=1))

    # ---- SBB r ----
    T(u"T-141", u"SBB B при CY=1", 2, [0x98],
      init={u"A": 0x10, u"B": 0x00, u"PSW": psw(cy=1)}, exp={u"A": 0x0F},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))
    T(u"T-142", u"SBB B при CY=0", 2, [0x98],
      init={u"A": 0x10, u"B": 0x01}, exp={u"A": 0x0F},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))

    # ---- INR r: r=0F -> 10, AC=1, CY не трогается (InitPSW: CY=1) ----
    n = 144
    for r in range(8):
        n += 1
        op = 0x04 | (r << 3)
        init = {u"PSW": psw(cy=1)}
        init.update(_reg_init(r, 0x0F))
        pre = [(D_HL, 0x0F)] if r == 6 else []
        exp = {} if r == 6 else {REG_NAMES[r]: 0x10}
        mem = (D_HL, 0x10) if r == 6 else None
        T(u"T-%03d" % n, u"INR %s (CY цел)" % REG_NAMES[r], 3, [op], init=init,
          exp=exp, preload=pre, mem=mem, psw_mask=PSW_MASK_SZP,
          exp_psw=psw(ac=1))

    # ---- DCR r: r=10 -> 0F, AC=1, P=1, CY не трогается ----
    for r in range(8):
        n += 1
        op = 0x05 | (r << 3)
        init = {u"PSW": psw(cy=1)}
        init.update(_reg_init(r, 0x10))
        pre = [(D_HL, 0x10)] if r == 6 else []
        exp = {} if r == 6 else {REG_NAMES[r]: 0x0F}
        mem = (D_HL, 0x0F) if r == 6 else None
        T(u"T-%03d" % n, u"DCR %s (CY цел)" % REG_NAMES[r], 3, [op], init=init,
          exp=exp, preload=pre, mem=mem, psw_mask=PSW_MASK_SZP,
          exp_psw=psw(ac=1, p=1))

    # ---- INX/DCX ----
    T(u"T-161", u"INX B 00FF->0100", 3, [0x03],
      init={u"B": 0x00, u"C": 0xFF}, exp={u"B": 0x01, u"C": 0x00})
    T(u"T-162", u"DCX B 0000->FFFF", 3, [0x0B],
      init={u"B": 0x00, u"C": 0x00}, exp={u"B": 0xFF, u"C": 0xFF})
    T(u"T-163", u"INX B FFFF->0000 (CY=0!)", 3, [0x03],
      init={u"B": 0xFF, u"C": 0xFF, u"PSW": psw(cy=1)},
      exp={u"B": 0x00, u"C": 0x00})   # маска 0 = PSW не должен измениться

    # ---- DAD ----
    T(u"T-164", u"DAD B FFFF+0001 -> CY", 3, [0x09],
      init={u"H": 0xFF, u"L": 0xFF, u"B": 0x00, u"C": 0x01},
      exp={u"H": 0x00, u"L": 0x00}, psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))
    T(u"T-190", u"DAD H 1234+1234", 3, [0x29],
      init={u"H": 0x12, u"L": 0x34}, exp={u"H": 0x24, u"L": 0x68},
      psw_mask=PSW_MASK_CY, exp_psw=psw())

    # ---- ANA r: A=F0, r=FF -> F0, CY=0, AC=1 (A3 или B3) ----
    T(u"T-165", u"ANA B", 3, [0xA0], init={u"A": 0xF0, u"B": 0xFF},
      exp={u"A": 0xF0}, psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, ac=1, p=1))
    T(u"T-166", u"ANA M", 3, [0xA6], init={u"A": 0xF0},
      preload=[(D_HL, 0xFF)], exp={u"A": 0xF0},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, ac=1, p=1))
    T(u"T-167", u"ANI 0Fh", 3, [0xE6, 0x0F], init={u"A": 0xFF},
      exp={u"A": 0x0F}, psw_mask=PSW_MASK_ALL, exp_psw=psw(ac=1, p=1))

    # ---- ORA r: A=F0, r=0F -> FF, CY=0, AC=0 ----
    T(u"T-168", u"ORA B", 3, [0xB0], init={u"A": 0xF0, u"B": 0x0F},
      exp={u"A": 0xFF}, psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, p=1))
    T(u"T-169", u"ORA M", 3, [0xB6], init={u"A": 0xF0},
      preload=[(D_HL, 0x0F)], exp={u"A": 0xFF},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, p=1))
    T(u"T-170", u"ORI 0Fh", 3, [0xF6, 0x0F], init={u"A": 0xF0},
      exp={u"A": 0xFF}, psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, p=1))

    # ---- XRA r: A=FF, r=FF -> 00, Z=1, P=1, CY=0, AC=0 ----
    T(u"T-171", u"XRA B", 3, [0xA8], init={u"A": 0xFF, u"B": 0xFF},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))
    T(u"T-172", u"XRA A (обнуление)", 3, [0xAF], init={u"A": 0xAA},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))
    T(u"T-173", u"XRI 0Fh", 3, [0xEE, 0x0F], init={u"A": 0x0F},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))

    # ---- CMP/CPI: A не меняется ----
    T(u"T-174", u"CMP B (10-20)", 3, [0xB8], init={u"A": 0x10, u"B": 0x20},
      exp={u"A": 0x10}, psw_mask=PSW_MASK_ALL, exp_psw=psw(s=1, cy=1, p=1))
    T(u"T-175", u"CMP B (равно)", 3, [0xB8], init={u"A": 0x55, u"B": 0x55},
      exp={u"A": 0x55}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))
    T(u"T-176", u"CPI 10h (равно)", 3, [0xFE, 0x10], init={u"A": 0x10},
      exp={u"A": 0x10}, psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1))

    # ---- флаговые команды ----
    T(u"T-177", u"STC", 3, [0x37], psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))
    T(u"T-178", u"CMC (CY=0 -> 1)", 3, [0x3F], psw_mask=PSW_MASK_CY,
      exp_psw=psw(cy=1))
    T(u"T-179", u"CMA (флаги целы)", 3, [0x2F], init={u"A": 0x55, u"PSW": 0xD7},
      exp={u"A": 0xAA}, psw_mask=PSW_MASK_NONE, exp_psw=0xD7)
    T(u"T-180", u"DAA 9Ah -> 00h CY=1", 3, [0x27], init={u"A": 0x9A},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_ALL,
      exp_psw=psw(z=1, ac=1, p=1, cy=1))

    # ---- сдвиги: меняют только CY ----
    T(u"T-181", u"RLC 85h", 3, [0x07], init={u"A": 0x85}, exp={u"A": 0x0B},
      psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))
    T(u"T-182", u"RRC 01h", 3, [0x0F], init={u"A": 0x01}, exp={u"A": 0x80},
      psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))
    T(u"T-183", u"RAL 80h при CY=0", 3, [0x17], init={u"A": 0x80},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))
    T(u"T-184", u"RAR 01h при CY=0", 3, [0x1F], init={u"A": 0x01},
      exp={u"A": 0x00}, psw_mask=PSW_MASK_CY, exp_psw=psw(cy=1))


def build_group4():
    u"""Группа 4: переходы, вызовы, стек, управление."""
    Z_ON = psw(z=1)
    Z_OFF = psw()
    S_ON = psw(s=1)
    S_OFF = psw()
    P_ON = psw(p=1)
    P_OFF = psw()
    CY_ON = psw(cy=1)
    CY_OFF = psw()

    T(u"T-261", u"JMP 0300h", 4, [0xC3, 0x00, 0x03], exp={u"PC": D_TARGET})
    T(u"T-262", u"JMP на себя (гонка PC)", 4, [0xC3, 0x00, 0x02],
      exp={u"PC": CODE_BASE}, tacts=4)
    T(u"T-263", u"JZ при Z=1", 4, [0xCA, 0x00, 0x03], init={u"PSW": Z_ON},
      exp={u"PC": D_TARGET})
    T(u"T-264", u"JZ при Z=0 (нет перехода)", 4, [0xCA, 0x00, 0x03],
      init={u"PSW": Z_OFF}, exp={u"PC": CODE_BASE + 3})
    T(u"T-265", u"JNZ при Z=0", 4, [0xC2, 0x00, 0x03], init={u"PSW": Z_OFF},
      exp={u"PC": D_TARGET})
    T(u"T-266", u"JNZ при Z=1 (нет перехода)", 4, [0xC2, 0x00, 0x03],
      init={u"PSW": Z_ON}, exp={u"PC": CODE_BASE + 3})
    T(u"T-267", u"JC при CY=1", 4, [0xDA, 0x00, 0x03], init={u"PSW": CY_ON},
      exp={u"PC": D_TARGET})
    T(u"T-268", u"JNC при CY=0", 4, [0xD2, 0x00, 0x03], init={u"PSW": CY_OFF},
      exp={u"PC": D_TARGET})
    T(u"T-269", u"JP при S=0", 4, [0xF2, 0x00, 0x03], init={u"PSW": S_OFF},
      exp={u"PC": D_TARGET})
    T(u"T-270", u"JM при S=1", 4, [0xFA, 0x00, 0x03], init={u"PSW": S_ON},
      exp={u"PC": D_TARGET})
    T(u"T-271", u"JPE при P=1", 4, [0xEA, 0x00, 0x03], init={u"PSW": P_ON},
      exp={u"PC": D_TARGET})
    T(u"T-272", u"JPO при P=0", 4, [0xE2, 0x00, 0x03], init={u"PSW": P_OFF},
      exp={u"PC": D_TARGET})

    T(u"T-273", u"CALL 0300h (адрес на стек)", 4, [0xCD, 0x00, 0x03],
      exp={u"PC": D_TARGET, u"SP": D_STACK - 2},
      mem=(D_STACK - 1, 0x02))
    T(u"T-274", u"RET", 4, [0xC9], init={u"SP": D_STACK - 2},
      exp={u"PC": D_TARGET, u"SP": D_STACK},
      preload=[(D_STACK - 2, 0x00), (D_STACK - 1, 0x03)], tacts=1)
    T(u"T-275", u"PUSH B", 4, [0xC5], init={u"B": 0x12, u"C": 0x34},
      exp={u"SP": D_STACK - 2}, mem=(D_STACK - 1, 0x12))
    T(u"T-276", u"POP D", 4, [0xD1], init={u"SP": D_STACK - 2},
      exp={u"D": 0x12, u"E": 0x34, u"SP": D_STACK},
      preload=[(D_STACK - 2, 0x34), (D_STACK - 1, 0x12)])
    T(u"T-277", u"PUSH PSW", 4, [0xF5], init={u"A": 0x3C, u"PSW": 0xD7},
      exp={u"SP": D_STACK - 2}, mem=(D_STACK - 1, 0x3C))
    T(u"T-278", u"POP PSW", 4, [0xF1], init={u"SP": D_STACK - 2},
      exp={u"A": 0x3C, u"SP": D_STACK, u"PSW": 0xD7},
      preload=[(D_STACK - 2, 0xD7), (D_STACK - 1, 0x3C)],
      psw_mask=PSW_MASK_ALL, exp_psw=0xD7)
    T(u"T-279", u"RST 1 (вектор 0008h)", 4, [0xCF],
      exp={u"PC": 0x0008, u"SP": D_STACK - 2}, mem=(D_STACK - 1, 0x02))
    T(u"T-280", u"CZ при Z=1 (вызов)", 4, [0xCC, 0x00, 0x03],
      init={u"PSW": Z_ON}, exp={u"PC": D_TARGET, u"SP": D_STACK - 2})
    T(u"T-281", u"CNZ при Z=1 (нет вызова)", 4, [0xC4, 0x00, 0x03],
      init={u"PSW": Z_ON}, exp={u"PC": CODE_BASE + 3, u"SP": D_STACK})
    T(u"T-282", u"RZ при Z=1 (возврат)", 4, [0xC8],
      init={u"PSW": Z_ON, u"SP": D_STACK - 2},
      exp={u"PC": D_TARGET, u"SP": D_STACK},
      preload=[(D_STACK - 2, 0x00), (D_STACK - 1, 0x03)])
    T(u"T-283", u"RNZ при Z=1 (нет возврата)", 4, [0xC0],
      init={u"PSW": Z_ON, u"SP": D_STACK - 2},
      exp={u"PC": CODE_BASE + 1, u"SP": D_STACK - 2})
    T(u"T-284", u"HLT (PC +1, затем стоп)", 4, [0x76], exp={u"PC": CODE_BASE + 1},
      tacts=4)
    T(u"T-285", u"EI (флаги целы)", 4, [0xFB], init={u"PSW": 0xD7},
      exp_psw=0xD7, psw_mask=PSW_MASK_NONE)
    T(u"T-286", u"DI (флаги целы)", 4, [0xF3], init={u"PSW": 0xD7},
      exp_psw=0xD7, psw_mask=PSW_MASK_NONE)
    T(u"T-287", u"NOP", 4, [0x00], init={u"PSW": 0xD7}, exp_psw=0xD7,
      psw_mask=PSW_MASK_NONE)


def build_group5():
    u"""Группа 5: память и адресация (границы)."""
    T(u"T-331", u"LDA 0000h (нижняя граница)", 5, [0x3A, 0x00, 0x00],
      exp={u"A": 0x5A}, preload=[(0x0000, 0x5A)])
    T(u"T-332", u"LDA FFFFh (верхняя граница)", 5, [0x3A, 0xFF, 0xFF],
      exp={u"A": 0x5A}, preload=[(0xFFFF, 0x5A)])
    T(u"T-333", u"STA FFFFh (запись за границей нет)", 5, [0x32, 0xFF, 0xFF],
      init={u"A": 0x77}, mem=(0xFFFF, 0x77))
    T(u"T-334", u"MOV A,M при HL=0000", 5, [0x7E], init={u"H": 0x00, u"L": 0x00},
      exp={u"A": 0x5A}, preload=[(0x0000, 0x5A)])
    # ОЖИДАНИЕ H/L ОБЯЗАТЕЛЬНО: программа делает LXI H,0200h, то есть H и L
    # МЕНЯЮТСЯ (H = 02h, L = 00h). Раньше exp их не задавал, и они сверялись
    # с начальными 06h/00h - кейс не мог пройти никогда.
    T(u"T-335", u"LXI H + MOV M,A (нет залипания старшего байта)", 5,
      [0x21, 0x00, 0x02, 0x77], init={u"A": 0x5A},
      exp={u"H": 0x02, u"L": 0x00}, mem=(0x0200, 0x5A), tacts=2)


def build_group6():
    u"""Группа 6: короткие программы целиком (влезают в 16 байт кода)."""
    # T-371: сложение двух ячеек с записью результата (12 байт, 6 тактов)
    prog371 = [0x3A, 0x00, 0x01,     # LDA 0100h
               0x47,                 # MOV B,A
               0x3A, 0x01, 0x01,     # LDA 0101h
               0x80,                 # ADD B
               0x32, 0x02, 0x01,     # STA 0102h
               0x76]                 # HLT
    T(u"T-371", u"25h+17h=3Ch в память", 6, prog371,
      preload=[(0x0100, 0x25), (0x0101, 0x17)], mem=(0x0102, 0x3C),
      exp={u"A": 0x3C, u"B": 0x25, u"PC": CODE_BASE + 12}, psw_mask=PSW_MASK_ALL,
      exp_psw=psw(p=1), tacts=6)
    # T-372: то же с переносом
    T(u"T-372", u"FFh+02h=01h с CY=1", 6, prog371,
      preload=[(0x0100, 0xFF), (0x0101, 0x02)], mem=(0x0102, 0x01),
      exp={u"A": 0x01, u"B": 0xFF, u"PC": CODE_BASE + 12}, psw_mask=PSW_MASK_ALL,
      exp_psw=psw(ac=1, cy=1), tacts=6)
    # T-373: обнуление с переносом
    T(u"T-373", u"80h+80h=00h Z=1 CY=1", 6, prog371,
      preload=[(0x0100, 0x80), (0x0101, 0x80)], mem=(0x0102, 0x00),
      exp={u"A": 0x00, u"B": 0x80, u"PC": CODE_BASE + 12}, psw_mask=PSW_MASK_ALL,
      exp_psw=psw(z=1, p=1, cy=1), tacts=6)
    # T-374: цикл MVI/DCR/JNZ/HLT - 12 тактов, 5 итераций
    prog374 = [0x3E, 0x05,             # MVI A,05h
               0x3D,                   # DCR A
               0xC2, 0x02, 0x02,       # JNZ 0202h
               0x76]                   # HLT
    T(u"T-374", u"цикл DCR/JNZ 5 итераций", 6, prog374,
      exp={u"A": 0x00, u"PC": CODE_BASE + 7}, psw_mask=PSW_MASK_ALL,
      exp_psw=psw(z=1, p=1), tacts=12)
    # T-375: сумма 5 чисел из памяти циклом (LXI H; MVI C; MVI A; ADD M; INX H;
    # DCR C; JNZ; STA; HLT) - 3+2+2+1+1+1+3+3+1 = 17 байт, не влезает;
    # поэтому упрощённый вариант: два числа подряд без цикла
    prog375 = [0x21, 0x00, 0x01,     # LXI H,0100h
               0x7E,                 # MOV A,M
               0x23,                 # INX H
               0x86,                 # ADD M
               0x32, 0x02, 0x01,     # STA 0102h
               0x76]                 # HLT
    T(u"T-375", u"MOV A,M + INX H + ADD M", 6, prog375,
      preload=[(0x0100, 0x01), (0x0101, 0x02)], mem=(0x0102, 0x03),
      exp={u"A": 0x03, u"H": 0x01, u"L": 0x01, u"PC": CODE_BASE + 10},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(p=1), tacts=6)


def build_group7():
    u"""Группа 7: синхронизация и порядок фаз (T-421..T-430)."""
    T(u"T-421", u"MOV A,A (чтение до записи)", 7, [0x7F],
      init={u"PSW": 0xD7}, exp_psw=0xD7, psw_mask=PSW_MASK_NONE)
    T(u"T-422", u"обмен A<->B через C", 7, [0x4F, 0x78, 0x41],
      init={u"A": 0xAA, u"B": 0x55}, exp={u"A": 0x55, u"B": 0xAA, u"C": 0xAA},
      tacts=3)
    T(u"T-423", u"ADD A,A (операнд до записи)", 7, [0x87], init={u"A": 0x21},
      exp={u"A": 0x42}, psw_mask=PSW_MASK_ALL, exp_psw=psw(p=1))
    T(u"T-424", u"INR A при A=FF (CY цел)", 7, [0x3C],
      init={u"A": 0xFF, u"PSW": psw(cy=1)}, exp={u"A": 0x00},
      psw_mask=PSW_MASK_SZP, exp_psw=psw(z=1, ac=1, p=1))
    T(u"T-425", u"MVI A,5Ah -> PC+2", 7, [0x3E, 0x5A], exp={u"A": 0x5A})
    T(u"T-426", u"цепочка 2+2+3 байта -> PC=0300h", 7,
      [0x3E, 0x5A, 0x06, 0x11, 0xC3, 0x00, 0x03],
      exp={u"A": 0x5A, u"B": 0x11, u"PC": D_TARGET}, tacts=3)
    T(u"T-427", u"JMP на 2 байта вперёд (нет двойного инкремента)", 7,
      [0xC3, 0x02, 0x02], exp={u"PC": CODE_BASE + 2})
    # XRA A обнуляет A и СТАВИТ флаги: Z=1, P=1. Раньше ожидание оставляло
    # флаги неизменными (маска 0), поэтому кейс не мог пройти никогда, хотя
    # эмулятор давал верный PSW=46h (видно в протоколе прогона).
    T(u"T-428", u"XRA A + JZ (флаги готовы сразу)", 7,
      [0xAF, 0xCA, 0x00, 0x03], exp={u"A": 0x00, u"PC": D_TARGET},
      psw_mask=PSW_MASK_ALL, exp_psw=psw(z=1, p=1), tacts=2)
    T(u"T-429", u"два одинаковых такта INR A подряд", 7, [0x3C, 0x3C],
      exp={u"A": 0x13}, psw_mask=PSW_MASK_ALL, exp_psw=psw(), tacts=2)
    # T-419 - не тест плана, а ПОДГОТОВКА T-430: ставит процессор в останов HLT,
    # чтобы следующий кейс начинался «из остановленного» состояния.
    T(u"T-419", u"HLT (подготовка T-430)", 7, [0x76], exp={u"PC": CODE_BASE + 1},
      tacts=2)
    # T-430: повтор T-421 сразу после HLT - раннер обязан снять останов и
    # восстановить регистры, иначе кейс даст FAIL от прошлого состояния.
    T(u"T-430", u"повтор T-421 после HLT", 7, [0x7F],
      init={u"PSW": 0xD7}, exp_psw=0xD7, psw_mask=PSW_MASK_NONE)


def build_all():
    del CASES[:]
    build_mov()
    build_mvi()
    build_group1()
    build_alu()
    build_group4()
    build_group5()
    build_group6()
    build_group7()
    # T-240: POP PSW восстанавливает ровно то, что положил PUSH PSW
    # (пара «туда-обратно» одной программой)
    prog240 = [0xF5, 0xF1]           # PUSH PSW ; POP PSW
    T(u"T-240", u"PUSH PSW + POP PSW", 3, prog240, init={u"A": 0x11, u"PSW": 0xD7},
      exp={u"A": 0x11}, psw_mask=PSW_MASK_ALL, exp_psw=0xD7, tacts=2)
    return CASES


# ======================================================================
# ТЕКСТ GVL_TEST
# ======================================================================
def _code_init(c):
    b = list(c[u"code"]) + [0] * (16 - len(c[u"code"]))
    return u"[%s]" % u", ".join([u"%d" % x for x in b])


def _cmd_bytes(text):
    u"""Строка команды -> 16 байт (с нулями до конца): данные для TEST_CPM."""
    b = [ord(ch) & 0xFF for ch in text]
    return (b + [0] * 16)[:16]


def _case_struct(c):
    i, e = c[u"init"], c[u"exp"]
    m = c[u"mem"]
    return (u"\t\t(Id := %d, Group := %d, Code := %s, CodeLen := %d, "
            u"Pre1Addr := 16#%04X, Pre1Val := %d, Pre2Addr := 16#%04X, Pre2Val := %d, "
            u"Pre3Addr := 16#%04X, Pre3Val := %d, "
            u"InitA := %d, InitB := %d, InitC := %d, InitD := %d, InitE := %d, "
            u"InitH := %d, InitL := %d, InitSP := 16#%04X, InitPC := 16#%04X, "
            u"InitPSW := 16#%02X, "
            u"ExpA := %d, ExpB := %d, ExpC := %d, ExpD := %d, ExpE := %d, "
            u"ExpH := %d, ExpL := %d, ExpSP := 16#%04X, ExpPC := 16#%04X, "
            u"ExpPSW := 16#%02X, PSWMask := 16#%02X, CheckMem := %s, "
            u"ExpMemAddr := 16#%04X, ExpMemVal := %d, MaxTacts := %d)"
            % (int(c[u"id"][2:]), c[u"group"], _code_init(c), len(c[u"code"]),
               c[u"pre"][0][0], c[u"pre"][0][1], c[u"pre"][1][0], c[u"pre"][1][1],
               c[u"pre"][2][0], c[u"pre"][2][1],
               i[u"A"], i[u"B"], i[u"C"], i[u"D"], i[u"E"], i[u"H"], i[u"L"],
               i[u"SP"], i[u"PC"], i[u"PSW"],
               e[u"A"], e[u"B"], e[u"C"], e[u"D"], e[u"E"], e[u"H"], e[u"L"],
               e[u"SP"], e[u"PC"], c[u"exp_psw"], c[u"mask"],
               u"TRUE" if c[u"check_mem"] else u"FALSE",
               m[0], m[1], c[u"tacts"]))


def gvl_test_text():
    u"""Текст GVL_TEST: данные тестов, состояние прогона и результаты."""
    cases = build_all()
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* ТЕСТОВЫЙ СЛОЙ ЭТАПА 4 (данные). Логика прогона - FBD.          *)")
    L.append(u"\t(* Здесь только ТЕСТОВЫЕ ДАННЫЕ (ST разрешён для данных) и          *)")
    L.append(u"\t(* переменные состояния/результатов, которые читает схема прогона  *)")
    L.append(u"\t(* и скрипт онлайн-прогона (отчёт PASS/FAIL).                     *)")
    L.append(u"\t(* Всего кейсов: %d.                                              *)"
             % len(cases))
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\tTests : ARRAY[0..%d] OF ST_TestCase := [" % (len(cases) - 1))
    L.append(u",\n".join([_case_struct(c) for c in cases]))
    L.append(u"\t];")
    L.append(u"")
    L.append(u"\t(* ==== ПРОГОН ==== *)")
    L.append(u"\tN_Cases   : INT := %d;  (* сколько кейсов в таблице *)" % len(cases))
    L.append(u"\tMode      : BYTE := 1;  (* 0=CP/M, 1=TEST_8080, 2=TEST_CPM, 3=TEST_IO *)")
    L.append(u"\tRun       : BOOL := TRUE;  (* разрешение прогона *)")
    # ЯВНЫЙ СИГНАЛ СБРОСА ПРОГОНА. Ставится хостом (скрипт прогона) и
    # снимается самой схемой TEST_8080 в конце того же скана.
    # Это единственно надёжный способ начать прогон с известного состояния:
    # локальные переменные POU (ph, idx, tact) и глобальные счётчики
    # сохраняются в проекте между запусками, а писать их по отдельности извне
    # НЕЛЬЗЯ - локальные недоступны, а на глобальные накладываются записи схемы
    # в том же скане (наблюдалось: Mode уходил 1 -> 2 -> 3 за два скана).
    L.append(u"\tReset     : BOOL;   (* сброс прогона в начальное состояние *)")
    L.append(u"\tIdx       : INT := 0;   (* номер текущего кейса *)")
    L.append(u"\tBusy      : BOOL;   (* кейс выполняется *)")
    L.append(u"\tDone8080  : BOOL;   (* набор 8080 пройден *)")
    L.append(u"\tDoneCpm   : BOOL;   (* набор CP/M пройден *)")
    L.append(u"\tDoneIo    : BOOL;   (* набор ввода-вывода пройден *)")
    L.append(u"\tPhase     : BYTE;   (* фаза автомата прогона (диагностика) *)")
    L.append(u"\tTact      : INT;    (* тактов выдано текущему кейсу *)")
    L.append(u"\tScans     : UDINT;  (* сканов с начала прогона *)")
    L.append(u"")
    L.append(u"\t(* ==== КОМАНДЫ, КОТОРЫЕ TEST_CPM НАБИРАЕТ В КОНСОЛЬ ==== *)")
    L.append(u"\t(* Это ДАННЫЕ: CCP отправляет их по одному знаку через HMI.    *)")
    L.append(u"\t(* 'DIR' + CR и 'TYPE README.TXT' + CR, добитые нулями до 16.  *)")
    L.append(u"\tCmd1 : ARRAY[0..15] OF BYTE := [%s];"
             % u", ".join([u"%d" % x for x in _cmd_bytes(u"DIR\r")]))
    L.append(u"\tCmd2 : ARRAY[0..15] OF BYTE := [%s];"
             % u", ".join([u"%d" % x for x in _cmd_bytes(u"TYPE README.TXT\r")]))
    L.append(u"")
    L.append(u"\t(* ==== РЕЗУЛЬТАТЫ 8080 ==== *)")
    L.append(u"\tResults   : ARRAY[0..%d] OF BOOL;   (* PASS по каждому кейсу *)"
             % (len(cases) - 1))
    L.append(u"\tActA      : ARRAY[0..%d] OF BYTE;   (* факт: аккумулятор *)"
             % (len(cases) - 1))
    L.append(u"\tActPC     : ARRAY[0..%d] OF WORD;   (* факт: PC *)"
             % (len(cases) - 1))
    L.append(u"\tActSP     : ARRAY[0..%d] OF WORD;   (* факт: SP *)"
             % (len(cases) - 1))
    L.append(u"\tActPSW    : ARRAY[0..%d] OF BYTE;   (* факт: флаги *)"
             % (len(cases) - 1))
    # ДИАГНОСТИКА ПО КАЖДОМУ КЕЙСУ (фаза B). Ловим последнее состояние
    # декодера в такте: реальный опкод, класс операции и код пары.
    # Это единственный способ увидеть, ЧТО процессор исполнил на самом деле:
    # поля декодера GVL_CPU.C_* живут один скан и при опросе снаружи почти
    # всегда нулевые (проверено пробой zz_tact.py - 2 сэмпла за 6 секунд).
    for _nm, _t, _c in ((u"ActIR", u"BYTE", u"факт: опкод последнего такта"),
                        (u"ActCls", u"BYTE", u"факт: класс операции"),
                        (u"ActRP", u"BYTE", u"факт: код пары"),
                        (u"ActUnc", u"BOOL", u"факт: безусловная форма"),
                        (u"ActAddr", u"WORD", u"факт: эффективный адрес HL"),
                        (u"ActPre", u"BYTE", u"факт: что прочиталось по адресу предустановки"),
                        (u"ActW", u"BYTE", u"факт: значение с выхода блока записи")):
        L.append(u"\t%s : ARRAY[0..%d] OF %s;   (* %s *)"
                 % (_nm, len(cases) - 1, _t, _c))
    L.append(u"\tPass_Cnt  : INT;    (* PASS *)")
    L.append(u"\tFail_Cnt  : INT;    (* FAIL *)")
    L.append(u"\tFirst_Fail: INT := -1;  (* номер первого FAIL (-1 = нет) *)")
    L.append(u"")
    L.append(u"\t(* ==== РЕЗУЛЬТАТЫ CP/M (TEST_CPM) ==== *)")
    L.append(u"\tCpm_Step  : BYTE;   (* шаг проверки CP/M *)")
    L.append(u"\tCpm_Base  : INT;    (* длина журнала консоли до команды *)")
    L.append(u"\tCpm_Res   : ARRAY[0..15] OF BOOL;  (* PASS/FAIL шагов CP/M *)")
    L.append(u"\tCpm_Phase : INT;   (* отладка: фаза теста CP/M *)")
    L.append(u"\tCpm_Pass  : INT;    (* PASS в наборе CP/M *)")
    L.append(u"\tCpm_Fail  : INT;    (* FAIL в наборе CP/M *)")
    L.append(u"\tCpm_Typed : BYTE;   (* сколько символов введено в консоль *)")
    L.append(u"\tCpm_LogLen: INT;    (* длина журнала консоли сейчас *)")
    L.append(u"\tCpm_Prompt: BOOL;   (* приглашение A> найдено *)")
    L.append(u"\tCpm_On    : BYTE;   (* отладка: идёт подача знаков (feed) *)")
    L.append(u"\t(* Снимок журнала консоли на момент завершения команды DIR:  *)")
    L.append(u"\t(* журнал - КОЛЬЦЕВОЙ буфер на 256 байт, и к концу прогона    *)")
    L.append(u"\t(* каталог уже перезаписан приглашениями, поэтому истинные    *)")
    L.append(u"\t(* имена файлов сохраняются в отдельном массиве.             *)")
    L.append(u"\tCpm_Snap  : ARRAY[0..31] OF BYTE;")
    L.append(u"")
    L.append(u"\t(* ==== РЕЗУЛЬТАТЫ ВВОДА-ВЫВОДА (TEST_IO) ==== *)")
    L.append(u"\tIo_Step   : BYTE;   (* шаг проверки ввода-вывода *)")
    L.append(u"\tIo_Res    : ARRAY[0..15] OF BOOL;  (* PASS/FAIL шагов IO *)")
    L.append(u"\tIo_Pass   : INT;    (* PASS в наборе IO *)")
    L.append(u"\tIo_Fail   : INT;    (* FAIL в наборе IO *)")
    L.append(u"\tIo_Wd_Prev: BOOL;   (* предыдущий признак тайм-аута watchdog *)")
    L.append(u"\tIo_Wd_Hit : BOOL;   (* watchdog сработал в ходе теста *)")
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


# ======================================================================
# СВОДКА ДЛЯ ОТЧЁТА (обычный Python, вне CODESYS)
# ======================================================================
def report_rows():
    u"""Таблица «ID - группа - имя - программа - ожидание» для отчёта."""
    rows = []
    for c in build_all():
        i, e = c[u"init"], c[u"exp"]
        code = u" ".join([u"%02X" % b for b in c[u"code"]])
        rows.append((c[u"id"], c[u"group"], c[u"name"], code,
                     u"A=%02X PC=%04X PSW=%02X/M%02X tacts=%d"
                     % (e[u"A"], e[u"PC"], c[u"exp_psw"], c[u"mask"], c[u"tacts"])))
    return rows


def summary():
    u"""Сколько кейсов получилось по группам."""
    d = {}
    for c in build_all():
        d[c[u"group"]] = d.get(c[u"group"], 0) + 1
    return d


if __name__ == u"__main__":
    import io
    cs = build_all()
    print("cases=%d" % len(cs))
    print("by group: %s" % summary())
    t = gvl_test_text()
    print("GVL_TEST text: %d chars" % len(t))
    for r in report_rows()[:5]:
        print(r)
