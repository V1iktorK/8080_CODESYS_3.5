# -*- coding: utf-8 -*-
u"""ШАГ 3.2-3.6 - драйвер сборки слоя CP/M 2.2 (BIOS + BDOS + CCP + диск + I/O).

Собирается весь слой:
  * FB_CPU8080_FULL  - ядро 8080 с ПОРТОМ ДОСТУПА CP/M к регистрам (pou_cpu_cpm)
                       и с ПОРТОМ ВВОДА-ВЫВОДА для команд IN/OUT (pou_cpu_io);
  * FB_CPM_Trap, FB_CPM_MemInit  - ловушки и инициализация (pou_cpm_trap);
  * 17 функций BIOS + диспетчер FB_BIOS  - pou_bios;
  * 27 функций BDOS + дисковый движок + диспетчер FB_BDOS - pou_bdos;
  * FB_CCP (полный консольный процессор, этап 3.4) - pou_ccp;
  * FB_COM_Loader (загрузчик .COM, этап 3.5) - pou_com_loader;
  * демонстрационные .COM и образ диска - pou_demo;
  * АППАРАТНЫЙ СЛОЙ (этап 3.6): FB_IO_Read / FB_IO_Write / FB_IO_AnalogIn /
    FB_IO_AnalogOut / FB_IO_Adapter_Sim / FB_IO_Adapter_SoftPLC /
    FB_IO_Adapter_HW / FB_IO_Dispatch / FB_IO_MapInit / FB_Watchdog /
    FB_HMI_Update - pou_io и pou_io_hw;
    карта портов GVL_IO_Map, каналы GVL_IO и HMI GVL_HMI - pou_io_defs;
    физические адреса адаптера C - GVL_IO_HW (pou_io_hw);
  * PLC_PRG_CPM  - главная программа (pou_prg_io дополняет pou_prg_cpm).
Плюс 27 зависимостей ядра из dep_ccp/*.plcopenxml (они не менялись).

АДАПТЕР FB_IO_Adapter_HW (реальный ПЛК, переменные AT %IB0/%QB0/%IW0/%QW0) ВХОДИТ
в сборку: отдельная проба gen_probe_hw.py показала, что CODESYS Control Win V3
принимает такие объявления и без модулей ввода-вывода (0 ошибок). Активным
остаётся адаптер из константы ADAPTER_TYPE (pou_io_defs.py) - сейчас Sim;
адаптер HW импортируется и компилируется, но не вызывается ни одной схемой.

Драйвер намеренно короткий: загрузчик скриптов CODESYS не выполняет файл
больше ~25 КБ (docs/03_ЖУРНАЛ_СБОРКИ.md, п. 9.2). Все схемы - в модулях.

ВНИМАНИЕ: сборка большая (импорт ~95 POU), поэтому RunTimeoutSec должен быть
не меньше 900 с - импорт одного POU в CODESYS занимает секунды.
"""

import os, sys, time, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

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

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_cpm.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


# ИЗОЛЯЦИЯ ЗАВИСИМОСТЕЙ. Рабочие папки C:\dsh8080\work\emu и ...\stage -
# ОБЩИЕ с соседним проектом Z80_EMU (у него свои FB_Reg8/FB_Reg16/FB_Memory64K/
# PLC_PRG). Его раннер копирует свои src/*.plcopenxml в ту же папку и способен
# подменить зависимости ядра 8080. Поэтому зависимости берутся из ОТДЕЛЬНОЙ
# папки C:\dsh8080\work\dep_ccp, снятой из src самого проекта 8080_EMU.
DEP_DIRS = (u"C:/dsh8080/work/dep_ccp", u"C:/dsh8080/work/dep_cpm")
DEP_DIR = None
for _d in DEP_DIRS:
    if os.path.isdir(_d) and os.path.exists(_d + u"/FB_CPU8080_FULL.plcopenxml"):
        DEP_DIR = _d
        break
if DEP_DIR is None:
    DEP_DIR = ROOT + u"/src"

L(u"=== ШАГ 3.2-3.6: слой CP/M 2.2 + аппаратный ввод-вывод, только FBD ===")
L(u"python: %s" % sys.version)
L(u"корень: %s" % ROOT)
L(u"зависимости берутся из: %s" % DEP_DIR)

GVL_MEM_TEXT = (u"VAR_GLOBAL\n"
                u"\t(* Общая память эмулятора Intel 8080: 64 КБ.\n"
                u"\t   Здесь же лежит страница нуля CP/M, таблица переходов BIOS,\n"
                u"\t   ловушки BDOS/BIOS/CCP, DPB и загруженная .COM-программа. *)\n"
                u"\tMemory : ARRAY[0..65535] OF BYTE;\n"
                u"END_VAR\n")

# зависимости ядра (собраны подшагами 3.2-3.4 и 3.1; эти файлы НЕ менялись)
DEPENDENCIES = (u"FB_PackByte", u"FB_UnpackByte", u"FB_FullAdder", u"FB_ALU8",
                u"FB_CtrlUnit", u"FB_Mux8x8", u"FB_Mux8x16", u"FB_Memory64K",
                u"FB_Reg8", u"FB_Reg16", u"FB_Reg8Q", u"FB_RegFileQ",
                u"FB_FlagsReg2", u"FB_Rotate8", u"FB_DAA", u"FB_Interrupt",
                u"FB_UnpackWord",
                u"FB_DecodeFull_ALU", u"FB_DecodeFull_ALUI", u"FB_DecodeFull_DATA",
                u"FB_DecodeFull_HLT", u"FB_DecodeFull_JMP", u"FB_DecodeFull_MOV",
                u"FB_DecodeFull_MVI", u"FB_DecodeFull_SPEC", u"FB_DecodeFull_STACK",
                u"FB_Decoder_Full")

GROUPS = ((u"процессор с портами CP/M и I/O", pou_cpu_io.ALL),
          (u"трапы и инициализация", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"BDOS", pou_bdos.ALL),
          (u"CCP (консольный процессор)", pou_ccp.ALL),
          (u"загрузчик .COM", pou_com_loader.ALL),
          (u"аппаратный ввод-вывод (этап 3.6)", pou_io.ALL),
          (u"адаптер C - реальный ПЛК (этап 3.6)", pou_io_hw.ALL),
          (u"программа", pou_prg_io.ALL))

POUS = []
for group, makers in GROUPS:
    for mk in makers:
        p = mk()
        POUS.append(p)
        L(u"[0] %-24s POU: %-22s сетей=%2d блоков=%3d"
          % (group, p.name, len(p.networks),
             sum([1 for net in p.networks
                  for it in net._items if it[0] == u"block"])))
NAMES = [p.name for p in POUS]
L(u"[0] всего новых POU: %d" % len(POUS))

src_path = ROOT + u"/src/cpm_full.plcopenxml"
size = fbd_xml.write_project(src_path, POUS, u"cpm_full")
cn = fbd_xml.count_elements(src_path)
L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
  % (size, cn[0], cn[3], cn[4]))

try:
    proj, app = cb.new_project(ROOT + u"/build/EMU8080_CPM.project", L)
except Exception:
    L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
    _LOG.close()
    raise

try:
    for nm, text in D.DUT_ALL + IOD.DUT_ALL:
        cb.add_dut(app, nm, text, L)
    cb.add_gvl(app, u"GVL_CPU", pou_decode_full.gvl_cpu_text(), L)
    cb.add_gvl(app, u"GVL_MEM", GVL_MEM_TEXT, L)
    cb.add_gvl(app, u"GVL_CPM", D.gvl_cpm_text(), L)
    cb.add_gvl(app, u"GVL_DISK", D.gvl_disk_text(), L)
    for nm, fn in IOD.GVL_ALL:
        cb.add_gvl(app, nm, fn(), L)
    # карта физических адресов адаптера C (AT %IB0/%QB0/%IW0/%QW0)
    cb.add_gvl(app, u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text(), L)

    for i, dep in enumerate(DEPENDENCIES):
        L(u"    зависимость %2d/%d: %s" % (i + 1, len(DEPENDENCIES), dep))
        app.import_xml(DEP_DIR + u"/%s.plcopenxml" % dep)

    cb.import_pous_one_by_one(app, POUS, ROOT + u"/src", L)
    # проект сохраняется ДО выгрузки-проверки: выгрузка 52 POU тяжёлая, и если
    # процесс будет снят (CODESYS - однопроцессное приложение, чужой запуск
    # убивает его через taskkill), результат импорта уже останется на диске
    L(u"[2] сохранение проекта ...")
    proj.save()
    L(u"[2] проект сохранён")
    # сборка идёт ДО выгрузки: сообщения компилятора важнее отчёта о связях,
    # а выгрузка 52 POU - самая тяжёлая операция (при снятии процесса она
    # повторяется отдельным коротким скриптом verify_cpm.py)
    cb.build(app, L)
    L(u"[3] СБОРКА ВЫПОЛНЕНА (сообщения компилятора - в stderr процесса)")
    ok = cb.verify_import(proj, app, NAMES, src_path,
                          ROOT + u"/src/cpm_full_reexport.xml", L)
    L(u"[4] ИТОГ: %s" % (u"УСПЕХ" if ok else u"ЕСТЬ РАСХОЖДЕНИЯ"))
except Exception:
    L(u"[3] ОШИБКА:\n" + traceback.format_exc())

L(u"=== DONE ===")
_LOG.close()
