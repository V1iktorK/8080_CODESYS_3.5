# -*- coding: utf-8 -*-
u"""ПРОБА ФОРМЫ ОБЪЯВЛЕНИЯ ОБРАЗА ДИСКА (причина ошибок C48/C32 при кодогенерации).

ГИПОТЕЗА. C48 «Для массива требуется ровно 1 индексов» + C32 «BYTE -> ARRAY[0..127]
OF BYTE» появляются на КАЖДОМ обращении `GVL_DISK.Disk[сектор, байт]`, то есть
генератор кода видит `Disk` как ОДНОМЕРНЫЙ массив, а его тип элемента называет
«ARRAY [0..127] OF BYTE». Это ровно то, что получается, если вложенная форма
объявления             Disk : ARRAY[0..2047] OF ARRAY[0..127] OF BYTE;
разбирается разборщиком объявлений, но НЕ поддерживается кодогенератором.
Запись `Disk[a, b] := X` даёт тогда сразу два сообщения (C48 по индексам и C32 по
типу приёмника), чтение `Disk[a, b]` - одно (C48): наблюдаемое соотношение
C48:C32 = 2:1 и тройки (C48, C48, C32) объясняются именно так.

ЧТО ПРОВЕРЯЕТ ЭТА ПРОБА (4 проекта, 4 сборки ЗА ОДИН запуск CODESYS):
  V1 - вложенная форма  ARRAY[0..2047] OF ARRAY[0..127] OF BYTE   (как сейчас);
  V2 - форма CODESYS    ARRAY[0..2047, 0..127] OF BYTE            (те же индексы!);
  V3 - плоский образ    ARRAY[0..262143] OF BYTE + адрес sec*128+b;
  V4 - массив структур  ARRAY[0..2047] OF ST_Sec (поле Data : ARRAY[0..127] OF BYTE).
В каждом проекте - программа, которая ПИШЕТ байт образа (с обратным чтением, как
pou_demo._wr) и ЧИТАЕТ его, и задача, вызывающая программу: без задачи
кодогенерация не включается и проба ничего не доказывает (docs/03, п. 15.1).
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import scriptengine
import fbd_xml
from fbd_xml import Pou
import codesys_build as cb
import run_online

ROOT = cb.ROOT
T0 = time.time()
# ВНИМАНИЕ: make_log принимает ИМЯ файла, а не путь (каталог log добавляет сам).
_LOG = cb.make_log(u"gen_probe_decl.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


def H(msg):
    L(u"")
    L(u"==== %s ====" % msg)


# ---------------------------------------------------------------- объявления
GVL_V1 = (u"VAR_GLOBAL\n"
          u"\t(* ВАРИАНТ 1: вложенная форма (так объявлено в проекте сейчас). *)\n"
          u"\tDisk : ARRAY[0..2047] OF ARRAY[0..127] OF BYTE;\n"
          u"END_VAR\n")
GVL_V2 = (u"VAR_GLOBAL\n"
          u"\t(* ВАРИАНТ 2: форма CODESYS - размерности через запятую. *)\n"
          u"\tDisk : ARRAY[0..2047, 0..127] OF BYTE;\n"
          u"END_VAR\n")
GVL_V3 = (u"VAR_GLOBAL\n"
          u"\t(* ВАРИАНТ 3: плоский образ, адрес считается как sec*128+b. *)\n"
          u"\tDisk : ARRAY[0..262143] OF BYTE;\n"
          u"END_VAR\n")
GVL_V4 = (u"VAR_GLOBAL\n"
          u"\t(* ВАРИАНТ 4: массив структур-секторов. *)\n"
          u"\tDisk : ARRAY[0..2047] OF ST_Sec;\n"
          u"END_VAR\n")
DUT_V4 = (u"TYPE ST_Sec :\n"
          u"STRUCT\n"
          u"\t(* 128 байт сектора образа диска *)\n"
          u"\tData : ARRAY[0..127] OF BYTE;\n"
          u"END_STRUCT\n"
          u"END_TYPE\n")


def make_prog(name, read_expr, write_expr, doc):
    u"""Программа: пишет байт образа (с обратным чтением) и читает его."""
    p = Pou(name, u"program", doc=doc)
    p.var(u"ix", u"WORD", u"номер сектора (переменный индекс, как в слое CP/M)")
    p.var(u"rd", u"BYTE", u"прочитанный байт")
    n = p.network(u"СЕТЬ 1. Запись байта с обратным чтением (как pou_demo._wr)")
    n.outvar(u"ix", I(n, u"WORD#3"))
    sel = n.block(u"SEL", [(u"G", n.invar(u"TRUE")),
                           (u"IN0", n.invar(write_expr)),
                           (u"IN1", n.invar(u"BYTE#16#5A"))], [u"OUT"])
    n.outvar(write_expr, sel)
    n = p.network(u"СЕТЬ 2. Чтение байта образа")
    n.outvar(u"rd", n.invar(read_expr))
    return p


def I(n, e):
    return n.invar(e)


VARIANTS = (
    (u"V1_NESTED", GVL_V1, None, u"GVL_D1", u"PRG_V1",
     u"GVL_D1.Disk[ix, 4]", u"GVL_D1.Disk[ix, 4]",
     u"Проба V1: вложенная форма объявления, индексы Disk[сектор, байт]."),
    (u"V2_COMMA", GVL_V2, None, u"GVL_D2", u"PRG_V2",
     u"GVL_D2.Disk[ix, 4]", u"GVL_D2.Disk[ix, 4]",
     u"Проба V2: размерности через запятую, индексы те же Disk[сектор, байт]."),
    (u"V3_FLAT", GVL_V3, None, u"GVL_D3", u"PRG_V3",
     u"GVL_D3.Disk[ix * 128 + 4]", u"GVL_D3.Disk[ix * 128 + 4]",
     u"Проба V3: плоский образ, адрес = сектор * 128 + байт."),
    (u"V4_STRUCT", GVL_V4, DUT_V4, u"GVL_D4", u"PRG_V4",
     u"GVL_D4.Disk[ix].Data[4]", u"GVL_D4.Disk[ix].Data[4]",
     u"Проба V4: массив структур-секторов, Disk[сектор].Data[байт]."),
)


def build_variant(tag, gvl_text, dut_text, gvl_name, prog_name, rd, wr, doc, idx):
    H(u"### EXP %d : %s" % (idx, tag))
    pdir = ROOT + u"/src/probe_decl"
    if not os.path.isdir(pdir):
        os.makedirs(pdir)
    try:
        proj, app = cb.new_project(ROOT + u"/build/DECL_%s.project" % tag, L)
    except Exception:
        L(u"[FAIL] проект %s:\n%s" % (tag, traceback.format_exc()))
        return
    try:
        if dut_text:
            cb.add_dut(app, u"ST_Sec", dut_text, L)
        cb.add_gvl(app, gvl_name, gvl_text, L)
        p = make_prog(prog_name, rd, wr, doc)
        one = u"%s/%s.plcopenxml" % (pdir, prog_name)
        fbd_xml.write_project(one, [p], prog_name)
        app.import_xml(one)
        L(u"    POU %s импортирован" % prog_name)
    except Exception:
        L(u"[FAIL] содержимое %s:\n%s" % (tag, traceback.format_exc()))
        return
    try:
        tc = app.create_task_configuration()
        task = tc.create_task(u"MainTask")
        task.pous.insert(0, prog_name, u"проба формы объявления")
        L(u"    задача создана, программа в задаче: %s" % prog_name)
    except Exception:
        L(u"[FAIL] задача %s:\n%s" % (tag, traceback.format_exc()))
        return
    L(u"    >>> СБОРКА %d (%s) <<<" % (idx, tag))
    try:
        cb.build(app, L)
        L(u"    сборка %s выполнена" % tag)
    except Exception:
        L(u"[FAIL] сборка %s:\n%s" % (tag, traceback.format_exc()))
    try:
        proj.save()
    except Exception:
        pass
    L(u"### EXP %d END" % idx)


def main():
    L(u"=== ПРОБА ФОРМЫ ОБЪЯВЛЕНИЯ ОБРАЗА ДИСКА ===")
    want = os.environ.get(u"DSH_S4_EXPS")
    tags = None
    if want:
        tags = [unicode(x).strip() for x in unicode(want).split(u",") if x.strip()]
    for i, v in enumerate(VARIANTS):
        if tags and v[0] not in tags:
            continue
        build_variant(v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], i + 1)


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
