# -*- coding: utf-8 -*-
u"""ПРОБА этапа 3.5: проверка конструкций дискового образа в диалекте FBD.

Проверяется ровно то, что нужно новому формату диска CP/M 2.2 и чего в проекте
ещё НЕ БЫЛО (а всё непроверенное в этом диалекте молча теряется):

  P_DISK_TWO  - образ как ДВУМЕРНЫЙ массив: GVL_DISK2.Disk[сектор, байт],
                чтение и ЗАПИСЬ с вычисляемым вторым индексом (Eb + k);
  P_DISK_ONE  - образ как одномерный массив с индексом типа DWORD
                (нужен для образа 256 КБ и более, где WORD не хватает);
  P_DISK_BIG  - объявление образа профиля HARD_8M: 65536 секторов по 128 байт
                (индекс сектора - WORD, ровно до 65535);
  P_DISK_DW   - 16/32-разрядная арифметика адреса: расширение WORD -> DWORD
                присваиванием, SHL/ADD над DWORD, блок WORD_TO_DWORD;
  P_DISK_INIT - инициализатор массива в тексте GVL (одномерный и двумерный):
                им будут залиты в образ демонстрационные .COM-файлы.

Результат - log/gen_probe_disk.log (по POU: сколько блоков сгенерировано и
сколько доехало до выгрузки).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import I, AND, ADD, SEL, SHL, B, H, W


def make_two():
    u"""Образ диска двумерным массивом [сектор][байт]: чтение и запись."""
    p = Pou(u"P_DISK_TWO", u"functionBlock",
            doc=u"Проба: образ диска как ДВУМЕРНЫЙ массив [сектор][байт].\n"
                u"\tЧитается и пишется байт записи каталога со СМЕЩЕНИЕМ внутри\n"
                u"\tсектора, вычисляемым в схеме (Eb + k). Именно так дисковый\n"
                u"\tдвижок будет разбирать 32-байтовую запись каталога.")
    p.var_in(u"Sec", u"WORD", u"номер сектора образа")
    p.var_in(u"Eb", u"BYTE", u"смещение записи внутри сектора (0, 32, 64, 96)")
    p.var(u"val", u"BYTE", u"прочитанный байт")
    p.var_out(u"Q", u"BYTE", u"результат")
    n = p.network(u"СЕТЬ 1. Чтение записи каталога по (сектор, смещение+k)")
    n.outvar(u"val", I(n, u"GVL_DISK2.Disk[Sec, Eb + 3]"))
    n.outvar(u"GVL_DISK2.Disk[Sec, Eb + 5]", I(n, u"val"))
    n = p.network(u"СЕТЬ 2. Второй байт записи и результат")
    n.outvar(u"GVL_DISK2.Disk[Sec, Eb + 6]",
             I(n, u"GVL_DISK2.Disk[Sec, Eb + 1]"))
    n.outvar(u"Q", I(n, u"val"))
    return p


def make_one():
    u"""Образ диска одномерным массивом с индексом DWORD."""
    p = Pou(u"P_DISK_ONE", u"functionBlock",
            doc=u"Проба: одномерный образ с индексом типа DWORD.\n"
                u"\tПроверяет, что CODESYS принимает DWORD как индекс массива\n"
                u"\tARRAY[0..262143] и что арифметика адреса в DWORD работает.")
    p.var_in(u"Dw", u"DWORD", u"адрес в образе")
    p.var(u"val", u"BYTE", u"прочитанный байт")
    p.var_out(u"Q", u"BYTE", u"результат")
    n = p.network(u"СЕТЬ 1. Чтение и запись по DWORD-адресу")
    n.outvar(u"val", I(n, u"GVL_DISK1.Disk[Dw]"))
    n.outvar(u"GVL_DISK1.Disk[Dw + DWORD#7]", I(n, u"val"))
    n = p.network(u"СЕТЬ 2. Результат")
    n.outvar(u"Q", I(n, u"val"))
    return p


def make_big():
    u"""Объявление образа профиля HARD_8M: 65536 секторов по 128 байт."""
    p = Pou(u"P_DISK_BIG", u"functionBlock",
            doc=u"Проба: образ профиля HARD_8M (8 МБ) как 65536 секторов\n"
                u"\tпо 128 байт. Индекс сектора - WORD: 65535 - предельный,\n"
                u"\tто есть двумерная раскладка позволяет обойтись БЕЗ DWORD.")
    p.var_in(u"Sec", u"WORD", u"номер сектора (0..65535)")
    p.var_in(u"B", u"BYTE", u"номер байта в секторе")
    p.var_out(u"Q", u"BYTE", u"результат")
    n = p.network(u"СЕТЬ 1. Доступ к последнему сектору образа 8 МБ")
    n.outvar(u"Q", I(n, u"GVL_DISK8.Disk[Sec, B]"))
    n.outvar(u"GVL_DISK8.Disk[Sec, B]", I(n, u"GVL_DISK8.Disk[Sec, B]"))
    return p


def make_dw():
    u"""32-разрядная арифметика адреса: расширение присваиванием и SHL/ADD."""
    p = Pou(u"P_DISK_DW", u"functionBlock",
            doc=u"Проба: адрес блока в 32 разрядах.\n"
                u"\tWORD расширяется до DWORD присваиванием (как BYTE до WORD,\n"
                u"\tправило 10.1 журнала), затем SHL/ADD над DWORD. Нужно для\n"
                u"\tпрофиля HARD_8M: блок 2047 по 4 КБ - это 8 384 512 байт.")
    p.var_in(u"Blk", u"WORD", u"номер блока диска")
    p.var_in(u"N", u"BYTE", u"сдвиг")
    p.var(u"bw", u"DWORD", u"номер блока как DWORD")
    p.var(u"sh", u"DWORD", u"сдвинутый адрес")
    p.var(u"ad", u"DWORD", u"адрес блока")
    p.var(u"conv", u"DWORD", u"результат блока WORD_TO_DWORD")
    p.var_out(u"Q", u"DWORD", u"результат")
    n = p.network(u"СЕТЬ 1. Расширение WORD -> DWORD, сдвиг и сложение")
    n.outvar(u"bw", I(n, u"Blk"))
    n.outvar(u"sh", SHL(n, I(n, u"bw"), I(n, u"DWORD#5"),
                        fbd_xml.COL_BLK + 200))
    n.outvar(u"ad", ADD(n, I(n, u"sh"), I(n, u"DWORD#52"),
                        fbd_xml.COL_BLK + 400))
    n = p.network(u"СЕТЬ 2. Блок преобразования WORD_TO_DWORD")
    n.outvar(u"conv", n.block(u"WORD_TO_DWORD", [(u"IN", I(n, u"Blk"))],
                              [u"OUT"], fbd_xml.COL_BLK + 200))
    n.outvar(u"Q", ADD(n, I(n, u"ad"), I(n, u"conv"), fbd_xml.COL_BLK + 400))
    return p


def make_init():
    u"""Проверка инициализатора массива в тексте GVL."""
    p = Pou(u"P_DISK_INIT", u"functionBlock",
            doc=u"Проба: инициализатор массива прямо в объявлении GVL.\n"
                u"\tИменно так в образ диска будут залиты демонстрационные\n"
                u"\t.COM-программы: это ДАННЫЕ, а не логика, поэтому текст\n"
                u"\tобъявления GVL для них допустим (план, раздел 4.2).")
    p.var_in(u"Ix", u"INT", u"индекс в таблице")
    p.var_out(u"Q", u"BYTE", u"результат")
    n = p.network(u"СЕТЬ 1. Чтение инициализированных массивов")
    n.outvar(u"Q", I(n, u"GVL_INIT.Tab[Ix]"))
    n.outvar(u"GVL_DISK2.Disk[0, 0]", I(n, u"GVL_INIT.Grid[1, 2]"))
    return p


ALL = (make_two, make_one, make_big, make_dw, make_init)
NAMES = tuple([u"P_DISK_TWO", u"P_DISK_ONE", u"P_DISK_BIG", u"P_DISK_DW",
               u"P_DISK_INIT"])

GVLS = (
    (u"GVL_DISK2",
     u"VAR_GLOBAL\n"
     u"\t(* Проба: образ 256 КБ как 2048 секторов по 128 байт. *)\n"
     u"\tDisk : ARRAY[0..2047] OF ARRAY[0..127] OF BYTE;\n"
     u"END_VAR\n"),
    (u"GVL_DISK1",
     u"VAR_GLOBAL\n"
     u"\t(* Проба: тот же образ, но одномерный, с индексом DWORD. *)\n"
     u"\tDisk : ARRAY[0..262143] OF BYTE;\n"
     u"END_VAR\n"),
    (u"GVL_DISK8",
     u"VAR_GLOBAL\n"
     u"\t(* Проба: образ профиля HARD_8M - 8 МБ. *)\n"
     u"\tDisk : ARRAY[0..65535] OF ARRAY[0..127] OF BYTE;\n"
     u"END_VAR\n"),
    (u"GVL_INIT",
     u"VAR_GLOBAL\n"
     u"\t(* Проба: инициализатор массива в тексте объявления. *)\n"
     u"\tTab  : ARRAY[0..7] OF BYTE := [16#C3, 16#0E, 16#00, 16#3F, 16#41,"
     u" 16#42, 16#43, 16#44];\n"
     u"\tGrid : ARRAY[0..1] OF ARRAY[0..3] OF BYTE := "
     u"[[1, 2, 3, 4], [5, 6, 7, 8]];\n"
     u"END_VAR\n"),
)
