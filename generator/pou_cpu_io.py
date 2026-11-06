# -*- coding: utf-8 -*-
u"""Этап 3.6: обмен IN/OUT в ЯДРЕ 8080 (порт ввода-вывода).

ЗАДАЧА. Классы 33 (IN d8) и 34 (OUT d8) декодировались и имели длину 2 байта,
но обмен с портом ядро не выполняло: PC просто проходил дальше, A не менялся,
а OUT никуда не выводился. Здесь это доделано.

КАК ЭТО СДЕЛАНО (файлы ядра НЕ правятся).
  1. Модуль вызывает make_cpu_cpm() - процессор с уже проверенным портом CP/M
     (pou_cpu_cpm.py) - и ДОПОЛНЯЕТ готовый POU новой сетью и патчами готовых
     сетей, ровно тем же приёмом, каким этап 3.2 добавил порт CP/M. Файлы
     pou_cpu_full.py / pou_decode_full.py / pou_extra.py не менялись.
  2. Обмен идёт через шину GVL_IO (Req/Port/WData/RW -> Ack/RData) - так же, как
     ядро уже общается с GVL_CPU. Поэтому ИНТЕРФЕЙС FB_CPU8080_FULL не меняется
     и вызов процессора в главной программе остаётся прежним.
  3. Команда выполняется за ДВА скана (wait state), потому что аппаратный слой
     вызывается ниже по программе:
        скан N   : декодировали IN/OUT -> Req + Port + WData + RW; PC и счётчик
                   тактов НЕ двигаются (такт считается незавершённым);
        скан N   : FB_IO_Dispatch выполняет обращение, ставит Ack (+ RData);
        скан N+1 : для IN A := RData через порт 1 регистрового файла,
                   PC := PC + 2, счётчик тактов +1.
     Пока идёт ожидание, ни один регистр не пишется: у IN/OUT декодер уже
     выставляет C_WReg1..4 = FALSE и C_SZP_En/CY_En = FALSE, то есть флаги эти
     команды не трогают - требование задания выполнено схемой декодера.
  4. Патчи готовых сетей (по три связи, ничего не переписывая целиком):
     * СЕТЬ 25 (регистровый файл): у порта 1 появляется ещё один источник -
       "IN: A := GVL_IO.RData" по признаку io_in_load;
     * СЕТЬ 27 (запись PC): LD гасится на время ожидания (PC не продвигается);
     * СЕТЬ 29 (счётчик тактов): шаг не считается, пока такт не завершён.
  5. Защита индекса: номер порта - байт 0..255, а карта портов имеет ровно 256
     элементов, поэтому индекс порта в границах ПО ПОСТРОЕНИЮ; номера каналов
     ограничиваются блоком LIMIT внутри аппаратного слоя (pou_io.py).
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
import pou_cpu_cpm
from fbd_xml import Pou, Src
from pou_cpm_defs import I, NOT, AND, OR, EQ, SEL, IF, ADD, ORL, B, H
from pou_io_defs import patch_block, patch_src_block, net_of, find_block, pins
from pou_cpu_full import C_IN, C_OUT

# локальные переменные порта ввода-вывода
IO_LOCALS = (
    (u"io_go", u"BOOL", u"выполняется команда IN/OUT (класс 33/34 и такт идёт)"),
    (u"io_ack", u"BOOL", u"квитанция аппаратного слоя (GVL_IO.Ack)"),
    (u"io_rdata", u"BYTE", u"байт, прочитанный из порта (GVL_IO.RData)"),
    (u"io_done", u"BOOL", u"квитанция получена, такт завершается"),
    (u"io_wait", u"BOOL", u"процессор ждёт ответа устройства (wait state)"),
    (u"io_wait_p", u"BOOL", u"признак ожидания на прошлом скане"),
    (u"io_req", u"BOOL", u"запрос к аппаратному слою (живёт один скан)"),
    (u"io_in_load", u"BOOL", u"IN: загрузить A из порта в этом скане"),
    (u"io_done_p", u"BOOL", u"io_done на прошлом скане"),
    (u"io_out_l", u"BOOL", u"признак OUT, защёлкнутый по io_done"),
    (u"io_port_l", u"BYTE", u"защёлка номера порта (для HMI)"),
    (u"io_pc_ld", u"BOOL", u"такт завершается: PC будет обновлён"),
    (u"tact_busy_l", u"BOOL", u"такт начался и не завершён (вход watchdog); имя не должно совпадать с выходом IO_Busy"),
    (u"k_in", u"BOOL", u"класс операции 33 (IN d8)"),
    (u"k_out", u"BOOL", u"класс операции 34 (OUT d8)"),
)

IO_OUTPUTS = (
    (u"IO_Port", u"BYTE", u"последний порт, к которому обращались (для HMI)"),
    (u"IO_Busy", u"BOOL", u"процессор в wait state (такт не завершён)"),
    (u"Tact_Done", u"BOOL", u"такт завершён в этом скане"),
)


def make_cpu_io():
    u"""FB_CPU8080_FULL с обменом IN/OUT через шину GVL_IO."""
    p = pou_cpu_cpm.make_cpu_cpm()
    p.doc = (p.doc + u"\n\tДОПОЛНЕНО АППАРАТНЫМ СЛОЕМ (этап 3.6): команды IN d8 (33)\n"
             u"\tи OUT d8 (34) реально обмениваются с портом. Номер порта - байт\n"
             u"\tпо адресу PC+1, канал берётся из карты GVL_IO_Map. Обмен идёт через\n"
             u"\tшину GVL_IO (Req/Port/WData/RW -> Ack/RData), поэтому интерфейс\n"
             u"\tблока не изменился. Обращение занимает два скана (wait state):\n"
             u"\tв первом выставляется запрос, во втором по квитанции A := RData\n"
             u"\t(для IN) и PC := PC + 2. Пока идёт ожидание, счётчик тактов и PC\n"
             u"\tне двигаются, регистры и флаги не меняются.")

    for nm, t, c in IO_LOCALS:
        p.var(nm, t, c)
    for nm, t, c in IO_OUTPUTS:
        p.var_out(nm, t, c)

    # ---- признаки классов IN/OUT - в сеть признаков (СЕТЬ 10) ----
    k10, net10 = net_of(p, u"СЕТЬ 10")
    net10.outvar(u"k_in", EQ(net10, I(net10, u"cls"), I(net10, B % C_IN),
                             fbd_xml.COL_BLK + 1100))
    net10.outvar(u"k_out", EQ(net10, I(net10, u"cls"), I(net10, B % C_OUT),
                              fbd_xml.COL_BLK + 1220))

    # ---- НОВАЯ СЕТЬ 25Б: порт ввода-вывода ----
    # Ставится ПЕРЕД сетью регистрового файла (СЕТЬ 25): так все ссылки идут
    # "назад", а запись A от команды IN делается там же, где A пишет процессор.
    n = p.network(u"СЕТЬ 25Б (ПОРТ ВВОДА-ВЫВОДА). IN d8 / OUT d8: обмен через GVL_IO")
    n.outvar(u"io_go", AND(n, ORL(n, [I(n, u"k_in"), I(n, u"k_out")]),
                           I(n, u"run_i"), fbd_xml.COL_BLK + 400))
    n.outvar(u"io_ack", I(n, u"GVL_IO.Ack"))
    n.outvar(u"io_rdata", I(n, u"GVL_IO.RData"))
    n.outvar(u"io_wait_p", I(n, u"io_wait"))
    # квитанция получена -> такт завершается; иначе ждём, пока идёт обращение
    n.outvar(u"io_done", AND(n, I(n, u"io_wait_p"), I(n, u"io_ack"),
                             fbd_xml.COL_BLK + 520))
    n.outvar(u"io_wait", IF(n, I(n, u"io_done"), I(n, u"FALSE"),
                            IF(n, I(n, u"io_go"), I(n, u"TRUE"),
                               I(n, u"io_wait_p"), fbd_xml.COL_BLK + 660),
                            fbd_xml.COL_BLK + 800))
    # запрос живёт один скан: как только пришла квитанция, он снимается
    n.outvar(u"io_req", AND(n, I(n, u"io_go"),
                            NOT(n, I(n, u"io_ack"), fbd_xml.COL_BLK + 940),
                            fbd_xml.COL_BLK + 1080))
    # A загружается из порта ТОЛЬКО для команды IN (OUT регистр не трогает)
    # ОТЛАДОЧНЫЕ СЧЁТЧИКИ ПУТИ IN (обычные поля GVL, не структуры).
    for _nm, _g in ((u"GVL_IO.Dbg_IoW", u"io_wait_p"),
                    (u"GVL_IO.Dbg_IoA", u"io_ack"),
                    (u"GVL_IO.Dbg_IoD", u"io_done")):
        n.outvar(_nm, IF(n, I(n, _g),
                         ADD(n, I(n, _nm), I(n, u"UDINT#1"),
                             fbd_xml.COL_BLK + 1400),
                         I(n, _nm), fbd_xml.COL_BLK + 1460))
    # ФАЗА B. ЗАГРУЗКА A - НА СЛЕДУЮЩЕМ СКАНЕ ПОСЛЕ ЗАВЕРШЕНИЯ ТАКТА.
    # Замер: диспетчер отвечает на скане 4826, ядро завершает такт на 4828,
    # но байт в этот момент уже обнулён (запроса в скане нет). Данные
    # успевают установиться только к следующему скану, поэтому загрузку
    # разносим с завершением такта на один скан (PC при этом уже сдвинут,
    # поэтому признак OUT тоже защёлкивается).
    n.outvar(u"io_done_p", I(n, u"io_done"), fbd_xml.COL_BLK + 1180)
    n.outvar(u"io_out_l", IF(n, I(n, u"io_done"), I(n, u"k_out"),
                              I(n, u"io_out_l"), fbd_xml.COL_BLK + 1200))
    n.outvar(u"io_in_load", AND(n, I(n, u"io_done_p"),
                                NOT(n, I(n, u"io_out_l"), fbd_xml.COL_BLK + 1240),
                                fbd_xml.COL_BLK + 1360))
    # МЕТКИ ФАЗ ДЛЯ ПРОВЕРКИ 8: сравниваем номера сканов, когда ядро
    # завершает такт IN и когда диспетчер отвечает на порт 10h.
    n.outvar(u"GVL_IO.Dbg_SD", IF(n, I(n, u"io_done"),
                                 I(n, u"GVL_IO.Dbg_N"),
                                 I(n, u"GVL_IO.Dbg_SD"),
                                 fbd_xml.COL_BLK + 1700))
    n.outvar(u"GVL_IO.Dbg_RdL",
             IF(n, I(n, u"io_in_load"), I(n, u"io_rdata"),
                I(n, u"GVL_IO.Dbg_RdL"), fbd_xml.COL_BLK + 1640))
    n.outvar(u"GVL_IO.Dbg_IoL",
             IF(n, I(n, u"io_in_load"),
                ADD(n, I(n, u"GVL_IO.Dbg_IoL"), I(n, u"UDINT#1"),
                    fbd_xml.COL_BLK + 1520),
                I(n, u"GVL_IO.Dbg_IoL"), fbd_xml.COL_BLK + 1580))

    # номер порта - ВТОРОЙ БАЙТ КОМАНДЫ, он прочитан из памяти по адресу PC+1
    n.outvar(u"io_port_l", IF(n, I(n, u"io_go"), I(n, u"op_lo"),
                              I(n, u"GVL_IO.Port"), fbd_xml.COL_BLK + 1500))
    n.outvar(u"GVL_IO.Port", I(n, u"io_port_l"))
    n.outvar(u"GVL_IO.RW", IF(n, I(n, u"io_go"), I(n, u"k_out"),
                              I(n, u"GVL_IO.RW"), fbd_xml.COL_BLK + 1640))
    n.outvar(u"GVL_IO.WData", IF(n, I(n, u"io_go"), I(n, u"regs.A"),
                                 I(n, u"GVL_IO.WData"), fbd_xml.COL_BLK + 1780))
    n.outvar(u"GVL_IO.Req", I(n, u"io_req"))
    n.outvar(u"GVL_IO.Wait", I(n, u"io_wait"))
    n.outvar(u"IO_Port", I(n, u"io_port_l"))
    n.outvar(u"IO_Busy", I(n, u"io_wait"))
    # сеть порта переносится ПЕРЕД сетью регистрового файла
    k25, _net25 = net_of(p, u"СЕТЬ 25 (ФАЗА 9)")
    p.networks.remove(n)
    p.networks.insert(k25, n)

    # ---- ПАТЧ 1: у порта 1 регистрового файла появляется запись A от IN ----
    net_regs, it_regs = find_block(p, u"regs")
    net_regs._items.remove(it_regs)
    pin = pins(it_regs)
    sel_data = SEL(net_regs, I(net_regs, u"io_in_load"), pin[u"Data1"],
                   I(net_regs, u"io_rdata"), fbd_xml.COL_BLK + 400)
    sel_dst = SEL(net_regs, I(net_regs, u"io_in_load"), pin[u"Dst1"],
                  I(net_regs, H % 7), fbd_xml.COL_BLK + 540)
    or_wr = OR(net_regs, pin[u"Wr1"], I(net_regs, u"io_in_load"),
               fbd_xml.COL_BLK + 680)
    repl = {u"Data1": sel_data, u"Dst1": sel_dst, u"Wr1": or_wr}
    ins = [(pn, repl.get(pn, src)) for pn, src in it_regs[3]]
    net_regs._items.append((u"block", it_regs[1], it_regs[2], ins, it_regs[4],
                            it_regs[5], it_regs[6]))

    # ---- ПАТЧ 2: запись PC гасится, пока такт не завершён (wait state) ----
    #
    # ФАЗА B - ЗДЕСЬ БЫЛА ПРИЧИНА ПОЛНОГО ОТКАЗА ПРОГОНА ТЕСТОВ.
    # Раньше гейт собирался ЗАНОВО из OR(run_i, int_take):
    #     pc_gate = AND(OR(run_i, int_take), NOT(io_wait))
    #     patch_block(p, u"pc", {u"LD": pc_gate})
    # и тем самым ЗАТИРАЛ патч слоя CP/M, который раньше наложил pou_cpu_cpm:
    #     pc.LD = OR(<то же>, cpm_pc_wr)
    # В результате запись PC ЧЕРЕЗ ПОРТ CP/M полностью пропадала (аналогичный
    # патч для SP никто не перекрывал, поэтому SP писался, а PC - нет).
    # Последствия: стартовая установка PC := 0F100h не доходила до процессора,
    # Reg_PC оставался 0, CPU исполнял нулевую страницу и уходил в BIOS,
    # автомат трапов застревал в фазе TRAP (без активного диспетчера и без
    # квитанции Func_Done), CPU_Enable навсегда становился FALSE - процессор
    # не делал ни одного такта, и все 199 тестов были FAIL.
    # Теперь гейт накладывается НА ТЕКУЩИЙ источник входа LD (в нём уже есть
    # cpm_pc_wr), а не собирается заново.
    k27, net27 = net_of(p, u"СЕТЬ 27")
    _net_pc, _it_pc = find_block(p, u"pc")
    cur_ld = pins(_it_pc)[u"LD"]
    pc_gate = AND(net27, cur_ld,
                  NOT(net27, I(net27, u"io_wait"), fbd_xml.COL_BLK + 340),
                  fbd_xml.COL_BLK + 480)
    patch_block(p, u"pc", {u"LD": pc_gate})

    # ---- ПАТЧ 3: счётчик тактов не растёт на скане ожидания ----
    k29, net29 = net_of(p, u"СЕТЬ 29")
    step_gate = AND(net29, I(net29, u"run"),
                    NOT(net29, I(net29, u"io_wait"), fbd_xml.COL_BLK + 200),
                    fbd_xml.COL_BLK + 340)
    patch_src_block(p, u"step_n", {u"G": step_gate})

    # ---- НОВАЯ СЕТЬ 31: признаки такта для watchdog ----
    n = p.network(u"СЕТЬ 31 (ПОРТ ВВОДА-ВЫВОДА). Признаки такта для watchdog")
    n.outvar(u"io_pc_ld", AND(n, ORL(n, [I(n, u"run_i"), I(n, u"int_take")]),
                              NOT(n, I(n, u"io_wait"), fbd_xml.COL_BLK + 300),
                              fbd_xml.COL_BLK + 440))
    n.outvar(u"Tact_Done", I(n, u"io_pc_ld"))
    n.outvar(u"tact_busy_l", AND(n, I(n, u"run"),
                             NOT(n, I(n, u"io_pc_ld"), fbd_xml.COL_BLK + 200),
                             fbd_xml.COL_BLK + 340))
    n.outvar(u"GVL_IO.Tact_Done", I(n, u"io_pc_ld"))
    n.outvar(u"GVL_IO.Tact_Busy", I(n, u"tact_busy_l"))
    return p


ALL = (make_cpu_io,)
