# -*- coding: utf-8 -*-
u"""Порт доступа CP/M к регистрам процессора (расширение FB_CPU8080_FULL).

ЗАДАЧА. Регистровый файл, PC, SP и флаги лежат ВНУТРИ FB_CPU8080_FULL, а слою
CP/M нужно их читать и писать: функция BDOS получает параметры в регистрах и
обязана вернуть результат в A/HL, снять адрес возврата со стека (SP+2) и
подменить PC. Прямого доступа снаружи нет, поэтому в процессор добавляется
ПОРТ СО СТОРОНЫ CP/M - точно так же, как в реальном 8080 есть шины, к которым
подключён контроллер ПДП.

КАК ЭТО СДЕЛАНО (и почему именно так).
  1. Ядро (pou_cpu_full.py) НЕ ПРАВИТСЯ: модуль вызывает make_cpu_full() и
     дополняет готовый POU - новые сети и новые входы/выходы интерфейса.
  2. Чтение: последняя сеть POU выкладывает значения регистров в выходные
     порты CPM_A..CPM_L, CPM_PC, CPM_SP, CPM_PSW. Значения берутся из уже
     существующих экземпляров (regs.A, pc.Q, sp.Q, flags.PSW) и обязательно
     защёлкиваются в переменные POU (правило 9.1 журнала).
  3. Запись: НЕ добавляется второй вызов регистрового файла (экземпляр один, а
     повторный вызов - лишний риск для импортёра). Вместо этого в СУЩЕСТВУЮЩИЕ
     сети записи (регистры, флаги, PC/SP) добавляется ещё один источник:
     сигналы CPM_* через SEL и OR подмешиваются к обычным сигналам такта.
     Во время трапа процессор не выполняет такт (run_i = FALSE), поэтому
     конфликта двух источников нет, а запись от CP/M попадает в штатное место
     схемы - в ту же сеть, где регистры пишет сам процессор.
  4. Сеть дешифрации порта ставится ПЕРЕД сетью регистрового файла, поэтому
     все ссылки идут "назад" - как требует импортёр CODESYS.

ИНТЕРФЕЙС (совпадает с заданием):
  входы : CPM_WE, CPM_LD1, CPM_Sel1, CPM_Data1, CPM_LD2, CPM_Sel2, CPM_Data2
  выходы: CPM_A..CPM_L, CPM_PC, CPM_SP, CPM_PSW
  CPM_Selk: 0=A 1=B 2=C 3=D 4=E 5=H 6=L 7=PC 8=SP 9=Flags
  Запись происходит при CPM_WE AND CPM_LDk. Для A..L и флагов берётся младший
  байт CPM_Datak, для PC/SP - всё слово.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
import pou_cpu_full
from fbd_xml import Pou
from pou_cpm_defs import (I, K, NOT, AND, OR, EQ, LT, SEL, ADD, W2B, ORL,
                          latch, B)

# локальные переменные-защёлки порта
PORT_LOCALS = (
    (u"cpm_wrreg1", u"BOOL", u"запись регистра A..L через порт 1"),
    (u"cpm_dst1", u"BYTE", u"код регистра-приёмника порта 1 (0=B..5=L, 7=A)"),
    (u"cpm_d8_1", u"BYTE", u"младший байт данных порта 1"),
    (u"cpm_wrreg2", u"BOOL", u"запись регистра A..L через порт 2"),
    (u"cpm_dst2", u"BYTE", u"код регистра-приёмника порта 2"),
    (u"cpm_d8_2", u"BYTE", u"младший байт данных порта 2"),
    (u"cpm_pc_wr", u"BOOL", u"запись PC со стороны CP/M"),
    (u"cpm_pc_data", u"WORD", u"новое значение PC"),
    (u"cpm_sp_wr", u"BOOL", u"запись SP со стороны CP/M"),
    (u"cpm_sp_data", u"WORD", u"новое значение SP"),
    (u"cpm_psw_wr", u"BOOL", u"загрузка флагов из байта состояния"),
    (u"cpm_psw_data", u"BYTE", u"байт состояния для загрузки флагов"),
    (u"cpm_a_l", u"BYTE", u"защёлка регистра A"),
    (u"cpm_b_l", u"BYTE", u"защёлка регистра B"),
    (u"cpm_c_l", u"BYTE", u"защёлка регистра C"),
    (u"cpm_d_l", u"BYTE", u"защёлка регистра D"),
    (u"cpm_e_l", u"BYTE", u"защёлка регистра E"),
    (u"cpm_h_l", u"BYTE", u"защёлка регистра H"),
    (u"cpm_l_l", u"BYTE", u"защёлка регистра L"),
    (u"cpm_pc_l", u"WORD", u"защёлка PC"),
    (u"cpm_sp_l", u"WORD", u"защёлка SP"),
    (u"cpm_psw_l", u"BYTE", u"защёлка байта состояния"),
)

# выходные порты процессора
PORT_OUTPUTS = (
    (u"CPM_A", u"BYTE", u"регистр A для слоя CP/M"),
    (u"CPM_B", u"BYTE", u"регистр B для слоя CP/M"),
    (u"CPM_C", u"BYTE", u"регистр C для слоя CP/M"),
    (u"CPM_D", u"BYTE", u"регистр D для слоя CP/M"),
    (u"CPM_E", u"BYTE", u"регистр E для слоя CP/M"),
    (u"CPM_H", u"BYTE", u"регистр H для слоя CP/M"),
    (u"CPM_L", u"BYTE", u"регистр L для слоя CP/M"),
    (u"CPM_PC", u"WORD", u"счётчик команд для слоя CP/M"),
    (u"CPM_SP", u"WORD", u"указатель стека для слоя CP/M"),
    (u"CPM_PSW", u"BYTE", u"байт состояния (флаги) для слоя CP/M"),
)

PORT_INPUTS = (
    (u"CPM_WE", u"BOOL", u"общее разрешение записи регистров со стороны CP/M"),
    (u"CPM_Sel1", u"BYTE", u"номер регистра канала 1: 0=A..6=L, 7=PC, 8=SP, 9=Flags"),
    (u"CPM_Data1", u"WORD", u"значение канала 1 (для A..L и флагов - младший байт)"),
    (u"CPM_LD1", u"BOOL", u"строб записи канала 1"),
    (u"CPM_Sel2", u"BYTE", u"номер регистра канала 2"),
    (u"CPM_Data2", u"WORD", u"значение канала 2"),
    (u"CPM_LD2", u"BOOL", u"строб записи канала 2"),
)

# имя вывода -> имя защёлки -> имя выходного порта
PUBLISH = (
    (u"regs.A", u"cpm_a_l", u"CPM_A"),
    (u"regs.B", u"cpm_b_l", u"CPM_B"),
    (u"regs.C", u"cpm_c_l", u"CPM_C"),
    (u"regs.D", u"cpm_d_l", u"CPM_D"),
    (u"regs.E", u"cpm_e_l", u"CPM_E"),
    (u"regs.H", u"cpm_h_l", u"CPM_H"),
    (u"regs.L", u"cpm_l_l", u"CPM_L"),
    (u"pc.Q", u"cpm_pc_l", u"CPM_PC"),
    (u"sp.Q", u"cpm_sp_l", u"CPM_SP"),
    (u"flags.PSW", u"cpm_psw_l", u"CPM_PSW"),
)


def _net_of(p, inst):
    u"""Индекс сети и сам элемент вызова экземпляра inst."""
    for k, net in enumerate(p.networks):
        for it in net._items:
            if it[0] == u"block" and p._inst.get(it[1]) == inst:
                return k, net, it
    raise ValueError(u"не найден вызов экземпляра %s" % inst)


def _pins(it):
    return dict([(pin, src) for pin, src in it[3]])


def _rebuild(it, repl):
    u"""Собрать элемент блока с заменёнными источниками входов.

    Сам элемент из списка сети уже извлечён (см. ниже), поэтому здесь только
    собирается новый кортеж: список входов пересобирается по именам выводов.
    """
    ins = [(pin, repl.get(pin, src)) for pin, src in it[3]]
    return (it[0], it[1], it[2], ins, it[4], it[5], it[6])


def make_cpu_cpm():
    u"""FB_CPU8080_FULL с портом доступа CP/M (ядро + патч порта)."""
    p = pou_cpu_full.make_cpu_full()
    p.doc = (p.doc + u"\n\tДОПОЛНЕНО СЛОЕМ CP/M (этап 3.2): порт доступа к регистрам.\n"
             u"\tВходы CPM_WE/CPM_Sel1..2/CPM_Data1..2/CPM_LD1..2 - запись регистров\n"
             u"\tсо стороны CP/M (коды: 0=A..6=L, 7=PC, 8=SP, 9=Flags).\n"
             u"\tВыходы CPM_A..CPM_L, CPM_PC, CPM_SP, CPM_PSW - текущие значения\n"
             u"\tрегистров для слоя CP/M. Запись применяется в тех же сетях, где\n"
             u"\tрегистры пишет сам процессор, поэтому отдельного такта не требует.")

    for nm, t, c in PORT_INPUTS:
        p.var_in(nm, t, c)
    for nm, t, c in PORT_OUTPUTS:
        p.var_out(nm, t, c)
    for nm, t, c in PORT_LOCALS:
        p.var(nm, t, c)

    # ------------------------------------------------------------------
    # СЕТЬ ДЕШИФРАЦИИ ПОРТА (ставится перед сетью регистрового файла)
    # ------------------------------------------------------------------
    k_regs, net_regs, it_regs = _net_of(p, u"regs")
    n = p.network(u"СЕТЬ 25А (ПОРТ CP/M). Дешифрация каналов записи регистров")
    we = I(n, u"CPM_WE")
    sel1 = I(n, u"CPM_Sel1")
    sel2 = I(n, u"CPM_Sel2")
    ld1 = I(n, u"CPM_LD1")
    ld2 = I(n, u"CPM_LD2")
    d1 = I(n, u"CPM_Data1")
    d2 = I(n, u"CPM_Data2")
    # стробы записи: канал активен, когда включён порт и выставлен его строб
    wr1 = AND(n, ld1, we)
    wr2 = AND(n, ld2, we, fbd_xml.COL_BLK + 130)
    # "регистр A..L" - это коды 0..6; коды 7/8/9 - это PC, SP и флаги
    isreg1 = LT(n, sel1, I(n, B % 7), fbd_xml.COL_BLK + 260)
    isreg2 = LT(n, sel2, I(n, B % 7), fbd_xml.COL_BLK + 390)
    latch(n, u"cpm_wrreg1", AND(n, wr1, isreg1, fbd_xml.COL_BLK + 520))
    latch(n, u"cpm_wrreg2", AND(n, wr2, isreg2, fbd_xml.COL_BLK + 650))
    # код регистра для FB_RegFileQ: 0=B 1=C 2=D 3=E 4=H 5=L 7=A.
    # Из кода CP/M (0=A 1=B ... 6=L) он получается как (код + 7) AND 7.
    latch(n, u"cpm_dst1", AND(n, ADD(n, sel1, I(n, B % 7), fbd_xml.COL_BLK + 780),
                              I(n, B % 7), fbd_xml.COL_BLK + 900))
    latch(n, u"cpm_dst2", AND(n, ADD(n, sel2, I(n, B % 7), fbd_xml.COL_BLK + 1030),
                              I(n, B % 7), fbd_xml.COL_BLK + 1150))
    latch(n, u"cpm_d8_1", W2B(n, d1, fbd_xml.COL_BLK + 1280))
    latch(n, u"cpm_d8_2", W2B(n, d2, fbd_xml.COL_BLK + 1390))
    # PC: код 7, SP: код 8, флаги: код 9 - по каждому каналу
    pc1 = AND(n, wr1, EQ(n, sel1, I(n, B % 7), fbd_xml.COL_BLK + 1520),
              fbd_xml.COL_BLK + 1630)
    pc2 = AND(n, wr2, EQ(n, sel2, I(n, B % 7), fbd_xml.COL_BLK + 1760),
              fbd_xml.COL_BLK + 1870)
    sp1 = AND(n, wr1, EQ(n, sel1, I(n, B % 8), fbd_xml.COL_BLK + 2000),
              fbd_xml.COL_BLK + 2110)
    sp2 = AND(n, wr2, EQ(n, sel2, I(n, B % 8), fbd_xml.COL_BLK + 2240),
              fbd_xml.COL_BLK + 2350)
    fs1 = AND(n, wr1, EQ(n, sel1, I(n, B % 9), fbd_xml.COL_BLK + 2480),
              fbd_xml.COL_BLK + 2590)
    fs2 = AND(n, wr2, EQ(n, sel2, I(n, B % 9), fbd_xml.COL_BLK + 2720),
              fbd_xml.COL_BLK + 2830)
    latch(n, u"cpm_pc_wr", OR(n, pc1, pc2, fbd_xml.COL_BLK + 2960))
    latch(n, u"cpm_sp_wr", OR(n, sp1, sp2, fbd_xml.COL_BLK + 3090))
    latch(n, u"cpm_psw_wr", OR(n, fs1, fs2, fbd_xml.COL_BLK + 3220))
    # данные: если пишет канал 2, берём его значение
    latch(n, u"cpm_pc_data", SEL(n, pc2, d1, d2, fbd_xml.COL_BLK + 3350))
    latch(n, u"cpm_sp_data", SEL(n, sp2, d1, d2, fbd_xml.COL_BLK + 3470))
    latch(n, u"cpm_psw_data", SEL(n, fs2, I(n, u"cpm_d8_1"), I(n, u"cpm_d8_2"),
                                  fbd_xml.COL_BLK + 3590))
    # перенести сеть порта ПЕРЕД сетью регистрового файла
    p.networks.remove(n)
    p.networks.insert(k_regs, n)

    # ------------------------------------------------------------------
    # ПАТЧ: регистровый файл - добавляем канал CP/M к портам 1 и 2
    # ------------------------------------------------------------------
    net_regs._items.remove(it_regs)
    pin = _pins(it_regs)
    repl = {}
    repl[u"Data1"] = SEL(net_regs, I(net_regs, u"cpm_wrreg1"), pin[u"Data1"],
                         I(net_regs, u"cpm_d8_1"))
    repl[u"Dst1"] = SEL(net_regs, I(net_regs, u"cpm_wrreg1"), pin[u"Dst1"],
                        I(net_regs, u"cpm_dst1"))
    repl[u"Wr1"] = OR(net_regs, pin[u"Wr1"], I(net_regs, u"cpm_wrreg1"))
    repl[u"Data2"] = SEL(net_regs, I(net_regs, u"cpm_wrreg2"), pin[u"Data2"],
                         I(net_regs, u"cpm_d8_2"), fbd_xml.COL_BLK + 200)
    repl[u"Dst2"] = SEL(net_regs, I(net_regs, u"cpm_wrreg2"), pin[u"Dst2"],
                        I(net_regs, u"cpm_dst2"), fbd_xml.COL_BLK + 200)
    repl[u"Wr2"] = OR(net_regs, pin[u"Wr2"], I(net_regs, u"cpm_wrreg2"),
                      fbd_xml.COL_BLK + 200)
    it_regs = _rebuild(it_regs, repl)
    net_regs._items.append(it_regs)

    # ------------------------------------------------------------------
    # ПАТЧ: флаги - POP PSW или загрузка байта состояния от CP/M
    # ------------------------------------------------------------------
    _k, net_f, it_f = _net_of(p, u"flags")
    net_f._items.remove(it_f)
    pin = _pins(it_f)
    repl = {}
    repl[u"PSW_In"] = SEL(net_f, I(net_f, u"cpm_psw_wr"), pin[u"PSW_In"],
                          I(net_f, u"cpm_psw_data"))
    repl[u"LD_PSW"] = OR(net_f, pin[u"LD_PSW"], I(net_f, u"cpm_psw_wr"))
    it_f = _rebuild(it_f, repl)
    net_f._items.append(it_f)

    # ------------------------------------------------------------------
    # ПАТЧ: PC и SP - к обычной записи добавляется запись от CP/M
    # ------------------------------------------------------------------
    _k, net_p, it_p = _net_of(p, u"pc")
    _k2, net_s, it_s = _net_of(p, u"sp")
    assert net_p is net_s
    net_p._items.remove(it_p)
    net_p._items.remove(it_s)
    pin = _pins(it_p)
    repl = {}
    repl[u"LD"] = OR(net_p, pin[u"LD"], I(net_p, u"cpm_pc_wr"))
    repl[u"D"] = SEL(net_p, I(net_p, u"cpm_pc_wr"), pin[u"D"], I(net_p, u"cpm_pc_data"))
    it_p = _rebuild(it_p, repl)
    net_p._items.append(it_p)
    pin = _pins(it_s)
    repl = {}
    repl[u"LD"] = OR(net_p, pin[u"LD"], I(net_p, u"cpm_sp_wr"))
    repl[u"D"] = SEL(net_p, I(net_p, u"cpm_sp_wr"), pin[u"D"], I(net_p, u"cpm_sp_data"))
    it_s = _rebuild(it_s, repl)
    net_p._items.append(it_s)

    # ------------------------------------------------------------------
    # ПУБЛИКАЦИЯ РЕГИСТРОВ (последняя сеть: значения - итог такта и порта)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 30 (ПОРТ CP/M). Публикация регистров, PC, SP и флагов")
    for src, loc, out in PUBLISH:
        latch(n, loc, I(n, src))
        n.outvar(out, I(n, loc))
    return p


ALL = (make_cpu_cpm,)
