# -*- coding: utf-8 -*-
u"""ШАГ 3, подшаг 3.4 - драйвер сборки: регистровый файл, FB_CPU8080 и PLC_PRG.

Схемы описаны в модуле pou_cpu.py.
"""

import os, sys, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_cpu
from pou_cpu import make_reg_file, make_cpu, make_plc_prg

ROOT = cb.ROOT
L = cb.make_log(u"gen_cpu.log")
L(u"=== ШАГ 3.4: регистровый файл, FB_CPU8080, PLC_PRG ===")
L(u"python: %s" % sys.version)

GVL_CPU_TEXT = u"""VAR_GLOBAL
\t(* ==== ШИНЫ ЭМУЛЯТОРА Intel 8080 ==== *)
\tBus_Data : BYTE;   (* шина данных, 8 бит *)
\tBus_Addr : WORD;   (* шина адреса, 16 бит *)
\tBus_IR   : BYTE;   (* регистр команды *)

\t(* ==== УПРАВЛЯЮЩЕЕ СЛОВО ДЕКОДЕРА ==== *)
\tC_Class  : BYTE;   (* 0=NOP 1=MOV 2=MVI 3=ALU 4=JMP 5=CALL 6=RET 9=HLT *)
\tC_Dst    : BYTE;   (* код регистра-приёмника 0..7 *)
\tC_Src    : BYTE;   (* код регистра-источника 0..7 *)
\tC_ALU_Op : BYTE;   (* код операции для FB_ALU8 *)
\tC_Cond   : BYTE;   (* код условия перехода *)
\tC_Uncond : BOOL;   (* переход безусловный *)
\tC_Len    : BYTE;   (* длина команды в байтах *)
\tC_IsCmp  : BOOL;   (* CMP: результат не записывать *)
\tC_Halt   : BOOL;   (* команда HLT *)

\t(* ==== СОСТОЯНИЕ И ОТЛАДКА ==== *)
\tEnable   : BOOL;   (* разрешение выполнения такта *)
\tStep_Cnt : WORD;   (* номер выполненного такта *)
\tHalted   : BOOL;   (* процессор остановлен *)
END_VAR
"""

GVL_MEM_TEXT = u"""VAR_GLOBAL
\t(* Общая память эмулятора Intel 8080: 64 КБ *)
\tMemory : ARRAY[0..65535] OF BYTE;
END_VAR
"""

POUS = []
for _maker in (make_reg_file, make_cpu, make_plc_prg):
    _p = _maker()
    POUS.append(_p)
    L(u"[0] POU собран: %-14s сетей=%d" % (_p.name, len(_p.networks)))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/cpu.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"cpu")
L(u"[1] PLCopenXML записан: %d символов" % size)

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.add_gvl(app, u"GVL_CPU", GVL_CPU_TEXT, L)
    cb.add_gvl(app, u"GVL_MEM", GVL_MEM_TEXT, L)
    # зависимости: всё, что вызывается внутри FB_CPU8080 (и через FB_RegFile)
    for dep in (u"FB_Reg8", u"FB_Reg16", u"FB_UnpackByte", u"FB_PackByte", u"FB_FullAdder",
                u"FB_Mux8x8", u"FB_ALU8", u"FB_Memory64K", u"FB_FlagsReg",
                u"FB_Decode_MOV", u"FB_Decode_MVI", u"FB_Decode_ALU", u"FB_Decode_JMP",
                u"FB_Decode_HLT", u"FB_Decoder", u"FB_CtrlUnit"):
        L(u"    импорт зависимости %s ..." % dep)
        app.import_xml(ROOT + u"/src/%s.plcopenxml" % dep)
        L(u"    импорт зависимости %s OK" % dep)

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/cpu_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
