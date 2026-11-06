# -*- coding: utf-8 -*-
u"""Этап 3.6: ОБЩИЕ ОПРЕДЕЛЕНИЯ аппаратного слоя ввода-вывода.

Этот модуль - единственное место, где заданы:
  * DUT: ST_IoChannel (дескриптор порта), ST_IoDiag (диагностика обмена);
  * GVL: GVL_IO_Map (карта портов и параметры защит), GVL_IO (каналы и шина
    обмена с ядром 8080), GVL_HMI (всё, что нужно визуализации);
  * коды: виды каналов, режимы отсутствующего порта, коды ошибок, коды событий;
  * демонстрационная карта портов (её заливает FB_IO_MapInit);
  * конструкторы элементов FBD (в дополнение к pou_cpm_defs: DIV, LIMIT, XOR,
    преобразования разрядности);
  * помощники правки ГОТОВЫХ схем (patch_block / patch_outvar): ими ядро
    дополняется новыми входами/связями без изменения файлов ядра - тем же
    приёмом, каким этап 3.2 добавил порт доступа CP/M (pou_cpu_cpm.py).

ПРАВИЛА ДИАЛЕКТА (docs/03_ЖУРНАЛ_СБОРКИ.md) соблюдаются здесь так же строго:
  * один выход = ровно одна связь (генератор размножает источники сам);
  * выход вызова FB ЗАЩЁЛКИВАЕТСЯ в переменную POU (latch);
  * порядок сетей = порядок чтения переменных; ссылки только "назад";
  * любой индекс массива ограничивается (LIMIT) - выход за границу массива
    в FBD это авария ПЛК, а не исключение языка.

ОБМЕН IN/OUT ЧЕРЕЗ ОДИН ЛИШНИЙ СКАН (wait state). Аппаратный слой вызывается
ПОСЛЕ процессора (иначе ломается существующий порядок: процессор -> трап ->
диспетчеры). Поэтому команда IN/OUT выполняется в два скана, как на реальной
машине с медленным устройством:

  скан N    : процессор декодирует IN/OUT, выставляет GVL_IO.Req + Port +
              WData + RW и НЕ продвигает PC (wait state);
  скан N    : (ниже по программе) FB_IO_Dispatch выполняет обращение и
              выставляет GVL_IO.Ack (+ RData для IN);
  скан N+1  : процессор видит Ack, для IN кладёт RData в A, продвигает PC на 2.

Такт при этом не теряется: пока идёт ожидание, счётчик тактов и PC не меняются.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou, Src
from pou_cpm_defs import (I, K, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, SEL, IF,
                          ADD, SUB, MUL, SHL, SHR, W2B, MOD, ORL, ANDL, CHAIN,
                          latch, rw, B, H, W, WH, D32, U1)

# ======================================================================
# ВИДЫ КАНАЛОВ (поле Kind дескриптора ST_IoChannel)
# ======================================================================
K_NONE, K_DI, K_DO, K_AI, K_AO, K_CONSOLE = 0, 1, 2, 3, 4, 5

KIND_NAMES = (
    (K_NONE, u"нет канала (порт не назначен)"),
    (K_DI, u"дискретный вход  DI[0..63]"),
    (K_DO, u"дискретный выход DO[0..63]"),
    (K_AI, u"аналоговый вход AI[0..15] (INT -> BYTE)"),
    (K_AO, u"аналоговый выход AO[0..15] (BYTE -> INT)"),
    (K_CONSOLE, u"консоль CP/M (IN - ввод символа, OUT - вывод символа)"),
)

# ======================================================================
# РЕЖИМЫ ОБРАЩЕНИЯ К ПОРТУ БЕЗ КАНАЛА (GVL_IO_Map.MissingPortMode)
# ======================================================================
MODE_STUB, MODE_DIAG, MODE_FAULT = 0, 1, 2

MODE_NAMES = (
    (MODE_STUB, u"STUB: IN вернул FFh, OUT отброшен, счётчик Unmapped_Cnt"),
    (MODE_DIAG, u"DIAG_ONLY: то же, но только запись в журнал событий"),
    (MODE_FAULT, u"FAULT: останов эмулятора, код ошибки E_UNMAPPED_PORT"),
)

# ======================================================================
# КОДЫ ОШИБОК И СОБЫТИЙ
# ======================================================================
E_NONE, E_UNMAPPED_PORT, E_TIMEOUT, E_CHAN_FAULT = 0, 1, 2, 3
E_BAD_KIND, E_RANGE, E_HMI_STOP = 4, 5, 6

ERR_NAMES = (
    (E_NONE, u"нет аварии"),
    (E_UNMAPPED_PORT, u"обращение к порту без канала (режим FAULT)"),
    (E_TIMEOUT, u"watchdog: такт не завершился за Limit_Scans сканов"),
    (E_CHAN_FAULT, u"канал помечен как неисправный (Fault)"),
    (E_BAD_KIND, u"в дескрипторе порта неизвестный вид канала"),
    (E_RANGE, u"аналоговое значение вышло за диапазон шкалы"),
    (E_HMI_STOP, u"останов с HMI (кнопка Стоп) или командой EXIT в CCP"),
)

EV_NONE, EV_UNMAPPED, EV_DIAG, EV_FAULT = 0, 1, 2, 3
EV_WATCHDOG, EV_RANGE, EV_KIND, EV_SAFE = 4, 5, 6, 7
EV_STOP, EV_RESET, EV_CONSOLE = 8, 9, 10

EVENT_NAMES = (
    (EV_NONE, u"нет события"),
    (EV_UNMAPPED, u"порт без канала (STUB: счётчик и событие)"),
    (EV_DIAG, u"порт без канала (DIAG_ONLY: только событие)"),
    (EV_FAULT, u"аварийное обращение к порту"),
    (EV_WATCHDOG, u"watchdog: сработал тайм-аут такта"),
    (EV_RANGE, u"аналог: насыщение по диапазону"),
    (EV_KIND, u"неизвестный вид канала в дескрипторе"),
    (EV_SAFE, u"сброс Tacts_Per_Scan в 1 (безопасный режим)"),
    (EV_STOP, u"останов эмулятора"),
    (EV_RESET, u"ручной сброс с HMI"),
    (EV_CONSOLE, u"обмен с консольным каналом"),
)

# ======================================================================
# РАЗМЕРЫ МАССИВОВ КАНАЛОВ (индексы ВСЕГДА ограничиваются этими числами)
# ======================================================================
DI_MAX, DO_MAX = 63, 63          # DI/DO : ARRAY[0..63]
AI_MAX, AO_MAX = 15, 15          # AI/AO : ARRAY[0..15]
PORT_MAX = 255                   # портов 8080 ровно 256 (BYTE)
EV_LOG_LEN = 32                  # длина журнала событий (кольцевой буфер)
EV_IDX_MAX = 31

# Порт по умолчанию для аналогового полного диапазона шкалы (0..27648 - это
# стандарт аналоговых модулей ОВЕН/WAGO/CODESYS). Меняется в карте портов.
AI_FULL_SCALE = 27648

# Тип адаптера, который вызывает FB_IO_Dispatch. СМЕНА АДАПТЕРА = правка ОДНОЙ
# строки: прикладной код (ядро 8080, трапы, программа) не меняется вообще.
ADAPTER_TYPE = u"FB_IO_Adapter_Sim"

# ======================================================================
# ДЕМОНСТРАЦИОННАЯ КАРТА ПОРТОВ (её заливает FB_IO_MapInit)
#   (порт, Kind, Index, ScaleNum, ScaleDen, Invert, комментарий)
# Порты, которых здесь нет, считаются неназначенными - именно на них
# проверяется политика MissingPortMode (STUB по умолчанию).
# ======================================================================
MAP_DEMO = (
    (0x00, K_DO, 0, 1, 1, False, u"лампа 'Останов'"),
    (0x01, K_DO, 1, 1, 1, False, u"лампа 'Работа'"),
    (0x02, K_DO, 2, 1, 1, False, u"лампа 'Ошибка'"),
    (0x10, K_DI, 0, 1, 1, False, u"тумблер 'Пуск'"),
    (0x11, K_DI, 1, 1, 1, False, u"тумблер 'Стоп'"),
    (0x12, K_DI, 2, 1, 1, False, u"тумблер 'Авария'"),
    (0x13, K_DI, 3, 1, 1, False, u"концевой выключатель"),
    (0x14, K_DI, 4, 1, 1, True, u"кнопка с инверсией (активный ноль)"),
    (0x20, K_AO, 0, 255, AI_FULL_SCALE, False, u"задание частоты (ЦАП 0..27648)"),
    (0x21, K_AO, 1, 255, AI_FULL_SCALE, False, u"задание скорости (ЦАП 0..27648)"),
    (0x28, K_AI, 0, 255, AI_FULL_SCALE, False, u"датчик 0..10 В (0..27648 -> 0..255)"),
    (0x29, K_AI, 1, 255, AI_FULL_SCALE, False, u"датчик 4..20 мА (0..27648 -> 0..255)"),
    (0x2A, K_AI, 2, 200, AI_FULL_SCALE, False, u"температура (0..27648 -> 0..200)"),
    (0x30, K_CONSOLE, 0, 1, 1, False, u"консоль CP/M: IN - ввод, OUT - вывод"),
    (0x31, K_DO, 3, 1, 1, True, u"дискретный выход с инверсией"),
)

# ======================================================================
# ТЕКСТЫ DUT
# ======================================================================
DUT_IOCHANNEL = u"""TYPE ST_IoChannel :
STRUCT
    (* Дескриптор одного порта 8080: чем этот порт является на стороне ПЛК.
       Лежит в GVL_IO_Map.Map[порт], порт 0..255 - ровно размер массива,
       поэтому индекс порта в границах ПО ПОСТРОЕНИЮ (тип BYTE).
       ПОЛЯ (совпадают с планом 04_ПЛАН_CPM.md, раздел 5.1):
         Kind      - 0=нет канала 1=DI 2=DO 3=AI 4=AO 5=консоль;
         Index     - номер канала в массиве DI/DO/AI/AO (0..63 или 0..15);
         ScaleNum  - числитель масштаба аналога: BYTE = INT * Num / Den;
         ScaleDen  - знаменатель масштаба (полная шкала входа, напр. 27648);
         Invert    - инверсия логики канала (активный ноль);
         Fault     - диагностика: канал не отвечает (пишет адаптер/ПЛК).
       Индекс канала ВСЕГДА ограничивается блоком LIMIT перед обращением
       к массиву: ошибка в карте портов не должна ронять ПЛК. *)
    Kind     : BYTE;
    Index    : INT;
    ScaleNum : INT;
    ScaleDen : INT;
    Invert   : BOOL;
    Fault    : BOOL;
END_STRUCT
END_TYPE
"""

DUT_IODIAG = u"""TYPE ST_IoDiag :
STRUCT
    (* Диагностика аппаратного слоя. Считается схемами (FB_IO_Dispatch и
       FB_Watchdog), читается HMI. *)
    Read_Cnt     : UDINT;   (* выполнено команд IN *)
    Write_Cnt    : UDINT;   (* выполнено команд OUT *)
    Unmapped_Cnt : UDINT;   (* обращений к портам без канала (режим STUB) *)
    Diag_Cnt     : UDINT;   (* обращений без канала в режиме DIAG_ONLY *)
    Fault_Cnt    : UDINT;   (* аварийных обращений (FAULT, неисправный канал) *)
    Range_Cnt    : UDINT;   (* аналоговых значений вне диапазона шкалы *)
    Console_Cnt  : UDINT;   (* обменов с консольным каналом (Kind=5) *)
    Event_Cnt    : UDINT;   (* всего записей в журнале событий *)
    Last_Port    : BYTE;    (* порт последнего обращения *)
    Last_Kind    : BYTE;    (* вид канала последнего обращения *)
    Last_Index   : INT;     (* номер канала последнего обращения *)
    Last_Value   : BYTE;    (* последний байт: прочитанный (IN) или записанный (OUT) *)
    Last_RW      : BOOL;    (* TRUE = последнее обращение было OUT *)
    Err_Code     : BYTE;    (* код последней аварии (см. E_* в этом модуле) *)
    Err_Port     : BYTE;    (* порт, на котором произошла авария *)
END_STRUCT
END_TYPE
"""

DUT_ALL = ((u"ST_IoChannel", DUT_IOCHANNEL), (u"ST_IoDiag", DUT_IODIAG))


# ======================================================================
# ТЕКСТ GVL_IO_MAP: КАРТА ПОРТОВ + ПАРАМЕТРЫ ЗАЩИТ
# ======================================================================
def gvl_io_map_text():
    u"""Объявление GVL_IO_Map: карта портов 8080 -> каналы ПЛК и настройки."""
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* КАРТА ПОРТОВ Intel 8080 -> КАНАЛЫ ПЛК (этап 3.6)               *)")
    L.append(u"\t(* Порт 8080 - это байт из команды (IN d8 / OUT d8), поэтому       *)")
    L.append(u"\t(* массив ровно 0..255: индекс порта В ГРАНИЦАХ ПО ПОСТРОЕНИЮ,     *)")
    L.append(u"\t(* ограничивать его не нужно (в отличие от номеров каналов).       *)")
    L.append(u"\t(* Неназначенные порты обрабатываются по MissingPortMode.          *)")
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\tMap : ARRAY[0..%d] OF ST_IoChannel;" % PORT_MAX)
    L.append(u"")
    L.append(u"\t(* ==== ВИДЫ КАНАЛОВ (поле Kind) ==== *)")
    for code, txt in KIND_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"")
    L.append(u"\t(* ==== ПАРАМЕТРЫ НАСТРОЙКИ ЭМУЛЯТОРА И ЗАЩИТ ==== *)")
    L.append(u"\t(* Параметры защит лежат здесь, а не в GVL_CPU: GVL_CPU генерируется  *)")
    L.append(u"\t(* модулем декодера (pou_decode_full.py), который на этапе 3.6 не     *)")
    L.append(u"\t(* меняется. Значения задаёт FB_IO_MapInit на первом скане, дальше    *)")
    L.append(u"\t(* их можно менять из HMI/online - схема их только читает.           *)")
    L.append(u"\tMissingPortMode      : BYTE;  (* что делать с портом без канала *)")
    L.append(u"\tAdapter_Enable       : BOOL;  (* разрешение аппаратного слоя: FALSE -")
    L.append(u"\t                                          устройство не отвечает, такт не")
    L.append(u"\t                                          завершается и watchdog снимает")
    L.append(u"\t                                          эмулятор в аварию E_TIMEOUT *)")
    L.append(u"\tWatchdog_Enable      : BOOL;  (* наблюдение за тактом включено *)")
    L.append(u"\tLimit_Scans          : UDINT; (* предел сканов на ОДИН такт *)")
    L.append(u"\tLimit_Scans_Per_Tact : UDINT; (* предел для контроля Tacts_Per_Scan *)")
    L.append(u"\tTacts_Per_Scan       : WORD;  (* сколько тактов 8080 за скан (в этом ядре 1) *)")
    L.append(u"\tMap_Ready            : BOOL;  (* карта портов инициализирована *)")
    L.append(u"")
    L.append(u"\t(* ==== РЕЖИМЫ ОТСУТСТВУЮЩЕГО ПОРТА (MissingPortMode) ==== *)")
    for code, txt in MODE_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"\t(* Любое другое значение трактуется как STUB (0). *)")
    L.append(u"\t(* ==== ДЕМОНСТРАЦИОННАЯ КАРТА (заливает FB_IO_MapInit) ==== *)")
    for port, kind, idx, num, den, inv, txt in MAP_DEMO:
        L.append(u"\t(* %02Xh : %-9s #%-2d Num=%-5d Den=%-5d Invert=%-5s %s *)"
                 % (port, kind_name(kind), idx, num, den,
                    u"TRUE" if inv else u"FALSE", txt))
    L.append(u"\t(* Остальные порты - без канала: на них работает MissingPortMode. *)")
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


def kind_name(kind):
    for code, txt in KIND_NAMES:
        if code == kind:
            return txt.split(u" ")[0]
    return u"?"


# ======================================================================
# ТЕКСТ GVL_IO: КАНАЛЫ ПЛК, ШИНА ОБМЕНА С ЯДРОМ, СЧЁТЧИКИ, ЖУРНАЛ
# ======================================================================
def gvl_io_text():
    u"""Объявление GVL_IO: каналы, шина IN/OUT, счётчики, журнал событий."""
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* КАНАЛЫ ВВОДА-ВЫВОДА ПЛК (этап 3.6)                             *)")
    L.append(u"\t(* Профиль A (Simulation Device) и профиль B (Control Win/RTE):    *)")
    L.append(u"\t(* каналы живут прямо здесь, их форсируют в online или пишет        *)")
    L.append(u"\t(* прикладная программа. Профиль C (реальный ПЛК): те же имена     *)")
    L.append(u"\t(* связаны с физическими модулями адаптером FB_IO_Adapter_HW.      *)")
    L.append(u"\t(* Дискретный канал в порт даёт ОДИН бит: DI[k] -> бит 0 байта      *)")
    L.append(u"\t(* (остальные биты нули, инверсия - по полю Invert дескриптора).    *)")
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\tDI : ARRAY[0..%d] OF BOOL;   (* дискретные входы *)" % DI_MAX)
    L.append(u"\tDO : ARRAY[0..%d] OF BOOL;   (* дискретные выходы *)" % DO_MAX)
    L.append(u"\tAI : ARRAY[0..%d] OF INT;    (* аналоговые входы (0..27648 и т.п.) *)" % AI_MAX)
    L.append(u"\tAO : ARRAY[0..%d] OF INT;    (* аналоговые выходы *)" % AO_MAX)
    L.append(u"")
    L.append(u"\t(* ==== ШИНА ОБМЕНА ЯДРА 8080 С АППАРАТНЫМ СЛОЕМ (команды IN/OUT) ==== *)")
    L.append(u"\t(* Процессор пишет Req/Port/WData/RW и читает Ack/RData; аппаратный    *)")
    L.append(u"\t(* слой (FB_IO_Dispatch) делает обратное. Обмен занимает ДВА скана:   *)")
    L.append(u"\t(* запрос -> квитанция -> процессор завершает такт (PC := PC + 2).    *)")
    L.append(u"\tReq       : BOOL;  (* запрос: выполнить обращение к порту *)")
    L.append(u"\tRW        : BOOL;  (* TRUE = OUT (вывод), FALSE = IN (ввод) *)")
    L.append(u"\tPort      : BYTE;  (* номер порта 0..255 (байт PC+1 команды) *)")
    L.append(u"\tWData     : BYTE;  (* байт для вывода (регистр A) *)")
    L.append(u"\tRData     : BYTE;  (* байт, прочитанный из порта (пойдёт в A) *)")
    L.append(u"\t(* ТЕСТ: вставить запрос в обход процессора. Процессор      *)")
    L.append(u"\t(* перезаписывает Req каждый скан, поэтому запрос теста      *)")
    L.append(u"\t(* через Req затирался и до диспетчера не доходил.           *)")
    L.append(u"\tInj       : BOOL;  (* запрос от теста (OR с Req) *)")
    L.append(u"\tDbg_Miss  : BOOL;  (* отладка: miss в диспетчере *)")
    L.append(u"\tDbg_RData : BYTE;  (* отладка: RData, который видит тест *)")
    L.append(u"\tDbg_Err   : BYTE;  (* отладка: Err_Code на фазе инъекции *)")
    L.append(u"\tDbg_PC    : WORD;  (* отладка: PC процессора *)")
    L.append(u"\tDbg_A     : BYTE;  (* отладка: A процессора в C9 *)")
    L.append(u"\tDbg_IoW   : UDINT; (* отладка: сканов с io_wait_p *)")
    L.append(u"\tDbg_IoA   : UDINT; (* отладка: сканов с io_ack *)")
    L.append(u"\tDbg_IoD   : UDINT; (* отладка: срабатываний io_done *)")
    L.append(u"\tDbg_IoL   : UDINT; (* отладка: срабатываний io_in_load *)")
    L.append(u"\tDbg_RdL   : BYTE;  (* отладка: байт, загруженный в A по IN *)")
    L.append(u"\tDbg_AL    : BYTE;  (* отладка: Reg_A сразу после IN *)")
    L.append(u"\tDbg_N     : UDINT; (* отладка: счётчик сканов *)")
    L.append(u"\tDbg_SD    : UDINT; (* отладка: скан события io_done *)")
    L.append(u"\tDbg_SR    : UDINT; (* отладка: скан ответа на порт 10h *)")
    L.append(u"\tDbg_ARd   : BYTE;  (* отладка: ad_rdata ответа на порт 10h *)")
    L.append(u"\tDbg_CRd   : BYTE;  (* отладка: ad_rdata на запросе ПРОЦЕССОРА *)")
    L.append(u"\tDbg_CP    : BYTE;  (* отладка: порт запроса ПРОЦЕССОРА *)")
    L.append(u"\tDbg_TB    : BOOL;  (* отладка: Tact_Busy был TRUE *)")
    L.append(u"\tDbg_WdT   : BOOL;  (* отладка: Wd_Timeout срабатывал *)")
    L.append(u"\tDbg_WdE   : BOOL;  (* отладка: Watchdog_Enable был TRUE *)")
    L.append(u"\tDbg_BS    : UDINT; (* отладка: максимум Busy_Scans *)")
    L.append(u"\tDbg_LogOK : BOOL;  (* отладка: символ записан в журнал консоли *)")
    L.append(u"\tDbg_Lim   : UDINT; (* отладка: Limit_Scans в I10 *)")
    L.append(u"\tDbg_Rdy   : UDINT; (* отладка: сканов с ready *)")
    L.append(u"\tDbg_P10   : UDINT; (* отладка: ready и Port=10h *)")
    L.append(u"\tDbg_CH    : UDINT; (* отладка: ready и is_chan *)")
    L.append(u"\tDbg_AD    : UDINT; (* отладка: ad_en *)")
    L.append(u"\tDbg_RDO   : UDINT; (* отладка: rd_ok *)")
    L.append(u"\tDbg_Step  : WORD;  (* отладка: Step_Cnt процессора *)")
    L.append(u"\tDbg_ReqC  : UDINT; (* отладка: сканов с GVL_IO.Req *)")
    L.append(u"\tDbg_AckC  : UDINT; (* отладка: сканов с GVL_IO.Ack *)")
    L.append(u"\tDbg_WaitC : UDINT; (* отладка: сканов с GVL_IO.Wait *)")
    L.append(u"\tDbg_Kind  : BYTE;  (* отладка: kind_l последнего запроса *)")
    L.append(u"\tAck       : BOOL;  (* квитанция аппаратного слоя *)")
    L.append(u"\tWait      : BOOL;  (* процессор ждёт ответа (такт не завершён) *)")
    L.append(u"\tTact_Done : BOOL;  (* такт завершён в этом скане (PC обновлён) *)")
    L.append(u"\tTact_Busy : BOOL;  (* такт начался и НЕ завершён (вход watchdog) *)")
    L.append(u"")
    L.append(u"\t(* ==== ДИАГНОСТИКА (ST_IoDiag: счётчики, последнее обращение, авария) ==== *)")
    L.append(u"\tDiag : ST_IoDiag;")
    # ОТЛАДОЧНЫЕ СЧЁТЧИКИ (фаза B). Обычные переменные, НЕ поля структуры:
    # нужно отличить "диспетчер не исполняется" от "записи в поля структуры
    # глобальной переменной импортёр теряет". Замер дал Diag.Read_Cnt = 0
    # при том, что проверки ввода проходят.
    L.append(u"\tDbg_Ready : UDINT;  (* отладка: сканов с ready=TRUE *)")
    L.append(u"\tDbg_Rd    : UDINT;  (* отладка: срабатываний rd_ok *)")
    L.append(u"\tDbg_Wr    : UDINT;  (* отладка: срабатываний wr_ok *)")
    L.append(u"\tDbg_Req   : UDINT;  (* отладка: сканов с Req=TRUE *)")
    L.append(u"\tDbg_Scan  : UDINT;  (* отладка: сколько раз блок вообще вызван *)")
    L.append(u"\tDbg_Inj   : UDINT;  (* отладка: сканов с inj=TRUE в TEST_IO *)")
    L.append(u"\tDbg_ReqL  : UDINT;  (* отладка: сканов с GVL_IO.Req=TRUE в PLC_PRG_CPM *)")
    L.append(u"")
    L.append(u"\t(* ==== ЖУРНАЛ СОБЫТИЙ (кольцевой буфер по EV_LOG_LEN записей) ==== *)")
    L.append(u"\tEvent_Log : ARRAY[0..%d] OF BYTE;  (* код события, см. EV_* *)" % EV_IDX_MAX)
    L.append(u"\tEvent_Idx : INT;                   (* куда писать следующее событие *)")
    L.append(u"")
    L.append(u"\t(* ==== КОДЫ ОШИБОК (Diag.Err_Code) ==== *)")
    for code, txt in ERR_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"\t(* ==== КОДЫ СОБЫТИЙ (Event_Log) ==== *)")
    for code, txt in EVENT_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


# ======================================================================
# ТЕКСТ GVL_HMI: ВСЁ ДЛЯ ВИЗУАЛИЗАЦИИ
# ======================================================================
def gvl_hmi_text():
    u"""Объявление GVL_HMI: состояние, консоль, кнопки, индикаторы, аварии."""
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* HMI (этап 3.6): переменные для VISU_CPM.                        *)")
    L.append(u"\t(* Сама страница визуализации схемой не рисуется (в ScriptEngine    *)")
    L.append(u"\t(* API визуализации нет) - здесь только переменные, к которым       *)")
    L.append(u"\t(* элементы VISU привязываются вручную (см. отчёт этапа 3.6).       *)")
    L.append(u"\t(* Пишет эти переменные FB_HMI_Update и аварийные сети программы.    *)")
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* ==== СОСТОЯНИЕ ПРОЦЕССОРА 8080 ==== *)")
    cpu = ((u"Cpu_Run", u"BOOL", u"эмулятор работает (GVL_CPM.CPU_Run)"),
           (u"Cpu_Halted", u"BOOL", u"процессор остановлен (HLT или авария)"),
           (u"Cpu_Step", u"WORD", u"номер выполненного такта"),
           (u"Cpu_PC", u"WORD", u"счётчик команд"),
           (u"Cpu_SP", u"WORD", u"указатель стека"),
           (u"Cpu_A", u"BYTE", u"аккумулятор"),
           (u"Cpu_IR", u"BYTE", u"регистр команды"),
           (u"Cpu_PSW", u"BYTE", u"байт состояния (флаги)"),
           (u"Cpu_Trap", u"BOOL", u"трап CP/M обрабатывается"),
           (u"Cpu_Wait", u"BOOL", u"процессор в wait state (ждёт IN/OUT)"))
    for n, t, c in cpu:
        L.append(u"\t%-14s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== КОНСОЛЬ CP/M ==== *)")
    L.append(u"\t(* Con_Buffer - ЗЕРКАЛО GVL_CPM.Con_Log: один байт за скан по кругу,   *)")
    L.append(u"\t(* полное обновление за 256 сканов. Отдельный буфер нужен потому, что  *)")
    L.append(u"\t(* копировать массив целиком в FBD нечем (MEMCPY не проверен).        *)")
    con = ((u"Con_Buffer", u"ARRAY[0..255] OF BYTE", u"зеркало журнала консоли CP/M"),
           (u"Con_Len", u"INT", u"сколько символов выведено (GVL_CPM.Con_Log_Len)"),
           (u"Con_Idx", u"INT", u"индекс зеркалирования (0..255, идёт по кругу)"),
           (u"Key_Char", u"BYTE", u"символ с клавиатуры HMI (ставит VISU)"),
           (u"Key_Ready", u"BOOL", u"символ готов (ставит VISU, снимает эта схема)"),
           (u"Key_Last", u"BYTE", u"последний переданный символ (для HMI)"),
           (u"Key_Cnt", u"UDINT", u"сколько символов передано в CP/M"))
    for n, t, c in con:
        L.append(u"\t%-14s : %-24s (* %s *)" % (n, t + u";", c))
    L.append(u"")
    L.append(u"\t(* ==== КНОПКИ (пишет VISU, читает схема) ==== *)")
    btn = ((u"Btn_Run", u"BOOL", u"ПУСК: снять останов и продолжить"),
           (u"Btn_Stop", u"BOOL", u"СТОП: остановить эмулятор"),
           (u"Btn_Step", u"BOOL", u"ШАГ: выполнить ровно один такт"),
           (u"Btn_Reset", u"BOOL", u"СБРОС: снять аварию и ошибки (единственный способ)"),
           (u"Btn_Enter", u"BOOL", u"ВВОД: послать в консоль символ CR (0Dh)"),
           (u"Btn_Clear_Log", u"BOOL", u"ОЧИСТИТЬ: обнулить буфер консоли HMI"))
    for n, t, c in btn:
        L.append(u"\t%-14s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== ИНДИКАТОРЫ ВВОДА-ВЫВОДА (зеркало GVL_IO.Diag) ==== *)")
    L.append(u"\t(* Сами каналы VISU показывает прямо из GVL_IO.DI/DO/AI/AO. *)")
    io = ((u"Io_Last_Port", u"BYTE", u"порт последнего обращения IN/OUT"),
          (u"Io_Last_Kind", u"BYTE", u"вид канала последнего обращения"),
          (u"Io_Last_Index", u"INT", u"номер канала последнего обращения"),
          (u"Io_Last_Value", u"BYTE", u"последний байт обмена"),
          (u"Io_Last_RW", u"BOOL", u"TRUE = последним был OUT"),
          (u"Io_Read_Cnt", u"UDINT", u"выполнено команд IN"),
          (u"Io_Write_Cnt", u"UDINT", u"выполнено команд OUT"),
          (u"Io_Unmapped_Cnt", u"UDINT", u"обращений к неназначенным портам"),
          (u"Io_Diag_Cnt", u"UDINT", u"обращений без канала в режиме DIAG_ONLY"),
          (u"Io_Fault_Cnt", u"UDINT", u"аварийных обращений"),
          (u"Io_Range_Cnt", u"UDINT", u"аналоговых значений вне диапазона"),
          (u"Io_Console_Cnt", u"UDINT", u"обменов с консольным каналом"),
          (u"Io_Mode", u"BYTE", u"режим отсутствующего порта (0=STUB 1=DIAG 2=FAULT)"),
          (u"Io_Wait", u"BOOL", u"процессор ждёт ответа аппаратного слоя"))
    for n, t, c in io:
        L.append(u"\t%-16s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== АВАРИИ И WATCHDOG ==== *)")
    al = ((u"Alarm_Active", u"BOOL", u"авария активна"),
          (u"Alarm_Code", u"BYTE", u"код аварии E_xx"),
          (u"Alarm_Port", u"BYTE", u"порт, на котором возникла авария"),
          (u"Alarm_Cnt", u"UDINT", u"сколько раз срабатывали аварии"),
          (u"Wd_Timeout", u"BOOL", u"watchdog: тайм-аут такта"),
          (u"Wd_Scan_Cnt", u"UDINT", u"сканов задачи (счётчик, не таймер)"),
          (u"Wd_Busy_Scans", u"UDINT", u"сканов в текущем незавершённом такте"),
          (u"Wd_Snapshot_PC", u"WORD", u"PC на момент аварии"),
          (u"Wd_Snapshot_IR", u"BYTE", u"регистр команды на момент аварии"),
          (u"Wd_Snapshot_PSW", u"BYTE", u"флаги на момент аварии"),
          (u"Wd_Snapshot_Valid", u"BOOL", u"снимок достоверен"),
          (u"Wd_Timeout_Cnt", u"UDINT", u"срабатываний watchdog"),
          (u"Wd_Slow_Cnt", u"UDINT", u"превышений Tacts_Per_Scan (2-й счётчик)"),
          (u"Wd_Safe_Mode", u"BOOL", u"Tacts_Per_Scan сброшен до 1"))
    for n, t, c in al:
        L.append(u"\t%-17s : %-5s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== ЖУРНАЛ СОБЫТИЙ И КОДЫ (для текста аварии на VISU) ==== *)")
    L.append(u"\tEvent_Last  : BYTE;  (* код последнего события *)")
    L.append(u"\tEvent_Idx   : INT;   (* куда писать следующее событие *)")
    L.append(u"\tEvent_Log   : ARRAY[0..%d] OF BYTE;  (* копия журнала GVL_IO *)" % EV_IDX_MAX)
    L.append(u"\tEvent_Cnt   : UDINT; (* всего событий *)")
    L.append(u"")
    L.append(u"\t(* ==== ТЕКСТЫ КОДОВ ДЛЯ VISU (индекс = код) ==== *)")
    L.append(u"\t(* Аварии (Alarm_Code): *)")
    for code, txt in ERR_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"\t(* События (Event_Last, Event_Log): *)")
    for code, txt in EVENT_NAMES:
        L.append(u"\t(* %d = %s *)" % (code, txt))
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


GVL_ALL = ((u"GVL_IO_Map", gvl_io_map_text),
           (u"GVL_IO", gvl_io_text),
           (u"GVL_HMI", gvl_hmi_text))


# ======================================================================
# КОНСТРУКТОРЫ FBD, КОТОРЫХ НЕТ В pou_cpm_defs
# ======================================================================
def DIV(n, a, b, x=None, y=None):
    u"""Деление. Нужно для масштабирования аналога: BYTE = INT * Num / Den."""
    return n.block(u"DIV", [(u"IN1", a), (u"IN2", b)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def XOR(n, a, b, x=None, y=None):
    u"""Исключающее ИЛИ. Нужно для инверсии логики канала (Invert)."""
    return n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def LIMIT(n, mn, v, mx, x=None, y=None):
    u"""Насыщение: LIMIT(MN, IN, MX). MN <= MX - обязательно.

    Применяется ДВАЖДЫ: как ограничитель индекса массива (0..63 / 0..15) и как
    насыщение аналогового значения. Индекс, взятый из дескриптора порта, может
    быть каким угодно - без LIMIT это выход за границу массива и авария ПЛК.
    """
    return n.block(u"LIMIT", [(u"MN", mn), (u"IN", v), (u"MX", mx)], [u"OUT"],
                   fbd_xml.COL_BLK if x is None else x, y)


def B2I(n, a, x=None, y=None):
    u"""BYTE -> INT (для аналоговых вычислений)."""
    return n.block(u"BYTE_TO_INT", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def I2B(n, a, x=None, y=None):
    u"""INT -> BYTE (результат аналогового входа, уже насыщенный)."""
    return n.block(u"INT_TO_BYTE", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def I2D(n, a, x=None, y=None):
    u"""INT -> DINT: шкала 27648 x 255 не влезает в INT, считаем в DINT."""
    return n.block(u"INT_TO_DINT", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def D2I(n, a, x=None, y=None):
    u"""DINT -> INT (после насыщения LIMIT значение заведомо влезает)."""
    return n.block(u"DINT_TO_INT", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def D2B(n, a, x=None, y=None):
    u"""DINT -> BYTE (после насыщения LIMIT(0, x, 255))."""
    return n.block(u"DINT_TO_BYTE", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


def I2U(n, a, x=None, y=None):
    u"""INT -> UDINT (для счётчиков, которые считают в UDINT)."""
    return n.block(u"INT_TO_UDINT", [(u"IN", a)], [u"OUT"], fbd_xml.COL_BLK if x is None else x, y)


# ======================================================================
# ПОМОЩНИКИ ПРАВКИ ГОТОВЫХ СХЕМ (ядро и главная программа не переписываются)
# ======================================================================
def find_block(p, inst):
    u"""Найти элемент вызова экземпляра FB: (сеть, элемент)."""
    for net in p.networks:
        for it in net._items:
            if it[0] == u"block" and p._inst.get(it[1]) == inst:
                return net, it
    raise ValueError(u"не найден вызов экземпляра %s в %s" % (inst, p.name))


def pins(it):
    return dict([(pin, src) for pin, src in it[3]])


def patch_block(p, inst, repl, add_inputs=(), add_outputs=()):
    u"""Заменить источники входов блока-вызова FB, не переписывая POU.

    repl        - {имя вывода: новый Src}
    add_inputs  - [(имя вывода, Src)] - НОВЫЕ входы (объявляются в конце списка)
    add_outputs - [имя вывода]        - НОВЫЕ выходы
    Элемент снимается со своего места и вставляется в конец списка: новые
    элементы-источники оказываются ПЕРЕД ним (ссылки только "назад").
    """
    net, it = find_block(p, inst)
    net._items.remove(it)
    ins = [(pin, repl.get(pin, src)) for pin, src in it[3]]
    ins.extend(list(add_inputs))
    outs = list(it[4]) + list(add_outputs)
    new = (u"block", it[1], it[2], ins, outs, it[5], it[6])
    net._items.append(new)
    return net, new


def find_outvar(p, expr):
    u"""Найти выходную переменную по имени: (сеть, элемент)."""
    for net in p.networks:
        for it in net._items:
            if it[0] == u"outvar" and it[2] == expr:
                return net, it
    raise ValueError(u"не найдена выходная переменная %s в %s" % (expr, p.name))


def _as_src(s):
    u"""Источник связи: Src или номер localId."""
    return s if isinstance(s, Src) else Src(int(s))


def patch_src_block(p, expr, repl):
    u"""Заменить входы блока, который питает выходную переменную expr.

    Нужно там, где у блока с несколькими входами надо поменять ОДИН вход:
    например у счётчика тактов погасить вход G (шаг не считается в wait state).
    Элемент-источник ищется в той же сети по его localId.
    """
    net, it = find_outvar(p, expr)
    eid = _as_src(it[3]).eid
    for item in list(net._items):
        if item[0] == u"block" and item[1] == eid:
            net._items.remove(item)
            ins = [(pin, repl.get(pin, src)) for pin, src in item[3]]
            new = (item[0], item[1], item[2], ins, item[4], item[5], item[6])
            net._items.append(new)
            return net, new
    raise ValueError(u"не найден блок-источник %s в %s" % (expr, p.name))


def patch_outvar(p, expr, src):
    u"""Заменить источник выходной переменной (для счётчиков, шага такта и т.п.)."""
    net, it = find_outvar(p, expr)
    net._items.remove(it)
    net._items.append((u"outvar", it[1], it[2], src, it[4], it[5]))
    return net


def net_of(p, title_part):
    u"""Найти сеть по части заголовка (для вставки новой сети перед ней)."""
    for k, net in enumerate(p.networks):
        if title_part in net.title:
            return k, net
    raise ValueError(u"не найдена сеть с заголовком %s в %s" % (title_part, p.name))


def insert_before(p, title_part, net):
    u"""Вставить готовую сеть перед сетью с указанным заголовком."""
    k, _n = net_of(p, title_part)
    p.networks.remove(net)
    p.networks.insert(k, net)
    return net


def log_event(p, n, gate, code, idx_local=u"ev_i"):
    u"""Записать событие в кольцевой журнал GVL_IO.Event_Log.

    Требует объявленной в POU переменной idx_local : INT (индекс записи).
    Журнал - ДИАГНОСТИКА, а не логика: если он переполнится, индекс идёт по
    кругу, и самые старые события затираются (так и задумано).
    """
    n.outvar(idx_local, MOD(n, I(n, u"GVL_IO.Event_Idx"), I(n, u"INT#32")))
    tgt = u"GVL_IO.Event_Log[%s]" % idx_local
    n.outvar(tgt, IF(n, gate, I(n, code), I(n, tgt)))
    n.outvar(u"GVL_IO.Event_Idx",
             IF(n, gate, ADD(n, I(n, idx_local), I(n, u"INT#1")),
                I(n, u"GVL_IO.Event_Idx")))
    n.outvar(u"GVL_IO.Diag.Event_Cnt",
             IF(n, gate, ADD(n, I(n, u"GVL_IO.Diag.Event_Cnt"), I(n, U1)),
                I(n, u"GVL_IO.Diag.Event_Cnt")))
    return n
