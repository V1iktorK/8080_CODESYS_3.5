# -*- coding: utf-8 -*-
u"""ЭТАП 4, ПРОБА №4: ПОЧЕМУ КОДОГЕНЕРАЦИЯ ДАЁТ ОШИБКИ В СТАРОМ СЛОЕ.

ФАКТ (прогон gen_stage4.py):
  * сборка БЕЗ конфигурации задач          -> "0 ошибок, 0 предупреждений";
  * та же сборка ПОСЛЕ создания задачи     -> "489 ошибок" (C212, C9, C189,
    C7, C22, C26, C31, C6, C142, C4, C2, C190, C23).

ВЫВОД, КОТОРЫЙ ПРОВЕРЯЕТСЯ ЭТОЙ ПРОБОЙ: пока задачи нет, CODESYS только
разбирает объявления, а КОД не генерирует - поэтому схема «компилировалась»
почти четыре этапа, ни разу не пройдя кодогенерацию. Первая же задача её
включила, и всплыли ошибки, которые видит ТОЛЬКО генератор кода
(например: имя переменной, совпадающее с ключевым словом IEC, безопасно в
объявлении, но ломает сгенерированный текст).

Проба собирает ТОЛЬКО СТАРЫЙ СЛОЙ (27 зависимостей + GVL/DUT + PLC_PRG_CPM)
и ВКЛЮЧАЕТ задачу с вызовом PLC_PRG_CPM. Если ошибки есть и здесь - они не
в тестах этапа 4, а в слое этапов 3.2-3.6.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import scriptengine
import fbd_xml
import codesys_build as cb
import pou_cpm_defs as D
import pou_io_defs as IOD
import pou_decode_full
import pou_cpu_io
import pou_cpm_trap
import pou_bios
import pou_bdos
import pou_com_loader
import pou_ccp
import pou_io
import pou_io_hw
import pou_prg_io
import pou_taskcfg

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_probe4d.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


def H(msg):
    L(u"")
    L(u"==== %s ====" % msg)


GVL_MEM_TEXT = (u"VAR_GLOBAL\n"
                u"\t(* Общая память эмулятора Intel 8080: 64 КБ. *)\n"
                u"\tMemory : ARRAY[0..65535] OF BYTE;\n"
                u"END_VAR\n")

DEPENDENCIES = (u"FB_PackByte", u"FB_UnpackByte", u"FB_FullAdder", u"FB_ALU8",
                u"FB_CtrlUnit", u"FB_Mux8x8", u"FB_Mux8x16", u"FB_Memory64K",
                u"FB_Reg8", u"FB_Reg16", u"FB_Reg8Q", u"FB_RegFileQ",
                u"FB_FlagsReg2", u"FB_Rotate8", u"FB_DAA", u"FB_Interrupt",
                u"FB_UnpackWord",
                u"FB_DecodeFull_ALU", u"FB_DecodeFull_ALUI", u"FB_DecodeFull_DATA",
                u"FB_DecodeFull_HLT", u"FB_DecodeFull_JMP", u"FB_DecodeFull_MOV",
                u"FB_DecodeFull_MVI", u"FB_DecodeFull_SPEC", u"FB_DecodeFull_STACK",
                u"FB_Decoder_Full")

GROUPS = ((u"процессор", pou_cpu_io.ALL),
          (u"трапы", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"BDOS", pou_bdos.ALL),
          (u"CCP", pou_ccp.ALL),
          (u"загрузчик", pou_com_loader.ALL),
          (u"ввод-вывод", pou_io.ALL),
          (u"адаптер C", pou_io_hw.ALL),
          (u"главная программа", pou_prg_io.ALL))


def main():
    L(u"=== ПРОБА 4D: кодогенерация СТАРОГО слоя с задачей ===")
    POUS = []
    for group, makers in GROUPS:
        for mk in makers:
            POUS.append(mk())
    NAMES = [p.name for p in POUS]
    L(u"POU старого слоя: %d" % len(POUS))

    src_path = ROOT + u"/src/probe4d_full.plcopenxml"
    fbd_xml.write_project(src_path, POUS, u"probe4d")

    proj, app = cb.new_project(ROOT + u"/build/PROBE4D.project", L)
    try:
        for nm, text in D.DUT_ALL + IOD.DUT_ALL:
            cb.add_dut(app, nm, text, L)
        cb.add_gvl(app, u"GVL_CPU", pou_decode_full.gvl_cpu_text(), L)
        cb.add_gvl(app, u"GVL_MEM", GVL_MEM_TEXT, L)
        cb.add_gvl(app, u"GVL_CPM", D.gvl_cpm_text(), L)
        cb.add_gvl(app, u"GVL_DISK", D.gvl_disk_text(), L)
        for nm, fn in IOD.GVL_ALL:
            cb.add_gvl(app, nm, fn(), L)
        cb.add_gvl(app, u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text(), L)
        dep = u"C:/dsh8080/work/dep_ccp"
        for name in DEPENDENCIES:
            app.import_xml(dep + u"/%s.plcopenxml" % name)
        cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
        proj.save()
        L(u"[A] сборка БЕЗ задачи (только разбор объявлений)")
        cb.build(app, L)
    except Exception:
        L(u"[FAIL] сборка без задачи:\n" + traceback.format_exc())

    H(u"[B] ЗАДАЧА С ОДНИМ ВЫЗОВОМ PLC_PRG_CPM")
    try:
        tc = app.create_task_configuration()
        task = tc.create_task(u"MainTask")
        task.priority = u"1"
        task.interval = u"T#10ms"
        task.pous.insert(0, u"PLC_PRG_CPM", u"только старая программа")
        L(u"[OK] задача: %d программ" % len(task.pous))
        proj.save()
        L(u"[C] сборка С ЗАДАЧЕЙ - кодогенерация включает старый слой")
        cb.build(app, L)
    except Exception:
        L(u"[FAIL] задача/сборка:\n" + traceback.format_exc())

    H(u"[D] ПРОВЕРКА СВЯЗЕЙ")
    try:
        cb.verify_import(proj, app, NAMES, src_path,
                         ROOT + u"/src/probe4d_reexport.xml", L)
    except Exception:
        L(u"[FAIL] verify:\n" + traceback.format_exc())

    try:
        proj.save()
        L(u"[OK] проект сохранён")
    except Exception:
        pass


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
