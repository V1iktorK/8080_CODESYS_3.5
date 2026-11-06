# -*- coding: utf-8 -*-
u"""BIOS CP/M 2.2 на FBD: 17 функций отдельными FB + диспетчер FB_BIOS.

ПОЧЕМУ ТАК. Ассемблера 8080 в системе нет, исходников BIOS тоже, поэтому BIOS
реализован методом HLE (high level emulation): в эмулируемой памяти лежит
таблица переходов (0E000h, 17 записей по 3 байта, каждая - JMP 0FE00h+3*i), а
сами функции написаны схемами. Программа CP/M вызывает BIOS по стандартным
адресам и получает стандартное поведение.

ДИСПЕТЧЕР FB_BIOS определяет, какая функция вызвана, по PC (номер функции
считается в FB_CPM_Trap и публикуется в GVL_CPM.BIOS_Func: сравниваются сами
адреса, деление на 3 в схеме не нужно) и передаёт всем 17 блокам сигнал
разрешения. Выбранный блок выполняет функцию и выставляет GVL_CPM.Func_Done -
квитанцию, по которой трап возвращает регистры и PC.

ЧТО РЕАЛИЗОВАНО ПОЛНОСТЬЮ: BOOT, WBOOT, CONST, CONIN, CONOUT, HOME, SELDSK,
SETTRK, SETSEC, SETDMA, READ, WRITE, LISTST, SECTRAN.
ЧТО ЗАГЛУШКИ (честно): LIST (5), PUNCH (6), READER (7) - устройства в наборе
нет, символ отбрасывается, счётчик Unimpl_Cnt растёт.

ОБРАЩЕНИЕ К ПАМЯТИ И ДИСКУ делается прямо из FBD-выражений:
GVL_MEM.Memory[адрес] и GVL_DISK.Disk[адрес] - так же, как в FB_Memory64K.
Адрес всегда маскируется, чтобы индекс не вышел за границу массива.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
import pou_cpm_defs as D
from pou_cpm_defs import (I, AND, OR, EQ, NE, LT, SEL, ADD, SUB, MUL, SHL, W2B,
                          MOD, ORL, CHAIN, B, H, W, U1)


def _head(num, name, doc, extra=None):
    u"""Общая часть функции BIOS: вход Enable, признак hit, выход Done."""
    p = Pou(u"FB_BIOS_" + name, u"functionBlock",
            doc=u"BIOS, функция %d (%s): %s\n"
                u"\tВызывается диспетчером FB_BIOS, когда PC попал на ловушку\n"
                u"\t0FE00h+3*%d. Вход Enable - 'эта функция выбрана и ещё не выполнена'.\n"
                u"\tПараметры берутся из GVL_CPM (регистры публикует процессор через\n"
                u"\tпорт CP/M). Результат пишется в GVL_CPM.Ret_Val / Ret_HL,\n"
                u"\tквитанция - GVL_CPM.Func_Done."
                % (num, name, doc, num))
    p.var_in(u"Enable", u"BOOL", u"функция BIOS выбрана и ещё не выполнена")
    p.var(u"hit", u"BOOL", u"выбрана именно эта функция")
    p.var(u"done_gate", u"BOOL", u"функция выполнена в этом скане")
    p.var(u"ch", u"BYTE", u"выводимый символ")
    p.var(u"log_i", u"INT", u"индекс в журнале консоли")
    if extra:
        for nm, t, c in extra:
            p.var(nm, t, c)
    p.var(u"cnt_inc", u"UDINT", u"счётчик для диагностики")
    p.var_out(u"Done", u"BOOL", u"функция выполнена")
    n = p.network(u"СЕТЬ 1. Выбор функции: BIOS_Func = %d (%s)" % (num, name))
    n.outvar(u"hit", AND(n, I(n, u"Enable"),
                         EQ(n, I(n, u"GVL_CPM.BIOS_Func"), I(n, B % num),
                            fbd_xml.COL_BLK + 200),
                         fbd_xml.COL_BLK + 320))
    return p


def _con_log(p, gate):
    u"""Символ консоли: счётчик длины + запись в журнал Con_Log.

    Массив пишется ЗДЕСЬ, в сетях этого же POU, и ТОЛЬКО по КОНСТАНТНЫМ
    индексам: запись по вычисляемому индексу импортёр теряет. Символ ch
    и признак gate - ЛОКАЛЬНЫЕ величины, поэтому нет задержки в скан,
    из-за которой условные записи через GVL-сигнал не срабатывали
    (замер: LogWr через GVL ни разу не был TRUE, а длина росла).
    """
    n = p.network(u"СЕТЬ: символ консоли - счётчик длины журнала")
    n.outvar(u"GVL_CPM.Con_Log_Len",
             SEL(n, gate, I(n, u"GVL_CPM.Con_Log_Len"),
                 ADD(n, I(n, u"GVL_CPM.Con_Log_Len"), I(n, u"INT#1"),
                     fbd_xml.COL_BLK + 460), fbd_xml.COL_BLK + 580))
    for bank in range(8):
        n = p.network(u"СЕТЬ: журнал консоли, индексы %d..%d"
                       % (bank * 32, bank * 32 + 31))
        idx_expr = MOD(n, ADD(n, I(n, u"GVL_CPM.Con_Log_Len"),
                             I(n, u"INT#255"), fbd_xml.COL_BLK + 60),
                        I(n, u"INT#256"), fbd_xml.COL_BLK + 120)
        for k in range(bank * 32, bank * 32 + 32):
            e = u"GVL_CPM.Con_Log[%d]" % k
            hit = AND(n, gate,
                      EQ(n, idx_expr, I(n, u"INT#%d" % k),
                         x=fbd_xml.COL_BLK + 130 * (k % 8), y=40 + 30 * (k % 32)),
                      x=fbd_xml.COL_BLK + 1100 + 130 * (k % 8),
                      y=40 + 30 * (k % 32))
            n.outvar(e, SEL(n, hit, I(n, e), I(n, u"ch"),
                            x=fbd_xml.COL_BLK + 2100 + 130 * (k % 8),
                            y=40 + 30 * (k % 32)))


def _finish(p, num, note=u""):
    u"""Сеть квитанции: Done, Func_Done, счётчики диагностики."""
    n = p.network(u"СЕТЬ ПОСЛЕДНЯЯ. Квитанция и диагностика%s" % (u" - " + note if note else u""))
    n.outvar(u"Done", I(n, u"done_gate"))
    n.outvar(u"GVL_CPM.Func_Done", SEL(n, I(n, u"done_gate"),
                                       I(n, u"GVL_CPM.Func_Done"), I(n, u"TRUE")))
    n.outvar(u"cnt_inc", ADD(n, I(n, u"GVL_CPM.Diag.BIOS_Cnt"), I(n, U1),
                             fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Diag.BIOS_Cnt",
             SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Diag.BIOS_Cnt"),
                 I(n, u"cnt_inc"), fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.Diag.Last_BIOS",
             SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Diag.Last_BIOS"),
                 I(n, B % num), fbd_xml.COL_BLK + 440))


def _unimpl(p, name):
    u"""Отметить обращение к нереализованному устройству."""
    n = p.network(u"СЕТЬ: счётчик нереализованных обращений (устройства %s нет)" % name)
    n.outvar(u"cnt_inc", ADD(n, I(n, u"GVL_CPM.Diag.Unimpl_Cnt"), I(n, U1)))
    n.outvar(u"GVL_CPM.Diag.Unimpl_Cnt",
             SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Diag.Unimpl_Cnt"),
                 I(n, u"cnt_inc"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Diag.Last_Err", SEL(n, I(n, u"done_gate"),
                                           I(n, u"GVL_CPM.Diag.Last_Err"),
                                           I(n, B % 5), fbd_xml.COL_BLK + 340))


def _boot(num, name, doc):
    u"""BOOT и WBOOT: старт системы и перезагрузка CCP - переход на 0F100h."""
    p = _head(num, name, doc)
    n = p.network(u"СЕТЬ 2. Переход на точку входа CCP (0F100h) со свежим стеком")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Jump_Req", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Jump_Req"),
                                      I(n, u"TRUE")))
    n.outvar(u"GVL_CPM.Jump_PC", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Jump_PC"),
                                     I(n, W % D.CCP_ENTRY), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Jump_SP", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Jump_SP"),
                                     I(n, W % D.STACK_TOP), fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 440))
    _finish(p, num, u"переход на CCP")
    return p


def make_boot():
    return _boot(0, u"BOOT", u"холодный старт: переход на CCP")


def make_wboot():
    return _boot(1, u"WBOOT", u"тёплый старт: перезагрузка CCP")


def make_const():
    p = _head(2, u"CONST", u"состояние консоли: A=FFh, если символ готов")
    n = p.network(u"СЕТЬ 2. A := FFh, если есть введённый символ, иначе 00h")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val",
             SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                 SEL(n, I(n, u"GVL_CPM.ConIn_Ready"), I(n, H % 0x00),
                     I(n, H % 0xFF), fbd_xml.COL_BLK + 200),
                 fbd_xml.COL_BLK + 340))
    _finish(p, 2)
    return p


def make_conin():
    p = _head(3, u"CONIN", u"ввод символа с консоли в A (ждёт готовности)")
    n = p.network(u"СЕТЬ 2. Ждём символ: как только он готов - забираем в A")
    n.outvar(u"done_gate", AND(n, I(n, u"hit"), I(n, u"GVL_CPM.ConIn_Ready"),
                               fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"GVL_CPM.ConIn_Char"),
                                     fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.ConIn_Ready", SEL(n, I(n, u"done_gate"),
                                         I(n, u"GVL_CPM.ConIn_Ready"), I(n, u"FALSE"),
                                         fbd_xml.COL_BLK + 440))
    _finish(p, 3, u"ждёт символ от HMI")
    return p


def make_conout():
    p = _head(4, u"CONOUT", u"вывод символа из C на консоль")
    n = p.network(u"СЕТЬ 2. Символ из регистра C - в консоль")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"ch", I(n, u"GVL_CPM.Reg_C"))
    n.outvar(u"GVL_CPM.ConOut_Char", SEL(n, I(n, u"hit"),
                                         I(n, u"GVL_CPM.ConOut_Char"), I(n, u"ch")))
    n.outvar(u"GVL_CPM.ConOut_Ready", I(n, u"hit"))
    _con_log(p, I(n, u"hit"))
    _finish(p, 4)
    return p


def make_list():
    p = _head(5, u"LIST", u"вывод на устройство LIST (устройства нет - заглушка)")
    n = p.network(u"СЕТЬ 2. Символ из C отбрасывается, A := 0")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0)))
    _unimpl(p, u"LIST")
    _finish(p, 5, u"заглушка")
    return p


def make_punch():
    p = _head(6, u"PUNCH", u"вывод на перфоратор (устройства нет - заглушка)")
    n = p.network(u"СЕТЬ 2. Символ из C отбрасывается, A := 0")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0)))
    _unimpl(p, u"PUNCH")
    _finish(p, 6, u"заглушка")
    return p


def make_reader():
    p = _head(7, u"READER", u"ввод с устройства READER (устройства нет - заглушка)")
    n = p.network(u"СЕТЬ 2. A := 1Ah (признак конца ввода)")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, H % 0x1A)))
    _unimpl(p, u"READER")
    _finish(p, 7, u"заглушка")
    return p


def make_home():
    p = _head(8, u"HOME", u"установить дорожку 0")
    n = p.network(u"СЕТЬ 2. Дорожка := 0")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Disk_Track", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Disk_Track"),
                                        I(n, W % 0)))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 200))
    _finish(p, 8)
    return p


def make_seldsk():
    p = _head(9, u"SELDSK", u"выбор диска из C; HL = адрес DPH, 0 - диска нет")
    n = p.network(u"СЕТЬ 2. Дисков два (A и B): HL := 0FF10h (DPH), иначе HL := 0")
    n.outvar(u"done_gate", I(n, u"hit"))
    ok = LT(n, I(n, u"GVL_CPM.Reg_C"), I(n, B % 2), fbd_xml.COL_BLK + 200)
    n.outvar(u"GVL_CPM.Ret_HL",
             SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL"),
                 SEL(n, ok, I(n, W % 0), I(n, W % D.DPH_ADDR),
                     fbd_xml.COL_BLK + 340), fbd_xml.COL_BLK + 480))
    n.outvar(u"GVL_CPM.Disk_Sel", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Disk_Sel"),
                                      SEL(n, ok, I(n, u"GVL_CPM.Disk_Sel"),
                                          I(n, u"GVL_CPM.Reg_C"),
                                          fbd_xml.COL_BLK + 620),
                                      fbd_xml.COL_BLK + 760))
    n.outvar(u"GVL_CPM.Ret_HL_En", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL_En"),
                                       I(n, u"TRUE"), fbd_xml.COL_BLK + 880))
    _finish(p, 9)
    return p


def make_settrk():
    p = _head(10, u"SETTRK", u"установить дорожку из BC")
    n = p.network(u"СЕТЬ 2. Дорожка := BC")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Disk_Track", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Disk_Track"),
                                        I(n, u"GVL_CPM.Param_BC")))
    _finish(p, 10)
    return p


def make_setsec():
    p = _head(11, u"SETSEC", u"установить сектор из BC")
    n = p.network(u"СЕТЬ 2. Сектор := BC")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Disk_Sector", SEL(n, I(n, u"hit"),
                                         I(n, u"GVL_CPM.Disk_Sector"),
                                         I(n, u"GVL_CPM.Param_BC")))
    _finish(p, 11)
    return p


def make_setdma():
    p = _head(12, u"SETDMA", u"установить адрес DMA из BC")
    n = p.network(u"СЕТЬ 2. DMA := BC")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.DMA", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.DMA"),
                                 I(n, u"GVL_CPM.Param_BC")))
    _finish(p, 12)
    return p


def _sector_offset(p, net):
    u"""Сектор образа, который соответствует дорожке и сектору BIOS.

    В настоящем CP/M BDOS работает с «виртуальными» дорожками, у которых
    дорожка 0 - первая дорожка ОБЛАСТИ ДАННЫХ, а BIOS сам прибавляет число
    резервных дорожек OFF. Так же и здесь:

        сектор_образа = OFF*SPT + дорожка*SPT + (сектор - 1)

    Сектор в BIOS нумеруется с ЕДИНИЦЫ (как в CP/M), поэтому вычитается 1.
    Результат маскируется по размеру массива образа: сбойный параметр не
    выведет индекс за границу массива (правило безопасности п. 12.5 журнала),
    а просто попадёт в другой сектор.
    """
    net.outvar(u"sec_abs",
               ADD(net, MUL(net, I(net, u"GVL_CPM.Disk_Track"), I(net, W % D.SPT),
                            fbd_xml.COL_BLK + 200),
                   SUB(net, I(net, u"GVL_CPM.Disk_Sector"), I(net, W % 1),
                       fbd_xml.COL_BLK + 340), fbd_xml.COL_BLK + 480))
    net.outvar(u"disk_ofs",
               AND(net, ADD(net, I(net, W % D.DIR_SECT), I(net, u"sec_abs"),
                            fbd_xml.COL_BLK + 620),
                   I(net, W % (D.DISK_ARR_SEC - 1)), fbd_xml.COL_BLK + 760))


def make_read():
    p = _head(13, u"READ", u"чтение 128 байт в DMA с дорожки и сектора",
              extra=((u"sec_abs", u"WORD", u"номер сектора от начала диска"),
                     (u"disk_ofs", u"WORD", u"смещение на диске"),
                     (u"dma_m", u"WORD", u"адрес DMA, выровненный по 128"),
                     (u"xfer_m", u"WORD", u"куда пишем: DMA или мусорный буфер")))
    n = p.network(u"СЕТЬ 2. Адрес сектора и адрес приёмника")
    n.outvar(u"done_gate", I(n, u"hit"))
    _sector_offset(p, n)
    # маска 0FF80h защищает индекс массива от выхода за границу 64 КБ
    n.outvar(u"dma_m", AND(n, I(n, u"GVL_CPM.DMA"), I(n, W % 0xFF80),
                           fbd_xml.COL_BLK + 620))
    n.outvar(u"xfer_m", SEL(n, I(n, u"hit"), I(n, W % D.SCRATCH), I(n, u"dma_m"),
                            fbd_xml.COL_BLK + 760))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 900))
    n = p.network(u"СЕТЬ 3. Перенос 128 байт: GVL_MEM.Memory[DMA+k] := Disk[сектор, k]")
    for k in range(D.REC_SIZE):
        n.outvar(u"GVL_MEM.Memory[xfer_m + %d]" % k,
                 I(n, u"GVL_DISK.Disk[disk_ofs, %d]" % k))
    _finish(p, 13)
    return p


def make_write():
    p = _head(14, u"WRITE", u"запись 128 байт из DMA на дорожку и сектор",
              extra=((u"sec_abs", u"WORD", u"номер сектора от начала диска"),
                     (u"disk_ofs", u"WORD", u"смещение на диске"),
                     (u"dma_m", u"WORD", u"адрес DMA, выровненный по 128"),
                     (u"xfer_d", u"WORD", u"куда пишем: сектор или мусорный блок")))
    n = p.network(u"СЕТЬ 2. Адрес сектора и адрес источника")
    n.outvar(u"done_gate", I(n, u"hit"))
    _sector_offset(p, n)
    n.outvar(u"dma_m", AND(n, I(n, u"GVL_CPM.DMA"), I(n, W % 0xFF80),
                           fbd_xml.COL_BLK + 620))
    n.outvar(u"xfer_d", SEL(n, I(n, u"hit"), I(n, W % D.DISK_SCRATCH_SEC),
                            I(n, u"disk_ofs"), fbd_xml.COL_BLK + 760))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 900))
    n = p.network(u"СЕТЬ 3. Перенос 128 байт: Disk[сектор, k] := GVL_MEM.Memory[DMA+k]")
    for k in range(D.REC_SIZE):
        n.outvar(u"GVL_DISK.Disk[xfer_d, %d]" % k,
                 I(n, u"GVL_MEM.Memory[dma_m + %d]" % k))
    _finish(p, 14)
    return p


def make_listst():
    p = _head(15, u"LISTST", u"состояние устройства LIST: A=FFh (всегда готов)")
    n = p.network(u"СЕТЬ 2. A := FFh")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, H % 0xFF)))
    _finish(p, 15)
    return p


def make_sectran():
    p = _head(16, u"SECTRAN", u"трансляция сектора: перекоса нет, HL := BC")
    n = p.network(u"СЕТЬ 2. HL := BC (таблица перекоса не используется)")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_HL", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL"),
                                    I(n, u"GVL_CPM.Param_BC")))
    n.outvar(u"GVL_CPM.Ret_HL_En", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL_En"),
                                       I(n, u"TRUE"), fbd_xml.COL_BLK + 100))
    _finish(p, 16)
    return p


# ======================================================================
BIOS_FNS = (
    (0, u"FB_BIOS_BOOT", make_boot), (1, u"FB_BIOS_WBOOT", make_wboot),
    (2, u"FB_BIOS_CONST", make_const), (3, u"FB_BIOS_CONIN", make_conin),
    (4, u"FB_BIOS_CONOUT", make_conout), (5, u"FB_BIOS_LIST", make_list),
    (6, u"FB_BIOS_PUNCH", make_punch), (7, u"FB_BIOS_READER", make_reader),
    (8, u"FB_BIOS_HOME", make_home), (9, u"FB_BIOS_SELDSK", make_seldsk),
    (10, u"FB_BIOS_SETTRK", make_settrk), (11, u"FB_BIOS_SETSEC", make_setsec),
    (12, u"FB_BIOS_SETDMA", make_setdma), (13, u"FB_BIOS_READ", make_read),
    (14, u"FB_BIOS_WRITE", make_write), (15, u"FB_BIOS_LISTST", make_listst),
    (16, u"FB_BIOS_SECTRAN", make_sectran),
)


def make_bios_dispatch():
    u"""FB_BIOS - диспетчер: по номеру функции включает нужный блок."""
    p = Pou(u"FB_BIOS", u"functionBlock",
            doc=u"Диспетчер BIOS CP/M 2.2.\n"
                u"\tВход Start: трап BIOS активен (PC стоит на 0FE00h+3*i).\n"
                u"\tНомер функции уже посчитан в FB_CPM_Trap (GVL_CPM.BIOS_Func),\n"
                u"\tздесь он раздаётся всем 17 блокам: каждый сам проверяет свой\n"
                u"\tномер и, если он выбран, выполняет функцию и ставит квитанцию\n"
                u"\tGVL_CPM.Func_Done. Пока квитанции нет, Enable остаётся высоким,\n"
                u"\tпоэтому многосканные функции (CONIN ждёт символ) работают.\n"
                u"\tВходные параметры функций - в GVL_CPM (Param_BC, Reg_C),\n"
                u"\tрезультаты - GVL_CPM.Ret_Val / Ret_HL.")
    p.var_in(u"Start", u"BOOL", u"трап BIOS активен")
    p.var(u"en", u"BOOL", u"функции BIOS разрешены (нет квитанции)")
    p.var_out(u"Done", u"BOOL", u"вызванная функция выполнена")
    n = p.network(u"СЕТЬ 1. Разрешение работы функций и признак готовности")
    n.outvar(u"en", AND(n, I(n, u"Start"), NOT_(n, I(n, u"GVL_CPM.Func_Done")),
                        fbd_xml.COL_BLK + 200))
    n.outvar(u"Done", I(n, u"GVL_CPM.Func_Done"))
    n = p.network(u"СЕТЬ 2. Вызов всех 17 функций BIOS (каждая выбирает себя сама)")
    insts = []
    for i, (num, name, _mk) in enumerate(BIOS_FNS):
        b = n.block(name, [(u"Enable", I(n, u"en"))], [u"Done"],
                    instance=u"bio%d" % num, x=fbd_xml.COL_BLK + 200 * (i % 4),
                    y=40 + 30 * i)
        insts.append(b)
    # ЭКЗЕМПЛЯРЫ 17 ФУНКЦИЙ ОБЯЗАНЫ БЫТЬ ОБЪЯВЛЕНЫ В САМОМ POU. Раньше их
    # здесь не было: разбор объявлений это пропускал, а кодогенерация (она
    # включается только вместе с конфигурацией задач) падала с
    # "'bio1' не является экземпляром 'FB_BIOS_WBOOT'". Найдено на этапе 4.
    for num, name, _mk in BIOS_FNS:
        p.var(u"bio%d" % num, name, u"экземпляр функции BIOS %d" % num)
    return p


def NOT_(n, a, x=None, y=None):
    return n.block(u"NOT", [(u"IN", a)], [u"OUT"],
                   fbd_xml.COL_BLK if x is None else x, y)


ALL = tuple([mk for _n, _nm, mk in BIOS_FNS] + [make_bios_dispatch])
NAMES = tuple([nm for _n, nm, _mk in BIOS_FNS] + [u"FB_BIOS"])
