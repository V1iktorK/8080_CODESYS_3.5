# -*- coding: utf-8 -*-
u"""TEST_IO - проверка аппаратного слоя ввода-вывода (FBD, этап 4).

ЧТО ПРОВЕРЯЕТСЯ (план docs/04, раздел 5):
  0. OUT 00h: запись байта в дискретный выход (DO[0] - лампа "Останов");
  1. IN 10h: чтение дискретного входа (DI[0] -> бит 0 байта);
  2. IN 14h: КАНАЛ С ИНВЕРСИЕЙ (активный ноль) - DI[4]=FALSE даёт 01h;
  3. IN 28h: МАСШТАБИРОВАНИЕ АНАЛОГА (AI[0]=27648 -> FFh, шкала 255/27648);
  4. OUT 20h: обратное масштабирование (FFh -> AO[0]=27648);
  5. IN 90h: ПОРТ БЕЗ КАНАЛА в режиме STUB -> FFh;
  6. то же - счётчик Unmapped_Cnt растёт;
  7. порт без канала в режиме FAULT -> код аварии E_UNMAPPED_PORT (1);
  8. РЕАЛЬНЫЙ ПУТЬ ЧЕРЕЗ ПРОЦЕССОР: программа `IN 10h` на ядре 8080 должна
     вернуть в аккумулятор 01h (проверяется wait state: запрос и квитанция
     разнесены по двум сказам);
  9. WATCHDOG: если аппаратный слой выключен, такт не завершается, и
     FB_Watchdog снимает эмулятор в аварию по тайм-ауту.

КАК УСТРОЕН ПРОГОН. Обращение к порту формируется в шине GVL_IO так же, как
его формирует процессор: Req / RW / Port / WData. FB_IO_Dispatch вызывается
программой PLC_PRG_CPM НИЖЕ по скану, поэтому квитанция Ack и байт RData
появляются к следующему скану - схема проверяет их в отдельной фазе.
Это проверяет ВЕСЬ аппаратный слой (карту портов, виды каналов, шкалы,
политику неназначенного порта, счётчики), не требуя второго экземпляра
процессора (второго экземпляра быть не может: декодер FB_CPU8080_FULL пишет
управляющее слово в GVL_CPU без гейта - см. pou_test8080.py).

Процессор на время всего набора I/O остановлен (GVL_CPM.CPU_Run := FALSE),
кроме проверки 8-9, где он нужен; после набора память CP/M пересобирается и
PC переводится на точку входа CCP - система возвращается в рабочее состояние.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, NOT, AND, OR, EQ, GE, GT, LE, LT, SEL, IF, ADD, ORL,
                          ANDL, B, H, W)
import pou_test_defs as TD

# коды видов каналов и режимов (см. pou_io_defs.py)
K_DI, K_DO, K_AI, K_AO, K_CONSOLE = 1, 2, 3, 4, 5
MODE_STUB, MODE_DIAG, MODE_FAULT = 0, 1, 2
E_UNMAPPED_PORT = 1
E_TIMEOUT = 2
AI_FULL = 27648

# ---- фазы ----
(IP_IDLE, IP_PREP,
 IP_I1, IP_C1, IP_I2, IP_C2, IP_I3, IP_C3, IP_I4, IP_C4,
 IP_I5, IP_C5, IP_I6, IP_C6, IP_I7, IP_C7,
 IP_PREP8, IP_I8, IP_C8,
 IP_PREP9, IP_I9, IP_W9, IP_C9,
 IP_PREP10, IP_I10, IP_W10, IP_C10,
 IP_FIN, IP_HAND, IP_DONE) = range(30)

WD_WAIT = 60        # сколько сканов ждём срабатывания watchdog
SAFE_PC = 0x0300
CCP_ENTRY = 0x0F100
STACK_TOP = 0x0F200
CODE = 0x0200

LOCALS = [
    (u"ph", u"BYTE", u"фаза набора ввода-вывода"),
    (u"sc", u"INT", u"счётчик сканов фазы"),
    (u"sc0", u"INT", u"сканов с начала набора (для сброса трапа)"),
    (u"sc2", u"INT", u"сканов в текущей фазе (фаза держится 2 скана)"),
    (u"ph_prev", u"BYTE", u"фаза на предыдущем скане"),
    (u"own", u"BOOL", u"схема владеет эмулятором"),
    (u"go", u"BOOL", u"набор I/O активен (Mode = 3)"),
    (u"inj", u"BOOL", u"фаза формирования запроса к порту"),
    (u"chk", u"BOOL", u"фаза проверки результата"),
    (u"port", u"BYTE", u"номер порта запроса"),
    (u"rw", u"BOOL", u"TRUE = вывод (OUT)"),
    (u"wdata", u"BYTE", u"байт вывода"),
    (u"exp", u"BYTE", u"ожидаемый прочитанный байт"),
    (u"unm0", u"UDINT", u"Unmapped_Cnt до проверки 6"),
    (u"dia0", u"UDINT", u"Diag_Cnt до проверки 7"),
    (u"ok0", u"BOOL", u"OUT 00h -> DO[0]"),
    (u"ok1", u"BOOL", u"IN 10h -> 01h"),
    (u"ok2", u"BOOL", u"IN 14h (инверсия) -> 01h"),
    (u"ok3", u"BOOL", u"IN 28h (аналог) -> FFh"),
    (u"ok4", u"BOOL", u"OUT 20h -> AO[0] = 27648"),
    (u"ok5", u"BOOL", u"IN 90h (нет канала, STUB) -> FFh"),
    (u"ok6", u"BOOL", u"Unmapped_Cnt вырос"),
    (u"ok7", u"BOOL", u"FAULT: код аварии E_UNMAPPED_PORT"),
    (u"ok8", u"BOOL", u"IN 10h через процессор -> A = 01h"),
    (u"ok9", u"BOOL", u"watchdog: тайм-аут такта"),
    (u"pass_n", u"INT", u"PASS в наборе I/O"),
    (u"fail_n", u"INT", u"FAIL в наборе I/O"),
]
for _i in range(30):
    LOCALS.append((u"f%d" % _i, u"BOOL", u"фаза %d" % _i))

# фазы -> признак (для читаемости схемы)
PHASE_NAMES = ((0, IP_IDLE), (1, IP_PREP), (2, IP_I1), (3, IP_C1), (4, IP_I2),
               (5, IP_C2), (6, IP_I3), (7, IP_C3), (8, IP_I4), (9, IP_C4),
               (10, IP_I5), (11, IP_C5), (12, IP_I6), (13, IP_C6), (14, IP_I7),
               (15, IP_C7), (16, IP_PREP8), (17, IP_I8), (18, IP_C8),
               (19, IP_PREP9), (20, IP_I9), (21, IP_W9), (22, IP_C9),
               (23, IP_PREP10), (24, IP_I10), (25, IP_W10), (26, IP_C10),
               (27, IP_FIN), (28, IP_HAND), (29, IP_DONE))


def _one(n, code, x, y=None):
    return EQ(n, I(n, u"ph"), I(n, B % code), x=x, y=y)


def _any(n, codes, x0, y=None):
    items = []
    for k, c in enumerate(codes):
        items.append(_one(n, c, x0 + 130 * k, y))
    return ORL(n, items, x0=x0 + 130 * len(codes), y=y)


def make_test_io():
    p = Pou(u"TEST_IO", u"program",
            doc=u"Проверка аппаратного слоя ввода-вывода (этап 4).\n"
                u"\tЗапрос к порту формируется в шине GVL_IO (Req/RW/Port/WData)\n"
                u"\tтак же, как его формирует процессор; FB_IO_Dispatch выполняется\n"
                u"\tНИЖЕ по скану, поэтому результат проверяется на следующем скане.\n"
                u"\tПроверяются: дискретный вход/выход, инверсия канала, шкала\n"
                u"\tаналога в обе стороны, порт без канала (STUB и FAULT),\n"
                u"\tреальный путь IN через ядро 8080 и срабатывание watchdog.\n"
                u"\tРезультат каждой проверки - BOOL в GVL_TEST.Io_Res[0..9].")
    for nm, t, c in LOCALS:
        p.var(nm, t, c)

    # ------------------------------------------------------------------
    # СЕТЬ 1. ПРИЗНАКИ ФАЗ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 1. Признаки фаз набора ввода-вывода")
    for k, (idx, code) in enumerate(PHASE_NAMES):
        # ВАЖНО: первый элемент пары PHASE_NAMES - НОМЕР фазы (0..29), а не имя
        # переменной. Раньше сюда попадал индекс, и схема писала результат в
        # числовой литерал: CODESYS выдавал
        #   C18: '26' не является корректным объектом присваивания  (30 штук),
        # плюс каскад C32 и C0 EN/ENO. Переменные называются f0..f29.
        n.outvar(u"f%d" % idx, _one(n, code, fbd_xml.COL_BLK + 130 * (k % 8), 40 + 30 * k))
    # ФАЗА B. В I9 ЗАПРОС ВЫДАЁТ ПРОЦЕССОР, а не тест.
    # В этой фазе проверяется команда IN 10h через ядро. Если тест в тот же
    # момент инжектирует свой запрос, диспетчер отвечает квитанцией на
    # него, и процессор завершает такт по «чужой» квитанции с чужим RData
    # (замер: тактов 248, запросов 3, квитанций 38, а A=0 вместо 1).
    n.outvar(u"inj", _any(n, (IP_I1, IP_I2, IP_I3, IP_I4, IP_I5, IP_I6, IP_I7,
                              IP_I8), fbd_xml.COL_BLK + 1200, 400))
    n.outvar(u"chk", _any(n, (IP_C1, IP_C2, IP_C3, IP_C4, IP_C5, IP_C6, IP_C7,
                              IP_C8, IP_C9, IP_C10), fbd_xml.COL_BLK + 1200, 430))
    n.outvar(u"own", AND(n, EQ(n, I(n, u"GVL_TEST.Mode"), I(n, B % 3),
                              fbd_xml.COL_BLK + 3000),
                         NOT(n, I(n, u"f29"), fbd_xml.COL_BLK + 3130),
                         fbd_xml.COL_BLK + 3260))
    n.outvar(u"go", ANDL(n, [
        EQ(n, I(n, u"GVL_TEST.Mode"), I(n, B % 3), fbd_xml.COL_BLK + 3390),
        I(n, u"GVL_TEST.Run"),
        NOT(n, I(n, u"GVL_TEST.DoneIo"), fbd_xml.COL_BLK + 3650)],
        x0=fbd_xml.COL_BLK + 3780))

    # ------------------------------------------------------------------
    # СЕТЬ 2. ПАРАМЕТРЫ ЗАПРОСА ПО ФАЗЕ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 2. Порт, направление и байт запроса по фазе")
    n.outvar(u"port", _sel_chain(n, ((IP_I1, 0x00), (IP_I2, 0x10), (IP_I3, 0x14),
                                     (IP_I4, 0x28), (IP_I5, 0x20), (IP_I6, 0x90),
                                     (IP_I7, 0x90), (IP_I8, 0x90), (IP_I9, 0x10),
                                     (IP_I10, 0x10)), u"BYTE#0"))
    n.outvar(u"rw", _sel_chain_b(n, ((IP_I1, True), (IP_I2, False), (IP_I3, False),
                                     (IP_I4, False), (IP_I5, True), (IP_I6, False),
                                     (IP_I7, False), (IP_I8, False),
                                     (IP_I9, False), (IP_I10, False))))
    n.outvar(u"wdata", _sel_chain(n, ((IP_I1, 0x01), (IP_I5, 0xFF),
                                      (IP_I9, 0x00), (IP_I10, 0x00)), u"BYTE#0"))
    # ОЖИДАНИЕ УДЕРЖИВАЕТСЯ: раньше exp считался только по фазам инъекции,
    # а в фазах проверки (C2/C3) цепочка давала 0 - и проверки 1-3
    # сравнивали правильный байт с нулём (замер: RData = 1, exp = 0).
    n.outvar(u"exp",
             IF(n, I(n, u"inj"),
                _sel_chain(n, ((IP_I2, 0x01), (IP_I3, 0x01),
                             (IP_I4, 0xFF), (IP_I6, 0xFF), (IP_I7, 0xFF)),
                           u"BYTE#0", fbd_xml.COL_BLK + 200),
                I(n, u"exp"), fbd_xml.COL_BLK + 420))

    # ------------------------------------------------------------------
    # СЕТЬ 3. ПРЕДУСТАНОВКИ: КАНАЛЫ И КАРТА ПОРТОВ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 3. Предустановки каналов: DI, AI, режим неназначенного порта")
    n.outvar(u"GVL_IO.DI[0]", IF(n, _one(n, IP_PREP, fbd_xml.COL_BLK + 200),
                                 I(n, u"TRUE"), I(n, u"GVL_IO.DI[0]"),
                                 fbd_xml.COL_BLK + 330))
    n.outvar(u"GVL_IO.DI[4]", IF(n, _one(n, IP_PREP, fbd_xml.COL_BLK + 460),
                                 I(n, u"FALSE"), I(n, u"GVL_IO.DI[4]"),
                                 fbd_xml.COL_BLK + 590))
    n.outvar(u"GVL_IO.AI[0]", IF(n, _one(n, IP_PREP, fbd_xml.COL_BLK + 720),
                                 I(n, u"INT#%d" % AI_FULL), I(n, u"GVL_IO.AI[0]"),
                                 fbd_xml.COL_BLK + 850))
    n.outvar(u"GVL_IO_Map.MissingPortMode",
             # ВНИМАНИЕ: режим FAULT нужен НА ФАЗЕ ИНЪЕКЦИИ неназначенного
             # порта. Проверка 7 ловит Err_Code в C7, а инъекция порта 90h
             # идёт в I7. Раньше FAULT включался только в PREP9 (позже
             # проверки), поэтому код аварии не мог быть замечен.
             _sel_chain_src(n, ((IP_PREP, MODE_STUB), (IP_PREP8, MODE_FAULT),
                                (IP_PREP9, MODE_STUB),
                                (IP_PREP10, MODE_STUB)),
                           I(n, u"GVL_IO_Map.MissingPortMode"),
                           fbd_xml.COL_BLK + 980))
    n.outvar(u"GVL_IO_Map.Adapter_Enable",
             _sel_chain_b2(n, ((IP_PREP, True), (IP_PREP10, False),
                               (IP_FIN, True)),
                           I(n, u"GVL_IO_Map.Adapter_Enable"), fbd_xml.COL_BLK + 1110))
    n.outvar(u"GVL_IO_Map.Watchdog_Enable",
             _sel_chain_b2(n, ((IP_PREP, False), (IP_PREP10, True),
                               (IP_FIN, False)),
                           I(n, u"FALSE"), fbd_xml.COL_BLK + 1240))
    # ФАЗА B. Предел watchdog ДОЛЖЕН быть меньше реального числа сканов
    # занятости, иначе срабатывания не будет по определению. Замер:
    # Busy_Scans доходит до 5, а предел оставался 100 (запись цепочкой
    # не применялась - карту портов заливает FB_IO_MapInit).
    # Поэтому в фазах проверки 9 предел задаётся ПРЯМО и равен 3.
    n.outvar(u"GVL_IO_Map.Limit_Scans",
             IF(n, AND(n, GE(n, I(n, u"ph"), I(n, B % IP_PREP10),
                            fbd_xml.COL_BLK + 1300),
                       LE(n, I(n, u"ph"), I(n, B % IP_C10),
                          fbd_xml.COL_BLK + 1340),
                       fbd_xml.COL_BLK + 1360),
                I(n, u"UDINT#3"),
                _sel_chain_w(n, ((IP_PREP10, 3), (IP_FIN, 100)),
                             I(n, u"UDINT#100"), fbd_xml.COL_BLK + 1370),
                fbd_xml.COL_BLK + 1400))

    # ------------------------------------------------------------------
    # СЕТЬ 4. ЗАПРОС К ПОРТУ (шина GVL_IO)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 4. Запрос к порту: шина GVL_IO (как её формирует процессор)")
    n.outvar(u"GVL_IO.Port", IF(n, I(n, u"inj"), I(n, u"port"), I(n, u"GVL_IO.Port"),
                                fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO.RW", IF(n, I(n, u"inj"), I(n, u"rw"), I(n, u"GVL_IO.RW"),
                              fbd_xml.COL_BLK + 330))
    n.outvar(u"GVL_IO.WData", IF(n, I(n, u"inj"), I(n, u"wdata"),
                                 I(n, u"GVL_IO.WData"), fbd_xml.COL_BLK + 460))
    n.outvar(u"GVL_IO.Dbg_Inj",
             IF(n, I(n, u"inj"),
                ADD(n, I(n, u"GVL_IO.Dbg_Inj"), I(n, u"UDINT#1"),
                    fbd_xml.COL_BLK + 900),
                I(n, u"GVL_IO.Dbg_Inj"),
                fbd_xml.COL_BLK + 1030))
    n.outvar(u"GVL_IO.Inj", AND3(n, I(n, u"inj"),
                                 NOT(n, I(n, u"f24"), fbd_xml.COL_BLK + 590),
                                 NOT(n, I(n, u"f25"), fbd_xml.COL_BLK + 720),
                                 fbd_xml.COL_BLK + 850))

    # ------------------------------------------------------------------
    # СЕТЬ 5. ЗАХВАТ БАЗОВЫХ ЗНАЧЕНИЙ СЧЁТЧИКОВ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 5. Захват счётчиков перед проверками 6 и 7")
    n.outvar(u"unm0", IF(n, _one(n, IP_I6, fbd_xml.COL_BLK + 200),
                         I(n, u"GVL_IO.Diag.Unmapped_Cnt"), I(n, u"unm0"),
                         fbd_xml.COL_BLK + 330))
    n.outvar(u"dia0", IF(n, _one(n, IP_PREP8, fbd_xml.COL_BLK + 460),
                         I(n, u"GVL_IO.Diag.Diag_Cnt"), I(n, u"dia0"),
                         fbd_xml.COL_BLK + 590))

    # ------------------------------------------------------------------
    # СЕТЬ 6. ПРОВЕРКИ 0-7 (прямое обращение к шине)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 6. Проверки 0-7: каналы, инверсия, шкала, порт без канала")
    n.outvar(u"ok0", IF(n, _one(n, IP_C1, fbd_xml.COL_BLK + 200),
                        I(n, u"GVL_IO.DO[0]"), I(n, u"ok0"), fbd_xml.COL_BLK + 330))
    # ЗАМЕР: фактический байт ответа в фазах проверок 1-3.
    n.outvar(u"GVL_IO.Dbg_AL",
             IF(n, ORL(n, [_one(n, IP_C2, fbd_xml.COL_BLK + 300),
                            _one(n, IP_C3, fbd_xml.COL_BLK + 320)],
                         x0=fbd_xml.COL_BLK + 340),
                I(n, u"GVL_IO.RData"), I(n, u"GVL_IO.Dbg_AL"),
                fbd_xml.COL_BLK + 360))
    n.outvar(u"ok1", IF(n, _one(n, IP_C2, fbd_xml.COL_BLK + 460),
                        EQ(n, I(n, u"GVL_IO.RData"), I(n, u"exp"),
                           fbd_xml.COL_BLK + 590), I(n, u"ok1"), fbd_xml.COL_BLK + 720))
    n.outvar(u"ok2", IF(n, _one(n, IP_C3, fbd_xml.COL_BLK + 850),
                        EQ(n, I(n, u"GVL_IO.RData"), I(n, u"exp"),
                           fbd_xml.COL_BLK + 980), I(n, u"ok2"), fbd_xml.COL_BLK + 1110))
    n.outvar(u"ok3", IF(n, _one(n, IP_C4, fbd_xml.COL_BLK + 1240),
                        EQ(n, I(n, u"GVL_IO.RData"), I(n, u"exp"),
                           fbd_xml.COL_BLK + 1370), I(n, u"ok3"), fbd_xml.COL_BLK + 1500))
    n.outvar(u"ok4", IF(n, _one(n, IP_C5, fbd_xml.COL_BLK + 1630),
                        EQ(n, I(n, u"GVL_IO.AO[0]"), I(n, u"INT#%d" % AI_FULL),
                           fbd_xml.COL_BLK + 1760), I(n, u"ok4"), fbd_xml.COL_BLK + 1890))
    # ЗАЩЁЛКА БАЙТА И КОДА ОТВЕТА НА ФАЗЕ ИНЪЕКЦИИ.
    # Диспетчер обнуляет RData и Err_Code в сканах без запроса, а
    # обрабатывает запрос на СЛЕДУЮЩЕМ скане после выставления Inj.
    # Поэтому проверять их на фазе C (через фазу) нельзя: там уже 0.
    # Копим последнее значение, увиденное во время инъекции.
    n.outvar(u"GVL_IO.Dbg_RData",
             IF(n, I(n, u"inj"), I(n, u"GVL_IO.RData"),
                I(n, u"GVL_IO.Dbg_RData"), fbd_xml.COL_BLK + 1900))
    n.outvar(u"GVL_IO.Dbg_Err",
             IF(n, I(n, u"inj"), I(n, u"GVL_IO.Diag.Err_Code"),
                I(n, u"GVL_IO.Dbg_Err"), fbd_xml.COL_BLK + 1960))
    n.outvar(u"ok5", IF(n, _one(n, IP_C6, fbd_xml.COL_BLK + 2020),
                        EQ(n, I(n, u"GVL_IO.Dbg_RData"), I(n, u"BYTE#16#FF"),
                           fbd_xml.COL_BLK + 2150), I(n, u"ok5"), fbd_xml.COL_BLK + 2280))
    n.outvar(u"ok6", IF(n, _one(n, IP_C6, fbd_xml.COL_BLK + 2410),
                        GT(n, I(n, u"GVL_IO.Diag.Unmapped_Cnt"), I(n, u"unm0"),
                           fbd_xml.COL_BLK + 2540), I(n, u"ok6"), fbd_xml.COL_BLK + 2670))
    # ПРОВЕРКА 7 ЛОВИТСЯ В C8, А НЕ В C7: режим FAULT включается в PREP8,
    # то есть ПОСЛЕ C7, а неназначенный порт 90h инжектируется в I8.
    n.outvar(u"ok7", IF(n, _one(n, IP_C8, fbd_xml.COL_BLK + 2800),
                        EQ(n, I(n, u"GVL_IO.Dbg_Err"),
                           I(n, u"BYTE#%d" % E_UNMAPPED_PORT), fbd_xml.COL_BLK + 2930),
                        I(n, u"ok7"), fbd_xml.COL_BLK + 3060))

    # ------------------------------------------------------------------
    # СЕТЬ 7. ПРОЦЕССОР НА ВРЕМЯ НАБОРА I/O
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 7. Процессор: останов на время набора, включение для проверок 8-9")
    n.outvar(u"GVL_CPM.CPU_Run",
             IF(n, I(n, u"own"),
                # ФАЗА B. ПРОЦЕССОР РАБОТАЕТ ТОЛЬКО В ФАЗЕ ИНЪЕКЦИИ.
                # Раньше он был включён и в W9, поэтому после команды
                # IN 10h (2 байта по адресу 0200h) продолжал исполнять
                # содержимое памяти за командой и портил A до проверки.
                # Замер: тактов 249, запросов 3, квитанций 38 - процессор
                # работал, а A не равнялся 1. Инъекция I9 длится 4 скана,
                # обмену нужно 2-3 - этого достаточно.
                # ровно ТРИ скана: запрос, квитанция, загрузка A. В четвёртом
                # скане процессор уже выбирал бы следующую команду (мусор за
                # концом программы) и портил A до проверки (замер: A=0).
                # ФАЗА B. Сначала СКАН НА УСТАНОВКУ КОНВЕЙЕРА: замер показал,
                # что в первом же скане фазы процессор выдавал запрос с
                # Port = 0 (операнд команды DB 10h ещё не дошёл до цепи
                # выборки, у промежуточных величин задержка в скан).
                # Теперь процессор включается со ВТОРОГО скана фазы.
                ORL(n, [
                    # проверка 8: три скана - запрос, квитанция, загрузка A
                    AND(n, AND(n, _one(n, IP_I9, fbd_xml.COL_BLK + 200),
                               GE(n, I(n, u"sc2"), I(n, u"INT#2"),
                                  fbd_xml.COL_BLK + 230),
                               fbd_xml.COL_BLK + 260),
                        LE(n, I(n, u"sc2"), I(n, u"INT#4"),
                           fbd_xml.COL_BLK + 290),
                        fbd_xml.COL_BLK + 320),
                    # проверка 9 (watchdog): адаптер выключен (PREP10),
                    # такт не завершается - watchdog даёт тайм-аут
                    # ДИАПАЗОНОМ, а не двумя флагами: у флагов фаз есть
                    # задержка в скан, и на переходе I10 -> W10 признак
                    # занятости прерывался, а счётчик watchdog от этого
                    # обнуляется (внутри: c0 = busy ? Busy_Scans : 0).
                    AND(n, GE(n, I(n, u"ph"), I(n, B % IP_I10),
                           fbd_xml.COL_BLK + 330),
                        LE(n, I(n, u"ph"), I(n, B % IP_W10),
                           fbd_xml.COL_BLK + 345),
                        fbd_xml.COL_BLK + 360)],
                    x0=fbd_xml.COL_BLK + 390),
                I(n, u"GVL_CPM.CPU_Run"), fbd_xml.COL_BLK + 590))
    # РАЗРЕШЕНИЕ ПРОЦЕССОРУ НА ВРЕМЯ ПРОВЕРОК 8-9.
    # cpu_en = CPU_Run AND CPU_Enable, а CPU_Enable выставляет ловушка CP/M
    # как «фаза WORK». После набора CP/M ловушка остаётся в другой фазе, и
    # процессор не исполняет ни одного такта - поэтому IN 10h не доходил
    # до A (проверка 8). Тест пишет признак ПОСЛЕ ловушки в том же скане,
    # а блок процессора читает его со следующего скана.
    # ЗАМЕРОЧНЫЕ ЗАЩЁЛКИ ДЛЯ ПРОВЕРКИ 8 (путь IN через процессор).
    n.outvar(u"GVL_IO.Dbg_AL",
             IF(n, _one(n, IP_C9, fbd_xml.COL_BLK + 150),
                I(n, u"GVL_CPM.Reg_A"), I(n, u"GVL_IO.Dbg_AL"),
                fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO.Dbg_A",
             IF(n, _one(n, IP_C9, fbd_xml.COL_BLK + 250),
                I(n, u"GVL_CPM.Reg_A"), I(n, u"GVL_IO.Dbg_A"),
                fbd_xml.COL_BLK + 310))
    # ЗАМЕР WATCHDOG (проверка 9): фиксируем, БЫЛ ЛИ признак занятости
    # такта и срабатывал ли тайм-аут за весь прогон набора.
    # МАКСИМУМ счётчика занятости и предел на фазе I10 (для проверки 9).
    n.outvar(u"GVL_IO.Dbg_BS",
             IF(n, GT(n, I(n, u"GVL_HMI.Wd_Busy_Scans"),
                       I(n, u"GVL_IO.Dbg_BS"), fbd_xml.COL_BLK + 60),
                I(n, u"GVL_HMI.Wd_Busy_Scans"), I(n, u"GVL_IO.Dbg_BS"),
                fbd_xml.COL_BLK + 90))
    n.outvar(u"GVL_IO.Dbg_Lim",
             IF(n, _one(n, IP_I10, fbd_xml.COL_BLK + 30),
                I(n, u"GVL_IO_Map.Limit_Scans"), I(n, u"GVL_IO.Dbg_Lim"),
                fbd_xml.COL_BLK + 45))
    n.outvar(u"GVL_IO.Dbg_TB", IF(n, I(n, u"GVL_IO.Tact_Busy"),
                                  I(n, u"TRUE"), I(n, u"GVL_IO.Dbg_TB"),
                                  fbd_xml.COL_BLK + 100))
    n.outvar(u"GVL_IO.Dbg_WdT", IF(n, I(n, u"GVL_HMI.Wd_Timeout"),
                                    I(n, u"TRUE"), I(n, u"GVL_IO.Dbg_WdT"),
                                    fbd_xml.COL_BLK + 150))
    n.outvar(u"GVL_IO.Dbg_WdE", IF(n, I(n, u"GVL_IO_Map.Watchdog_Enable"),
                                    I(n, u"TRUE"), I(n, u"GVL_IO.Dbg_WdE"),
                                    fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO.Dbg_Step", I(n, u"GVL_CPU.Step_Cnt"))
    for _nm, _g in ((u"GVL_IO.Dbg_ReqC", u"GVL_IO.Req"),
                    (u"GVL_IO.Dbg_AckC", u"GVL_IO.Ack"),
                    (u"GVL_IO.Dbg_WaitC", u"GVL_IO.Wait")):
        n.outvar(_nm, IF(n, I(n, _g),
                         ADD(n, I(n, _nm), I(n, u"UDINT#1"),
                             fbd_xml.COL_BLK + 400),
                         I(n, _nm), fbd_xml.COL_BLK + 530))
    n.outvar(u"GVL_CPM.CPU_Enable",
             IF(n, I(n, u"own"), I(n, u"TRUE"), I(n, u"GVL_CPM.CPU_Enable"),
                fbd_xml.COL_BLK + 650))
    n.outvar(u"GVL_CPU.Halted",
             IF(n, I(n, u"own"), I(n, u"FALSE"), I(n, u"GVL_CPU.Halted"),
                fbd_xml.COL_BLK + 720))
    # код проверки 8 и 9: IN 10h (DBh 10h) по адресу 0200h
    n.outvar(u"GVL_MEM.Memory[%d]" % CODE,
             IF(n, _pc_prep(n, fbd_xml.COL_BLK + 850),
                I(n, u"BYTE#16#DB"), I(n, u"GVL_MEM.Memory[%d]" % CODE),
                fbd_xml.COL_BLK + 980))
    n.outvar(u"GVL_MEM.Memory[%d]" % (CODE + 1),
             IF(n, _pc_prep(n, fbd_xml.COL_BLK + 1110),
                I(n, u"BYTE#16#10"), I(n, u"GVL_MEM.Memory[%d]" % (CODE + 1)),
                fbd_xml.COL_BLK + 1240))
    # PC := 0200h через порт CP/M (стробы записи - фазы подготовки 9 и 10)
    n.outvar(u"GVL_CPM.CPM_WE", IF(n, _pc_prep(n, fbd_xml.COL_BLK + 1370),
                                   I(n, u"TRUE"), I(n, u"GVL_CPM.CPM_WE"),
                                   fbd_xml.COL_BLK + 1500))
    n.outvar(u"GVL_CPM.CPM_LD1", IF(n, _pc_prep(n, fbd_xml.COL_BLK + 1630),
                                    I(n, u"TRUE"), I(n, u"GVL_CPM.CPM_LD1"),
                                    fbd_xml.COL_BLK + 1760))
    n.outvar(u"GVL_CPM.CPM_Sel1", IF(n, _pc_prep(n, fbd_xml.COL_BLK + 1890),
                                     I(n, B % 7), I(n, u"GVL_CPM.CPM_Sel1"),
                                     fbd_xml.COL_BLK + 2020))
    n.outvar(u"GVL_CPM.CPM_Data1", IF(n, _pc_prep(n, fbd_xml.COL_BLK + 2150),
                                      I(n, W % CODE), I(n, u"GVL_CPM.CPM_Data1"),
                                      fbd_xml.COL_BLK + 2280))

    # ------------------------------------------------------------------
    # СЕТЬ 8. ПРОВЕРКИ 8 И 9
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 8. Проверки 8 и 9: IN через процессор и watchdog")
    n.outvar(u"ok8", IF(n, _one(n, IP_C9, fbd_xml.COL_BLK + 200),
                        EQ(n, I(n, u"GVL_CPM.Reg_A"), I(n, u"BYTE#1"),
                           fbd_xml.COL_BLK + 330), I(n, u"ok8"), fbd_xml.COL_BLK + 460))
    n.outvar(u"ok9", IF(n, _one(n, IP_C10, fbd_xml.COL_BLK + 590),
                        I(n, u"GVL_HMI.Wd_Timeout"), I(n, u"ok9"),
                        fbd_xml.COL_BLK + 720))
    n.outvar(u"GVL_HMI.Btn_Reset", IF(n, _one(n, IP_FIN, fbd_xml.COL_BLK + 850),
                                      I(n, u"TRUE"), I(n, u"FALSE"),
                                      fbd_xml.COL_BLK + 980))

    # ------------------------------------------------------------------
    # СЕТЬ 9. ЗАПИСЬ РЕЗУЛЬТАТОВ И ИТОГИ
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 9. Результаты проверок I/O и итоги набора")
    for k in range(10):
        n.outvar(u"GVL_TEST.Io_Res[%d]" % k, I(n, u"ok%d" % k),
                 x=fbd_xml.COL_BLK + 130 * k)
    n.outvar(u"Io_Wd_Prev" if False else u"GVL_TEST.Io_Wd_Hit",
             OR(n, I(n, u"GVL_TEST.Io_Wd_Hit"),
                AND(n, _one(n, IP_C10, fbd_xml.COL_BLK + 1400),
                    I(n, u"ok9"), fbd_xml.COL_BLK + 1530), fbd_xml.COL_BLK + 1660))
    n.outvar(u"pass_n", _sum_true(n, [u"ok%d" % k for k in range(10)],
                                  x0=fbd_xml.COL_BLK + 1800))
    n.outvar(u"fail_n", n.block(u"SUB", [(u"IN1", I(n, u"INT#10")),
                                         (u"IN2", I(n, u"pass_n"))], [u"OUT"],
                                fbd_xml.COL_BLK + 3100))
    n.outvar(u"GVL_TEST.Io_Pass", IF(n, I(n, u"f29"), I(n, u"pass_n"),
                                     I(n, u"GVL_TEST.Io_Pass"),
                                     fbd_xml.COL_BLK + 3230))
    n.outvar(u"GVL_TEST.Io_Fail", IF(n, I(n, u"f29"), I(n, u"fail_n"),
                                     I(n, u"GVL_TEST.Io_Fail"),
                                     fbd_xml.COL_BLK + 3360))
    n.outvar(u"GVL_TEST.DoneIo", OR(n, I(n, u"GVL_TEST.DoneIo"),
                                    I(n, u"f29"), fbd_xml.COL_BLK + 3490))
    n.outvar(u"GVL_TEST.Io_Step", I(n, u"ph"))
    # ФАЗА B: Mode := 0 (возврат в CP/M) только если ЭТОТ набор реально работал
    # (Mode = 3). Без гейта набор проскакивал фазы в самом начале и уводил
    # систему в CP/M, так и не дав отработать набору 8080.
    n.outvar(u"GVL_TEST.Mode",
             IF(n, AND(n, I(n, u"f29"), I(n, u"own"), fbd_xml.COL_BLK + 3560),
                I(n, B % 0), I(n, u"GVL_TEST.Mode"), fbd_xml.COL_BLK + 3690))

    # ------------------------------------------------------------------
    # СЕТЬ 10. ВОЗВРАТ СИСТЕМЫ CP/M (пересборка памяти и PC := 0F100h)
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 10. Возврат CP/M: безопасный PC, пересборка памяти, PC := CCP")
    n.outvar(u"GVL_CPM.CPM_WE", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 200),
                                   I(n, u"TRUE"), I(n, u"GVL_CPM.CPM_WE"),
                                   fbd_xml.COL_BLK + 330))
    n.outvar(u"GVL_CPM.CPM_LD1", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 460),
                                    I(n, u"TRUE"), I(n, u"GVL_CPM.CPM_LD1"),
                                    fbd_xml.COL_BLK + 590))
    n.outvar(u"GVL_CPM.CPM_LD2", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 720),
                                    I(n, u"TRUE"), I(n, u"GVL_CPM.CPM_LD2"),
                                    fbd_xml.COL_BLK + 850))
    n.outvar(u"GVL_CPM.CPM_Sel1", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 980),
                                     I(n, B % 7), I(n, u"GVL_CPM.CPM_Sel1"),
                                     fbd_xml.COL_BLK + 1110))
    n.outvar(u"GVL_CPM.CPM_Sel2", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 1240),
                                     I(n, B % 8), I(n, u"GVL_CPM.CPM_Sel2"),
                                     fbd_xml.COL_BLK + 1370))
    n.outvar(u"GVL_CPM.CPM_Data1", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 1500),
                                      I(n, W % CCP_ENTRY), I(n, u"GVL_CPM.CPM_Data1"),
                                      fbd_xml.COL_BLK + 1630))
    n.outvar(u"GVL_CPM.CPM_Data2", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 1760),
                                      I(n, W % STACK_TOP), I(n, u"GVL_CPM.CPM_Data2"),
                                      fbd_xml.COL_BLK + 1890))
    n.outvar(u"GVL_CPM.Init_Done", IF(n, _one(n, IP_HAND, fbd_xml.COL_BLK + 2020),
                                      I(n, u"FALSE"), I(n, u"GVL_CPM.Init_Done"),
                                      fbd_xml.COL_BLK + 2150))

    # ------------------------------------------------------------------
    # СЕТЬ 11. АВТОМАТ НАБОРА I/O
    # ------------------------------------------------------------------
    n = p.network(u"СЕТЬ 11. Автомат набора ввода-вывода (ph -> ph)")
    # ФАЗА B. КАЖДАЯ ФАЗА ДЛИТСЯ НЕ МЕНЬШЕ ДВУХ СКАНОВ.
    #
    # Раньше переход шёл безусловно каждый скан. Но порядок вызова в задаче:
    # TEST_8080 -> PLC_PRG_CPM (диспетчер I/O) -> ... -> TEST_IO (последняя).
    # Тест выставляет GVL_IO.Req в скане N, а диспетчер прочитает его только
    # в скане N+1 - когда фаза уже сменилась и Req снят. Замер подтвердил:
    # блок диспетчера вызывался 11622 раза, но Req не был TRUE НИ РАЗУ
    # (Dbg_Req = 0), поэтому ни одна проверка вывода/счётчиков не могла пройти.
    # Теперь фаза держится два скана: тест выставил запрос -> диспетчер
    # обслужил -> на следующем скане фаза сменилась и проверка сняла результат.
    n.outvar(u"sc2", IF(n, NOT(n, EQ(n, I(n, u"ph"), I(n, u"ph_prev"), fbd_xml.COL_BLK + 4000), fbd_xml.COL_BLK + 4060),
                        I(n, u"INT#1"),
                        ADD(n, I(n, u"sc2"), I(n, u"INT#1"), fbd_xml.COL_BLK + 4130),
                        fbd_xml.COL_BLK + 4260))
    n.outvar(u"ph_prev", I(n, u"ph"), fbd_xml.COL_BLK + 4390)
    hold = GE(n, I(n, u"sc2"), I(n, u"INT#4"), fbd_xml.COL_BLK + 4520)
    acc = I(n, u"ph")
    seq = ((IP_IDLE, IP_PREP), (IP_PREP, IP_I1), (IP_I1, IP_C1), (IP_C1, IP_I2),
           (IP_I2, IP_C2), (IP_C2, IP_I3), (IP_I3, IP_C3), (IP_C3, IP_I4),
           (IP_I4, IP_C4), (IP_C4, IP_I5), (IP_I5, IP_C5), (IP_C5, IP_I6),
           (IP_I6, IP_C6), (IP_C6, IP_I7), (IP_I7, IP_C7), (IP_C7, IP_PREP8),
           (IP_PREP8, IP_I8), (IP_I8, IP_C8), (IP_C8, IP_PREP9),
           (IP_PREP9, IP_I9), (IP_I9, IP_W9), (IP_W9, IP_C9), (IP_C9, IP_PREP10),
           (IP_PREP10, IP_I10), (IP_I10, IP_W10), (IP_W10, IP_C10),
           (IP_C10, IP_FIN), (IP_FIN, IP_HAND), (IP_HAND, IP_DONE))
    # у W9/W10 свои условия ожидания (несколько тактов/сканов), их не тормозим
    no_hold = (IP_W9, IP_W10)
    for k, (a, b) in enumerate(seq):
        one = _one(n, a, fbd_xml.COL_BLK + 130 * (k % 8), 40 + 30 * k)
        if a in no_hold:
            cond = one
        else:
            cond = AND(n, one, hold, fbd_xml.COL_BLK + 4650)
        acc = SEL(n, cond, acc, I(n, B % b), x=fbd_xml.COL_BLK + 1100 + 130 * (k % 8),
                  y=40 + 30 * k)
    # старт набора
    acc = SEL(n, ANDL(n, [
        I(n, u"f0"),
        I(n, u"go"),
        I(n, u"GVL_IO_Map.Map_Ready"),
        EQ(n, I(n, u"GVL_CPM.Trap_Phase"), I(n, B % 8), fbd_xml.COL_BLK + 2690)],
        x0=fbd_xml.COL_BLK + 2820), acc, I(n, B % IP_PREP), fbd_xml.COL_BLK + 2950)
    # ожидание watchdog и двух тактов IN: не один скан, а несколько
    n.outvar(u"sc", ADD(n, I(n, u"sc"), I(n, u"INT#1"), fbd_xml.COL_BLK))
    n.outvar(u"sc", IF(n, OR(n, _one(n, IP_W9, fbd_xml.COL_BLK + 200),
                            _one(n, IP_W10, fbd_xml.COL_BLK + 330),
                            fbd_xml.COL_BLK + 460),
                       I(n, u"sc"), I(n, u"INT#0"), fbd_xml.COL_BLK + 590))
    # IN через процессор занимает ДВА такта (запрос и квитанция), а включение
    # CPU_Run действует со СЛЕДУЮЩЕГО скана - поэтому ждём 3 скана
    acc = SEL(n, AND(n, _one(n, IP_W9, fbd_xml.COL_BLK + 720),
                     GE(n, I(n, u"sc"), I(n, u"INT#3"), fbd_xml.COL_BLK + 850),
                     fbd_xml.COL_BLK + 980),
              acc, I(n, B % IP_C9), fbd_xml.COL_BLK + 1110)
    acc = SEL(n, AND(n, _one(n, IP_W10, fbd_xml.COL_BLK + 1240),
                     GE(n, I(n, u"sc"), I(n, u"INT#%d" % WD_WAIT),
                        fbd_xml.COL_BLK + 1370), fbd_xml.COL_BLK + 1500),
              acc, I(n, B % IP_C10), fbd_xml.COL_BLK + 1630)
    # ПАУЗА (фаза B): автомат работает ТОЛЬКО в своём режиме (Mode = 3).
    # Без паузы он проскакивал все проверки за первые сканы, ещё до начала
    # наборов 8080 и CP/M, и сразу уводил Mode в 0.
    acc = SEL(n, NOT(n, I(n, u"own"), fbd_xml.COL_BLK + 1760),
              acc, I(n, u"ph"), fbd_xml.COL_BLK + 1890)
    n.outvar(u"ph", acc)
    return p


def _sel_chain(n, pairs, dflt, x0=None, y=None):
    u"""Цепочка SEL по фазе: результатом становится значение нужной фазы (BYTE)."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = I(n, dflt)
    for k, (code, val) in enumerate(pairs):
        acc = SEL(n, _one(n, code, x0 + 130 * k, y), acc, I(n, H % val),
                  x0 + 130 * k, y)
    return acc


def _sel_chain_src(n, pairs, dflt_src, x0=None, y=None):
    u"""Цепочка SEL по фазе со значением по умолчанию ИЗ ПЕРЕМЕННОЙ (BYTE)."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = dflt_src
    for k, (code, val) in enumerate(pairs):
        acc = SEL(n, _one(n, code, x0 + 130 * k, y), acc, I(n, H % val),
                  x0 + 130 * k, y)
    return acc


def _pc_prep(n, x, y=None):
    u"""Фазы подготовки PC для проверок 8-10 (через порт CP/M)."""
    return ORL(n, [_one(n, IP_PREP9, x, y),
                   _one(n, IP_PREP10, x + 130, y)], x0=x + 260, y=y)


def _sel_chain_b(n, pairs, x0=None, y=None):
    u"""То же для BOOL-значений."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = I(n, u"FALSE")
    for k, (code, val) in enumerate(pairs):
        acc = SEL(n, _one(n, code, x0 + 130 * k, y), acc,
                  I(n, u"TRUE" if val else u"FALSE"), x0 + 130 * k, y)
    return acc


def _sel_chain_b2(n, pairs, dflt_src, x0=None, y=None):
    u"""Цепочка SEL по фазе для BOOL; умолчание - ССЫЛКА (Src), не строка."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = dflt_src
    for k, (code, val) in enumerate(pairs):
        acc = SEL(n, _one(n, code, x0 + 130 * k, y), acc,
                  I(n, u"TRUE" if val else u"FALSE"), x0 + 130 * k, y)
    return acc


def _sel_chain_w(n, pairs, dflt, x0=None, y=None):
    u"""Цепочка SEL по фазе для UDINT-значений."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = dflt
    for k, (code, val) in enumerate(pairs):
        acc = SEL(n, _one(n, code, x0 + 130 * k, y), acc,
                  I(n, u"UDINT#%d" % val), x0 + 130 * k, y)
    return acc


def _sum_true(n, names, x0=None):
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    acc = None
    for k, nm in enumerate(names):
        one = SEL(n, I(n, nm), I(n, u"INT#0"), I(n, u"INT#1"), x=x0 + 130 * k)
        acc = one if acc is None else ADD(n, acc, one)
    return acc


def AND3(n, a, b, c, x=None, y=None):
    u"""AND с ТРЕМЯ входами (в pou_cpm_defs.py есть только двухвходовый)."""
    ab = AND(n, a, b, x, y)
    return AND(n, ab, c, fbd_xml.COL_BLK if x is None else x + 130, y)


ALL = (make_test_io,)
