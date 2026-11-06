# -*- coding: utf-8 -*-
u"""BDOS CP/M 2.2 на FBD: 28 функций отдельными FB + диспетчер FB_BDOS.

АРХИТЕКТУРА.
  * FB_BDOS - диспетчер: на трапе ловит номер функции (регистр C) и параметры
    (DE - FCB, буфер, строка; BC - дорожка/сектор/DMA), затем раздаёт всем 28
    блокам сигнал разрешения. Блок сам проверяет свой номер, выполняет функцию и
    ставит квитанцию GVL_CPM.Func_Done, по которой трап возвращает регистры.
  * FB_CPM_DirEngine - общий дисковый движок: просмотр каталога (по ОДНОЙ записи
    за скан), открытие/закрытие/создание/удаление/переименование, перенос записи
    128 байт, выделение блоков через битовую карту занятости. Циклов в FBD нет,
    поэтому проход по каталогу идёт по сканам, а процессор в это время
    остановлен - ровно как в настоящем CP/M, где BDOS надолго занимает
    процессор (docs/04_ПЛАН_CPM.md, раздел 7).
  * Консольные функции работают через GVL_CPM.ConIn_*/ConOut_* (вход - от HMI),
    вывод дублируется в GVL_CPM.Con_Log - его видно в online-режиме.

ФОРМАТ ДИСКА - НАСТОЯЩИЙ CP/M 2.2 (этап 3.5, профиль задан в pou_cpm_defs):
  * каталог: DRM+1 записей по 32 байта, начинается с сектора OFF*SPT;
  * данные: блоки по 128<<BSH байт, блок N - с сектора OFF*SPT + N*(1<<BSH);
  * адресация образа - по секторам: GVL_DISK.Disk[сектор, байт] (128 байт);
  * размещение блоков - через битовую карту GVL_DISK.Alloc, начальное
    состояние которой задают AL0/AL1 (системная область) и демонстрационные
    файлы, залитые в образ при инициализации; освобождение - при DELETE.

ЧТО РЕАЛИЗОВАНО ПОЛНОСТЬЮ: 1, 2, 9, 10, 11, 12, 13, 14, 15, 16, 17, 18, 19,
20, 21, 22, 23 (RENAME), 24, 25, 26, 30 (ATTRIB), 32, 33 (READ RANDOM),
34 (WRITE RANDOM), 35 (FILE SIZE), 36 (SET RANDOM RECORD), 40 (WRITE RANDOM
WITH ZERO FILL).
ЧТО ОСТАЛОСЬ ЗАГЛУШКОЙ: 24 (LOGINVEC) - в CP/M 2.2 функция не используется.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
import pou_cpm_defs as D
from pou_cpm_defs import (I, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, SEL, ADD,
                          SHL, SHR, W2B, MOD, ORL, ANDL, CHAIN, B, H, W, WH, U1)

# номера функций BDOS
F_CONIN, F_CONOUT, F_PRINTSTR, F_READLINE, F_CONST = 1, 2, 9, 10, 11
F_VERSION, F_RESETDISK, F_SELDSK = 12, 13, 14
F_OPEN, F_CLOSE, F_SEARCHF, F_SEARCHN = 15, 16, 17, 18
F_DELETE, F_READSEQ, F_WRITESEQ, F_MAKE = 19, 20, 21, 22
F_RENAME, F_LOGINVEC, F_CURDISK, F_SETDMA = 23, 24, 25, 26
F_ATTRIB, F_USER = 30, 32
F_READRAND, F_WRITERAND, F_FILESIZE, F_SETRANDREC, F_WRITERANDZF = 33, 34, 35, 36, 40

WILDCARD = 0x3F          # '?' - символ подстановки в имени FCB
DELETED = 0xE5           # признак удалённой (свободной) записи каталога
CR = 0x0D                # возврат каретки
LF = 0x0A                # перевод строки
NAME_MASK = 0x7F         # старший бит имени - атрибут, при сравнении он снимается
ATTR_BIT = 0x80          # старший бит - признак атрибута (R/O, SYS, ARCHIVE)
ENT_SHIFT = D.RECS_PER_ENTRY.bit_length() - 1   # записей в записи каталога: 2^7/2^8


# ======================================================================
def _head(num, name, doc, extra=None):
    u"""Общая часть функции BDOS: вход Enable, признак hit, выход Done."""
    p = Pou(u"FB_BDOS_" + name, u"functionBlock",
            doc=u"BDOS, функция %d (%s): %s\n"
                u"\tВызывается диспетчером FB_BDOS, когда PC попал на 0F000h и\n"
                u"\tрегистр C равен %d. Вход Enable - 'функция выбрана и ещё не\n"
                u"\tвыполнена'. Параметры берутся из GVL_CPM: Param_DE/Param_BC/\n"
                u"\tFCB_Addr (пары DE и BC на момент вызова) и регистры Reg_*.\n"
                u"\tРезультат пишется в GVL_CPM.Ret_Val (аккумулятор A) и\n"
                u"\tGVL_CPM.Ret_HL, квитанция - GVL_CPM.Func_Done."
                % (num, name, doc, num))
    p.var_in(u"Enable", u"BOOL", u"функция выбрана и ещё не выполнена")
    p.var(u"hit", u"BOOL", u"выбрана именно эта функция")
    p.var(u"done_gate", u"BOOL", u"функция выполнена в этом скане")
    p.var(u"ch", u"BYTE", u"рабочий символ")
    # ВАЖНО: ch объявлен BYTE и используется как символ/данные. Там, где нужно
    # УСЛОВИЕ (вход G блока SEL, операнд AND), нужна отдельная переменная BOOL -
    # иначе CODESYS на кодогенерации даёт C32 'BYTE' -> 'BOOL'.
    p.var(u"chb", u"BOOL", u"рабочий признак (результат сравнения), НЕ символ")
    p.var(u"val", u"BYTE", u"рабочее значение")
    # Аналогично chb: val объявлен BYTE (данные), а кое-где нужен признак BOOL.
    p.var(u"valb", u"BOOL", u"рабочий признак (результат сравнения), НЕ данные")
    p.var(u"log_i", u"INT", u"индекс в журнале консоли")
    p.var(u"cnt_inc", u"UDINT", u"счётчик для диагностики")
    if extra:
        for nm, t, c in extra:
            p.var(nm, t, c)
    p.var_out(u"Done", u"BOOL", u"функция выполнена")
    n = p.network(u"СЕТЬ 1. Выбор функции: BDOS_Func = %d (%s)" % (num, name))
    n.outvar(u"hit", AND(n, I(n, u"Enable"),
                         EQ(n, I(n, u"GVL_CPM.BDOS_Func"), I(n, B % num),
                            fbd_xml.COL_BLK + 200),
                         fbd_xml.COL_BLK + 320))
    return p


def _finish(p, num, note=u""):
    u"""Сеть квитанции: Done, Func_Done, счётчики диагностики."""
    n = p.network(u"СЕТЬ ПОСЛЕДНЯЯ. Квитанция и диагностика%s"
                  % (u" - " + note if note else u""))
    n.outvar(u"Done", I(n, u"done_gate"))
    n.outvar(u"GVL_CPM.Func_Done", SEL(n, I(n, u"done_gate"),
                                       I(n, u"GVL_CPM.Func_Done"), I(n, u"TRUE")))
    n.outvar(u"cnt_inc", ADD(n, I(n, u"GVL_CPM.Diag.BDOS_Cnt"), I(n, U1),
                             fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Diag.BDOS_Cnt",
             SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Diag.BDOS_Cnt"),
                 I(n, u"cnt_inc"), fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.Diag.Last_Func",
             SEL(n, I(n, u"done_gate"), I(n, u"GVL_CPM.Diag.Last_Func"),
                 I(n, B % num), fbd_xml.COL_BLK + 440))


def _echo_log(p, gate):
    u"""Символ консоли: запрос в журнал (пишут сети PLC_PRG_CPM)."""
    n = p.network(u"СЕТЬ: символ консоли - запрос в журнал")
    n.outvar(u"GVL_CPM.LogWr", gate)
    n.outvar(u"GVL_CPM.LogCh", I(n, u"ch"))
    n.outvar(u"GVL_CPM.Con_Log_Len",
             SEL(n, gate, I(n, u"GVL_CPM.Con_Log_Len"),
                 ADD(n, I(n, u"GVL_CPM.Con_Log_Len"), I(n, u"INT#1"),
                     fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 320))


def _stub(num, name, doc, code=0xFF):
    u"""Функция BDOS-заглушка: честно отвечает ошибкой и считает обращение."""
    p = _head(num, name, doc)
    n = p.network(u"СЕТЬ 2. Заглушка: A := %d, счётчик нереализованных растёт" % code)
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, H % code)))
    n.outvar(u"cnt_inc", ADD(n, I(n, u"GVL_CPM.Diag.Unimpl_Cnt"), I(n, U1)))
    n.outvar(u"GVL_CPM.Diag.Unimpl_Cnt",
             SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Diag.Unimpl_Cnt"),
                 I(n, u"cnt_inc"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Diag.Last_Err", SEL(n, I(n, u"hit"),
                                           I(n, u"GVL_CPM.Diag.Last_Err"),
                                           I(n, B % 5), fbd_xml.COL_BLK + 340))
    _finish(p, num, u"заглушка")
    return p


# ======================================================================
# ДИСКОВЫЙ ДВИЖОК
# ======================================================================
ENGINE_LOCALS = (
    # ---- автомат фаз ----
    (u"start_p", u"BOOL", u"импульс запуска"),
    (u"active", u"BOOL", u"движок занят"),
    (u"phase", u"BYTE", u"фаза: 0 простой, 1 обход каталога, 2 перенос, "
                       u"4 поиск блока, 5 забивка, 9 готово"),
    (u"ph1", u"BOOL", u"идёт обход каталога"),
    (u"ph2", u"BOOL", u"идёт перенос записи"),
    (u"ph4", u"BOOL", u"идёт поиск свободного блока"),
    (u"ph5", u"BOOL", u"идёт забивка блока нулями"),
    (u"ph9", u"BOOL", u"операция завершена"),
    (u"ph_a", u"BYTE", u"фаза: старт"),
    (u"ph_b", u"BYTE", u"фаза: конец обхода каталога"),
    (u"ph_c", u"BYTE", u"фаза: конец переноса"),
    (u"ph_d", u"BYTE", u"фаза: конец поиска блока"),
    (u"ph_e", u"BYTE", u"фаза: конец забивки нулями"),
    (u"ph_f", u"BYTE", u"новая фаза"),
    (u"disk_full", u"BOOL", u"на диске нет свободных блоков"),
    (u"zf_last", u"BOOL", u"забит последний блок записи"),
    (u"zf_g", u"BYTE", u"номер записи блока для забивки нулями"),
    (u"zf_w", u"WORD", u"номер записи для забивки как слово"),
    (u"in_zf", u"BOOL", u"идёт забивка нулями"),
    # ---- признаки операций ----
    (u"op_s", u"BOOL", u"поиск записи каталога"),
    (u"op_open", u"BOOL", u"открытие (или поиск экстента)"),
    (u"op_close", u"BOOL", u"закрытие"),
    (u"op_make", u"BOOL", u"создание файла"),
    (u"op_del", u"BOOL", u"удаление файла"),
    (u"op_rd", u"BOOL", u"чтение записи"),
    (u"op_wr", u"BOOL", u"запись записи"),
    (u"op_ren", u"BOOL", u"переименование"),
    (u"op_att", u"BOOL", u"установка атрибутов"),
    (u"op_ext", u"BOOL", u"поиск записи с заданным номером экстента"),
    (u"op_size", u"BOOL", u"вычисление размера файла"),
    (u"xfer_op", u"BOOL", u"идёт перенос записи файла"),
    # ---- номер записи каталога и её адрес ----
    (u"idx", u"WORD", u"номер текущей записи каталога"),
    (u"ix_a", u"WORD", u"номер записи, шаг 1"),
    (u"ix_b", u"WORD", u"номер записи, шаг 2"),
    (u"ix_c", u"WORD", u"новый номер записи"),
    (u"idx_last", u"BOOL", u"просмотрена последняя запись каталога"),
    (u"ents", u"WORD", u"сектор образа, в котором лежит запись каталога"),
    (u"entb", u"BYTE", u"смещение записи внутри сектора (0, 32, 64, 96)"),
    (u"st", u"BYTE", u"первый байт записи: пользователь или E5h"),
    (u"free_ent", u"BOOL", u"запись свободна (st = E5h)"),
    (u"name_ok", u"BOOL", u"имя и расширение совпали с FCB"),
    (u"match", u"BOOL", u"запись подходит (имя и пользователь)"),
    (u"m_eff", u"BOOL", u"совпадение с учётом номера экстента"),
    (u"ex_db", u"BYTE", u"номер экстента в записи каталога"),
    (u"ex_fcb", u"BYTE", u"номер экстента в FCB"),
    (u"ex_ok", u"BOOL", u"номера экстентов совпали"),
    (u"hit_now", u"BOOL", u"запись найдена в этом скане"),
    (u"dc_w", u"WORD", u"код каталога 0..3 как слово"),
    (u"dir_code", u"BYTE", u"код каталога 0..3 (возвращается в A)"),
    (u"dir_off", u"WORD", u"смещение записи в буфере DMA (код*32)"),
    (u"any_del", u"BOOL", u"при удалении что-то удалено"),
    (u"dst_addr", u"WORD", u"адрес записи в буфере DMA"),
    (u"copy_a", u"WORD", u"куда копировать найденную запись"),
    (u"dma_m", u"WORD", u"адрес DMA, выровненный по 128"),
    # ---- действия по операциям ----
    (u"in_scan", u"BOOL", u"идёт обход каталога"),
    (u"act_search", u"BOOL", u"в этом скане копируем найденную запись"),
    (u"act_open", u"BOOL", u"в этом скане открываем файл"),
    (u"act_close", u"BOOL", u"в этом скане закрываем файл"),
    (u"act_make", u"BOOL", u"в этом скане создаём файл"),
    (u"act_del", u"BOOL", u"в этом скане удаляем запись"),
    (u"act_ren", u"BOOL", u"в этом скане переименовываем"),
    (u"act_att", u"BOOL", u"в этом скане ставим атрибуты"),
    (u"act_size", u"BOOL", u"в этом скане считаем размер файла"),
    (u"stop_now", u"BOOL", u"обход каталога закончен"),
    (u"done_ev", u"BOOL", u"фаза завершения"),
    (u"size_ev", u"BOOL", u"запись размера файла в FCB"),
    # ---- размер файла ----
    (u"fs_seen", u"BOOL", u"подходящая запись найдена"),
    (u"fs_code", u"BYTE", u"код каталога последней подходящей записи"),
    (u"fs_max", u"WORD", u"наибольший размер файла в записях"),
    (u"fs_ent", u"WORD", u"размер текущей записи в записях"),
    (u"ex_w", u"WORD", u"номер экстента как слово"),
    (u"rc_w", u"WORD", u"rc как слово"),
    (u"rc", u"BYTE", u"число записей в экстенте (FCB+15)"),
    # ---- работа с картой занятости блоков ----
    (u"cr", u"BYTE", u"текущая запись файла (FCB+32)"),
    (u"cr_w", u"WORD", u"cr как слово"),
    (u"cr_n", u"BYTE", u"следующее значение cr"),
    (u"blkidx", u"WORD", u"индекс блока в карте FCB"),
    (u"blk2", u"WORD", u"индекс блока в байтах карты"),
    (u"blkaddr", u"WORD", u"адрес байта карты блоков в FCB"),
    (u"ofs", u"WORD", u"номер записи внутри блока"),
    (u"blk", u"WORD", u"номер блока файла (0 = не выделен)"),
    (u"blk_lo_w", u"WORD", u"младший байт номера блока"),
    (u"blk_hi_w", u"WORD", u"старший байт номера блока (DSM > 255)"),
    (u"blk_hi_s", u"WORD", u"старший байт блока, сдвинутый на 8"),
    (u"blk0", u"BOOL", u"блок файла ещё не выделен"),
    (u"blk_sec", u"WORD", u"сектор, с которого начинается блок"),
    (u"dsk", u"WORD", u"сектор записи файла на диске"),
    (u"dsk_zf", u"WORD", u"сектор забивки нулями"),
    (u"in_alloc", u"BOOL", u"идёт поиск свободного блока"),
    (u"na", u"WORD", u"текущий проверяемый блок"),
    (u"na_i", u"WORD", u"байт битовой карты для блока na"),
    (u"na_byte", u"BYTE", u"байт битовой карты"),
    (u"na_bit", u"BYTE", u"бит блока na"),
    (u"na_used", u"BOOL", u"блок занят"),
    (u"na_free", u"BOOL", u"блок свободен - его и выделяем"),
    (u"na_step", u"WORD", u"следующий проверяемый блок"),
    (u"alloc_rdy", u"BOOL", u"нужный блок есть (выделен ранее или только что)"),
    (u"nf_cnt", u"WORD", u"сколько блоков проверено в поиске свободного"),
    (u"next_n", u"BYTE", u"подсказка распределения после выделения"),
    (u"rd_ok", u"BOOL", u"запись прочитана (данные есть)"),
    (u"wr_ok", u"BOOL", u"запись выполнена"),
    (u"inc_rc", u"BOOL", u"увеличить счётчик записей файла"),
    (u"cr_gate", u"BOOL", u"разрешение изменить cr"),
    (u"xfer_d", u"WORD", u"откуда читать диск (сектор)"),
    (u"xfer_m", u"WORD", u"куда писать в память"),
    (u"xfer_d2", u"WORD", u"куда писать на диск (сектор)"),
    (u"xfer_m2", u"WORD", u"откуда читать память"),
    # ---- код возврата ----
    (u"res_a", u"BYTE", u"код возврата, шаг 1"),
    (u"res_b", u"BYTE", u"код возврата, шаг 2"),
    (u"res_c", u"BYTE", u"код возврата, шаг 3"),
    (u"res_d", u"BYTE", u"код возврата, шаг 4"),
    (u"res_x", u"BYTE", u"код возврата по факту переноса записи"),
    (u"res_e", u"BYTE", u"код возврата, шаг 5"),
    (u"eng_cnt", u"UDINT", u"счётчик проходов по каталогу"),
)

# байты имени и расширения в записи каталога и в FCB
NAME_BYTES = tuple(range(1, 12))


def _blk_read(n, p, hi_name, lo_name, out_name, addr):
    u"""Прочитать номер блока из карты FCB: 1 байт (DSM<256) или 2 байта."""
    n.outvar(lo_name, I(n, u"GVL_MEM.Memory[%s]" % addr))
    if D.BLK_BYTES == 1:
        n.outvar(out_name, I(n, lo_name))
    else:
        n.outvar(hi_name, I(n, u"GVL_MEM.Memory[%s + 1]" % addr))
        n.outvar(u"blk_hi_s", SHL(n, I(n, hi_name), I(n, W % 8),
                                  fbd_xml.COL_BLK + 200))
        n.outvar(out_name, OR(n, I(n, u"blk_hi_s"), I(n, lo_name),
                              fbd_xml.COL_BLK + 400))


def make_dir_engine():
    p = Pou(u"FB_CPM_DirEngine", u"functionBlock",
            doc=u"Дисковый движок BDOS в НАСТОЯЩЕМ формате CP/M 2.2.\n"
                u"\tВходы: Start - импульс запуска; Op - операция (0 SEARCH FIRST,\n"
                u"\t1 SEARCH NEXT, 2 OPEN, 3 CLOSE, 4 MAKE, 5 DELETE, 6 READ SEQ,\n"
                u"\t7 WRITE SEQ, 8 RENAME, 9 ATTRIB, 10 FIND EXTENT, 11 FILE SIZE,\n"
                u"\t12 FREE BLOCK); Entry - начальная запись каталога для\n"
                u"\tSEARCH NEXT; FCB - адрес блока управления файлом;\n"
                u"\tZeroFill - забить нулями только что выделенный блок.\n"
                u"\tВыходы: Busy - движок занят; Done - импульс окончания; Result -\n"
                u"\tкод возврата в A (0..3 - код каталога, FFh - не найдено);\n"
                u"\tOut_HL - адрес найденной записи каталога в буфере DMA;\n"
                u"\tOut_Idx - номер найденной записи (для SEARCH NEXT).\n"
                u"\tКаталог лежит по сектору OFF*SPT, запись - 32 байта, то есть\n"
                u"\tчетверть сектора; блоки данных начинаются с сектора\n"
                u"\tOFF*SPT + N*(1<<BSH). За скан просматривается ОДНА запись\n"
                u"\tкаталога и проверяется ОДИН блок карты занятости: циклов в FBD\n"
                u"\tнет, поэтому и обход каталога, и поиск свободного блока идут по\n"
                u"\tсканам, а процессор в это время остановлен.")
    for nm, t, c in ENGINE_LOCALS:
        p.var(nm, t, c)
    for k in NAME_BYTES:
        p.var(u"e%d" % k, u"BYTE", u"байт имени из записи каталога")
        p.var(u"p%d" % k, u"BYTE", u"байт имени из FCB")
        p.var(u"m%d" % k, u"BOOL", u"байт имени совпал")
    for j in range(D.BLOCKS_PER_ENTRY):
        p.var(u"fb%d" % j, u"WORD", u"номер блока из удаляемой записи")
        p.var(u"fi%d" % j, u"WORD", u"байт карты занятости")
        p.var(u"fm%d" % j, u"BYTE", u"маска сброса бита")
    p.var_in(u"Start", u"BOOL", u"запуск операции")
    p.var_in(u"Op", u"BYTE", u"код операции")
    p.var_in(u"Entry", u"WORD", u"начальная запись каталога")
    p.var_in(u"FCB", u"WORD", u"адрес FCB")
    p.var_in(u"ZeroFill", u"BOOL", u"забить нулями только что выделенный блок")
    p.var_out(u"Busy", u"BOOL", u"движок занят")
    p.var_out(u"Done", u"BOOL", u"операция завершена")
    p.var_out(u"Result", u"BYTE", u"код возврата в A")
    p.var_out(u"Out_HL", u"WORD", u"адрес найденной записи каталога")
    p.var_out(u"Out_Idx", u"WORD", u"номер найденной записи")

    # ---- СЕТЬ 1: признаки операций, номер записи каталога, автомат фаз ----
    n = p.network(u"СЕТЬ 1. Запуск движка, признаки операций, номер записи, фазы")
    n.outvar(u"start_p", AND(n, I(n, u"Start"), NOT(n, I(n, u"active"),
                             fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 320))
    n.outvar(u"op_s", OR(n, EQ(n, I(n, u"Op"), I(n, B % D.OP_SEARCH_FIRST)),
                         EQ(n, I(n, u"Op"), I(n, B % D.OP_SEARCH_NEXT),
                            fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 340))
    n.outvar(u"op_open", OR(n, EQ(n, I(n, u"Op"), I(n, B % D.OP_OPEN),
                                 fbd_xml.COL_BLK + 200),
                            EQ(n, I(n, u"Op"), I(n, B % D.OP_FINDEXT),
                               fbd_xml.COL_BLK + 340), fbd_xml.COL_BLK + 480))
    n.outvar(u"op_close", EQ(n, I(n, u"Op"), I(n, B % D.OP_CLOSE),
                             fbd_xml.COL_BLK + 600))
    n.outvar(u"op_make", EQ(n, I(n, u"Op"), I(n, B % D.OP_MAKE),
                            fbd_xml.COL_BLK + 720))
    n.outvar(u"op_del", EQ(n, I(n, u"Op"), I(n, B % D.OP_DELETE),
                           fbd_xml.COL_BLK + 840))
    n.outvar(u"op_rd", EQ(n, I(n, u"Op"), I(n, B % D.OP_READSEQ),
                          fbd_xml.COL_BLK + 960))
    n.outvar(u"op_wr", EQ(n, I(n, u"Op"), I(n, B % D.OP_WRITESEQ),
                          fbd_xml.COL_BLK + 1080))
    n.outvar(u"op_ren", EQ(n, I(n, u"Op"), I(n, B % D.OP_RENAME),
                           fbd_xml.COL_BLK + 1200))
    n.outvar(u"op_att", EQ(n, I(n, u"Op"), I(n, B % D.OP_ATTRIB),
                           fbd_xml.COL_BLK + 1320))
    n.outvar(u"op_ext", EQ(n, I(n, u"Op"), I(n, B % D.OP_FINDEXT),
                           fbd_xml.COL_BLK + 1440))
    n.outvar(u"op_size", EQ(n, I(n, u"Op"), I(n, B % D.OP_FILESIZE),
                            fbd_xml.COL_BLK + 1560))
    n.outvar(u"xfer_op", OR(n, I(n, u"op_rd"), I(n, u"op_wr"),
                            fbd_xml.COL_BLK + 1680))
    # Номер записи каталога. Порядок элементов важен: сначала новое значение
    # idx, только потом запись новой фазы (иначе EQ(phase,1) прочитает уже
    # новую фазу и первая запись каталога будет пропущена).
    n.outvar(u"ix_a", SEL(n, I(n, u"start_p"), I(n, u"idx"),
                          SEL(n, EQ(n, I(n, u"Op"), I(n, B % D.OP_SEARCH_NEXT),
                                  fbd_xml.COL_BLK + 1800),
                              I(n, w_0()), I(n, u"Entry"), fbd_xml.COL_BLK + 1920),
                          fbd_xml.COL_BLK + 2040))
    n.outvar(u"ix_b", SEL(n, I(n, u"stop_now"), I(n, u"ix_a"), I(n, u"idx"),
                          fbd_xml.COL_BLK + 2160))
    n.outvar(u"ix_c", SEL(n, EQ(n, I(n, u"phase"), I(n, B % 1),
                                fbd_xml.COL_BLK + 2280),
                          I(n, u"ix_b"),
                          ADD(n, I(n, u"idx"), I(n, w_1()),
                              fbd_xml.COL_BLK + 2400), fbd_xml.COL_BLK + 2520))
    n.outvar(u"idx", I(n, u"ix_c"))
    n.outvar(u"idx_last", EQ(n, I(n, u"idx"), I(n, w_(D.DIR_ENTRIES - 1)),
                             fbd_xml.COL_BLK + 2640))
    # ---- автомат фаз. ВНИМАНИЕ: SEL(G, IN0, IN1) = G ? IN1 : IN0, поэтому
    # "если G то A иначе B" записывается SEL(G, B, A). Промежуточные значения
    # держим в именованных переменных Python: так полярность не перепутать.
    sel_start = SEL(n, I(n, u"op_wr"), SEL(n, I(n, u"xfer_op"), I(n, B % 1),
                                          I(n, B % 2), fbd_xml.COL_BLK + 2760),
                    I(n, B % 4), fbd_xml.COL_BLK + 2880)      # запись ? 4 : (перенос ? 2 : 1)
    n.outvar(u"ph_a", SEL(n, I(n, u"start_p"), I(n, u"phase"), sel_start,
                          fbd_xml.COL_BLK + 3000))                # старт ? sel_start : phase
    n.outvar(u"ph_b", SEL(n, I(n, u"stop_now"), I(n, u"ph_a"), I(n, B % 9),
                          fbd_xml.COL_BLK + 3120))                # конец обхода ? 9 : ph_a
    n.outvar(u"ph_c", SEL(n, EQ(n, I(n, u"phase"), I(n, B % 2),
                                fbd_xml.COL_BLK + 3240),
                          I(n, u"ph_b"), I(n, B % 9), fbd_xml.COL_BLK + 3360))
    sel_zf = SEL(n, I(n, u"ZeroFill"), I(n, B % 2), I(n, B % 5),
                 fbd_xml.COL_BLK + 3480)                          # забивка ? 5 : 2
    sel_al = SEL(n, I(n, u"alloc_rdy"), I(n, B % 4), sel_zf,
                 fbd_xml.COL_BLK + 3600)                          # блок есть ? sel_zf : 4
    sel_df = SEL(n, I(n, u"disk_full"), sel_al, I(n, B % 9),
                 fbd_xml.COL_BLK + 3720)                          # места нет ? 9 : sel_al
    n.outvar(u"ph_d", SEL(n, EQ(n, I(n, u"phase"), I(n, B % 4),
                                fbd_xml.COL_BLK + 3840),
                          I(n, u"ph_c"), sel_df, fbd_xml.COL_BLK + 3960))
    n.outvar(u"ph_e", SEL(n, EQ(n, I(n, u"phase"), I(n, B % 5),
                                fbd_xml.COL_BLK + 4080),
                          I(n, u"ph_d"),
                          SEL(n, I(n, u"zf_last"), I(n, B % 5), I(n, B % 2),
                              fbd_xml.COL_BLK + 4200), fbd_xml.COL_BLK + 4320))
    n.outvar(u"ph_f", SEL(n, EQ(n, I(n, u"phase"), I(n, B % 9),
                                fbd_xml.COL_BLK + 4440),
                          I(n, u"ph_e"), I(n, B % 0), fbd_xml.COL_BLK + 4560))
    n.outvar(u"phase", I(n, u"ph_f"))
    n.outvar(u"active", OR(n, AND(n, I(n, u"active"), NOT(n, I(n, u"ph9"),
                                                         fbd_xml.COL_BLK + 4680),
                                 fbd_xml.COL_BLK + 4800),
                           I(n, u"start_p"), fbd_xml.COL_BLK + 4920))

    # ---- СЕТЬ 2: адрес записи каталога, чтение и сравнение имени ----
    n = p.network(u"СЕТЬ 2. Адрес записи каталога, чтение и сравнение имени с FCB")
    n.outvar(u"ents", ADD(n, I(n, W % D.DIR_SECT),
                          SHR(n, I(n, u"idx"), I(n, W % 2),
                              fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 340))
    n.outvar(u"entb", W2B(n, SHL(n, AND(n, I(n, u"idx"), I(n, W % 3),
                                       fbd_xml.COL_BLK + 460),
                                I(n, W % 5), fbd_xml.COL_BLK + 580),
                          fbd_xml.COL_BLK + 700))
    n.outvar(u"st", I(n, u"GVL_DISK.Disk[ents, entb]"))
    n.outvar(u"free_ent", EQ(n, I(n, u"st"), I(n, H % DELETED),
                             fbd_xml.COL_BLK + 200))
    # Старший бит имени - признак атрибута, при сравнении он снимается маской
    # 7Fh и в записи каталога, и в FCB - ровно как в настоящем BDOS.
    for k in NAME_BYTES:
        n.outvar(u"e%d" % k, AND(n, I(n, u"GVL_DISK.Disk[ents, entb + %d]" % k),
                                 I(n, H % NAME_MASK), fbd_xml.COL_BLK + 200))
        n.outvar(u"p%d" % k, AND(n, I(n, u"GVL_MEM.Memory[FCB + %d]" % k),
                                 I(n, H % NAME_MASK), fbd_xml.COL_BLK + 320))
    for k in NAME_BYTES:
        # '?' в FCB - подстановка: подходит любой символ
        n.outvar(u"m%d" % k, OR(n, EQ(n, I(n, u"p%d" % k), I(n, H % WILDCARD)),
                                EQ(n, I(n, u"p%d" % k), I(n, u"e%d" % k),
                                   fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 340))
    n.outvar(u"name_ok", ANDL(n, [I(n, u"m%d" % k) for k in NAME_BYTES],
                              x0=fbd_xml.COL_BLK + 480))
    n.outvar(u"match", ANDL(n, [I(n, u"name_ok"),
                                EQ(n, I(n, u"st"), I(n, u"GVL_CPM.CurUser"),
                                   fbd_xml.COL_BLK + 720)],
                            x0=fbd_xml.COL_BLK + 860))
    n.outvar(u"ex_db", I(n, u"GVL_DISK.Disk[ents, entb + 12]"))
    n.outvar(u"ex_fcb", I(n, u"GVL_MEM.Memory[FCB + 12]"))
    n.outvar(u"ex_ok", EQ(n, I(n, u"ex_db"), I(n, u"ex_fcb"),
                          fbd_xml.COL_BLK + 200))
    n.outvar(u"m_eff", SEL(n, I(n, u"op_ext"), I(n, u"match"),
                           AND(n, I(n, u"match"), I(n, u"ex_ok"),
                               fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 320))
    n.outvar(u"dc_w", AND(n, I(n, u"idx"), I(n, W % 3), fbd_xml.COL_BLK + 440))
    n.outvar(u"dir_code", W2B(n, I(n, u"dc_w"), fbd_xml.COL_BLK + 560))
    n.outvar(u"dir_off", SHL(n, I(n, u"dc_w"), I(n, W % 5),
                             fbd_xml.COL_BLK + 680))
    n.outvar(u"dma_m", AND(n, I(n, u"GVL_CPM.DMA"), I(n, W % 0xFF80),
                           fbd_xml.COL_BLK + 800))
    n.outvar(u"dst_addr", ADD(n, I(n, u"dma_m"), I(n, u"dir_off"),
                              fbd_xml.COL_BLK + 920))

    # ---- СЕТЬ 3: действия по операциям ----
    n = p.network(u"СЕТЬ 3. Действия: поиск, открытие, закрытие, создание, "
                  u"удаление, переименование, атрибуты, размер")
    n.outvar(u"in_scan", EQ(n, I(n, u"phase"), I(n, B % 1), fbd_xml.COL_BLK + 120))
    n.outvar(u"act_search", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                     I(n, u"op_s")],
                                 x0=fbd_xml.COL_BLK + 240))
    n.outvar(u"act_open", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                   I(n, u"op_open")],
                               x0=fbd_xml.COL_BLK + 480))
    n.outvar(u"act_close", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                    I(n, u"op_close")],
                                x0=fbd_xml.COL_BLK + 720))
    n.outvar(u"act_make", ANDL(n, [I(n, u"in_scan"), I(n, u"free_ent"),
                                   I(n, u"op_make")],
                               x0=fbd_xml.COL_BLK + 960))
    n.outvar(u"act_del", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                  I(n, u"op_del")],
                              x0=fbd_xml.COL_BLK + 1200))
    n.outvar(u"act_ren", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                  I(n, u"op_ren")],
                              x0=fbd_xml.COL_BLK + 1440))
    n.outvar(u"act_att", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                  I(n, u"op_att")],
                              x0=fbd_xml.COL_BLK + 1680))
    n.outvar(u"act_size", ANDL(n, [I(n, u"in_scan"), I(n, u"m_eff"),
                                   I(n, u"op_size")],
                               x0=fbd_xml.COL_BLK + 1920))
    n.outvar(u"hit_now", ORL(n, [I(n, u"act_search"), I(n, u"act_open"),
                                 I(n, u"act_close"), I(n, u"act_make"),
                                 I(n, u"act_ren"), I(n, u"act_att")],
                             x0=fbd_xml.COL_BLK + 2160))
    n.outvar(u"stop_now", OR(n, I(n, u"hit_now"), I(n, u"idx_last"),
                             fbd_xml.COL_BLK + 2400))
    n.outvar(u"copy_a", SEL(n, I(n, u"act_search"), I(n, W % D.SCRATCH),
                            I(n, u"dst_addr"), fbd_xml.COL_BLK + 2520))
    # поиск: найденная запись каталога копируется в буфер DMA (32 байта)
    for k in range(D.ENT_SIZE):
        n.outvar(u"GVL_MEM.Memory[copy_a + %d]" % k,
                 I(n, u"GVL_DISK.Disk[ents, entb + %d]" % k))
    # открытие (и поиск экстента): запись каталога переписывается в FCB
    for k in range(D.ENT_SIZE):
        tgt = u"GVL_MEM.Memory[FCB + %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"act_open"), I(n, tgt),
                          I(n, u"GVL_DISK.Disk[ents, entb + %d]" % k),
                          fbd_xml.COL_BLK + 200))
    tgt = u"GVL_MEM.Memory[FCB + 32]"
    n.outvar(tgt, SEL(n, I(n, u"act_open"), I(n, tgt), I(n, B % 0),
                      fbd_xml.COL_BLK + 200))
    # закрытие: счётчик записей и карта блоков возвращаются в каталог
    for k in range(15, D.ENT_SIZE):
        tgt = u"GVL_DISK.Disk[ents, entb + %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"act_close"), I(n, tgt),
                          I(n, u"GVL_MEM.Memory[FCB + %d]" % k),
                          fbd_xml.COL_BLK + 200))
    # создание файла: свободная запись каталога заполняется из FCB
    tgt = u"GVL_DISK.Disk[ents, entb]"
    n.outvar(tgt, SEL(n, I(n, u"act_make"), I(n, tgt), I(n, u"GVL_CPM.CurUser"),
                      fbd_xml.COL_BLK + 400))
    for k in NAME_BYTES:
        tgt = u"GVL_DISK.Disk[ents, entb + %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"act_make"), I(n, tgt),
                          I(n, u"GVL_MEM.Memory[FCB + %d]" % k),
                          fbd_xml.COL_BLK + 520))
    for k in range(12, D.ENT_SIZE):
        tgt = u"GVL_DISK.Disk[ents, entb + %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"act_make"), I(n, tgt), I(n, B % 0),
                          fbd_xml.COL_BLK + 640))
    for k in list(range(12, D.ENT_SIZE)) + [32]:
        tgt = u"GVL_MEM.Memory[FCB + %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"act_make"), I(n, tgt), I(n, B % 0),
                          fbd_xml.COL_BLK + 760))
    # переименование: новое имя лежит в FCB+16 (как требует BDOS 23)
    for k in range(11):
        tgt = u"GVL_DISK.Disk[ents, entb + %d]" % (1 + k)
        n.outvar(tgt, SEL(n, I(n, u"act_ren"), I(n, tgt),
                          I(n, u"GVL_MEM.Memory[FCB + %d]" % (16 + k)),
                          fbd_xml.COL_BLK + 880))
    # атрибуты: старшие биты расширения записи (t1 - R/O, t2 - SYS, t3 - ARC)
    for i in range(3):
        tgt = u"GVL_DISK.Disk[ents, entb + %d]" % (9 + i)
        n.outvar(tgt, SEL(n, I(n, u"act_att"), I(n, tgt),
                          OR(n, AND(n, I(n, tgt), I(n, H % NAME_MASK),
                                    fbd_xml.COL_BLK + 1000),
                              AND(n, I(n, u"GVL_MEM.Memory[FCB + %d]" % (9 + i)),
                                  I(n, H % ATTR_BIT), fbd_xml.COL_BLK + 1120),
                              fbd_xml.COL_BLK + 1240), fbd_xml.COL_BLK + 1360))
    # удаление: первый байт записи становится E5h, блоки освобождаются
    tgt = u"GVL_DISK.Disk[ents, entb]"
    n.outvar(tgt, SEL(n, I(n, u"act_del"), I(n, tgt), I(n, H % DELETED),
                      fbd_xml.COL_BLK + 1480))
    n.outvar(u"any_del", OR(n, I(n, u"any_del"), I(n, u"act_del"),
                            fbd_xml.COL_BLK + 1600))
    for j in range(D.BLOCKS_PER_ENTRY):
        if D.BLK_BYTES == 1:
            n.outvar(u"fb%d" % j, I(n, u"GVL_DISK.Disk[ents, entb + %d]"
                                    % (16 + j)))
        else:
            n.outvar(u"fb%d" % j,
                     OR(n, SHL(n, I(n, u"GVL_DISK.Disk[ents, entb + %d]"
                                     % (17 + 2 * j)), I(n, W % 8),
                                fbd_xml.COL_BLK + 1000),
                        I(n, u"GVL_DISK.Disk[ents, entb + %d]" % (16 + 2 * j),
                          fbd_xml.COL_BLK + 1120), fbd_xml.COL_BLK + 1240))
        # индекс байта карты маскируется: сбойная запись не выведет индекс за
        # границу массива (иначе авария ПЛК), а просто испортит не тот бит
        n.outvar(u"fi%d" % j, AND(n, SHR(n, I(n, u"fb%d" % j), I(n, W % 3),
                                         fbd_xml.COL_BLK + 1360),
                                  I(n, W % (D.ALLOC_BYTES - 1)),
                                  fbd_xml.COL_BLK + 1480))
        n.outvar(u"fm%d" % j, NOT(n, SHL(n, I(n, H % 1),
                                         W2B(n, AND(n, I(n, u"fb%d" % j),
                                                    I(n, W % 7),
                                                    fbd_xml.COL_BLK + 1600),
                                             fbd_xml.COL_BLK + 1720),
                                  fbd_xml.COL_BLK + 1840),
                                  fbd_xml.COL_BLK + 1900))
        tgt = u"GVL_DISK.Alloc[fi%d]" % j
        n.outvar(tgt, SEL(n, ANDL(n, [I(n, u"act_del"),
                                      NE(n, I(n, u"fb%d" % j), I(n, w_0()),
                                         fbd_xml.COL_BLK + 1960)],
                                  x0=fbd_xml.COL_BLK + 2080),
                          I(n, tgt),
                          AND(n, I(n, tgt), I(n, u"fm%d" % j),
                              fbd_xml.COL_BLK + 2200), fbd_xml.COL_BLK + 2320))
    # размер файла: максимальный номер последней записи + 1 по всему каталогу.
    # rc берётся ИЗ ЗАПИСИ КАТАЛОГА, а не из FCB: функция 35 обязана работать
    # и для файла, который программой не открывался.
    n.outvar(u"ex_w", I(n, u"ex_db"))
    n.outvar(u"rc_w", I(n, u"GVL_DISK.Disk[ents, entb + 15]"))
    n.outvar(u"fs_ent", ADD(n, SHL(n, I(n, u"ex_w"), I(n, W % ENT_SHIFT),
                                  fbd_xml.COL_BLK + 2440),
                            I(n, u"rc_w"), fbd_xml.COL_BLK + 2560))
    n.outvar(u"fs_max", SEL(n, AND(n, I(n, u"act_size"),
                                   GT(n, I(n, u"fs_ent"), I(n, u"fs_max"),
                                      fbd_xml.COL_BLK + 2680), fbd_xml.COL_BLK + 2800),
                            I(n, u"fs_max"), I(n, u"fs_ent"), fbd_xml.COL_BLK + 2920))
    n.outvar(u"fs_code", SEL(n, I(n, u"act_size"), I(n, u"fs_code"),
                             I(n, u"dir_code"), fbd_xml.COL_BLK + 3040))
    n.outvar(u"fs_seen", OR(n, I(n, u"fs_seen"), I(n, u"act_size"),
                            fbd_xml.COL_BLK + 3160))
    # запись размера в поля случайного номера записи (FCB+33..35)
    n.outvar(u"done_ev", EQ(n, I(n, u"phase"), I(n, B % 9), fbd_xml.COL_BLK + 3280))
    n.outvar(u"size_ev", AND(n, I(n, u"done_ev"), I(n, u"op_size"),
                             fbd_xml.COL_BLK + 3400))
    tgt = u"GVL_MEM.Memory[FCB + 33]"
    n.outvar(tgt, SEL(n, I(n, u"size_ev"), I(n, tgt),
                      W2B(n, AND(n, I(n, u"fs_max"), I(n, W % 0xFF),
                                 fbd_xml.COL_BLK + 3520), fbd_xml.COL_BLK + 3640),
                      fbd_xml.COL_BLK + 3760))
    tgt = u"GVL_MEM.Memory[FCB + 34]"
    n.outvar(tgt, SEL(n, I(n, u"size_ev"), I(n, tgt),
                      W2B(n, AND(n, SHR(n, I(n, u"fs_max"), I(n, W % 8),
                                        fbd_xml.COL_BLK + 3880),
                                 I(n, W % 0xFF), fbd_xml.COL_BLK + 4000),
                           fbd_xml.COL_BLK + 4120), fbd_xml.COL_BLK + 4240))
    tgt = u"GVL_MEM.Memory[FCB + 35]"
    n.outvar(tgt, SEL(n, I(n, u"size_ev"), I(n, tgt),
                      W2B(n, SHR(n, I(n, u"fs_max"), I(n, W % 8),
                                 fbd_xml.COL_BLK + 4360), fbd_xml.COL_BLK + 4480),
                      fbd_xml.COL_BLK + 4600))
    n.outvar(u"Out_HL", SEL(n, I(n, u"hit_now"), I(n, u"Out_HL"),
                            I(n, u"dst_addr"), fbd_xml.COL_BLK + 4720))
    n.outvar(u"Out_Idx", SEL(n, I(n, u"hit_now"), I(n, u"Out_Idx"), I(n, u"idx"),
                             fbd_xml.COL_BLK + 4840))
    n.outvar(u"eng_cnt", ADD(n, I(n, u"eng_cnt"), I(n, U1),
                             fbd_xml.COL_BLK + 4960))
    n.outvar(u"GVL_CPM.Diag.Search_Cnt",
             SEL(n, I(n, u"start_p"), I(n, u"GVL_CPM.Diag.Search_Cnt"),
                 I(n, u"eng_cnt"), fbd_xml.COL_BLK + 5080))

    # ---- СЕТЬ 4: адресация блока, выделение блока, адреса переноса ----
    n = p.network(u"СЕТЬ 4. Адресация блока файла, выделение блока из карты "
                  u"занятости, адреса переноса")
    n.outvar(u"cr", I(n, u"GVL_MEM.Memory[FCB + 32]"))
    n.outvar(u"cr_w", I(n, u"cr"))
    n.outvar(u"cr_n", ADD(n, I(n, u"cr"), I(n, B % 1), fbd_xml.COL_BLK + 200))
    n.outvar(u"blkidx", SHR(n, I(n, u"cr_w"), I(n, W % D.BSH),
                            fbd_xml.COL_BLK + 320))
    if D.BLK_BYTES == 2:
        # при DSM > 255 карта блоков занимает 2 байта на блок
        n.outvar(u"blk2", SHL(n, I(n, u"blkidx"), I(n, W % 1),
                              fbd_xml.COL_BLK + 440))
    else:
        n.outvar(u"blk2", I(n, u"blkidx"))
    n.outvar(u"ofs", AND(n, I(n, u"cr_w"), I(n, W % (D.RECS_PER_BLOCK - 1)),
                         fbd_xml.COL_BLK + 680))
    n.outvar(u"blkaddr", ADD(n, ADD(n, I(n, u"FCB"), I(n, W % 16),
                                    fbd_xml.COL_BLK + 800),
                             I(n, u"blk2"), fbd_xml.COL_BLK + 920))
    _blk_read(n, p, u"blk_hi_w", u"blk_lo_w", u"blk", u"blkaddr")
    n.outvar(u"rc", I(n, u"GVL_MEM.Memory[FCB + 15]"))
    n.outvar(u"blk0", EQ(n, I(n, u"blk"), I(n, w_0()), fbd_xml.COL_BLK + 1040))
    # ---- поиск свободного блока в битовой карте занятости ----
    n.outvar(u"in_alloc", EQ(n, I(n, u"phase"), I(n, B % 4),
                             fbd_xml.COL_BLK + 1160))
    n.outvar(u"na_i", AND(n, SHR(n, I(n, u"na"), I(n, W % 3),
                                 fbd_xml.COL_BLK + 1280),
                          I(n, W % (D.ALLOC_BYTES - 1)), fbd_xml.COL_BLK + 1400))
    n.outvar(u"na_byte", I(n, u"GVL_DISK.Alloc[na_i]"))
    n.outvar(u"na_bit", SHL(n, I(n, H % 1),
                            W2B(n, AND(n, I(n, u"na"), I(n, W % 7),
                                       fbd_xml.COL_BLK + 1520),
                                fbd_xml.COL_BLK + 1640), fbd_xml.COL_BLK + 1760))
    n.outvar(u"na_used", NE(n, AND(n, I(n, u"na_byte"), I(n, u"na_bit"),
                                   fbd_xml.COL_BLK + 1880),
                            I(n, H % 0), fbd_xml.COL_BLK + 2000))
    n.outvar(u"na_free", ANDL(n, [I(n, u"in_alloc"), I(n, u"blk0"),
                                  NOT(n, I(n, u"na_used"), fbd_xml.COL_BLK + 2120),
                                  GE(n, I(n, u"na"), I(n, w_(D.FIRST_DATA_BLOCK)),
                                     fbd_xml.COL_BLK + 2240),
                                  LE(n, I(n, u"na"), I(n, w_(D.DSM)),
                                     fbd_xml.COL_BLK + 2360)],
                              x0=fbd_xml.COL_BLK + 2480))
    n.outvar(u"alloc_rdy", AND(n, I(n, u"in_alloc"),
                               OR(n, NOT(n, I(n, u"blk0"), fbd_xml.COL_BLK + 2600),
                                  I(n, u"na_free"), fbd_xml.COL_BLK + 2720),
                               fbd_xml.COL_BLK + 2840))
    # блок записывается в карту FCB и помечается в битовой карте занятости
    tgt = u"GVL_MEM.Memory[blkaddr]"
    n.outvar(tgt, SEL(n, I(n, u"na_free"), I(n, tgt),
                      W2B(n, AND(n, I(n, u"na"), I(n, W % 0xFF),
                                 fbd_xml.COL_BLK + 2960), fbd_xml.COL_BLK + 3080),
                      fbd_xml.COL_BLK + 3200))
    if D.BLK_BYTES == 2:
        tgt = u"GVL_MEM.Memory[blkaddr + 1]"
        n.outvar(tgt, SEL(n, I(n, u"na_free"), I(n, tgt),
                          W2B(n, SHR(n, I(n, u"na"), I(n, W % 8),
                                     fbd_xml.COL_BLK + 3320), fbd_xml.COL_BLK + 3440),
                          fbd_xml.COL_BLK + 3560))
    tgt = u"GVL_DISK.Alloc[na_i]"
    n.outvar(tgt, SEL(n, I(n, u"na_free"), I(n, tgt),
                      OR(n, I(n, tgt), I(n, u"na_bit"), fbd_xml.COL_BLK + 3680),
                      fbd_xml.COL_BLK + 3800))
    n.outvar(u"next_n", W2B(n, ADD(n, AND(n, I(n, u"na"), I(n, W % 0xFF),
                                          fbd_xml.COL_BLK + 3920),
                                  I(n, w_1()), fbd_xml.COL_BLK + 4040),
                            fbd_xml.COL_BLK + 4160))
    n.outvar(u"GVL_CPM.Next_Block",
             SEL(n, I(n, u"na_free"), I(n, u"GVL_CPM.Next_Block"),
                 I(n, u"next_n"), fbd_xml.COL_BLK + 4280))
    n.outvar(u"GVL_CPM.Last_Block",
             SEL(n, I(n, u"na_free"), I(n, u"GVL_CPM.Last_Block"),
                 W2B(n, I(n, u"na"), fbd_xml.COL_BLK + 4400),
                 fbd_xml.COL_BLK + 4520))
    n.outvar(u"na_step", SEL(n, GE(n, I(n, u"na"), I(n, w_(D.DSM)),
                                   fbd_xml.COL_BLK + 4640),
                             I(n, w_(D.FIRST_DATA_BLOCK)),
                             ADD(n, I(n, u"na"), I(n, w_1()),
                                 fbd_xml.COL_BLK + 4760), fbd_xml.COL_BLK + 4880))
    n.outvar(u"na", SEL(n, I(n, u"start_p"), I(n, u"GVL_CPM.Next_Block"),
                        SEL(n, AND(n, I(n, u"in_alloc"), I(n, u"blk0"),
                                   fbd_xml.COL_BLK + 5000),
                            I(n, u"na_step"), I(n, u"na"), fbd_xml.COL_BLK + 5120),
                        fbd_xml.COL_BLK + 5240))
    n.outvar(u"nf_cnt", SEL(n, I(n, u"start_p"), I(n, w_0()),
                            SEL(n, AND(n, I(n, u"in_alloc"), I(n, u"blk0"),
                                       fbd_xml.COL_BLK + 5360),
                                ADD(n, I(n, u"nf_cnt"), I(n, w_1()),
                                    fbd_xml.COL_BLK + 5480), I(n, u"nf_cnt"),
                                fbd_xml.COL_BLK + 5600), fbd_xml.COL_BLK + 5720))
    n.outvar(u"disk_full", AND(n, I(n, u"in_alloc"),
                               GT(n, I(n, u"nf_cnt"), I(n, w_(D.TOTAL_BLOCKS)),
                                  fbd_xml.COL_BLK + 5840), fbd_xml.COL_BLK + 5960))
    # ---- адрес записи на диске ----
    n.outvar(u"blk_sec", ADD(n, SHL(n, I(n, u"blk"), I(n, W % D.BSH),
                                   fbd_xml.COL_BLK + 6080),
                             I(n, W % D.DIR_SECT), fbd_xml.COL_BLK + 6200))
    n.outvar(u"dsk", ADD(n, I(n, u"blk_sec"), I(n, u"ofs"),
                         fbd_xml.COL_BLK + 6320))
    n.outvar(u"zf_w", I(n, u"zf_g"))
    n.outvar(u"dsk_zf", ADD(n, I(n, u"blk_sec"), I(n, u"zf_w"),
                            fbd_xml.COL_BLK + 6440))
    # чтение возможно, только если блок выделен и запись есть в файле
    n.outvar(u"rd_ok", ANDL(n, [I(n, u"ph2"), I(n, u"op_rd"),
                                NOT(n, I(n, u"blk0"), fbd_xml.COL_BLK + 6680),
                                LT(n, I(n, u"cr"), I(n, u"rc"),
                                   fbd_xml.COL_BLK + 6800)],
                            x0=fbd_xml.COL_BLK + 6920))
    n.outvar(u"wr_ok", AND(n, I(n, u"ph2"), I(n, u"op_wr"),
                           fbd_xml.COL_BLK + 7040))
    n.outvar(u"inc_rc", AND(n, I(n, u"wr_ok"),
                            NOT(n, LT(n, I(n, u"cr"), I(n, u"rc"),
                                      fbd_xml.COL_BLK + 7160),
                                fbd_xml.COL_BLK + 7280), fbd_xml.COL_BLK + 7400))
    n.outvar(u"cr_gate", OR(n, I(n, u"rd_ok"), I(n, u"wr_ok"),
                            fbd_xml.COL_BLK + 7520))
    tgt = u"GVL_MEM.Memory[FCB + 32]"
    n.outvar(tgt, SEL(n, I(n, u"cr_gate"), I(n, tgt), I(n, u"cr_n"),
                      fbd_xml.COL_BLK + 7640))
    tgt = u"GVL_MEM.Memory[FCB + 15]"
    n.outvar(tgt, SEL(n, I(n, u"inc_rc"), I(n, tgt), I(n, u"cr_n"),
                      fbd_xml.COL_BLK + 7760))
    # Обе копии выполняются каждый скан, но у неактивного направления адрес
    # заменён «мусорным» сектором: данные портятся только в мусорном месте.
    n.outvar(u"xfer_m", SEL(n, I(n, u"rd_ok"), I(n, W % D.SCRATCH),
                            I(n, u"dma_m"), fbd_xml.COL_BLK + 7880))
    n.outvar(u"xfer_d", SEL(n, I(n, u"rd_ok"), I(n, W % D.DISK_SCRATCH_SEC),
                            I(n, u"dsk"), fbd_xml.COL_BLK + 8000))
    n.outvar(u"xfer_d2", SEL(n, I(n, u"wr_ok"), I(n, W % D.DISK_SCRATCH_SEC),
                             I(n, u"dsk"), fbd_xml.COL_BLK + 8120))
    n.outvar(u"xfer_m2", SEL(n, I(n, u"wr_ok"), I(n, W % D.SCRATCH),
                             I(n, u"dma_m"), fbd_xml.COL_BLK + 8240))

    # ---- СЕТЬ 5: перенос 128 байт ----
    n = p.network(u"СЕТЬ 5. Перенос 128 байт: Disk[сектор, k] и Memory[DMA+k]")
    for k in range(D.REC_SIZE):
        n.outvar(u"GVL_MEM.Memory[xfer_m + %d]" % k,
                 I(n, u"GVL_DISK.Disk[xfer_d, %d]" % k))
    for k in range(D.REC_SIZE):
        n.outvar(u"GVL_DISK.Disk[xfer_d2, %d]" % k,
                 I(n, u"GVL_MEM.Memory[xfer_m2 + %d]" % k))

    # ---- СЕТЬ 6: забивка нулями вновь выделенного блока ----
    n = p.network(u"СЕТЬ 6. Забивка нулями вновь выделенного блока "
                  u"(по одной записи 128 байт за скан)")
    n.outvar(u"in_zf", EQ(n, I(n, u"phase"), I(n, B % 5), fbd_xml.COL_BLK + 120))
    n.outvar(u"zf_last", SEL(n, I(n, u"in_zf"),
                             EQ(n, I(n, u"zf_g"), I(n, B % (D.RECS_PER_BLOCK - 1)),
                                fbd_xml.COL_BLK + 200), I(n, u"FALSE"),
                             fbd_xml.COL_BLK + 320))
    for k in range(D.REC_SIZE):
        tgt = u"GVL_DISK.Disk[dsk_zf, %d]" % k
        n.outvar(tgt, SEL(n, I(n, u"in_zf"), I(n, tgt), I(n, H % 0),
                          fbd_xml.COL_BLK + 440))
    n.outvar(u"zf_g", SEL(n, I(n, u"in_zf"),
                          ADD(n, I(n, u"zf_g"), I(n, B % 1),
                              fbd_xml.COL_BLK + 560), I(n, B % 0),
                          fbd_xml.COL_BLK + 680))

    # ---- СЕТЬ 7: код возврата и выходные сигналы ----
    n = p.network(u"СЕТЬ 7. Код возврата и выходные сигналы движка")
    n.outvar(u"ph1", EQ(n, I(n, u"phase"), I(n, B % 1), fbd_xml.COL_BLK + 120))
    n.outvar(u"ph2", EQ(n, I(n, u"phase"), I(n, B % 2), fbd_xml.COL_BLK + 240))
    n.outvar(u"ph4", EQ(n, I(n, u"phase"), I(n, B % 4), fbd_xml.COL_BLK + 360))
    n.outvar(u"ph5", EQ(n, I(n, u"phase"), I(n, B % 5), fbd_xml.COL_BLK + 480))
    n.outvar(u"ph9", EQ(n, I(n, u"phase"), I(n, B % 9), fbd_xml.COL_BLK + 600))
    # 1) старт - код "не найдено"; 2) нашли запись - код каталога 0..3
    n.outvar(u"res_a", SEL(n, I(n, u"start_p"), I(n, u"Result"), I(n, H % 0xFF),
                           fbd_xml.COL_BLK + 720))
    n.outvar(u"res_b", SEL(n, I(n, u"hit_now"), I(n, u"dir_code"), I(n, u"res_a"),
                           fbd_xml.COL_BLK + 840))
    # 3) конец прохода для DELETE: 0 - удалено, FFh - нечего удалять
    n.outvar(u"res_c", SEL(n, AND(n, I(n, u"ph1"), I(n, u"idx_last"),
                                  fbd_xml.COL_BLK + 960),
                           SEL(n, I(n, u"any_del"), I(n, H % 0xFF), I(n, H % 0x00),
                               fbd_xml.COL_BLK + 1080), I(n, u"res_b"),
                           fbd_xml.COL_BLK + 1200))
    # 4) перенос записи. ВАЖНО: rd_ok/wr_ok вычисляются в сети 4 по фазе
    # ПРОШЛОГО скана, то есть истинны ровно в том скане, когда перенос уже
    # сделан, - и это же скан завершения (фаза 9). Поэтому код возврата
    # берётся по rd_ok/wr_ok, а не по ph2: по ph2 он всегда получался бы
    # "данных нет", и любая программа CP/M решила бы, что файл кончился.
    n.outvar(u"res_x", SEL(n, I(n, u"rd_ok"), I(n, u"res_c"), I(n, H % 0x00),
                           fbd_xml.COL_BLK + 1320))
    res_size = SEL(n, I(n, u"fs_seen"), I(n, H % 0xFF), I(n, u"fs_code"),
                   fbd_xml.COL_BLK + 1440)
    n.outvar(u"res_e", SEL(n, AND(n, I(n, u"ph9"), I(n, u"op_size"),
                                  fbd_xml.COL_BLK + 1560),
                           I(n, u"res_x"), res_size, fbd_xml.COL_BLK + 1680))
    sel_wr = SEL(n, I(n, u"wr_ok"), I(n, u"res_e"), I(n, H % 0x00),
                 fbd_xml.COL_BLK + 1800)
    n.outvar(u"Result", SEL(n, I(n, u"disk_full"), sel_wr, I(n, H % 0xFF),
                            fbd_xml.COL_BLK + 1920))
    n.outvar(u"GVL_CPM.IO_Result",
             SEL(n, I(n, u"hit_now"), I(n, u"GVL_CPM.IO_Result"),
                 I(n, u"dir_code"), fbd_xml.COL_BLK + 2040))
    n.outvar(u"Busy", I(n, u"active"))
    n.outvar(u"Done", I(n, u"ph9"))
    return p


def w_0():
    return u"WORD#0"


def w_1():
    return u"WORD#1"


def w_(v):
    return u"WORD#%d" % v


def _file_fn(num, name, op, doc, out_hl=False, entry_from_search=False,
             note=u""):
    u"""Построить функцию BDOS, работающую через дисковый движок (одна операция)."""
    extra = ((u"busy", u"BOOL", u"движок занят"),
             (u"start", u"BOOL", u"импульс запуска движка"),
             (u"done_l", u"BOOL", u"защёлка выхода Done движка"),
             (u"res", u"BYTE", u"защёлка кода возврата"),
             (u"hl", u"WORD", u"защёлка адреса записи каталога"),
             (u"idx", u"WORD", u"защёлка номера найденной записи"),
             (u"next_idx", u"WORD", u"номер следующей записи для SEARCH NEXT"),
             (u"eng", u"FB_CPM_DirEngine", u"экземпляр дискового движка"))
    p = _head(num, name, doc, extra=extra)
    n = p.network(u"СЕТЬ 2. Запуск дискового движка и защёлкивание его выходов")
    n.outvar(u"start", AND(n, I(n, u"hit"), NOT(n, I(n, u"busy"),
                                                fbd_xml.COL_BLK + 200),
                           fbd_xml.COL_BLK + 320))
    entry = I(n, u"GVL_CPM.Search_Idx") if entry_from_search else I(n, u"WORD#0")
    eng = n.block(u"FB_CPM_DirEngine", [
        (u"Start", I(n, u"start")),
        (u"Op", I(n, B % op)),
        (u"Entry", entry),
        (u"FCB", I(n, u"GVL_CPM.FCB_Addr")),
        (u"ZeroFill", I(n, u"FALSE")),
    ], [u"Busy", u"Done", u"Result", u"Out_HL", u"Out_Idx"], instance=u"eng",
        x=fbd_xml.COL_BLK + 560)
    # правило 9.1: выход вызова FB сразу защёлкивается в переменную POU
    n.outvar(u"busy", eng.out(u"Busy"))
    n.outvar(u"done_l", eng.out(u"Done"))
    n.outvar(u"res", eng.out(u"Result"))
    n.outvar(u"hl", eng.out(u"Out_HL"))
    n.outvar(u"idx", eng.out(u"Out_Idx"))
    n = p.network(u"СЕТЬ 3. Результат: A, HL и номер записи для SEARCH NEXT")
    n.outvar(u"done_gate", I(n, u"done_l"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"done_l"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"res"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Dir_Result", SEL(n, I(n, u"done_l"),
                                        I(n, u"GVL_CPM.Dir_Result"), I(n, u"res"),
                                        fbd_xml.COL_BLK + 320))
    if out_hl:
        n.outvar(u"GVL_CPM.Ret_HL", SEL(n, I(n, u"done_l"),
                                        I(n, u"GVL_CPM.Ret_HL"), I(n, u"hl"),
                                        fbd_xml.COL_BLK + 440))
        # функция вернула значение в HL - трап запишет его в пару HL
        n.outvar(u"GVL_CPM.Ret_HL_En",
                 SEL(n, I(n, u"done_l"), I(n, u"GVL_CPM.Ret_HL_En"),
                     I(n, u"TRUE"), fbd_xml.COL_BLK + 560))
    if entry_from_search:
        n.outvar(u"next_idx", ADD(n, I(n, u"idx"), I(n, u"WORD#1"),
                                  fbd_xml.COL_BLK + 560))
        n.outvar(u"GVL_CPM.Search_Idx",
                 SEL(n, I(n, u"done_l"), I(n, u"GVL_CPM.Search_Idx"),
                     I(n, u"next_idx"), fbd_xml.COL_BLK + 680))
    _finish(p, num, note)
    return p


# ======================================================================
# ФУНКЦИИ BDOS
# ======================================================================
def make_conin():
    p = _head(F_CONIN, u"CONIN", u"ввод символа с консоли в A",
              extra=((u"got", u"BOOL", u"символ получен"),))
    n = p.network(u"СЕТЬ 2. Ждём символ от HMI: как только он готов - забираем")
    n.outvar(u"got", AND(n, I(n, u"hit"), I(n, u"GVL_CPM.ConIn_Ready"),
                         fbd_xml.COL_BLK + 200))
    n.outvar(u"done_gate", I(n, u"got"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"got"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"GVL_CPM.ConIn_Char"),
                                     fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.ConIn_Ready", SEL(n, I(n, u"got"),
                                         I(n, u"GVL_CPM.ConIn_Ready"), I(n, u"FALSE"),
                                         fbd_xml.COL_BLK + 440))
    _finish(p, F_CONIN, u"ждёт символ от HMI")
    return p


def make_conout():
    p = _head(F_CONOUT, u"CONOUT", u"вывод символа из E на консоль")
    n = p.network(u"СЕТЬ 2. Символ из регистра E - в консоль и в журнал")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"ch", I(n, u"GVL_CPM.Reg_E"))
    n.outvar(u"GVL_CPM.ConOut_Char", SEL(n, I(n, u"hit"),
                                         I(n, u"GVL_CPM.ConOut_Char"), I(n, u"ch")))
    n.outvar(u"GVL_CPM.ConOut_Ready", I(n, u"hit"))
    _echo_log(p, I(n, u"hit"))
    _finish(p, F_CONOUT)
    return p


def make_printstr():
    p = _head(F_PRINTSTR, u"PRINTSTR",
              u"вывод строки по адресу DE до символа '$' (один символ за скан)",
              extra=((u"ptr", u"WORD", u"указатель на следующий символ"),
                     (u"init_p", u"BOOL", u"первый скан вывода - загрузка указателя"),
                     (u"ptr_eff", u"WORD", u"адрес символа в этом скане"),
                     (u"is_end", u"BOOL", u"встречен символ '$'"),
                     # take - ПРИЗНАК, а не байт. Раньше здесь стояла переменная
                     # val : BYTE, и кодогенерация выдавала C32 'BOOL' -> 'BYTE'
                     # (запись признака в байт) и C32 'BYTE' -> 'BOOL' (байт на
                     # входе G блока SEL). Найдено на этапе 4.
                     (u"take", u"BOOL", u"символ выводится в этом скане")))
    n = p.network(u"СЕТЬ 2. Чтение символа строки, вывод и продвижение указателя")
    n.outvar(u"init_p", AND(n, I(n, u"hit"), EQ(n, I(n, u"ptr"), I(n, u"WORD#0"),
                                           fbd_xml.COL_BLK + 200),
                            fbd_xml.COL_BLK + 320))
    n.outvar(u"ptr_eff", SEL(n, I(n, u"init_p"), I(n, u"ptr"),
                             I(n, u"GVL_CPM.Param_DE"), fbd_xml.COL_BLK + 440))
    n.outvar(u"ch", I(n, u"GVL_MEM.Memory[ptr_eff]"))
    n.outvar(u"is_end", EQ(n, I(n, u"ch"), I(n, H % 0x24), fbd_xml.COL_BLK + 560))
    n.outvar(u"take", AND(n, I(n, u"hit"), NOT(n, I(n, u"is_end"),
                                              fbd_xml.COL_BLK + 680),
                          fbd_xml.COL_BLK + 800))
    n.outvar(u"GVL_CPM.ConOut_Char", SEL(n, I(n, u"take"),
                                         I(n, u"GVL_CPM.ConOut_Char"), I(n, u"ch"),
                                         fbd_xml.COL_BLK + 920))
    n.outvar(u"GVL_CPM.ConOut_Ready", I(n, u"take"))
    _echo_log(p, I(n, u"take"))
    n = p.network(u"СЕТЬ 3. Продвижение указателя, конец строки и сброс указателя")
    n.outvar(u"ptr", SEL(n, I(n, u"take"),
                         SEL(n, I(n, u"hit"), I(n, u"WORD#0"), I(n, u"ptr"),
                             fbd_xml.COL_BLK + 200),
                         ADD(n, I(n, u"ptr_eff"), I(n, u"WORD#1"),
                             fbd_xml.COL_BLK + 320), fbd_xml.COL_BLK + 440))
    n.outvar(u"done_gate", AND(n, I(n, u"hit"), I(n, u"is_end"),
                               fbd_xml.COL_BLK + 560))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"done_gate"),
                                     I(n, u"GVL_CPM.Ret_Val"), I(n, H % 0x00),
                                     fbd_xml.COL_BLK + 680))
    _finish(p, F_PRINTSTR, u"по одному символу за скан")
    return p


def make_readline():
    p = _head(F_READLINE, u"READLINE",
              u"ввод строки в буфер по DE: [0]=макс.длина, [1]=длина, [2..]=текст",
              extra=((u"buf", u"WORD", u"адрес буфера"),
                     (u"buf2", u"WORD", u"адрес начала текста (buf+2)"),
                     (u"got", u"BOOL", u"символ получен"),
                     (u"is_cr", u"BOOL", u"получен CR - конец строки"),
                     (u"buflen", u"BYTE", u"текущая длина строки"),
                     (u"bl_w", u"WORD", u"длина строки как слово"),
                     (u"maxlen", u"BYTE", u"максимальная длина из буфера"),
                     (u"room", u"BOOL", u"в буфере есть место"),
                     # take - ПРИЗНАК (BOOL): раньше использовалась переменная
                     # val : BYTE, что давало C32 'BOOL' -> 'BYTE' и
                     # C32 'BYTE' -> 'BOOL' в кодогенерации (этап 4).
                     (u"take", u"BOOL", u"символ принимается в буфер")))
    n = p.network(u"СЕТЬ 2. Приём строки: символы копятся в буфере, CR завершает ввод")
    n.outvar(u"buf", I(n, u"GVL_CPM.Param_DE"))
    n.outvar(u"buf2", ADD(n, I(n, u"buf"), I(n, u"WORD#2"), fbd_xml.COL_BLK + 200))
    n.outvar(u"buflen", I(n, u"GVL_MEM.Memory[buf + 1]"))
    n.outvar(u"maxlen", I(n, u"GVL_MEM.Memory[buf]"))
    n.outvar(u"bl_w", I(n, u"buflen"))
    n.outvar(u"got", AND(n, I(n, u"hit"), I(n, u"GVL_CPM.ConIn_Ready"),
                         fbd_xml.COL_BLK + 320))
    n.outvar(u"ch", I(n, u"GVL_CPM.ConIn_Char"))
    n.outvar(u"is_cr", EQ(n, I(n, u"ch"), I(n, H % CR), fbd_xml.COL_BLK + 440))
    n.outvar(u"room", LT(n, I(n, u"buflen"), I(n, u"maxlen"),
                         fbd_xml.COL_BLK + 560))
    n.outvar(u"take", ANDL(n, [I(n, u"got"), I(n, u"room"),
                               NOT(n, I(n, u"is_cr"), fbd_xml.COL_BLK + 680)],
                           x0=fbd_xml.COL_BLK + 800))
    tgt = u"GVL_MEM.Memory[buf2 + bl_w]"
    n.outvar(tgt, SEL(n, I(n, u"take"), I(n, tgt), I(n, u"ch"),
                      fbd_xml.COL_BLK + 920))
    n.outvar(u"GVL_MEM.Memory[buf + 1]",
             SEL(n, I(n, u"take"), I(n, u"buflen"),
                 ADD(n, I(n, u"buflen"), I(n, B % 1), fbd_xml.COL_BLK + 1040),
                 fbd_xml.COL_BLK + 1160))
    _echo_log(p, I(n, u"got"))
    n.outvar(u"GVL_CPM.ConOut_Char", SEL(n, I(n, u"got"),
                                         I(n, u"GVL_CPM.ConOut_Char"), I(n, u"ch"),
                                         fbd_xml.COL_BLK + 1280))
    n.outvar(u"GVL_CPM.ConOut_Ready", I(n, u"got"))
    n.outvar(u"GVL_CPM.ConIn_Ready", SEL(n, I(n, u"got"),
                                         I(n, u"GVL_CPM.ConIn_Ready"), I(n, u"FALSE"),
                                         fbd_xml.COL_BLK + 1400))
    n = p.network(u"СЕТЬ 3. Конец ввода по CR")
    n.outvar(u"done_gate", AND(n, I(n, u"got"), I(n, u"is_cr"),
                               fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"done_gate"),
                                     I(n, u"GVL_CPM.Ret_Val"), I(n, H % 0x00),
                                     fbd_xml.COL_BLK + 320))
    _finish(p, F_READLINE, u"конец ввода - CR (редактирование строки не сделано)")
    return p


def make_const_state():
    p = _head(F_CONST, u"CONST", u"состояние консоли: E=FFh - есть ли символ")
    n = p.network(u"СЕТЬ 2. E=FFh: A := FFh, если символ готов; E=FEh: A := FFh")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"chb", EQ(n, I(n, u"GVL_CPM.Reg_E"), I(n, H % 0xFF),
                       fbd_xml.COL_BLK + 200))
    n.outvar(u"val", SEL(n, I(n, u"chb"),
                         SEL(n, I(n, u"GVL_CPM.ConIn_Ready"), I(n, H % 0x00),
                             I(n, H % 0xFF), fbd_xml.COL_BLK + 320),
                         I(n, H % 0xFF), fbd_xml.COL_BLK + 440))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"val"), fbd_xml.COL_BLK + 560))
    _finish(p, F_CONST)
    return p


def make_version():
    p = _head(F_VERSION, u"VERSION", u"версия CP/M: HL := 0022h (2.2)")
    n = p.network(u"СЕТЬ 2. HL := 0022h, A := 22h")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_HL", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL"),
                                    I(n, u"WORD#16#0022")))
    n.outvar(u"GVL_CPM.Ret_HL_En", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_HL_En"),
                                       I(n, u"TRUE"), fbd_xml.COL_BLK + 100))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, H % 0x22), fbd_xml.COL_BLK + 200))
    _finish(p, F_VERSION)
    return p


def make_resetdisk():
    p = _head(F_RESETDISK, u"RESETDISK", u"сброс диска: DMA := 0080h, диск A")
    n = p.network(u"СЕТЬ 2. DMA, диск и пользователь - в исходное состояние")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.DMA", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.DMA"),
                                 I(n, u"WORD#%d" % D.DMA_DEF)))
    n.outvar(u"GVL_CPM.CurDisk", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.CurDisk"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 400))
    _finish(p, F_RESETDISK)
    return p


def make_seldsk():
    p = _head(F_SELDSK, u"SELDSK", u"выбор диска по регистру E")
    n = p.network(u"СЕТЬ 2. Дисков два: A := 0, иначе A := FFh")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"chb", LT(n, I(n, u"GVL_CPM.Reg_E"), I(n, B % 2),
                       fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_CPM.CurDisk", SEL(n, AND(n, I(n, u"hit"), I(n, u"chb"),
                                            fbd_xml.COL_BLK + 320),
                                     I(n, u"GVL_CPM.CurDisk"), I(n, u"GVL_CPM.Reg_E"),
                                     fbd_xml.COL_BLK + 440))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     SEL(n, I(n, u"chb"), I(n, H % 0xFF),
                                         I(n, H % 0x00), fbd_xml.COL_BLK + 560),
                                     fbd_xml.COL_BLK + 680))
    _finish(p, F_SELDSK)
    return p


def make_open():
    return _file_fn(F_OPEN, u"OPEN", D.OP_OPEN,
                    u"открыть файл: найденная запись каталога переписывается в FCB",
                    note=u"обход каталога по одной записи за скан")


def make_close():
    return _file_fn(F_CLOSE, u"CLOSE", D.OP_CLOSE,
                    u"закрыть файл: карта блоков из FCB возвращается в каталог",
                    note=u"обход каталога по одной записи за скан")


def make_searchfirst():
    return _file_fn(F_SEARCHF, u"SEARCHFIRST", D.OP_SEARCH_FIRST,
                    u"поиск первой подходящей записи каталога (для DIR и STAT)",
                    out_hl=True,
                    note=u"HL - адрес записи в буфере DMA, A - код каталога 0..3")


def make_searchnext():
    return _file_fn(F_SEARCHN, u"SEARCHNEXT", D.OP_SEARCH_NEXT,
                    u"поиск следующей записи каталога (продолжение с Search_Idx)",
                    out_hl=True, entry_from_search=True,
                    note=u"продолжает с номера в GVL_CPM.Search_Idx")


def make_delete():
    return _file_fn(F_DELETE, u"DELETE", D.OP_DELETE,
                    u"удалить файл: все подходящие записи помечаются E5h, "
                    u"а их блоки освобождаются в карте занятости",
                    note=u"освобождение блоков - через битовую карту AL0/AL1")


def make_readseq():
    return _file_fn(F_READSEQ, u"READSEQ", D.OP_READSEQ,
                    u"чтение записи 128 байт по FCB в буфер DMA",
                    note=u"A=0 - прочитано, A=1 - данных нет (конец файла)")


def make_writeseq():
    return _file_fn(F_WRITESEQ, u"WRITESEQ", D.OP_WRITESEQ,
                    u"запись записи 128 байт из буфера DMA в файл",
                    note=u"блок выделяется первым свободным по карте занятости")


def make_make():
    return _file_fn(F_MAKE, u"MAKE", D.OP_MAKE,
                    u"создать файл: занимается первая свободная запись каталога")


def make_rename():
    return _file_fn(F_RENAME, u"RENAME", D.OP_RENAME,
                    u"переименовать файл: старое имя в FCB+0, новое - в FCB+16 "
                    u"(ровно так требует BDOS 23)",
                    note=u"переименовывается первая подходящая запись")


def make_attrib():
    return _file_fn(F_ATTRIB, u"ATTRIB", D.OP_ATTRIB,
                    u"установить атрибуты файла: старшие биты расширения записи "
                    u"каталога (t1 - только чтение, t2 - системный, t3 - архивный)",
                    note=u"атрибуты берутся из старших битов FCB+9..11")


def make_filesize():
    return _file_fn(F_FILESIZE, u"FILESIZE", D.OP_FILESIZE,
                    u"вычислить размер файла: обход ВСЕГО каталога, берётся "
                    u"наибольший ex*записей_в_экстенте + rc, результат кладётся "
                    u"в поля случайного номера записи FCB+33..35",
                    out_hl=False,
                    note=u"A - код каталога последней найденной записи или FFh")


def make_setrandrec():
    u"""BDOS 36 (SET RANDOM RECORD): чистая арифметика, диск не нужен."""
    p = _head(F_SETRANDREC, u"SETRANDREC",
              u"вычислить случайный номер записи из текущего положения файла: "
              u"r0..r2 := ex * записей_в_экстенте + cr (диск не читается)",
              extra=((u"ex_w", u"WORD", u"номер экстента как слово"),
                     (u"cr_w", u"WORD", u"текущая запись как слово"),
                     (u"rr", u"WORD", u"случайный номер записи"),
                     (u"r0b", u"BYTE", u"младший байт номера"),
                     (u"r1b", u"BYTE", u"средний байт номера"),
                     (u"r2b", u"BYTE", u"старший байт номера"),
                     (u"off", u"WORD", u"адрес FCB")))
    n = p.network(u"СЕТЬ 2. Номер записи := ex*записей_в_экстенте + cr, "
                  u"раскладка по трём байтам FCB")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"off", I(n, u"GVL_CPM.FCB_Addr"))
    n.outvar(u"ex_w", I(n, u"GVL_MEM.Memory[off + 12]"))
    n.outvar(u"cr_w", I(n, u"GVL_MEM.Memory[off + 32]"))
    n.outvar(u"rr", ADD(n, SHL(n, I(n, u"ex_w"), I(n, W % ENT_SHIFT),
                               fbd_xml.COL_BLK + 200),
                        I(n, u"cr_w"), fbd_xml.COL_BLK + 320))
    n.outvar(u"r0b", W2B(n, AND(n, I(n, u"rr"), I(n, W % 0xFF),
                                fbd_xml.COL_BLK + 440), fbd_xml.COL_BLK + 560))
    n.outvar(u"r1b", W2B(n, AND(n, SHR(n, I(n, u"rr"), I(n, W % 8),
                                       fbd_xml.COL_BLK + 680),
                                I(n, W % 0xFF), fbd_xml.COL_BLK + 800),
                         fbd_xml.COL_BLK + 920))
    n.outvar(u"r2b", W2B(n, SHR(n, I(n, u"rr"), I(n, W % 8),
                                fbd_xml.COL_BLK + 1040), fbd_xml.COL_BLK + 1160))
    tgt = u"GVL_MEM.Memory[off + 33]"
    n.outvar(tgt, SEL(n, I(n, u"hit"), I(n, tgt), I(n, u"r0b"),
                      fbd_xml.COL_BLK + 1280))
    tgt = u"GVL_MEM.Memory[off + 34]"
    n.outvar(tgt, SEL(n, I(n, u"hit"), I(n, tgt), I(n, u"r1b"),
                      fbd_xml.COL_BLK + 1400))
    tgt = u"GVL_MEM.Memory[off + 35]"
    n.outvar(tgt, SEL(n, I(n, u"hit"), I(n, tgt), I(n, u"r2b"),
                      fbd_xml.COL_BLK + 1520))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 1640))
    _finish(p, F_SETRANDREC)
    return p


# шаги автомата функций случайного доступа
RS_PREP, RS_FIND, RS_WAITF, RS_SETCR, RS_XFER, RS_WAITX, RS_END = 0, 1, 2, 3, 4, 5, 6


def _rand_fn(num, name, doc, is_read=True, zero_fill=False, note=u""):
    u"""Функции случайного доступа (33, 34, 40).

    Последовательность: разобрать номер записи на экстент и запись внутри
    экстента, найти в каталоге запись нужного экстента (это ровно то, что
    делает настоящий BDOS: он переоткрывает экстент), подставить cr и
    выполнить обычный последовательный перенос. Два обращения к дисковому
    движку подряд - поэтому у функции свой маленький автомат шагов.
    """
    extra = ((u"busy", u"BOOL", u"движок занят"),
             (u"start", u"BOOL", u"запуск операции движка"),
             (u"done_l", u"BOOL", u"защёлка выхода Done движка"),
             (u"res", u"BYTE", u"защёлка кода возврата"),
             (u"hl", u"WORD", u"защёлка адреса записи каталога"),
             (u"ix", u"WORD", u"защёлка номера записи каталога"),
             (u"step", u"BYTE", u"шаг автомата (см. RS_* в pou_bdos.py)"),
             (u"st0", u"BOOL", u"шаг подготовки"),
             (u"st1", u"BOOL", u"шаг запуска поиска экстента"),
             (u"st2", u"BOOL", u"шаг ожидания поиска экстента"),
             (u"st3", u"BOOL", u"шаг подстановки номера записи"),
             (u"st4", u"BOOL", u"шаг запуска переноса"),
             (u"st5", u"BOOL", u"шаг ожидания переноса"),
             (u"st6", u"BOOL", u"шаг завершения"),
             (u"r0w", u"WORD", u"случайный номер, младший байт"),
             (u"r1w", u"WORD", u"случайный номер, средний байт"),
             (u"r2w", u"WORD", u"случайный номер, старший байт"),
             (u"rnd_ext", u"WORD", u"номер экстента из случайного номера"),
             (u"rnd_rec", u"WORD", u"запись внутри экстента"),
             (u"ext_b", u"BYTE", u"номер экстента"),
             (u"rec_b", u"BYTE", u"запись внутри экстента"),
             (u"fe_bad", u"BOOL", u"запись нужного экстента не найдена"),
             (u"fin", u"BOOL", u"функция завершена"),
             (u"fin_res", u"BYTE", u"код возврата"),
             (u"op_xf", u"BYTE", u"код операции переноса"),
             (u"fail_c", u"BYTE", u"код возврата при отсутствии экстента"),
             (u"new_step", u"BYTE", u"следующий шаг автомата"),
             (u"off", u"WORD", u"адрес FCB"),
             (u"eng", u"FB_CPM_DirEngine", u"экземпляр дискового движка"))
    p = _head(num, name, doc, extra=extra)
    n = p.network(u"СЕТЬ 2. Разбор случайного номера записи на экстент и запись")
    n.outvar(u"off", I(n, u"GVL_CPM.FCB_Addr"))
    n.outvar(u"r0w", I(n, u"GVL_MEM.Memory[off + 33]"))
    n.outvar(u"r1w", I(n, u"GVL_MEM.Memory[off + 34]"))
    n.outvar(u"r2w", I(n, u"GVL_MEM.Memory[off + 35]"))
    # R = r0 + r1*256 + r2*65536; экстент = R / записей_в_экстенте,
    # запись внутри экстента = R по модулю - обе операции сдвигами.
    n.outvar(u"rnd_ext", ORL(n, [
        SHR(n, I(n, u"r0w"), I(n, W % ENT_SHIFT), fbd_xml.COL_BLK + 200),
        SHL(n, I(n, u"r1w"), I(n, W % (8 - ENT_SHIFT)), fbd_xml.COL_BLK + 340),
        SHL(n, I(n, u"r2w"), I(n, W % (16 - ENT_SHIFT)), fbd_xml.COL_BLK + 480),
    ], x0=fbd_xml.COL_BLK + 620))
    n.outvar(u"rnd_rec", AND(n, I(n, u"r0w"), I(n, W % (D.RECS_PER_ENTRY - 1)),
                             fbd_xml.COL_BLK + 900))
    n.outvar(u"ext_b", W2B(n, I(n, u"rnd_ext"), fbd_xml.COL_BLK + 1020))
    n.outvar(u"rec_b", W2B(n, I(n, u"rnd_rec"), fbd_xml.COL_BLK + 1140))
    n.outvar(u"op_xf", I(n, B % (D.OP_WRITESEQ if is_read is False
                                 else D.OP_READSEQ)))
    n.outvar(u"fail_c", I(n, H % (0x01 if is_read else 0xFF)))

    n = p.network(u"СЕТЬ 3. Признаки шагов автомата (считаются ДО вызова движка)")
    for k in range(7):
        n.outvar(u"st%d" % k, EQ(n, I(n, u"step"), I(n, B % k),
                                 fbd_xml.COL_BLK + 130 * k))

    n = p.network(u"СЕТЬ 4. Запуск дискового движка и защёлкивание его выходов")
    n.outvar(u"start", ANDL(n, [I(n, u"hit"),
                                OR(n, I(n, u"st1"), I(n, u"st4"),
                                   fbd_xml.COL_BLK + 200)],
                            x0=fbd_xml.COL_BLK + 320))
    eng = n.block(u"FB_CPM_DirEngine", [
        (u"Start", I(n, u"start")),
        (u"Op", SEL(n, I(n, u"st4"), I(n, B % D.OP_FINDEXT), I(n, u"op_xf"),
                    fbd_xml.COL_BLK + 460)),
        (u"Entry", I(n, u"WORD#0")),
        (u"FCB", I(n, u"GVL_CPM.FCB_Addr")),
        (u"ZeroFill", I(n, u"TRUE" if zero_fill else u"FALSE")),
    ], [u"Busy", u"Done", u"Result", u"Out_HL", u"Out_Idx"], instance=u"eng",
        x=fbd_xml.COL_BLK + 700)
    n.outvar(u"busy", eng.out(u"Busy"))
    n.outvar(u"done_l", eng.out(u"Done"))
    n.outvar(u"res", eng.out(u"Result"))
    n.outvar(u"hl", eng.out(u"Out_HL"))
    n.outvar(u"ix", eng.out(u"Out_Idx"))

    n = p.network(u"СЕТЬ 5. Автомат шагов: найти экстент, затем перенести запись")
    n.outvar(u"fe_bad", ANDL(n, [I(n, u"st2"),
                                 I(n, u"done_l"),
                                 EQ(n, I(n, u"res"), I(n, H % 0xFF),
                                    fbd_xml.COL_BLK + 320)],
                             x0=fbd_xml.COL_BLK + 440))
    n.outvar(u"fin", OR(n, I(n, u"fe_bad"),
                        AND(n, I(n, u"st5"), I(n, u"done_l"),
                            fbd_xml.COL_BLK + 560), fbd_xml.COL_BLK + 680))
    n.outvar(u"new_step", CHAIN(n, I(n, u"step"), [
        (I(n, u"st0"), I(n, B % RS_FIND)),
        (I(n, u"st1"), I(n, B % RS_WAITF)),
        (AND(n, I(n, u"st2"), I(n, u"done_l"), fbd_xml.COL_BLK + 800),
         SEL(n, I(n, u"fe_bad"), I(n, B % RS_SETCR), I(n, B % RS_END),
             fbd_xml.COL_BLK + 920)),
        (I(n, u"st3"), I(n, B % RS_XFER)),
        (I(n, u"st4"), I(n, B % RS_WAITX)),
        (AND(n, I(n, u"st5"), I(n, u"done_l"), fbd_xml.COL_BLK + 1040),
         I(n, B % RS_END)),
        (I(n, u"st6"), I(n, B % RS_PREP)),
        (NOT(n, I(n, u"hit"), fbd_xml.COL_BLK + 1160), I(n, B % RS_PREP)),
    ], x0=fbd_xml.COL_BLK + 1280))
    n.outvar(u"step", I(n, u"new_step"))

    n = p.network(u"СЕТЬ 6. Действия шагов и код возврата")
    n.outvar(u"done_gate", I(n, u"fin"))
    n.outvar(u"fin_res", SEL(n, I(n, u"fe_bad"), I(n, u"res"), I(n, u"fail_c"),
                             fbd_xml.COL_BLK + 200))
    tgt = u"GVL_MEM.Memory[off + 12]"
    n.outvar(tgt, SEL(n, I(n, u"st0"), I(n, tgt), I(n, u"ext_b"),
                      fbd_xml.COL_BLK + 320))
    tgt = u"GVL_MEM.Memory[off + 32]"
    n.outvar(tgt, SEL(n, I(n, u"st3"), I(n, tgt), I(n, u"rec_b"),
                      fbd_xml.COL_BLK + 440))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"fin"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"fin_res"), fbd_xml.COL_BLK + 560))
    n.outvar(u"GVL_CPM.Dir_Result", SEL(n, I(n, u"fin"),
                                        I(n, u"GVL_CPM.Dir_Result"),
                                        I(n, u"fin_res"), fbd_xml.COL_BLK + 680))
    _finish(p, num, note)
    return p


def make_readrand():
    return _rand_fn(F_READRAND, u"READRAND",
                    u"чтение записи по случайному номеру: экстент находится по "
                    u"каталогу, затем выполняется обычное последовательное чтение",
                    is_read=True,
                    note=u"A=0 - прочитано, A=1 - данных нет, A=FFh - нет экстента")


def make_writerand():
    return _rand_fn(F_WRITERAND, u"WRITERAND",
                    u"запись записи по случайному номеру: экстент находится по "
                    u"каталогу, затем обычная последовательная запись",
                    is_read=False,
                    note=u"A=0 - записано, A=FFh - экстент не найден")


def make_writerandzf():
    return _rand_fn(F_WRITERANDZF, u"WRITERANDZF",
                    u"запись по случайному номеру с забивкой нулями: только что "
                    u"выделенный блок предварительно заполняется нулями, поэтому "
                    u"незаписанные записи читаются как нули",
                    is_read=False, zero_fill=True,
                    note=u"забивка идёт по одной записи 128 байт за скан")


def make_loginvec():
    p = _head(F_LOGINVEC, u"LOGINVEC", u"вектор входа - в CP/M 2.2 не используется")
    n = p.network(u"СЕТЬ 2. Заглушка: A := 0")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0)))
    _finish(p, F_LOGINVEC)
    return p


def make_curdisk():
    p = _head(F_CURDISK, u"CURDISK", u"номер текущего диска в A")
    n = p.network(u"СЕТЬ 2. A := CurDisk")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, u"GVL_CPM.CurDisk")))
    _finish(p, F_CURDISK)
    return p


def make_setdma():
    p = _head(F_SETDMA, u"SETDMA", u"установить адрес DMA из пары DE")
    n = p.network(u"СЕТЬ 2. DMA := DE")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"GVL_CPM.DMA", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.DMA"),
                                 I(n, u"GVL_CPM.Param_DE")))
    n.outvar(u"GVL_CPM.Ret_Val", SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                                     I(n, B % 0), fbd_xml.COL_BLK + 200))
    _finish(p, F_SETDMA)
    return p


def make_user():
    p = _head(F_USER, u"USER", u"установить номер пользователя из регистра E")
    n = p.network(u"СЕТЬ 2. Номера 0..15 допустимы, иначе A := FFh")
    n.outvar(u"done_gate", I(n, u"hit"))
    n.outvar(u"chb", LT(n, I(n, u"GVL_CPM.Reg_E"), I(n, B % 16),
                       fbd_xml.COL_BLK + 200))
    n.outvar(u"valb", AND(n, I(n, u"hit"), I(n, u"chb"), fbd_xml.COL_BLK + 320))
    n.outvar(u"GVL_CPM.CurUser", SEL(n, I(n, u"valb"), I(n, u"GVL_CPM.CurUser"),
                                     I(n, u"GVL_CPM.Reg_E"), fbd_xml.COL_BLK + 440))
    n.outvar(u"GVL_CPM.Ret_Val",
             SEL(n, I(n, u"hit"), I(n, u"GVL_CPM.Ret_Val"),
                 SEL(n, I(n, u"chb"), I(n, H % 0xFF), I(n, H % 0x00),
                     fbd_xml.COL_BLK + 560), fbd_xml.COL_BLK + 680))
    _finish(p, F_USER)
    return p


# ======================================================================
BDOS_FNS = (
    (F_CONIN, u"FB_BDOS_CONIN", make_conin),
    (F_CONOUT, u"FB_BDOS_CONOUT", make_conout),
    (F_PRINTSTR, u"FB_BDOS_PRINTSTR", make_printstr),
    (F_READLINE, u"FB_BDOS_READLINE", make_readline),
    (F_CONST, u"FB_BDOS_CONST", make_const_state),
    (F_VERSION, u"FB_BDOS_VERSION", make_version),
    (F_RESETDISK, u"FB_BDOS_RESETDISK", make_resetdisk),
    (F_SELDSK, u"FB_BDOS_SELDSK", make_seldsk),
    (F_OPEN, u"FB_BDOS_OPEN", make_open),
    (F_CLOSE, u"FB_BDOS_CLOSE", make_close),
    (F_SEARCHF, u"FB_BDOS_SEARCHFIRST", make_searchfirst),
    (F_SEARCHN, u"FB_BDOS_SEARCHNEXT", make_searchnext),
    (F_DELETE, u"FB_BDOS_DELETE", make_delete),
    (F_READSEQ, u"FB_BDOS_READSEQ", make_readseq),
    (F_WRITESEQ, u"FB_BDOS_WRITESEQ", make_writeseq),
    (F_MAKE, u"FB_BDOS_MAKE", make_make),
    (F_RENAME, u"FB_BDOS_RENAME", make_rename),
    (F_LOGINVEC, u"FB_BDOS_LOGINVEC", make_loginvec),
    (F_CURDISK, u"FB_BDOS_CURDISK", make_curdisk),
    (F_SETDMA, u"FB_BDOS_SETDMA", make_setdma),
    (F_ATTRIB, u"FB_BDOS_ATTRIB", make_attrib),
    (F_USER, u"FB_BDOS_USER", make_user),
    (F_READRAND, u"FB_BDOS_READRAND", make_readrand),
    (F_WRITERAND, u"FB_BDOS_WRITERAND", make_writerand),
    (F_FILESIZE, u"FB_BDOS_FILESIZE", make_filesize),
    (F_SETRANDREC, u"FB_BDOS_SETRANDREC", make_setrandrec),
    (F_WRITERANDZF, u"FB_BDOS_WRITERANDZF", make_writerandzf),
)


def make_bdos_dispatch():
    u"""FB_BDOS - диспетчер BDOS: ловит номер функции и параметры, раздаёт Enable."""
    p = Pou(u"FB_BDOS", u"functionBlock",
            doc=u"Диспетчер BDOS CP/M 2.2.\n"
                u"\tВход Start: трап BDOS активен (PC = 0F000h, то есть программа\n"
                u"\tвыполнила CALL 0005h, а по 0005h лежит JMP 0F000h).\n"
                u"\tПока трап активен, диспетчер фиксирует параметры вызова:\n"
                u"\t  BDOS_Func := C   - номер функции (1..40);\n"
                u"\t  Param_DE  := DE  - FCB, буфер или адрес строки;\n"
                u"\t  Param_BC  := BC  - дорожка, сектор, адрес DMA;\n"
                u"\t  FCB_Addr  := DE  - адрес FCB для файловых функций.\n"
                u"\tЗатем всем 27 блокам выдаётся Enable; выбранный блок выполняет\n"
                u"\tфункцию и ставит GVL_CPM.Func_Done. Пока квитанции нет, Enable\n"
                u"\tдержится, поэтому многосканные функции (поиск по каталогу,\n"
                u"\tожидание символа, вывод строки) работают без потери состояния.")
    p.var_in(u"Start", u"BOOL", u"трап BDOS активен")
    p.var(u"en", u"BOOL", u"функции BDOS разрешены (нет квитанции)")
    p.var(u"de", u"WORD", u"пара DE на момент вызова")
    p.var(u"bc", u"WORD", u"пара BC на момент вызова")
    p.var(u"d_w", u"WORD", u"регистр D как слово")
    p.var(u"e_w", u"WORD", u"регистр E как слово")
    p.var(u"b_w", u"WORD", u"регистр B как слово")
    p.var(u"c_w", u"WORD", u"регистр C как слово")
    p.var_out(u"Done", u"BOOL", u"вызванная функция выполнена")
    n = p.network(u"СЕТЬ 1. Параметры вызова: C - функция, DE и BC - данные")
    n.outvar(u"d_w", I(n, u"GVL_CPM.Reg_D"))
    n.outvar(u"e_w", I(n, u"GVL_CPM.Reg_E"))
    n.outvar(u"b_w", I(n, u"GVL_CPM.Reg_B"))
    n.outvar(u"c_w", I(n, u"GVL_CPM.Reg_C"))
    n.outvar(u"de", OR(n, SHL(n, I(n, u"d_w"), I(n, u"WORD#8"),
                              fbd_xml.COL_BLK + 200), I(n, u"e_w"),
                       fbd_xml.COL_BLK + 320))
    n.outvar(u"bc", OR(n, SHL(n, I(n, u"b_w"), I(n, u"WORD#8"),
                              fbd_xml.COL_BLK + 440), I(n, u"c_w"),
                       fbd_xml.COL_BLK + 560))
    n.outvar(u"GVL_CPM.BDOS_Func", SEL(n, I(n, u"Start"), I(n, u"GVL_CPM.BDOS_Func"),
                                       I(n, u"GVL_CPM.Reg_C"), fbd_xml.COL_BLK + 680))
    n.outvar(u"GVL_CPM.Param_DE", SEL(n, I(n, u"Start"), I(n, u"GVL_CPM.Param_DE"),
                                      I(n, u"de"), fbd_xml.COL_BLK + 800))
    n.outvar(u"GVL_CPM.Param_BC", SEL(n, I(n, u"Start"), I(n, u"GVL_CPM.Param_BC"),
                                      I(n, u"bc"), fbd_xml.COL_BLK + 920))
    n.outvar(u"GVL_CPM.FCB_Addr", SEL(n, I(n, u"Start"), I(n, u"GVL_CPM.FCB_Addr"),
                                      I(n, u"de"), fbd_xml.COL_BLK + 1040))
    n = p.network(u"СЕТЬ 2. Разрешение работы функций и признак готовности")
    n.outvar(u"en", AND(n, I(n, u"Start"), NOT(n, I(n, u"GVL_CPM.Func_Done"),
                                               fbd_xml.COL_BLK + 200),
                        fbd_xml.COL_BLK + 320))
    n.outvar(u"Done", I(n, u"GVL_CPM.Func_Done"))
    n = p.network(u"СЕТЬ 3. Вызов всех 27 функций BDOS (каждая выбирает себя сама)")
    for i, (num, name, _mk) in enumerate(BDOS_FNS):
        n.block(name, [(u"Enable", I(n, u"en"))], [u"Done"],
                instance=u"bd%d" % num, x=fbd_xml.COL_BLK + 200 * (i % 4),
                y=40 + 30 * i)
    # ЭКЗЕМПЛЯРЫ 27 ФУНКЦИЙ ОБЯЗАНЫ БЫТЬ ОБЪЯВЛЕНЫ В САМОМ POU. Раньше их
    # здесь не было: разбор объявлений это пропускал, а кодогенерация (она
    # включается только вместе с конфигурацией задач) падала с
    # "'bd17' не является экземпляром 'FB_BDOS_SEARCHFIRST'". Найдено на этапе 4.
    for num, name, _mk in BDOS_FNS:
        p.var(u"bd%d" % num, name, u"экземпляр функции BDOS %d" % num)
    return p


ALL = tuple([mk for _n, _nm, mk in BDOS_FNS] + [make_dir_engine, make_bdos_dispatch])
NAMES = tuple([nm for _n, nm, _mk in BDOS_FNS] + [u"FB_CPM_DirEngine", u"FB_BDOS"])
