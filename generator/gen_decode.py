# -*- coding: utf-8 -*-
u"""ШАГ 3, подшаг 3.3 - драйвер сборки: шина управления, флаги, декодер, блок управления.

Сами схемы описаны в модуле pou_decode.py (см. пояснение там про размер скрипта).
"""

import os, sys, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\\\", "/")
sys.path.insert(0, BASE)

import fbd_xml
import codesys_build as cb
import pou_decode
from pou_decode import (make_flags_reg, make_decode_mov, make_decode_mvi,
                        make_decode_alu, make_decode_jmp, make_decode_hlt,
                        make_decoder, make_ctrl_unit)

ROOT = cb.ROOT
L = cb.make_log(u"gen_decode.log")
L(u"=== ШАГ 3.3: шина управления, флаги, декодер, блок управления ===")
L(u"python: %s" % sys.version)

GVL_CPU_TEXT = u"""VAR_GLOBAL
\t(* ==== ШИНЫ ЭМУЛЯТОРА Intel 8080 ==== *)
\tBus_Data : BYTE;   (* шина данных, 8 бит *)
\tBus_Addr : WORD;   (* шина адреса, 16 бит *)
\tBus_IR   : BYTE;   (* регистр команды, прочитанный из памяти *)

\t(* ==== УПРАВЛЯЮЩЕЕ СЛОВО ДЕКОДЕРА ==== *)
\tC_Class  : BYTE;   (* 0=NOP 1=MOV 2=MVI 3=ALU 4=JMP 5=CALL 6=RET 7=PUSH 8=POP 9=HLT *)
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

POUS = []
for _maker in (make_flags_reg, make_decode_mov, make_decode_mvi, make_decode_alu,
               make_decode_jmp, make_decode_hlt, make_decoder, make_ctrl_unit):
    _p = _maker()
    POUS.append(_p)
    L(u"[0] POU собран: %-16s сетей=%d" % (_p.name, len(_p.networks)))
NAMES = [p.name for p in POUS]

src_path = ROOT + u"/src/decode.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"decode")
L(u"[1] PLCopenXML записан: %d символов" % size)
L(u"    POU: %s" % u", ".join(NAMES))

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    L.close()
    raise

try:
    cb.add_gvl(app, u"GVL_CPU", GVL_CPU_TEXT, L)
    cb.add_gvl(app, u"GVL_MEM",
               u"VAR_GLOBAL\n\t(* Общая память эмулятора Intel 8080: 64 КБ *)\n"
               u"\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n", L)
    # из зависимостей нужны только те, что вызываются внутри новых блоков:
    # FB_FlagsReg использует FB_UnpackByte и FB_PackByte. Остальные блоки уже
    # собраны раньше и в этом прогоне не требуются - меньше импортов, меньше риск.
    for dep in (u"FB_UnpackByte", u"FB_PackByte"):
        L(u"    импорт зависимости %s ..." % dep)
        app.import_xml(ROOT + u"/src/%s.plcopenxml" % dep)
        L(u"    импорт зависимости %s OK" % dep)

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/decode_reexport.xml", L)
    proj.save()
    cb.build(app, L)
    L(u"[3] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
L.close()
