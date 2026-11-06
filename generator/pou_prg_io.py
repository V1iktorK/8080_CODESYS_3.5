# -*- coding: utf-8 -*-
u"""Этап 3.6: главная программа эмулятора с аппаратным слоем ввода-вывода.

ПОРЯДОК СЕТЕЙ (= порядок выполнения в скане задачи):
  1.  FB_CPM_MemInit  - память, таблицы, диск (как было, pou_prg_cpm.py);
  1Б. FB_IO_MapInit   - карта портов и параметры защит (новое, этап 3.6);
  2.  включение процессора: GVL_CPU.Enable := GVL_CPM.CPU_Run;
  3.  FB_CPU8080_FULL - один такт 8080 + порт CP/M + ПОРТ ВВОДА-ВЫВОДА:
                        команда IN/OUT выставляет запрос в GVL_IO (Req/Port/
                        WData/RW) и НЕ завершает такт, пока нет квитанции;
  4.  FB_CPM_Trap     - ловушки CP/M;
  5.  FB_BDOS / BIOS / CCP - диспетчеры вызванной функции CP/M;
  6.  FB_IO_Dispatch  - аппаратный слой: выполняет обращение к порту, ставит
                        квитанцию GVL_IO.Ack и байт GVL_IO.RData (для IN);
  7.  FB_Watchdog     - контроль незавершённого такта (снимок PC/IR/флагов);
  8.  аварийный останов и РУЧНОЙ сброс (кнопки HMI, режим ШАГ);
  9.  FB_HMI_Update   - обновление переменных HMI (последняя сеть).

ПОЧЕМУ ДИСПЕТЧЕР И WATCHDOG ИМЕННО ЗДЕСЬ. Процессор вызывается первым (так
устроен уже проверенный порядок слоя CP/M: процессор -> трап -> диспетчеры),
поэтому ответ аппаратного слоя приходит процессору на СЛЕДУЮЩЕМ скане - это и
есть wait state, описанный в pou_io_defs.py. Ни один работающий POU при этом не
переписан: FB_CPU8080_FULL дополнен новыми сетями (pou_cpu_io.py), а вызов
процессора в сети 3 остался прежним.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, NOT, AND, OR, NE, EQ, IF, ADD, ORL, SEL,
                          latch, B, H)
import pou_prg_cpm
from pou_io_defs import ADAPTER_TYPE, net_of

# переменные программы, добавленные этапом 3.6
PRG_LOCALS = (
    (u"io_map_done", u"BOOL", u"карта портов инициализирована"),
    (u"io_req_l", u"BOOL", u"запрос ввода-вывода от процессора (защёлка)"),
    (u"io_rw_l", u"BOOL", u"направление обращения (защёлка)"),
    (u"io_port_l", u"BYTE", u"номер порта обращения (защёлка)"),
    (u"io_wdata_l", u"BYTE", u"байт вывода (защёлка)"),
    (u"io_ack_l", u"BOOL", u"квитанция аппаратного слоя (защёлка выхода FB)"),
    (u"io_rdata_l", u"BYTE", u"прочитанный байт (защёлка выхода FB)"),
    (u"io_rdata_d", u"BYTE", u"байт ответа, выровненный по Ack"),
    (u"io_fault_l", u"BOOL", u"обращение было аварийным"),
    (u"io_errc_l", u"BYTE", u"код аварии обращения"),
    (u"io_kind_l", u"BYTE", u"вид канала обращения"),
    (u"io_idx_l", u"INT", u"номер канала обращения"),
    (u"io_halt_l", u"BOOL", u"аппаратный слой требует останова"),
    (u"wd_timeout_l", u"BOOL", u"watchdog: тайм-аут такта"),
    (u"wd_halt_l", u"BOOL", u"watchdog требует остановить эмулятор"),
    (u"wd_err_l", u"BYTE", u"код аварии watchdog"),
    (u"wd_scan_l", u"UDINT", u"счётчик сканов задачи"),
    (u"wd_busy_l", u"UDINT", u"сканов в текущем такте"),
    (u"wd_tact_l", u"UDINT", u"счётчик завершённых тактов"),
    (u"wd_snap_pc_l", u"WORD", u"снимок PC на момент аварии"),
    (u"wd_snap_ir_l", u"BYTE", u"снимок IR на момент аварии"),
    (u"wd_snap_psw_l", u"BYTE", u"снимок флагов на момент аварии"),
    (u"wd_snap_ok_l", u"BOOL", u"снимок достоверен"),
    (u"wd_tcnt_l", u"UDINT", u"число срабатываний watchdog"),
    (u"wd_slow_l", u"UDINT", u"число срабатываний 2-го счётчика"),
    (u"wd_safe_l", u"BOOL", u"Tacts_Per_Scan сброшен в 1"),
    (u"wd_tps_l", u"WORD", u"значение Tacts_Per_Scan для GVL_IO_Map"),
    (u"hmi_done_l", u"BOOL", u"HMI обновлён"),
    (u"halt_all", u"BOOL", u"останов: авария аппаратного слоя или watchdog"),
    (u"reset_l", u"BOOL", u"кнопка СБРОС нажата"),
    (u"run_l", u"BOOL", u"кнопка ПУСК нажата"),
    (u"stop_l", u"BOOL", u"кнопка СТОП нажата"),
    (u"step_l", u"BOOL", u"кнопка ШАГ нажата (фронт: ровно один такт)"),
    (u"step_prev", u"BOOL", u"кнопка ШАГ была нажата на прошлом скане"),
    (u"cpu_run_new", u"BOOL", u"новое значение GVL_CPM.CPU_Run"),
    (u"cpu_halt_new", u"BOOL", u"новое значение GVL_CPU.Halted"),
    (u"err_res", u"BYTE", u"код ошибки после возможного сброса"),
)

PRG_VAR_INSTANCES = (
    (u"io_map", u"FB_IO_MapInit", u"инициализация карты портов"),
    (u"io", u"FB_IO_Dispatch", u"аппаратный слой ввода-вывода"),
    (u"wd", u"FB_Watchdog", u"watchdog такта"),
    (u"hmi", u"FB_HMI_Update", u"обновление переменных HMI"),
)


def make_plc_prg_io():
    u"""PLC_PRG_CPM с аппаратным слоем ввода-вывода (этап 3.6)."""
    p = pou_prg_cpm.make_plc_prg_cpm()
    p.doc = (p.doc + u"\n\tДОПОЛНЕНО АППАРАТНЫМ СЛОЕМ (этап 3.6): инициализация\n"
             u"\tкарты портов, FB_IO_Dispatch (обмен IN/OUT за два скана, wait\n"
             u"\tstate), FB_Watchdog (останов при незавершённом такте), аварийный\n"
             u"\tостанов с ручным сбросом и обновление HMI. Порядок: инициализация\n"
             u"\t-> процессор -> трап -> диспетчеры CP/M -> ввод-вывод -> watchdog\n"
             u"\t-> HMI.")

    for nm, t, c in PRG_LOCALS:
        p.var(nm, t, c)
    for nm, t, c in PRG_VAR_INSTANCES:
        p.var(nm, t, c)

    # ------------------------------------------------------------------
    # СЕТЬ 1Б. КАРТА ПОРТОВ (сразу после инициализации памяти CP/M)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 1Б. Карта портов и параметры защит (FB_IO_MapInit)")
    mp = n.block(u"FB_IO_MapInit", [(u"Enable", I(n, u"TRUE"))], [u"Done"],
                 instance=u"io_map")
    n.outvar(u"io_map_done", mp.out(u"Done"))
    k, _net1 = net_of(p, u"СЕТЬ 1.")
    p.networks.remove(n)
    p.networks.insert(k + 1, n)

    # ------------------------------------------------------------------
    # СЕТЬ 5. АППАРАТНЫЙ СЛОЙ: выполнение обращения IN/OUT
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 5. Аппаратный слой ввода-вывода (FB_IO_Dispatch, %s)"
                  % ADAPTER_TYPE)
    # входы диспетчера защёлкиваются из шины GVL_IO, которую заполнил процессор
    n.outvar(u"GVL_IO.Dbg_ReqL",
             IF(n, I(n, u"GVL_IO.Req"),
                ADD(n, I(n, u"GVL_IO.Dbg_ReqL"), I(n, u"UDINT#1"),
                    fbd_xml.COL_BLK + 5000),
                I(n, u"GVL_IO.Dbg_ReqL"),
                fbd_xml.COL_BLK + 5130))
    # Запрос приходит ИЛИ от процессора (IN/OUT), ИЛИ инъекцией теста:
    # процессор перезаписывает Req каждый скан, поэтому запрос теста
    # через Req терялся (замер: inj=36 сканов, Req в главной - 0).
    # ФАЗА B. ЗАПРОС ДЕРЖИТСЯ ДО КВИТАНЦИИ.
    # У процессора GVL_IO.Req живёт ОДИН скан (io_req = io_go AND NOT ack),
    # а диспетчер читает шину со СЛЕДУЮЩЕГО скана - то есть запрос
    # процессора до него не доходил НИКОГДА. Замер подтвердил: ядро
    # завершало такт IN (io_in_load = 4), но грузило в A байт 0, потому
    # что диспетчер не ответил. Теперь запрос защёлкивается до Ack
    # (штатный протокол: Req держится, пока не придёт квитанция).
    n.outvar(u"io_req_l", OR(n, OR(n, I(n, u"GVL_IO.Req"),
                                   I(n, u"GVL_IO.Inj"), fbd_xml.COL_BLK + 60),
                             AND(n, I(n, u"io_req_l"),
                                 NOT(n, I(n, u"GVL_IO.Ack"),
                                     fbd_xml.COL_BLK + 120),
                                 fbd_xml.COL_BLK + 160),
                             fbd_xml.COL_BLK + 100))
    n.outvar(u"io_rw_l", I(n, u"GVL_IO.RW"))
    n.outvar(u"io_port_l", I(n, u"GVL_IO.Port"))
    n.outvar(u"io_wdata_l", I(n, u"GVL_IO.WData"))
    io = n.block(u"FB_IO_Dispatch", [
        (u"Enable", I(n, u"GVL_IO_Map.Adapter_Enable")), (u"Req", I(n, u"io_req_l")),
        (u"RW", I(n, u"io_rw_l")), (u"Port", I(n, u"io_port_l")),
        (u"WData", I(n, u"io_wdata_l"))],
        [u"Ack", u"RData", u"Fault", u"Err_Code", u"Kind", u"Index", u"Halt_Req"],
        instance=u"io", x=fbd_xml.COL_BLK + 200)
    # выходы вызова FB защёлкиваются в переменные POU (правило 9.1 журнала)
    n.outvar(u"io_ack_l", io.out(u"Ack"))
    n.outvar(u"io_rdata_l", io.out(u"RData"))
    n.outvar(u"io_fault_l", io.out(u"Fault"))
    n.outvar(u"io_errc_l", io.out(u"Err_Code"))
    n.outvar(u"io_kind_l", io.out(u"Kind"))
    n.outvar(u"io_idx_l", io.out(u"Index"))
    n.outvar(u"io_halt_l", io.out(u"Halt_Req"))
    # квитанция и байт возвращаются процессору через ту же шину
    n.outvar(u"GVL_IO.Ack", I(n, u"io_ack_l"))
    # ФАЗА B. RData публикуется ТЕМ ЖЕ числом защёлок, что и Ack.
    # Раньше здесь стояла ЛИШНЯЯ защёлка io_rdata_d: байт запаздывал на
    # один скан относительно квитанции, и ядро в момент io_done читало
    # ещё не пришедший байт (замер: ad_rdata = 1, а ядро грузило 0).
    n.outvar(u"GVL_IO.RData", I(n, u"io_rdata_l"))

    # ------------------------------------------------------------------
    # СЕТЬ 6. WATCHDOG
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 6. Watchdog: такт не завершился за Limit_Scans сканов")
    wd = n.block(u"FB_Watchdog", [
        (u"Enable", I(n, u"GVL_IO_Map.Watchdog_Enable")),
        (u"Tact_Busy", I(n, u"GVL_IO.Tact_Busy")),
        (u"Tact_Done", I(n, u"GVL_IO.Tact_Done")),
        (u"Limit_Scans", I(n, u"GVL_IO_Map.Limit_Scans")),
        (u"Limit_Scans_Per_Tact", I(n, u"GVL_IO_Map.Limit_Scans_Per_Tact")),
        (u"Tacts_Per_Scan", I(n, u"GVL_IO_Map.Tacts_Per_Scan")),
        (u"Step_Cnt", I(n, u"GVL_CPU.Step_Cnt")),
        (u"Reset", I(n, u"GVL_HMI.Btn_Reset")),
        (u"PC", I(n, u"GVL_CPM.Reg_PC")), (u"IR", I(n, u"GVL_CPU.Bus_IR")),
        (u"PSW", I(n, u"GVL_CPM.Reg_PSW"))],
        [u"Timeout", u"Halted", u"Error_Code", u"Scan_Cnt", u"Busy_Scans",
         u"Tact_Cnt", u"Snapshot_PC", u"Snapshot_IR", u"Snapshot_PSW",
         u"Snapshot_Valid", u"Timeout_Cnt", u"Slow_Cnt", u"Safe_Mode",
         u"Tacts_Per_Scan_Out"], instance=u"wd", x=fbd_xml.COL_BLK + 200)
    n.outvar(u"wd_timeout_l", wd.out(u"Timeout"))
    n.outvar(u"wd_halt_l", wd.out(u"Halted"))
    n.outvar(u"wd_err_l", wd.out(u"Error_Code"))
    n.outvar(u"wd_scan_l", wd.out(u"Scan_Cnt"))
    n.outvar(u"wd_busy_l", wd.out(u"Busy_Scans"))
    n.outvar(u"wd_tact_l", wd.out(u"Tact_Cnt"))
    n.outvar(u"wd_snap_pc_l", wd.out(u"Snapshot_PC"))
    n.outvar(u"wd_snap_ir_l", wd.out(u"Snapshot_IR"))
    n.outvar(u"wd_snap_psw_l", wd.out(u"Snapshot_PSW"))
    n.outvar(u"wd_snap_ok_l", wd.out(u"Snapshot_Valid"))
    n.outvar(u"wd_tcnt_l", wd.out(u"Timeout_Cnt"))
    n.outvar(u"wd_slow_l", wd.out(u"Slow_Cnt"))
    n.outvar(u"wd_safe_l", wd.out(u"Safe_Mode"))
    n.outvar(u"wd_tps_l", wd.out(u"Tacts_Per_Scan_Out"))
    # второй счётчик: если настройка Tacts_Per_Scan нереалистична, watchdog
    # отдаёт 1 - возвращаем её в карту портов (единственное место настройки)
    n.outvar(u"GVL_IO_Map.Tacts_Per_Scan", I(n, u"wd_tps_l"))
    # состояние watchdog - сразу в HMI
    n.outvar(u"GVL_HMI.Wd_Timeout", I(n, u"wd_timeout_l"))
    n.outvar(u"GVL_HMI.Wd_Scan_Cnt", I(n, u"wd_scan_l"))
    n.outvar(u"GVL_HMI.Wd_Busy_Scans", I(n, u"wd_busy_l"))
    n.outvar(u"GVL_HMI.Wd_Snapshot_PC", I(n, u"wd_snap_pc_l"))
    n.outvar(u"GVL_HMI.Wd_Snapshot_IR", I(n, u"wd_snap_ir_l"))
    n.outvar(u"GVL_HMI.Wd_Snapshot_PSW", I(n, u"wd_snap_psw_l"))
    n.outvar(u"GVL_HMI.Wd_Snapshot_Valid", I(n, u"wd_snap_ok_l"))
    n.outvar(u"GVL_HMI.Wd_Timeout_Cnt", I(n, u"wd_tcnt_l"))
    n.outvar(u"GVL_HMI.Wd_Slow_Cnt", I(n, u"wd_slow_l"))
    n.outvar(u"GVL_HMI.Wd_Safe_Mode", I(n, u"wd_safe_l"))

    # ------------------------------------------------------------------
    # СЕТЬ 7. АВАРИЙНЫЙ ОСТАНОВ И РУЧНОЙ СБРОС
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 7. Останов по аварии и ручной сброс (кнопки HMI, режим ШАГ)")
    n.outvar(u"reset_l", I(n, u"GVL_HMI.Btn_Reset"))
    n.outvar(u"run_l", I(n, u"GVL_HMI.Btn_Run"))
    n.outvar(u"stop_l", I(n, u"GVL_HMI.Btn_Stop"))
    n.outvar(u"halt_all", ORL(n, [I(n, u"io_halt_l"), I(n, u"wd_halt_l")]))
    # ШАГ работает по ФРОНТУ: одно нажатие - ровно один такт. Значение step_prev
    # читается ДО его записи (правило 13.5: старые значения читаются раньше).
    n.outvar(u"step_l", AND(n, I(n, u"GVL_HMI.Btn_Step"),
                            NOT(n, I(n, u"step_prev"), fbd_xml.COL_BLK + 200),
                            fbd_xml.COL_BLK + 340))
    # приоритет: авария, СБРОС, СТОП, ПУСК, ШАГ (один такт), затем удержание ШАГа
    cr = I(n, u"GVL_CPM.CPU_Run")
    cr = IF(n, I(n, u"halt_all"), I(n, u"FALSE"), cr, fbd_xml.COL_BLK + 480)
    cr = IF(n, I(n, u"reset_l"), I(n, u"TRUE"), cr, fbd_xml.COL_BLK + 620)
    cr = IF(n, I(n, u"stop_l"), I(n, u"FALSE"), cr, fbd_xml.COL_BLK + 760)
    cr = IF(n, I(n, u"run_l"), I(n, u"TRUE"), cr, fbd_xml.COL_BLK + 900)
    cr = IF(n, I(n, u"step_l"), I(n, u"TRUE"), cr, fbd_xml.COL_BLK + 1040)
    cr = IF(n, I(n, u"step_prev"), I(n, u"FALSE"), cr, fbd_xml.COL_BLK + 1180)
    n.outvar(u"cpu_run_new", cr)
    n.outvar(u"GVL_CPM.CPU_Run", I(n, u"cpu_run_new"))
    n.outvar(u"step_prev", I(n, u"GVL_HMI.Btn_Step"))
    # останов процессора: защёлка HLT и авария снимаются ТОЛЬКО кнопкой СБРОС
    hl = I(n, u"GVL_CPU.Halted")
    hl = IF(n, I(n, u"halt_all"), I(n, u"TRUE"), hl, fbd_xml.COL_BLK + 1320)
    hl = IF(n, I(n, u"reset_l"), I(n, u"FALSE"), hl, fbd_xml.COL_BLK + 1460)
    n.outvar(u"cpu_halt_new", hl)
    n.outvar(u"GVL_CPU.Halted", I(n, u"cpu_halt_new"))
    # код аварии: сброс снимает, тайм-аут watchdog ставит
    er = I(n, u"GVL_IO.Diag.Err_Code")
    # ФАЗА B. КОД АВАРИИ ОТ ДИСПЕТЧЕРА.
    # Выход Err_Code вызова FB_IO_Dispatch защёлкивался в io_errc_l, но в
    # GVL_IO.Diag.Err_Code НИКОГДА не попадал: там были только watchdog и
    # сброс. Поэтому проверка 7 «порт без канала в режиме FAULT -> код 1»
    # всегда видела 0. Ненулевой код диспетчера теперь сохраняется.
    er = IF(n, NE(n, I(n, u"io_errc_l"), I(n, H % 0), fbd_xml.COL_BLK + 1500),
             I(n, u"io_errc_l"), er, fbd_xml.COL_BLK + 1560)
    er = IF(n, I(n, u"wd_timeout_l"), I(n, u"wd_err_l"), er, fbd_xml.COL_BLK + 1600)
    n.outvar(u"err_res", IF(n, I(n, u"reset_l"), I(n, H % 0), er,
                            fbd_xml.COL_BLK + 1740))
    n.outvar(u"GVL_IO.Diag.Err_Code", I(n, u"err_res"))
    n.outvar(u"GVL_HMI.Alarm_Code", I(n, u"err_res"))
    n.outvar(u"GVL_HMI.Alarm_Active", ORL(n, [
        NE(n, I(n, u"err_res"), I(n, H % 0)),
        I(n, u"halt_all")], x0=fbd_xml.COL_BLK + 1880))

    # ------------------------------------------------------------------
    # СЕТЬ 8. ОБНОВЛЕНИЕ HMI
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 8. Обновление переменных HMI (FB_HMI_Update)")
    hm = n.block(u"FB_HMI_Update", [(u"Enable", I(n, u"TRUE"))], [u"Done"],
                 instance=u"hmi")
    n.outvar(u"hmi_done_l", hm.out(u"Done"))
    return p


ALL = (make_plc_prg_io,)
