# -*- coding: utf-8 -*-
u"""ЛОКАЛИЗАЦИЯ ДЕФЕКТА КОДОГЕНЕРАЦИИ: какие POU дают C48/C32/C80.

ЗАЧЕМ. Компилятор CODESYS в stderr пишет только КОД и ТЕКСТ ошибки, без имени
POU (позиция C181 - «Относительная позиция», без подробностей). Поэтому
единственный способ найти виновника - СТРОИТЬ ПРОЕКТ НЕСКОЛЬКО РАЗ, каждый раз
без части POU, и смотреть, в какой сборке ошибки класса C48/C32 пропадают.

Все эксперименты делаются ЗА ОДИН запуск CODESYS (процесс однопроцессный,
а соседний Z80_EMU снимает его - docs/03, п. 12.6): для каждого эксперимента
создаётся СВОЙ проект, импортируются одни и те же объявления и те же файлы,
кроме исключённых POU, ставится та же задача и вызывается build().

ПОРЯДОК РАЗБОРА stderr: каждая сборка печатает
    ------ Компиляция : Приложение: Device.Application -------
    ...
    C0: Компиляция завершена -- N ошибок, M предупреждений
Блоки идут в том порядке, в котором шли эксперименты, поэтому номер блока в
stderr = номер эксперимента (в лог пишутся маркеры ### EXP k).

УПРАВЛЕНИЕ: список экспериментов - переменная окружения DSH_S4_EXPS со списком
имён через запятую (ALL, NO_TEST, NO_MEMINIT, NO_ENGINE, MEM_N3, MEM_N4, MEM_N5).
По умолчанию - первый набор.
"""

import io, os, sys, time, traceback

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
import pou_test_defs as TD
import pou_test8080
import pou_testcpm
import pou_testio
import pou_rename
import pou_taskcfg
import run_online

ROOT = cb.ROOT

# Лог открывается БЕЗ os.makedirs: каталог log создаёт раннер, а путь берётся так
# же, как в gen_stage4.py (проверено работающим прогоном). Если по какой-то
# причине записать не удалось - пишем рядом со скриптом, чтобы прогон не пропал.
class _Log(object):
    def __init__(self, path):
        self.path = path
        f = io.open(path, "wb")
        f.close()

    def __call__(self, msg):
        f = io.open(self.path, "ab")
        f.write((unicode(msg) + u"\n").encode("utf-8"))
        f.close()

    def close(self):
        pass


T0 = time.time()
try:
    _LOG = _Log(ROOT + u"/log/gen_find.log")
    _LOG(u"[diag] ROOT=%r" % ROOT)
except Exception:
    _LOG = _Log(BASE + u"/gen_find.log")
    _LOG(u"[diag] основной лог недоступен, пишу рядом со скриптом; ROOT=%r" % ROOT)


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


def H(msg):
    L(u"")
    L(u"==== %s ====" % msg)


GVL_MEM_TEXT = (u"VAR_GLOBAL\n"
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
          (u"главная", pou_prg_io.ALL),
          (u"ТЕСТ 8080", pou_test8080.ALL),
          (u"ТЕСТ CP/M", pou_testcpm.ALL),
          (u"ТЕСТ IO", pou_testio.ALL))

TEST_NAMES = (u"TEST_8080", u"TEST_CPM", u"TEST_IO")
ENGINE_NAMES = (u"FB_CPM_MemInit", u"FB_CPM_DirEngine", u"FB_BIOS_READ",
                u"FB_BIOS_WRITE")


def all_pous():
    out = []
    for grp, makers in GROUPS:
        for mk in makers:
            out.append(mk())
    return out


def variant_mem(keep):
    u"""FB_CPM_MemInit только с указанными сетями (индексы с нуля)."""
    p = pou_cpm_trap.make_mem_init()
    p.networks = [p.networks[k] for k in keep]
    return p


EXPS = {
    u"ALL":         (),
    u"NO_TEST":     TEST_NAMES,
    u"NO_T8080":    (u"TEST_8080",),
    u"NO_TCPM":     (u"TEST_CPM",),
    u"NO_TIO":      (u"TEST_IO",),
    u"NO_OLD":      None,      # особый случай: только тестовый слой
    u"NO_MEMINIT":  TEST_NAMES + (u"FB_CPM_MemInit",),
    u"NO_ENGINE":   TEST_NAMES + ENGINE_NAMES,
    u"NO_BIOSRW":   TEST_NAMES + (u"FB_BIOS_READ", u"FB_BIOS_WRITE"),
    u"ONLY_MEM":    None,      # особый случай: только MemInit из старого слоя
    u"MEM_N3":      (u"__MEM_N3__",),
    u"MEM_N4":      (u"__MEM_N4__",),
    u"MEM_N5":      (u"__MEM_N5__",),
    u"MEM_N6":      (u"__MEM_N6__",),
}
ORDER = (u"ALL", u"NO_TEST", u"NO_MEMINIT", u"NO_ENGINE", u"NO_BIOSRW",
         u"MEM_N3", u"MEM_N4", u"MEM_N5", u"MEM_N6")


def main():
    want = os.environ.get(u"DSH_S4_EXPS")
    if want:
        names = [unicode(x).strip() for x in unicode(want).split(u",") if x.strip()]
    else:
        names = [u"ALL", u"NO_TEST", u"NO_MEMINIT", u"NO_ENGINE"]
    L(u"=== ЛОКАЛИЗАЦИЯ: эксперименты %s ===" % u", ".join(names))

    POUS = all_pous()
    by_name = {}
    for p in POUS:
        by_name[p.name] = p
    L(u"сгенерировано POU: %d" % len(POUS))

    pdir = ROOT + u"/src/find_pous"
    if not os.path.isdir(pdir):
        try:
            os.makedirs(pdir)
        except Exception, e:
            L(u"[WARN] не удалось создать %s : %s" % (pdir, e))
    L(u"диагностика: ROOT=%r isdir(src)=%r isdir(log)=%r isdir(build)=%r"
      % (ROOT, os.path.isdir(ROOT + u"/src"), os.path.isdir(ROOT + u"/log"),
         os.path.isdir(ROOT + u"/build")))

    # зависимости
    dep = u"C:/dsh8080/work/dep_ccp"
    if not os.path.isdir(dep):
        dep = u"C:/dsh8080/work/dep_cpm"
    dep_fix = ROOT + u"/src/dep_fix"
    n_all, n_fix = pou_rename.fix_dir(dep, dep_fix, names=DEPENDENCIES)
    L(u"зависимости: %s (файлов %d, изменено %d)" % (dep_fix, n_all, n_fix))

    for idx, label in enumerate(names):
        H(u"### EXP %d : %s" % (idx + 1, label))
        skip = EXPS.get(label)
        special = {}
        if skip and len(skip) == 1 and unicode(skip[0]).startswith(u"__MEM_"):
            keep = {u"__MEM_N3__": [3], u"__MEM_N4__": [4],
                    u"__MEM_N5__": [5], u"__MEM_N6__": [6]}[skip[0]]
            special[u"FB_CPM_MemInit"] = keep
            skip = ()
        if skip is None:
            skip = tuple([p.name for p in POUS if p.name != u"FB_CPM_MemInit"])
        try:
            proj, app = cb.new_project(ROOT + u"/build/FIND_%s.project" % label, L)
        except Exception:
            L(u"[FAIL] проект %s:\n%s" % (label, traceback.format_exc()))
            continue

        try:
            for nm, text in D.DUT_ALL + IOD.DUT_ALL + TD.DUT_ALL:
                cb.add_dut(app, nm, pou_rename.decl_text(text), L)
            cb.add_gvl(app, u"GVL_CPU", pou_rename.decl_text(pou_decode_full.gvl_cpu_text()), L)
            cb.add_gvl(app, u"GVL_MEM", pou_rename.decl_text(GVL_MEM_TEXT), L)
            cb.add_gvl(app, u"GVL_CPM", pou_rename.decl_text(D.gvl_cpm_text()), L)
            cb.add_gvl(app, u"GVL_DISK", pou_rename.decl_text(D.gvl_disk_text()), L)
            for nm, fn in IOD.GVL_ALL:
                cb.add_gvl(app, nm, pou_rename.decl_text(fn()), L)
            cb.add_gvl(app, u"GVL_IO_HW",
                       pou_rename.decl_text(pou_io_hw.gvl_io_hw_text()), L)
            cb.add_gvl(app, u"GVL_TEST", pou_rename.decl_text(TD.gvl_test_text()), L)
        except Exception:
            L(u"[FAIL] объявления %s:\n%s" % (label, traceback.format_exc()))
            continue

        try:
            for name in DEPENDENCIES:
                app.import_xml(dep_fix + u"/%s.plcopenxml" % name)
            n_imp = 0
            for p in POUS:
                if p.name in skip:
                    continue
                if p.name in special:
                    p = variant_mem(special[p.name])
                one = u"%s/%s.plcopenxml" % (pdir, p.name)
                fbd_xml.write_project(one, [p], p.name)
                pou_rename.fix_file(one)
                app.import_xml(one)
                n_imp += 1
            L(u"    импортировано POU: %d (исключено %d)" % (n_imp, len(skip)))
        except Exception:
            L(u"[FAIL] импорт %s:\n%s" % (label, traceback.format_exc()))
            continue

        try:
            pou_taskcfg.setup_tasks(app, proj, lambda m: None, interval=u"T#20ms")
        except Exception:
            L(u"[WARN] задача %s: %s" % (label, run_online.s_of(sys.exc_info()[1])))

        L(u"    >>> СБОРКА ЭКСПЕРИМЕНТА %d (%s) <<<" % (idx + 1, label))
        try:
            cb.build(app, L)
            L(u"    сборка %s выполнена" % label)
        except Exception:
            L(u"[FAIL] сборка %s:\n%s" % (label, traceback.format_exc()))
        try:
            proj.save()
        except Exception:
            pass
        L(u"### EXP %d END" % (idx + 1))


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
