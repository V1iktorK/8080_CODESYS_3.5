# -*- coding: utf-8 -*-
u"""FB_COM_Loader - загрузчик .COM-программ CP/M в TPA.

ЧТО ДЕЛАЕТ (ровно так, как это делает CCP настоящего CP/M):
  1. находит файл в каталоге по FCB (OPEN через дисковый движок);
  2. читает его записями по 128 байт (READ SEQ) и кладёт в память начиная
     с 0x0100 - начала TPA;
  3. сообщает, сколько байт загружено, и что загрузка удалась.

ЧТО ДЕЛАЕТ CCP ПОСЛЕ ЗАГРУЗКИ (не этот блок, а вызывающий):
  * SP := 0xF200, PC := бутстрап-заглушка BOOT_STUB (0F380h) - через
    GVL_CPM.Jump_Req/Jump_PC/Jump_SP;
  * заглушку (LXI B, LXI D, LXI H, XRA A, JMP 0100h) кладёт в память
    FB_CPM_MemInit: она обнуляет регистры и передаёт управление программе.
    Это ДАННЫЕ (машинный код), а не логика: логика остаётся в FBD.

ПОЧЕМУ ЗАГРУЗЧИК ОТДЕЛЬНЫМ БЛОКОМ. Его вызывает CCP, но он же нужен и HMI
(запуск программы кнопкой), и тестам. Движок каталога у него свой экземпляр,
поэтому загрузка не мешает функциям BDOS, которые работают через трап.

ЧЕСТНОЕ ОГРАНИЧЕНИЕ: чтение идёт последовательным READ SEQ по карте блоков
FCB, то есть в пределах ОДНОГО экстента (16 КБ на дискете, 32 КБ на
винчестере). Файл большего размера будет прочитан не полностью - настоящий
CCP для перехода к следующему экстенту переоткрывает файл по номеру
экстента, здесь этого нет.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
import pou_cpm_defs as D
from pou_cpm_defs import (I, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, SEL, ADD,
                          SHL, SHR, W2B, ORL, ANDL, CHAIN, B, H, W, U1)

# шаги загрузчика
LO_IDLE = 0
LO_OPEN = 1
LO_WOPEN = 2
LO_DMA = 3
LO_WREAD = 4
LO_NEXT = 5
LO_END = 6

# предел: смещение последней записи, которую ещё можно уложить в TPA
LOAD_LIMIT = D.TPA_TOP - D.TPA_ENTRY - D.REC_SIZE


def make_com_loader():
    p = Pou(u"FB_COM_Loader", u"functionBlock",
            doc=u"Загрузчик .COM-программ CP/M в TPA (с 0100h).\n"
                u"\tВход Start - запуск загрузки (держится, пока идёт загрузка);\n"
                u"\tFCB - адрес блока управления файлом, имя в нём уже заполнено\n"
                u"\t(например CCP пишет туда имя команды и расширение COM).\n"
                u"\tВыходы: Busy - идёт загрузка; Done - загрузка закончена\n"
                u"\t(успешно или нет, смотри Ok); Ok - файл найден и прочитан;\n"
                u"\tSize - сколько байт прочитано.\n"
                u"\tВнутри: дисковый движок (OPEN, затем READ SEQ по одной записи\n"
                u"\t128 байт за скан) и адрес DMA = 0100h + смещение, чтобы каждая\n"
                u"\tзапись легла на своё место в TPA.")
    p.var_in(u"Start", u"BOOL", u"запуск загрузки")
    p.var_in(u"FCB", u"WORD", u"адрес FCB с именем файла")
    loc = (
        (u"step", u"BYTE", u"шаг загрузки"),
        (u"s1", u"BOOL", u"шаг: открыть файл"),
        (u"s2", u"BOOL", u"шаг: ждать открытия"),
        (u"s3", u"BOOL", u"шаг: прочитать запись"),
        (u"s4", u"BOOL", u"шаг: ждать чтения"),
        (u"s5", u"BOOL", u"шаг: перейти к следующей записи"),
        (u"s6", u"BOOL", u"шаг: конец"),
        (u"start_e", u"BOOL", u"запуск операции движка"),
        (u"done_l", u"BOOL", u"защёлка Done движка"),
        (u"res", u"BYTE", u"защёлка кода возврата движка"),
        (u"ofs", u"WORD", u"сколько байт уже загружено"),
        (u"next_ofs", u"WORD", u"смещение после этой записи"),
        (u"dma_n", u"WORD", u"адрес DMA для следующей записи"),
        (u"too_big", u"BOOL", u"программа не влезает в TPA"),
        (u"found", u"BOOL", u"файл найден в каталоге"),
        (u"fail", u"BOOL", u"файл не найден"),
        (u"rd_ok_done", u"BOOL", u"запись прочитана успешно"),
        (u"new_step", u"BYTE", u"следующий шаг"),
        (u"eng", u"FB_CPM_DirEngine", u"экземпляр дискового движка"),
    )
    for nm, t, c in loc:
        p.var(nm, t, c)
    p.var_out(u"Busy", u"BOOL", u"идёт загрузка")
    p.var_out(u"Done", u"BOOL", u"загрузка закончена")
    p.var_out(u"Ok", u"BOOL", u"файл найден и прочитан")
    p.var_out(u"Size", u"WORD", u"сколько байт прочитано")

    # ---- СЕТЬ 1: признаки шагов ----
    n = p.network(u"СЕТЬ 1. Шаги загрузчика: открыть файл, читать записи по 128 Б")
    n.outvar(u"s1", EQ(n, I(n, u"step"), I(n, B % LO_OPEN), fbd_xml.COL_BLK + 120))
    n.outvar(u"s2", EQ(n, I(n, u"step"), I(n, B % LO_WOPEN),
                       fbd_xml.COL_BLK + 240))
    n.outvar(u"s3", EQ(n, I(n, u"step"), I(n, B % LO_DMA), fbd_xml.COL_BLK + 360))
    n.outvar(u"s4", EQ(n, I(n, u"step"), I(n, B % LO_WREAD),
                       fbd_xml.COL_BLK + 480))
    n.outvar(u"s5", EQ(n, I(n, u"step"), I(n, B % LO_NEXT), fbd_xml.COL_BLK + 600))
    n.outvar(u"s6", EQ(n, I(n, u"step"), I(n, B % LO_END), fbd_xml.COL_BLK + 720))

    # ---- СЕТЬ 2: вызов дискового движка и защёлкивание выходов ----
    n = p.network(u"СЕТЬ 2. Дисковый движок: OPEN, затем READ SEQ")
    n.outvar(u"start_e", ANDL(n, [I(n, u"Start"),
                                  OR(n, I(n, u"s1"), I(n, u"s3"),
                                     fbd_xml.COL_BLK + 200)],
                              x0=fbd_xml.COL_BLK + 320))
    eng = n.block(u"FB_CPM_DirEngine", [
        (u"Start", I(n, u"start_e")),
        (u"Op", SEL(n, I(n, u"s3"), I(n, B % D.OP_OPEN),
                    I(n, B % D.OP_READSEQ), fbd_xml.COL_BLK + 460)),
        (u"Entry", I(n, u"WORD#0")),
        (u"FCB", I(n, u"FCB")),
        (u"ZeroFill", I(n, u"FALSE")),
    ], [u"Busy", u"Done", u"Result", u"Out_HL", u"Out_Idx"], instance=u"eng",
        x=fbd_xml.COL_BLK + 700)
    # правило 9.1: выход вызова FB сразу защёлкивается в переменную POU
    n.outvar(u"done_l", eng.out(u"Done"))
    n.outvar(u"res", eng.out(u"Result"))

    # ---- СЕТЬ 3: продвижение по шагам ----
    n = p.network(u"СЕТЬ 3. Шаги: следующая запись, конец загрузки")
    n.outvar(u"fail", ANDL(n, [I(n, u"s2"), I(n, u"done_l"),
                               EQ(n, I(n, u"res"), I(n, H % 0xFF),
                                  fbd_xml.COL_BLK + 320)],
                           x0=fbd_xml.COL_BLK + 440))
    n.outvar(u"rd_ok_done", ANDL(n, [I(n, u"s4"),
                                     I(n, u"done_l"),
                                     EQ(n, I(n, u"res"), I(n, H % 0),
                                        fbd_xml.COL_BLK + 680)],
                                 x0=fbd_xml.COL_BLK + 800))
    n.outvar(u"next_ofs", ADD(n, I(n, u"ofs"), I(n, u"WORD#%d" % D.REC_SIZE),
                              fbd_xml.COL_BLK + 920))
    n.outvar(u"dma_n", ADD(n, I(n, u"WORD#%d" % D.TPA_ENTRY), I(n, u"ofs"),
                           fbd_xml.COL_BLK + 1040))
    n.outvar(u"too_big", GT(n, I(n, u"dma_n"), I(n, u"WORD#%d" % LOAD_LIMIT),
                            fbd_xml.COL_BLK + 1160))
    n.outvar(u"new_step", CHAIN(n, I(n, u"step"), [
        (AND(n, I(n, u"Start"), EQ(n, I(n, u"step"), I(n, B % LO_IDLE),
                                   fbd_xml.COL_BLK + 1220),
             fbd_xml.COL_BLK + 1280), I(n, B % LO_OPEN)),
        (I(n, u"s1"), I(n, B % LO_WOPEN)),
        (AND(n, I(n, u"s2"), I(n, u"done_l"), fbd_xml.COL_BLK + 1400),
         SEL(n, I(n, u"fail"), I(n, B % LO_DMA), I(n, B % LO_END),
             fbd_xml.COL_BLK + 1520)),
        (I(n, u"s3"), I(n, B % LO_WREAD)),
        (AND(n, I(n, u"s4"), I(n, u"done_l"), fbd_xml.COL_BLK + 1640),
         SEL(n, I(n, u"rd_ok_done"), I(n, B % LO_NEXT), I(n, B % LO_END),
             fbd_xml.COL_BLK + 1760)),
        (I(n, u"s5"), SEL(n, I(n, u"too_big"), I(n, B % LO_DMA), I(n, B % LO_END),
                          fbd_xml.COL_BLK + 1880)),
    ], x0=fbd_xml.COL_BLK + 2000))
    # пока загрузка идёт - шаг по автомату; как только Start снят - сброс в 0
    n.outvar(u"step", SEL(n, I(n, u"Start"), I(n, B % LO_IDLE), I(n, u"new_step"),
                          fbd_xml.COL_BLK + 2120))
    n.outvar(u"ofs", SEL(n, I(n, u"rd_ok_done"), I(n, u"ofs"),
                         I(n, u"next_ofs"), fbd_xml.COL_BLK + 2360))
    n.outvar(u"found", SEL(n, AND(n, I(n, u"s2"), I(n, u"done_l"),
                                  fbd_xml.COL_BLK + 2480),
                           I(n, u"found"), NOT(n, I(n, u"fail"),
                                               fbd_xml.COL_BLK + 2600),
                           fbd_xml.COL_BLK + 2720))

    # ---- СЕТЬ 4: адрес DMA для следующей записи и выходные сигналы ----
    n = p.network(u"СЕТЬ 4. DMA := 0100h + смещение; выходные сигналы загрузчика")
    n.outvar(u"GVL_CPM.DMA", SEL(n, I(n, u"Start"), I(n, u"GVL_CPM.DMA"),
                                 I(n, u"dma_n"), fbd_xml.COL_BLK + 200))
    n.outvar(u"Busy", AND(n, I(n, u"Start"), NOT(n, I(n, u"s6"),
                                              fbd_xml.COL_BLK + 320),
                          fbd_xml.COL_BLK + 440))
    n.outvar(u"Done", I(n, u"s6"))
    n.outvar(u"Ok", SEL(n, I(n, u"s6"), I(n, u"FALSE"), I(n, u"found"),
                        fbd_xml.COL_BLK + 560))
    n.outvar(u"Size", I(n, u"ofs"))
    return p


ALL = (make_com_loader,)
NAMES = (u"FB_COM_Loader",)
