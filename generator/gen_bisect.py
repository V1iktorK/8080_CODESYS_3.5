# -*- coding: utf-8 -*-
u"""ЭТАП 4 - драйвер: конфигурация задач + тесты + онлайн-прогон в симуляции.

ЧТО ДЕЛАЕТ ОДНИМ ПРОГОНОМ (и почему одним):
очередь CODESYS - однопроцессная, а соседний проект Z80_EMU снимает наш процесс
перед каждым своим запуском (docs/03, п. 12.6). Поэтому сборка, конфигурация
задач, тесты и онлайн-прогон делаются ЗА ОДИН запуск CODESYS - иначе каждая
неудача стоила бы полного цикла сборки.

СОСТАВ ПРОЕКТА:
  * 27 зависимостей ядра из dep_ccp/*.plcopenxml (файлы этапов 3.1-3.4 НЕ менялись);
  * 64 POU слоя CP/M и аппаратного ввода-вывода (этап 3.6), генерируются теми же
    модулями, что и раньше (pou_cpu_io, pou_cpm_trap, pou_bios, pou_bdos, pou_ccp,
    pou_com_loader, pou_io, pou_io_hw, pou_prg_io);
  * НОВОЕ этапа 4: DUT ST_TestCase, GVL_TEST (данные тестов), программы
    TEST_8080, TEST_CPM, TEST_IO и конфигурация задач (pou_taskcfg).
  * ВАЖНО: файлы предыдущих этапов не правятся ни строки - тесты работают с тем
    же экземпляром процессора, которым управляет PLC_PRG_CPM, через штатный
    порт CP/M, а память CP/M пересобирается сбросом признака GVL_CPM.Init_Done
    (FB_CPM_MemInit гейтится им сам).

ПОРЯДОК ВЫЗОВА ПРОГРАММ В ЗАДАЧЕ (см. pou_taskcfg.py):
    TEST_8080 -> PLC_PRG_CPM -> TEST_CPM -> TEST_IO
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
import pou_extra
import pou_test_defs as TD
import pou_test8080
import pou_testcpm
import pou_testio
import pou_rename
import pou_taskcfg_bisect as pou_taskcfg
import run_online

ROOT = cb.ROOT
T0 = time.time()
_LOG = cb.make_log(u"gen_stage4.log")


def L(msg):
    _LOG(u"[%6.1f s] %s" % (time.time() - T0, msg))


def H(msg):
    L(u"")
    L(u"==== %s ====" % msg)


GVL_MEM_TEXT = (u"VAR_GLOBAL\n"
                u"\t(* Общая память эмулятора Intel 8080: 64 КБ.\n"
                u"\t   Здесь же страница нуля CP/M, таблица BIOS, ловушки\n"
                u"\t   BDOS/BIOS/CCP, DPB, образ диска и код тестов. *)\n"
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

# группы POU этапов 3.2-3.6: НЕ менялись
GROUPS = ((u"процессор с портами CP/M и I/O", pou_cpu_io.ALL),
          (u"трапы и инициализация", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"загрузчик .COM", pou_com_loader.ALL),
          (u"адаптер C", pou_io_hw.ALL),
          (u"главная программа", pou_prg_io.ALL),
          (u"ТЕСТЫ: ядро 8080", pou_test8080.ALL))
INTERVAL = os.environ.get(u"DSH_S4_INTERVAL") or u"T#2ms"
WAIT_SEC = int(os.environ.get(u"DSH_S4_WAIT") or u"420")
TAIL_SEC = int(os.environ.get(u"DSH_S4_TAIL") or u"20")
NO_ONLINE = bool(os.environ.get(u"DSH_S4_NO_ONLINE"))


def main():
    L(u"=== ЭТАП 4: конфигурация задач, тесты TEST_8080/TEST_CPM/TEST_IO, "
      u"онлайн-прогон в симуляции ===")
    L(u"python: %s" % sys.version)
    L(u"корень: %s" % ROOT)
    L(u"кейсов 8080 в таблице: %d, интервал задачи %s" % (len(TD.build_all()), INTERVAL))

    H(u"[0] ГЕНЕРАЦИЯ СХЕМ")
    POUS = []
    for group, makers in GROUPS:
        for mk in makers:
            p = mk()
            POUS.append(p)
            L(u"[0] %-26s POU: %-22s сетей=%2d блоков=%3d"
              % (group, p.name, len(p.networks),
                 sum([1 for net in p.networks
                      for it in net._items if it[0] == u"block"])))
    NAMES = [p.name for p in POUS]
    L(u"[0] всего POU: %d" % len(POUS))

    src_path = ROOT + u"/src/stage4_full.plcopenxml"
    size = fbd_xml.write_project(src_path, POUS, u"stage4_full")
    cn = fbd_xml.count_elements(src_path)
    L(u"[1] PLCopenXML записан: %d символов (блоков=%d связей=%d пустых.входов=%d)"
      % (size, cn[0], cn[3], cn[4]))

    try:
        proj, app = cb.new_project(ROOT + u"/build/EMU8080_STAGE4.project", L)
    except Exception:
        L(u"[2] ОШИБКА проекта:\n" + traceback.format_exc())
        _LOG.close()
        return

    try:
        # ИМЕНА, СОВПАДАЮЩИЕ С КЛЮЧЕВЫМИ СЛОВАМИ IEC (LD, S, R, DO), ломают
        # КОДОГЕНЕРАЦИЮ (разбор объявлений их принимает). Поэтому все тексты
        # объявлений проходят через pou_rename - см. шапку этого модуля.
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

        # зависимости берутся из отдельной папки dep_ccp (см. gen_cpm.py)
        dep = u"C:/dsh8080/work/dep_ccp"
        if not os.path.isdir(dep):
            dep = u"C:/dsh8080/work/dep_cpm"
        if not os.path.isdir(dep):
            dep = ROOT + u"/src"
        dep_fix = ROOT + u"/src/dep_fix"
        n_all, n_fix = pou_rename.fix_dir(dep, dep_fix, names=DEPENDENCIES)
        L(u"    зависимости ядра: %s -> %s (файлов %d, изменено имён в %d)"
          % (dep, dep_fix, n_all, n_fix))
        # ВАЖНО (этап 4). Часть зависимостей ядра порождается модулем pou_extra,
        # а dep_ccp - это СНИМОК прошлых сборок. Кодогенерация нашла в снимке
        # FB_UnpackWord два вызова FB_PackByte БЕЗ экземпляра (C80 x2 + C32).
        # Чтобы проект всегда соответствовал генератору, а не снимку,
        # зависимости pou_extra перегенерируются прямо здесь.
        n_re = 0
        for mk in pou_extra.ALL:
            pp = mk()
            if pp.name not in DEPENDENCIES:
                continue
            one_dep = dep_fix + u"/%s.plcopenxml" % pp.name
            fbd_xml.write_project(one_dep, [pp], pp.name)
            pou_rename.fix_file(one_dep)
            n_re += 1
        L(u"    перегенерировано зависимостей pou_extra: %d" % n_re)
        for i, name in enumerate(DEPENDENCIES):
            app.import_xml(dep_fix + u"/%s.plcopenxml" % name)
        L(u"    импортировано зависимостей: %d" % len(DEPENDENCIES))

        n_bad = 0
        pdir = ROOT + u"/src/s4_pous"
        if not os.path.isdir(pdir):
            try:
                os.makedirs(pdir)
            except Exception:
                pass
        for p in POUS:
            one = u"%s/%s.plcopenxml" % (pdir, p.name)
            fbd_xml.write_project(one, [p], p.name)
            pou_rename.fix_file(one)
            ok_p = False
            for _try in range(4):
                try:
                    app.import_xml(one)
                    ok_p = True
                    break
                except Exception, e:
                    L(u"    повтор импорта %s: %s" % (p.name, run_online.s_of(e)))
                    time.sleep(1.5)
            if not ok_p:
                n_bad += 1
                L(u"    ОШИБКА импорта POU %s" % p.name)
        L(u"    импортировано по одному файлу: %d POU (сбоев %d)"
          % (len(POUS), n_bad))
        proj.save()
        L(u"[2] проект сохранён (до сборки)")
        cb.build(app, L)
        L(u"[3] СБОРКА ВЫПОЛНЕНА")
    except Exception:
        L(u"[3] ОШИБКА сборки:\n" + traceback.format_exc())

    H(u"[4] КОНФИГУРАЦИЯ ЗАДАЧ (блокер этапа)")
    try:
        pou_taskcfg.setup_tasks(app, proj, L, interval=INTERVAL)
        cb.build(app, L)
        L(u"[OK] сборка с конфигурацией задач выполнена")
    except Exception:
        L(u"[FAIL] конфигурация задач:\n" + traceback.format_exc())

    H(u"[5] РЕЖИМ СИМУЛЯЦИИ И BOOT-ПРИЛОЖЕНИЕ")
    sim_ok = False
    try:
        sim_ok = run_online.enable_simulation(proj, L)
    except Exception:
        L(u"[FAIL] режим симуляции:\n" + traceback.format_exc())
    try:
        app.create_boot_application(ROOT + u"/build/EMU8080_STAGE4.app")
        L(u"[OK] app.create_boot_application(EMU8080_STAGE4.app)")
    except Exception, e:
        L(u"[FAIL] create_boot_application: %s" % run_online.s_of(e))

    H(u"[6] ПРОВЕРКА СВЯЗЕЙ И ВЫГРУЗКА")
    try:
        ok = cb.verify_import(proj, app, NAMES, src_path,
                              ROOT + u"/src/stage4_full_reexport.xml", L)
        L(u"[6] ИТОГ ПРОВЕРКИ СВЯЗЕЙ: %s" % (u"УСПЕХ" if ok else u"РАСХОЖДЕНИЯ"))
    except Exception:
        L(u"[FAIL] verify_import:\n" + traceback.format_exc())

    data = None
    if NO_ONLINE:
        L(u"[7] онлайн-прогон отключён переменной DSH_S4_NO_ONLINE")
    else:
        H(u"[7] ОНЛАЙН-ПРОГОН В СИМУЛЯЦИИ")
        try:
            data = run_online.online_run(app, L, wait_sec=WAIT_SEC, tail_sec=TAIL_SEC)
        except Exception:
            L(u"[FAIL] онлайн-прогон:\n" + traceback.format_exc())

    if data:
        H(u"[8] ОТЧЁТ")
        try:
            run_online.write_report(ROOT, data, L)
        except Exception:
            L(u"[FAIL] отчёт:\n" + traceback.format_exc())
    else:
        L(u"[8] отчёта нет: онлайн-прогон не дал данных")

    try:
        proj.save()
        L(u"[9] проект сохранён: %s" % (ROOT + u"/build/EMU8080_STAGE4.project"))
    except Exception:
        L(u"[FAIL] save:\n" + traceback.format_exc())
    L(u"[9] ИТОГ: выполнено")


try:
    main()
except Exception:
    L(u"FATAL:\n%s" % traceback.format_exc())
L(u"=== DONE ===")
_LOG.close()
