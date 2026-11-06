# -*- coding: utf-8 -*-
u"""Этап 3.6: АППАРАТНЫЙ СЛОЙ ВВОДА-ВЫВОДА на FBD.

Состав (совпадает с планом 04_ПЛАН_CPM.md, разделы 5 и 6):
  FB_IO_Read        - дискретный канал -> байт для команды IN (бит 0, инверсия);
  FB_IO_Write       - байт команды OUT -> дискретный канал (бит 0, инверсия);
  FB_IO_AnalogIn    - INT -> BYTE с масштабом Num/Den, насыщением LIMIT
                      и признаком выхода за диапазон;
  FB_IO_AnalogOut   - BYTE -> INT (обратное преобразование);
  FB_IO_Dispatch    - КАРТА ПОРТОВ, политика отсутствующего порта, консольный
                      канал, счётчики, журнал событий, квитанция процессору;
  FB_IO_MapInit     - заливка демонстрационной карты портов на первом скане;
  FB_IO_Adapter_Sim / _SoftPLC - адаптеры каналов (ОДИН интерфейс);
  FB_Watchdog       - контроль незавершённого такта (снимок PC/IR/флагов);
  FB_HMI_Update     - обновление переменных HMI.

ПОЧЕМУ ОБМЕН ЗАНИМАЕТ ДВА СКАНА. Аппаратный слой обязан вызываться ПОСЛЕ
процессора (процессор -> трап -> диспетчеры CP/M -> I/O), иначе ломается уже
проверенный порядок слоя CP/M. Поэтому команда IN/OUT работает как обращение к
медленному устройству (wait state):

  скан N   : процессор декодирует IN/OUT, выставляет GVL_IO.Req/Port/WData/RW и
             НЕ продвигает PC и не считает такт (ждут);
  скан N   : ниже по программе FB_IO_Dispatch выполняет обращение и выставляет
             GVL_IO.Ack (для IN - ещё и GVL_IO.RData);
  скан N+1 : процессор видит Ack, для IN кладёт RData в A и продвигает PC на 2.

Флаги IN/OUT не трогают (декодер уже ставит C_SZP_En/CY_En = FALSE), длина
команды 2 байта - PC получает PC+2 штатным путём.

ЗАЩИТА ИНДЕКСОВ. Номер порта - байт команды, а массив карты ровно 0..255,
поэтому индекс порта в границах ПО ПОСТРОЕНИЮ. Номера каналов берутся из
дескриптора (их пишет человек) и ВСЕГДА проходят через LIMIT: выход за границу
массива в FBD - это авария ПЛК, а не исключение языка.

ПРАВИЛА ДИАЛЕКТА соблюдаются: один выход = одна связь; выход вызова FB
защёлкивается в переменную POU; порядок сетей = порядок чтения переменных.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
from pou_cpm_defs import (I, K, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, SEL, IF,
                          ADD, SUB, MUL, MOD, SHL, SHR, W2B, ORL, ANDL, CHAIN,
                          latch, rw, B, H, W, WH, D32, U1)
from pou_io_defs import (K_NONE, K_DI, K_DO, K_AI, K_AO, K_CONSOLE,
                         MODE_STUB, MODE_DIAG, MODE_FAULT,
                         E_NONE, E_UNMAPPED_PORT, E_TIMEOUT, E_CHAN_FAULT,
                         E_BAD_KIND, E_RANGE,
                         EV_NONE, EV_UNMAPPED, EV_DIAG, EV_FAULT,
                         EV_WATCHDOG, EV_RANGE, EV_KIND, EV_SAFE,
                         EV_STOP, EV_RESET, EV_CONSOLE,
                         DI_MAX, DO_MAX, AI_MAX, AO_MAX, EV_IDX_MAX,
                         DIV, XOR, LIMIT, B2I, I2B, I2D, D2I, D2B, I2U,
                         log_event, MAP_DEMO, ADAPTER_TYPE)


# ======================================================================
# ДИСКРЕТНЫЙ ВВОД: канал -> байт
# ======================================================================
def make_io_read():
    p = Pou(u"FB_IO_Read", u"functionBlock",
            doc=u"Дискретный канал DI -> байт для команды IN d8.\n"
                u"\tПорт 8080 побайтовый, а дискретный канал один: DI[k] даёт бит 0\n"
                u"\tбайта, остальные биты нули (так ведут себя тумблерные порты\n"
                u"\tреальных машин). Поле Invert дескриптора инвертирует логику\n"
                u"\t(активный ноль). Индекс канала ОГРАНИЧИВАЕТСЯ блоком LIMIT,\n"
                u"\tпризнак выхода за диапазон отдаётся в Fault: схема не выходит\n"
                u"\tза границу массива никогда, но ошибку в карте портов видно.")
    p.var_in(u"En_IO", u"BOOL", u"выполнять чтение")
    p.var_in(u"Index", u"INT", u"номер дискретного входа 0..63")
    p.var_in(u"Invert", u"BOOL", u"инверсия логики канала")
    p.var_out(u"RData", u"BYTE", u"байт для аккумулятора: 01h или 00h")
    p.var_out(u"Bit", u"BOOL", u"прочитанный уровень (после инверсии)")
    p.var_out(u"Fault", u"BOOL", u"индекс канала вне диапазона 0..63")
    p.var(u"idx", u"INT", u"ограниченный индекс канала")
    p.var(u"raw", u"BOOL", u"уровень канала до инверсии")
    p.var(u"eff", u"BOOL", u"уровень канала после инверсии")

    n = p.network(u"СЕТЬ 1. Ограничение индекса канала (LIMIT) и признак ошибки")
    n.outvar(u"idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#63")))
    n.outvar(u"Fault", ORL(n, [LT(n, I(n, u"Index"), I(n, u"INT#0")),
                               GT(n, I(n, u"Index"), I(n, u"INT#63"),
                                  fbd_xml.COL_BLK + 200)],
                           x0=fbd_xml.COL_BLK + 340))

    n = p.network(u"СЕТЬ 2. Чтение канала и инверсия логики")
    n.outvar(u"raw", I(n, u"GVL_IO.DI[idx]"))
    n.outvar(u"eff", XOR(n, I(n, u"raw"), I(n, u"Invert")))
    n.outvar(u"Bit", I(n, u"eff"))

    n = p.network(u"СЕТЬ 3. Байт для аккумулятора: бит 0, остальные нули")
    n.outvar(u"RData", IF(n, I(n, u"eff"), I(n, H % 0x01), I(n, H % 0x00)))
    return p


# ======================================================================
# ДИСКРЕТНЫЙ ВЫВОД: байт -> канал
# ======================================================================
def make_io_write():
    p = Pou(u"FB_IO_Write", u"functionBlock",
            doc=u"Байт команды OUT d8 -> дискретный канал DO.\n"
                u"\tВ канал идёт бит 0 байта (с учётом инверсии Invert).\n"
                u"\tЗапись выполняется ТОЛЬКО когда En = TRUE, поэтому канал не\n"
                u"\tпереписывается каждый скан. Индекс ограничивается LIMIT, при\n"
                u"\tвыходе за диапазон запись НЕ делается, а выставляется Fault.")
    p.var_in(u"En_IO", u"BOOL", u"выполнять запись")
    p.var_in(u"Index", u"INT", u"номер дискретного выхода 0..63")
    p.var_in(u"WData", u"BYTE", u"записываемый байт (берётся бит 0)")
    p.var_in(u"Invert", u"BOOL", u"инверсия логики канала")
    p.var_out(u"Bit", u"BOOL", u"что записано в канал (после инверсии)")
    p.var_out(u"Fault", u"BOOL", u"индекс канала вне диапазона 0..63")
    p.var(u"idx", u"INT", u"ограниченный индекс канала")
    p.var(u"b1", u"BOOL", u"бит 0 байта")
    p.var(u"eff", u"BOOL", u"уровень после инверсии")
    p.var(u"ok", u"BOOL", u"запись разрешена и индекс корректен")

    n = p.network(u"СЕТЬ 1. Ограничение индекса и признак ошибки")
    n.outvar(u"idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#63")))
    n.outvar(u"Fault", ORL(n, [LT(n, I(n, u"Index"), I(n, u"INT#0")),
                               GT(n, I(n, u"Index"), I(n, u"INT#63"),
                                  fbd_xml.COL_BLK + 200)],
                           x0=fbd_xml.COL_BLK + 340))

    n = p.network(u"СЕТЬ 2. Бит 0 байта и инверсия логики")
    n.outvar(u"b1", NE(n, AND(n, I(n, u"WData"), I(n, H % 0x01)), I(n, H % 0x00)))
    n.outvar(u"eff", XOR(n, I(n, u"b1"), I(n, u"Invert")))
    n.outvar(u"Bit", I(n, u"eff"))

    n = p.network(u"СЕТЬ 3. Запись в канал (только при En и корректном индексе)")
    n.outvar(u"ok", AND(n, I(n, u"En_IO"), NOT(n, I(n, u"Fault"), fbd_xml.COL_BLK + 200),
                        fbd_xml.COL_BLK + 320))
    # ФАЗА B. ЗАПИСЬ ТОЛЬКО ПО ПОСТОЯННОМУ ИНДЕКСУ.
    # Было: outvar(u"GVL_IO.DO[idx]", ...) - запись в массив по ВЫЧИСЛЯЕМОМУ
    # индексу. Импортёр PLCopenXML такие записи МОЛЧА ТЕРЯЕТ (та же ловушка,
    # что была с GVL_MEM.Memory[c_p1a]). Поэтому каналы ввода (чтение) работали,
    # а ВСЕ каналы вывода - нет: DO[0] оставался FALSE после OUT 00h.
    # Теперь на каждый канал своё условное присваивание по константе.
    for k in range(64):
        _e = u"GVL_IO.DO[%d]" % k
        n.outvar(_e, IF(n, AND(n, I(n, u"ok"),
                               EQ(n, I(n, u"idx"), I(n, u"INT#%d" % k),
                                  fbd_xml.COL_BLK2 + 900 + 40 * (k % 16)),
                               fbd_xml.COL_BLK2 + 1500 + 40 * (k % 16)),
                      I(n, u"eff"), I(n, _e),
                      fbd_xml.COL_BLK2 + 2100 + 40 * (k % 16)))
    return p


# ======================================================================
# АНАЛОГОВЫЙ ВВОД: INT -> BYTE
# ======================================================================
def make_io_analog_in():
    p = Pou(u"FB_IO_AnalogIn", u"functionBlock",
            doc=u"Аналоговый вход AI (INT) -> байт для команды IN.\n"
                u"\tМасштаб: BYTE = INT * ScaleNum / ScaleDen, полная шкала входа -\n"
                u"\tэто ScaleDen (например 27648 при 0..10 В), результат 0..255.\n"
                u"\tВход сначала ОГРАНИЧИВАЕТСЯ шкалой, произведение считается в DINT\n"
                u"\t(27648 * 255 = 7 050 240 в INT не влезает), результат насыщается\n"
                u"\tблоком LIMIT, и только потом переводится в BYTE.\n"
                u"\tOverflow := вход вне 0..ScaleDen ИЛИ результат больше 255:\n"
                u"\tэто признак того, что шкала подобрана неверно или сигнал вне\n"
                u"\tдиапазона (обрыв, перегруз).\n"
                u"\tОГРАНИЧЕНИЕ: шкала однополярная (Num >= 0, Den > 0). Для\n"
                u"\tдвуполярного сигнала ставится Num по диапазону, а отрицательные\n"
                u"\tзначения входа дают Overflow и 00h на выходе.")
    p.var_in(u"En_IO", u"BOOL", u"выполнять чтение")
    p.var_in(u"Index", u"INT", u"номер аналогового входа 0..15")
    p.var_in(u"Num", u"INT", u"числитель масштаба (0..255)")
    p.var_in(u"Den", u"INT", u"знаменатель масштаба: полная шкала входа")
    p.var_in(u"Invert", u"BOOL", u"инверсия шкалы (байт := 255 - байт)")
    p.var_out(u"RData", u"BYTE", u"байт для аккумулятора (0..255)")
    p.var_out(u"Raw", u"INT", u"сырое значение входа (для HMI)")
    p.var_out(u"Overflow", u"BOOL", u"вход или результат вне диапазона шкалы")
    p.var_out(u"Fault", u"BOOL", u"индекс вне 0..15 или недопустимая шкала")
    p.var(u"idx", u"INT", u"ограниченный индекс канала")
    p.var(u"den0", u"BOOL", u"знаменатель <= 0 (делить нельзя)")
    p.var(u"num_neg", u"BOOL", u"отрицательный числитель (не поддерживается)")
    p.var(u"den_e", u"INT", u"знаменатель, приведённый к допустимому")
    p.var(u"num_e", u"INT", u"числитель, приведённый к допустимому")
    p.var(u"raw_in", u"INT", u"сырое значение входа (не путать с выходом Raw)")
    p.var(u"d1", u"DINT", u"вход, ограниченный шкалой, в DINT")
    p.var(u"d2", u"DINT", u"произведение вход * Num")
    p.var(u"d3", u"DINT", u"частное (результат масштабирования)")
    p.var(u"d4", u"DINT", u"насыщенный результат 0..255")
    p.var(u"b1", u"BYTE", u"результат в байте")
    p.var(u"over_in", u"BOOL", u"вход за пределами шкалы")

    n = p.network(u"СЕТЬ 1. Индекс канала и проверка шкалы")
    n.outvar(u"idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#15")))
    n.outvar(u"den0", LE(n, I(n, u"Den"), I(n, u"INT#0"), fbd_xml.COL_BLK + 200))
    n.outvar(u"num_neg", LT(n, I(n, u"Num"), I(n, u"INT#0"), fbd_xml.COL_BLK + 340))
    n.outvar(u"den_e", IF(n, I(n, u"den0"), I(n, u"INT#1"), I(n, u"Den"),
                          fbd_xml.COL_BLK + 480))
    n.outvar(u"num_e", IF(n, I(n, u"num_neg"), I(n, u"INT#0"), I(n, u"Num"),
                          fbd_xml.COL_BLK + 620))
    n.outvar(u"Fault", ORL(n, [
        ORL(n, [LT(n, I(n, u"Index"), I(n, u"INT#0")),
                GT(n, I(n, u"Index"), I(n, u"INT#15"), fbd_xml.COL_BLK + 760)],
            x0=fbd_xml.COL_BLK + 900),
        I(n, u"den0"), I(n, u"num_neg")], x0=fbd_xml.COL_BLK + 1040))

    n = p.network(u"СЕТЬ 2. Масштабирование в DINT: LIMIT -> MUL -> DIV -> LIMIT")
    n.outvar(u"raw_in", I(n, u"GVL_IO.AI[idx]"))
    n.outvar(u"Raw", I(n, u"raw_in"))
    n.outvar(u"d1", I2D(n, LIMIT(n, I(n, u"INT#0"), I(n, u"raw_in"), I(n, u"den_e"),
                                 fbd_xml.COL_BLK + 200)))
    n.outvar(u"d2", MUL(n, I(n, u"d1"), I2D(n, I(n, u"num_e"), fbd_xml.COL_BLK + 320),
                        fbd_xml.COL_BLK + 440))
    n.outvar(u"d3", DIV(n, I(n, u"d2"), I2D(n, I(n, u"den_e"), fbd_xml.COL_BLK + 560),
                        fbd_xml.COL_BLK + 680))
    n.outvar(u"d4", LIMIT(n, I(n, u"DINT#0"), I(n, u"d3"), I(n, u"DINT#255"),
                          fbd_xml.COL_BLK + 800))

    n = p.network(u"СЕТЬ 3. Байт результата, инверсия шкалы и признак выхода")
    n.outvar(u"b1", D2B(n, I(n, u"d4")))
    n.outvar(u"RData", XOR(n, I(n, u"b1"),
                           IF(n, I(n, u"Invert"), I(n, H % 0xFF), I(n, H % 0x00),
                              fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 320))
    n.outvar(u"over_in", ORL(n, [GT(n, I(n, u"raw_in"), I(n, u"den_e")),
                                 LT(n, I(n, u"raw_in"), I(n, u"INT#0"),
                                    fbd_xml.COL_BLK + 440)],
                             x0=fbd_xml.COL_BLK + 580))
    n.outvar(u"Overflow", ORL(n, [I(n, u"over_in"),
                                  GT(n, I(n, u"d3"), I(n, u"DINT#255"),
                                     fbd_xml.COL_BLK + 720)],
                              x0=fbd_xml.COL_BLK + 860))
    return p


# ======================================================================
# АНАЛОГОВЫЙ ВЫВОД: BYTE -> INT
# ======================================================================
def make_io_analog_out():
    p = Pou(u"FB_IO_AnalogOut", u"functionBlock",
            doc=u"Байт команды OUT -> аналоговый выход AO (INT).\n"
                u"\tОбратное преобразование: INT = BYTE * ScaleDen / ScaleNum.\n"
                u"\tПолная шкала выхода - ScaleDen (например 27648). Считается в DINT,\n"
                u"\tнасыщается LIMIT, при недопустимой шкале (Num <= 0 или Den <= 0)\n"
                u"\tвыставляется Fault и берётся безопасный делитель 1.\n"
                u"\tЗапись в канал идёт только при En и корректном индексе.")
    p.var_in(u"En_IO", u"BOOL", u"выполнять запись")
    p.var_in(u"Index", u"INT", u"номер аналогового выхода 0..15")
    p.var_in(u"WData", u"BYTE", u"записываемый байт (0..255)")
    p.var_in(u"Num", u"INT", u"числитель масштаба (0..255)")
    p.var_in(u"Den", u"INT", u"знаменатель масштаба: полная шкала выхода")
    p.var_out(u"AOut", u"INT", u"значение для аналогового выхода")
    p.var_out(u"Overflow", u"BOOL", u"результат обрезан по шкале")
    p.var_out(u"Fault", u"BOOL", u"индекс вне 0..15 или недопустимая шкала")
    p.var(u"idx", u"INT", u"ограниченный индекс канала")
    p.var(u"bad", u"BOOL", u"недопустимая шкала")
    p.var(u"den_bad", u"BOOL", u"знаменатель <= 0")
    p.var(u"den_e", u"INT", u"знаменатель, приведённый к допустимому")
    p.var(u"num_e", u"INT", u"числитель, приведённый к допустимому")
    p.var(u"d1", u"DINT", u"байт * Den")
    p.var(u"d2", u"DINT", u"частное")
    p.var(u"d3", u"DINT", u"насыщенный результат")
    p.var(u"ao_calc", u"INT", u"значение выхода (не путать с выходом AOut)")
    p.var(u"ok", u"BOOL", u"запись разрешена и индекс корректен")

    n = p.network(u"СЕТЬ 1. Индекс канала и проверка шкалы")
    n.outvar(u"idx", LIMIT(n, I(n, u"INT#0"), I(n, u"Index"), I(n, u"INT#15")))
    n.outvar(u"den_bad", LE(n, I(n, u"Den"), I(n, u"INT#0"), fbd_xml.COL_BLK + 200))
    n.outvar(u"bad", ORL(n, [I(n, u"den_bad"),
                             LE(n, I(n, u"Num"), I(n, u"INT#0"),
                                fbd_xml.COL_BLK + 340)],
                         x0=fbd_xml.COL_BLK + 480))
    n.outvar(u"den_e", IF(n, I(n, u"den_bad"), I(n, u"INT#1"), I(n, u"Den"),
                          fbd_xml.COL_BLK + 620))
    n.outvar(u"num_e", IF(n, I(n, u"bad"), I(n, u"INT#1"), I(n, u"Num"),
                          fbd_xml.COL_BLK + 760))
    n.outvar(u"Fault", ORL(n, [
        ORL(n, [LT(n, I(n, u"Index"), I(n, u"INT#0")),
                GT(n, I(n, u"Index"), I(n, u"INT#15"), fbd_xml.COL_BLK + 900)],
            x0=fbd_xml.COL_BLK + 1040),
        I(n, u"bad")], x0=fbd_xml.COL_BLK + 1180))

    n = p.network(u"СЕТЬ 2. Масштабирование BYTE -> INT в DINT с насыщением")
    n.outvar(u"d1", MUL(n, I2D(n, B2I(n, I(n, u"WData"))),
                        I2D(n, I(n, u"den_e"), fbd_xml.COL_BLK + 200),
                        fbd_xml.COL_BLK + 340))
    n.outvar(u"d2", DIV(n, I(n, u"d1"), I2D(n, I(n, u"num_e"), fbd_xml.COL_BLK + 460),
                        fbd_xml.COL_BLK + 580))
    n.outvar(u"d3", LIMIT(n, I(n, u"DINT#0"), I(n, u"d2"),
                          I2D(n, I(n, u"den_e"), fbd_xml.COL_BLK + 700),
                          fbd_xml.COL_BLK + 820))
    n.outvar(u"ao_calc", D2I(n, I(n, u"d3"), fbd_xml.COL_BLK + 940))
    n.outvar(u"AOut", I(n, u"ao_calc"))

    n = p.network(u"СЕТЬ 3. Запись в аналоговый канал")
    n.outvar(u"Overflow", GT(n, I(n, u"d2"), I2D(n, I(n, u"den_e"), fbd_xml.COL_BLK + 200),
                             fbd_xml.COL_BLK + 320))
    n.outvar(u"ok", AND(n, I(n, u"En_IO"), NOT(n, I(n, u"Fault"), fbd_xml.COL_BLK + 440),
                        fbd_xml.COL_BLK + 560))
    # ФАЗА B. Аналоговый вывод - тоже только по постоянному индексу
    # (см. комментарий в FB_IO_DigitalOut: запись по вычисляемому индексу
    # импортёр теряет, поэтому AO[0] не получал значение).
    for k in range(16):
        _e = u"GVL_IO.AO[%d]" % k
        n.outvar(_e, IF(n, AND(n, I(n, u"ok"),
                               EQ(n, I(n, u"idx"), I(n, u"INT#%d" % k),
                                  fbd_xml.COL_BLK2 + 900 + 40 * k),
                               fbd_xml.COL_BLK2 + 1500 + 40 * k),
                      I(n, u"ao_calc"), I(n, _e),
                      fbd_xml.COL_BLK2 + 2100 + 40 * k))
    return p


# ======================================================================
# АДАПТЕРЫ КАНАЛОВ: ОДИН И ТОТ ЖЕ ИНТЕРФЕЙС
# ======================================================================
ADAPTER_PINS_IN = (
    (u"En_IO", u"BOOL", u"обслуживать обращение (запрос принят и разрешён)"),
    (u"RW", u"BOOL", u"TRUE = вывод (OUT), FALSE = ввод (IN)"),
    (u"Kind", u"BYTE", u"вид канала: 1=DI 2=DO 3=AI 4=AO (консоль ведёт диспетчер)"),
    (u"Index", u"INT", u"номер канала из дескриптора порта"),
    (u"WData", u"BYTE", u"байт для вывода"),
    (u"Invert", u"BOOL", u"инверсия логики/шкалы канала"),
    (u"Num", u"INT", u"числитель масштаба"),
    (u"Den", u"INT", u"знаменатель масштаба (полная шкала)"),
)

ADAPTER_PINS_OUT = (
    (u"RData", u"BYTE", u"прочитанный байт (для IN)"),
    (u"Fault", u"BOOL", u"канал недоступен или карта портов задана неверно"),
    (u"Overflow", u"BOOL", u"аналоговое значение вышло за диапазон шкалы"),
)


def _make_adapter(name, doc):
    u"""Адаптер каналов: вид канала -> нужный FB, результат - в один байт.

    Логика ОДНА на все адаптеры (Sim и SoftPLC), различается только физическая
    привязка каналов, поэтому смена адаптера в прикладном коде не видна: тип
    адаптера задан ОДНОЙ константой ADAPTER_TYPE в pou_io_defs.py.
    """
    p = Pou(name, u"functionBlock", doc=doc)
    for nm, t, c in ADAPTER_PINS_IN:
        p.var_in(nm, t, c)
    for nm, t, c in ADAPTER_PINS_OUT:
        p.var_out(nm, t, c)
    p.var(u"is_di", u"BOOL", u"вид канала - дискретный вход")
    p.var(u"is_do", u"BOOL", u"вид канала - дискретный выход")
    p.var(u"is_ai", u"BOOL", u"вид канала - аналоговый вход")
    p.var(u"is_ao", u"BOOL", u"вид канала - аналоговый выход")
    p.var(u"g_in", u"BOOL", u"идёт ввод (IN)")
    p.var(u"g_out", u"BOOL", u"идёт вывод (OUT)")
    p.var(u"e_rd", u"BOOL", u"разрешение чтения дискретного входа")
    p.var(u"e_wr", u"BOOL", u"разрешение записи дискретного выхода")
    p.var(u"e_ai", u"BOOL", u"разрешение чтения аналогового входа")
    p.var(u"e_ao", u"BOOL", u"разрешение записи аналогового выхода")
    p.var(u"rd", u"FB_IO_Read", u"чтение дискретного входа")
    p.var(u"wr", u"FB_IO_Write", u"запись дискретного выхода")
    p.var(u"ai", u"FB_IO_AnalogIn", u"чтение аналогового входа")
    p.var(u"ao", u"FB_IO_AnalogOut", u"запись аналогового выхода")
    for nm, t, c in ((u"rd_data", u"BYTE", u"защёлка байта дискретного входа"),
                     (u"rd_flt", u"BOOL", u"защёлка ошибки дискретного входа"),
                     (u"wr_bit", u"BOOL", u"защёлка бита дискретного выхода"),
                     (u"wr_flt", u"BOOL", u"защёлка ошибки дискретного выхода"),
                     (u"ai_data", u"BYTE", u"защёлка байта аналогового входа"),
                     (u"ai_flt", u"BOOL", u"защёлка ошибки аналогового входа"),
                     (u"ai_ovf", u"BOOL", u"защёлка выхода за диапазон (вход)"),
                     (u"ao_val", u"INT", u"защёлка значения аналогового выхода"),
                     (u"ao_flt", u"BOOL", u"защёлка ошибки аналогового выхода"),
                     (u"ao_ovf", u"BOOL", u"защёлка выхода за диапазон (выход)")):
        p.var(nm, t, c)

    n = p.network(u"СЕТЬ 1. Вид канала и стробы обращения (ввод/вывод)")
    n.outvar(u"is_di", EQ(n, I(n, u"Kind"), I(n, H % K_DI)))
    n.outvar(u"is_do", EQ(n, I(n, u"Kind"), I(n, H % K_DO), fbd_xml.COL_BLK + 120))
    n.outvar(u"is_ai", EQ(n, I(n, u"Kind"), I(n, H % K_AI), fbd_xml.COL_BLK + 240))
    n.outvar(u"is_ao", EQ(n, I(n, u"Kind"), I(n, H % K_AO), fbd_xml.COL_BLK + 360))
    n.outvar(u"g_in", AND(n, I(n, u"En_IO"), NOT(n, I(n, u"RW"), fbd_xml.COL_BLK + 480),
                          fbd_xml.COL_BLK + 600))
    n.outvar(u"g_out", AND(n, I(n, u"En_IO"), I(n, u"RW"), fbd_xml.COL_BLK + 720))
    n.outvar(u"e_rd", AND(n, I(n, u"g_in"), I(n, u"is_di"), fbd_xml.COL_BLK + 840))
    n.outvar(u"e_wr", AND(n, I(n, u"g_out"), I(n, u"is_do"), fbd_xml.COL_BLK + 960))
    n.outvar(u"e_ai", AND(n, I(n, u"g_in"), I(n, u"is_ai"), fbd_xml.COL_BLK + 1080))
    n.outvar(u"e_ao", AND(n, I(n, u"g_out"), I(n, u"is_ao"), fbd_xml.COL_BLK + 1200))

    n = p.network(u"СЕТЬ 2. Четыре обращения к каналам (каждое под своим стробом)")
    rd = n.block(u"FB_IO_Read", [(u"En_IO", I(n, u"e_rd")), (u"Index", I(n, u"Index")),
                                 (u"Invert", I(n, u"Invert"))],
                 [u"RData", u"Bit", u"Fault"], instance=u"rd", x=fbd_xml.COL_BLK)
    n.outvar(u"rd_data", rd.out(u"RData"))
    n.outvar(u"rd_flt", rd.out(u"Fault"))
    wr = n.block(u"FB_IO_Write", [(u"En_IO", I(n, u"e_wr")), (u"Index", I(n, u"Index")),
                                  (u"WData", I(n, u"WData")), (u"Invert", I(n, u"Invert"))],
                 [u"Bit", u"Fault"], instance=u"wr", x=fbd_xml.COL_BLK + 200)
    n.outvar(u"wr_bit", wr.out(u"Bit"))
    n.outvar(u"wr_flt", wr.out(u"Fault"))
    ai = n.block(u"FB_IO_AnalogIn", [(u"En_IO", I(n, u"e_ai")), (u"Index", I(n, u"Index")),
                                     (u"Num", I(n, u"Num")), (u"Den", I(n, u"Den")),
                                     (u"Invert", I(n, u"Invert"))],
                 [u"RData", u"Raw", u"Overflow", u"Fault"], instance=u"ai",
                 x=fbd_xml.COL_BLK + 400)
    n.outvar(u"ai_data", ai.out(u"RData"))
    n.outvar(u"ai_ovf", ai.out(u"Overflow"))
    n.outvar(u"ai_flt", ai.out(u"Fault"))
    ao = n.block(u"FB_IO_AnalogOut", [(u"En_IO", I(n, u"e_ao")), (u"Index", I(n, u"Index")),
                                      (u"WData", I(n, u"WData")), (u"Num", I(n, u"Num")),
                                      (u"Den", I(n, u"Den"))],
                 [u"AOut", u"Overflow", u"Fault"], instance=u"ao",
                 x=fbd_xml.COL_BLK + 600)
    n.outvar(u"ao_val", ao.out(u"AOut"))
    n.outvar(u"ao_ovf", ao.out(u"Overflow"))
    n.outvar(u"ao_flt", ao.out(u"Fault"))

    n = p.network(u"СЕТЬ 3. Сборка результата: байт, неисправность, диапазон")
    d = I(n, H % 0x00)
    d = IF(n, I(n, u"is_di"), I(n, u"rd_data"), d, fbd_xml.COL_BLK)
    d = IF(n, I(n, u"is_ai"), I(n, u"ai_data"), d, fbd_xml.COL_BLK + 160)
    n.outvar(u"RData", d)
    n.outvar(u"Fault", ORL(n, [
        AND(n, I(n, u"is_di"), I(n, u"rd_flt")),
        AND(n, I(n, u"is_do"), I(n, u"wr_flt"), fbd_xml.COL_BLK + 140),
        AND(n, I(n, u"is_ai"), I(n, u"ai_flt"), fbd_xml.COL_BLK + 280),
        AND(n, I(n, u"is_ao"), I(n, u"ao_flt"), fbd_xml.COL_BLK + 420)],
        x0=fbd_xml.COL_BLK + 560))
    n.outvar(u"Overflow", ORL(n, [
        AND(n, I(n, u"is_ai"), I(n, u"ai_ovf")),
        AND(n, I(n, u"is_ao"), I(n, u"ao_ovf"), fbd_xml.COL_BLK + 140)],
        x0=fbd_xml.COL_BLK + 280))
    return p


def make_adapter_sim():
    return _make_adapter(u"FB_IO_Adapter_Sim",
                         u"АДАПТЕР A (симуляция): каналы берутся из GVL_IO напрямую.\n"
                         u"\tDI/DO/AI/AO - обычные переменные ПЛК, их форсируют в\n"
                         u"\tonline-режиме или пишет прикладная программа. Физических\n"
                         u"\tмодулей нет - это профиль 'Simulation Device x64'.\n"
                         u"\tИНТЕРФЕЙС ОДИНАКОВ У ВСЕХ ТРЁХ АДАПТЕРОВ: смена адаптера -\n"
                         u"\tэто замена типа экземпляра в FB_IO_Dispatch (константа\n"
                         u"\tADAPTER_TYPE в pou_io_defs.py), прикладной код не меняется.")


def make_adapter_softplc():
    return _make_adapter(u"FB_IO_Adapter_SoftPLC",
                         u"АДАПТЕР B (SoftPLC: Control Win / RTE): то же, что Sim.\n"
                         u"\tКаналы - массивы GVL_IO.DI/DO/AI/AO. Отличие профиля только\n"
                         u"\tв привязке: в реальном проекте эти массивы связываются с\n"
                         u"\tпеременными OPC UA / Modbus в I/O-конфигурации устройства\n"
                         u"\t(в этой установке такого устройства нет, поэтому связи не\n"
                         u"\tсоздаются и не выдумываются).\n"
                         u"\tИНТЕРФЕЙС ОДИНАКОВ У ВСЕХ ТРЁХ АДАПТЕРОВ: прикладной код\n"
                         u"\t(ядро 8080, трапы, главная программа) не меняется.")


# ======================================================================
# ДИСПЕТЧЕР: КАРТА ПОРТОВ, ПОЛИТИКА, КОНСОЛЬ, СЧЁТЧИКИ
# ======================================================================
def make_io_dispatch():
    p = Pou(u"FB_IO_Dispatch", u"functionBlock",
            doc=u"Аппаратный слой: выполнение отложенной операции IN/OUT.\n"
                u"\tВызывается КАЖДЫЙ скан ПОСЛЕ процессора. Когда процессор\n"
                u"\tвыставил GVL_IO.Req (команда IN d8 / OUT d8), диспетчер:\n"
                u"\t  1) берёт дескриптор порта GVL_IO_Map.Map[Port] (индекс порта\n"
                u"\t     0..255 - в границах массива по построению, тип BYTE);\n"
                u"\t  2) каналы DI/DO/AI/AO отдаёт ВЫБРАННОМУ АДАПТЕРУ (сейчас это\n"
                u"\t     %s - смена адаптера не меняет ни одну другую схему);\n"
                u"\t  3) консольный канал (Kind=5) обслуживает сам: OUT выводит\n"
                u"\t     символ в консоль CP/M и её журнал, IN забирает символ от\n"
                u"\t     HMI (если символа нет - возвращает FFh, ожидания нет);\n"
                u"\t  4) порт без канала обрабатывает по GVL_IO_Map.MissingPortMode\n"
                u"\t     (0=STUB 1=DIAG_ONLY 2=FAULT);\n"
                u"\t  5) выставляет GVL_IO.Ack с прочитанным байтом - по этой\n"
                u"\t     квитанции процессор завершает такт и продвигает PC на 2;\n"
                u"\t  6) считает счётчики и пишет события в GVL_IO.Event_Log.\n"
                u"\tАВАРИИ. В режиме FAULT обращение к порту без канала или битый\n"
                u"\tдескриптор поднимают Halt_Req (программа останавливает эмулятор\n"
                u"\tс кодом E_UNMAPPED_PORT / E_BAD_KIND). Неисправный канал и выход\n"
                u"\tаналога за диапазон считаются и журналируются, но эмулятор НЕ\n"
                u"\tостанавливают - это процессная авария, а не отказ эмулятора."
                % ADAPTER_TYPE)
    p.var_in(u"Enable", u"BOOL", u"обслуживание обращений разрешено")
    p.var_in(u"Req", u"BOOL", u"запрос процессора (GVL_IO.Req)")
    p.var_in(u"RW", u"BOOL", u"TRUE = OUT (вывод), FALSE = IN (ввод)")
    p.var_in(u"Port", u"BYTE", u"номер порта 0..255 (байт PC+1 команды)")
    p.var_in(u"WData", u"BYTE", u"байт для вывода (регистр A)")
    p.var_out(u"Ack", u"BOOL", u"квитанция процессору")
    p.var_out(u"RData", u"BYTE", u"прочитанный байт (в аккумулятор)")
    p.var_out(u"Fault", u"BOOL", u"обращение было аварийным")
    p.var_out(u"Err_Code", u"BYTE", u"код аварии этого обращения (0 - нет)")
    p.var_out(u"Kind", u"BYTE", u"вид канала, к которому обратились")
    p.var_out(u"Index", u"INT", u"номер канала, к которому обратились")
    p.var_out(u"Halt_Req", u"BOOL", u"требование остановить эмулятор")

    p.var(u"ready", u"BOOL", u"запрос принят и обслуживание разрешено")
    p.var(u"kind_l", u"BYTE", u"вид канала из дескриптора (не путать с выходом Kind)")
    p.var(u"idx", u"INT", u"номер канала из дескриптора")
    p.var(u"num", u"INT", u"числитель масштаба из дескриптора")
    p.var(u"den", u"INT", u"знаменатель масштаба из дескриптора")
    p.var(u"inv", u"BOOL", u"инверсия канала из дескриптора")
    p.var(u"chf", u"BOOL", u"канал помечен как неисправный")
    p.var(u"mode", u"BYTE", u"режим отсутствующего порта")
    p.var(u"is_none", u"BOOL", u"вид канала 0 - канала нет")
    p.var(u"is_chan", u"BOOL", u"канал DI/DO/AI/AO (ведёт адаптер)")
    p.var(u"is_cons", u"BOOL", u"канал консоли (ведёт диспетчер)")
    p.var(u"is_bad", u"BOOL", u"вид канала вне 0..5 - битый дескриптор")
    p.var(u"m_stub", u"BOOL", u"режим STUB")
    p.var(u"m_diag", u"BOOL", u"режим DIAG_ONLY")
    p.var(u"m_fault", u"BOOL", u"режим FAULT")
    p.var(u"ad_en", u"BOOL", u"обращение к адаптеру разрешено")
    p.var(u"ad", ADAPTER_TYPE, u"адаптер каналов (тип задан ADAPTER_TYPE)")
    p.var(u"ad_rdata", u"BYTE", u"защёлка байта от адаптера")
    p.var(u"ad_fault", u"BOOL", u"защёлка неисправности от адаптера")
    p.var(u"ad_ovf", u"BOOL", u"защёлка выхода за диапазон от адаптера")
    p.var(u"cons", u"BOOL", u"обращение к консольному каналу")
    p.var(u"cons_in", u"BOOL", u"ввод из консоли (IN)")
    p.var(u"cons_out", u"BOOL", u"вывод в консоль (OUT)")
    p.var(u"take", u"BOOL", u"у HMI есть символ, забираем его")
    p.var(u"cin_rdy", u"BOOL", u"защёлка GVL_CPM.ConIn_Ready (в этой же схеме ячейка пишется)")
    p.var(u"cons_data", u"BYTE", u"байт, прочитанный из консоли")
    p.var(u"log_i", u"INT", u"индекс записи в журнале консоли")
    p.var(u"hdl", u"BOOL", u"обработано веткой порта без канала")
    p.var(u"rdata_h", u"BYTE", u"удержанный байт ответа")
    p.var(u"rdy_d", u"BOOL", u"ready на прошлом скане")
    p.var(u"rdy_d2", u"BOOL", u"ready два скана назад")
    p.var(u"hdl_d", u"BOOL", u"hdl на прошлом скане")
    p.var(u"miss", u"BOOL", u"обращение к порту без канала / битому дескриптору")
    p.var(u"p_stub", u"BOOL", u"обработать как STUB")
    p.var(u"p_diag", u"BOOL", u"обработать как DIAG_ONLY")
    p.var(u"p_fault", u"BOOL", u"обработать как FAULT")
    p.var(u"bad_kind", u"BOOL", u"битый дескриптор (вид канала вне 0..5)")
    p.var(u"chf_hit", u"BOOL", u"обратились к неисправному каналу")
    p.var(u"ovf_hit", u"BOOL", u"аналоговое значение вышло за диапазон")
    p.var(u"fault_flag", u"BOOL", u"обращение аварийное")
    p.var(u"halt", u"BOOL", u"нужен останов эмулятора")
    p.var(u"err", u"BYTE", u"код аварии этого обращения")
    p.var(u"rf", u"BYTE", u"собираемый байт результата")
    p.var(u"ev", u"BYTE", u"код события для журнала")
    p.var(u"ev_i", u"INT", u"индекс записи в журнале событий")
    p.var(u"c1", u"UDINT", u"счётчик IN + 1")
    p.var(u"c2", u"UDINT", u"счётчик OUT + 1")
    p.var(u"c3", u"UDINT", u"счётчик неназначенных портов + 1")
    p.var(u"c4", u"UDINT", u"счётчик режима DIAG_ONLY + 1")
    p.var(u"c5", u"UDINT", u"счётчик аварий + 1")
    p.var(u"c6", u"UDINT", u"счётчик выхода за диапазон + 1")
    p.var(u"c7", u"UDINT", u"счётчик консольных обменов + 1")
    p.var(u"rd_ok", u"BOOL", u"обслужен ввод")
    p.var(u"wr_ok", u"BOOL", u"обслужен вывод")

    # ---- 1. дескриптор порта ----
    n = p.network(u"СЕТЬ 1. Дескриптор порта: GVL_IO_Map.Map[Port] (порт 0..255)")
    n.outvar(u"ready", AND(n, I(n, u"Enable"), I(n, u"Req")))
    n.outvar(u"rdy_d", I(n, u"ready"))
    n.outvar(u"rdy_d2", I(n, u"rdy_d"))
    n.outvar(u"kind_l", I(n, u"GVL_IO_Map.Map[Port].Kind"))
    n.outvar(u"idx", I(n, u"GVL_IO_Map.Map[Port].Index"))
    n.outvar(u"num", I(n, u"GVL_IO_Map.Map[Port].ScaleNum"))
    n.outvar(u"den", I(n, u"GVL_IO_Map.Map[Port].ScaleDen"))
    n.outvar(u"inv", I(n, u"GVL_IO_Map.Map[Port].Invert"))
    n.outvar(u"chf", I(n, u"GVL_IO_Map.Map[Port].Fault"))
    n.outvar(u"mode", I(n, u"GVL_IO_Map.MissingPortMode"))

    # ---- 2. классификация канала ----
    n = p.network(u"СЕТЬ 2. Вид канала: канал ПЛК / консоль / нет канала / битый")
    n.outvar(u"is_none", EQ(n, I(n, u"kind_l"), I(n, H % K_NONE)))
    n.outvar(u"is_cons", EQ(n, I(n, u"kind_l"), I(n, H % K_CONSOLE),
                            fbd_xml.COL_BLK + 120))
    n.outvar(u"is_chan", ORL(n, [
        EQ(n, I(n, u"kind_l"), I(n, H % K_DI)),
        EQ(n, I(n, u"kind_l"), I(n, H % K_DO), fbd_xml.COL_BLK + 140),
        EQ(n, I(n, u"kind_l"), I(n, H % K_AI), fbd_xml.COL_BLK + 280),
        EQ(n, I(n, u"kind_l"), I(n, H % K_AO), fbd_xml.COL_BLK + 420)],
        x0=fbd_xml.COL_BLK + 560))
    n.outvar(u"is_bad", AND(n, NOT(n, I(n, u"is_none"), fbd_xml.COL_BLK + 700),
                            AND(n, NOT(n, I(n, u"is_chan"), fbd_xml.COL_BLK + 840),
                                NOT(n, I(n, u"is_cons"), fbd_xml.COL_BLK + 980),
                                fbd_xml.COL_BLK + 1120),
                            fbd_xml.COL_BLK + 1260))
    n.outvar(u"m_stub", EQ(n, I(n, u"mode"), I(n, H % MODE_STUB),
                           fbd_xml.COL_BLK + 1400))
    n.outvar(u"m_diag", EQ(n, I(n, u"mode"), I(n, H % MODE_DIAG),
                           fbd_xml.COL_BLK + 1520))
    n.outvar(u"m_fault", EQ(n, I(n, u"mode"), I(n, H % MODE_FAULT),
                            fbd_xml.COL_BLK + 1640))

    # ---- 3. каналы ПЛК: адаптер ----
    n = p.network(u"СЕТЬ 3. Каналы DI/DO/AI/AO: вызов адаптера (%s)" % ADAPTER_TYPE)
    n.outvar(u"ad_en", AND(n, I(n, u"ready"), I(n, u"is_chan")))
    ad = n.block(ADAPTER_TYPE, [
        (u"En_IO", I(n, u"ad_en")), (u"RW", I(n, u"RW")), (u"Kind", I(n, u"kind_l")),
        (u"Index", I(n, u"idx")), (u"WData", I(n, u"WData")), (u"Invert", I(n, u"inv")),
        (u"Num", I(n, u"num")), (u"Den", I(n, u"den"))],
        [u"RData", u"Fault", u"Overflow"], instance=u"ad", x=fbd_xml.COL_BLK + 200)
    n.outvar(u"ad_rdata", ad.out(u"RData"))
    n.outvar(u"ad_fault", ad.out(u"Fault"))
    n.outvar(u"ad_ovf", ad.out(u"Overflow"))

    # ---- 4. консольный канал ----
    n = p.network(u"СЕТЬ 4. Консольный канал (Kind=5): ввод символа и вывод в консоль")
    n.outvar(u"cons", AND(n, I(n, u"ready"), I(n, u"is_cons")))
    n.outvar(u"cons_in", AND(n, I(n, u"cons"), NOT(n, I(n, u"RW"),
                                                  fbd_xml.COL_BLK + 200),
                             fbd_xml.COL_BLK + 320))
    n.outvar(u"cons_out", AND(n, I(n, u"cons"), I(n, u"RW"), fbd_xml.COL_BLK + 440))
    # Готовность символа читается в ОТДЕЛЬНУЮ переменную POU: эта же ячейка
    # ниже ЗАПИСЫВАЕТСЯ (снятие признака после приёма). Прямое чтение
    # GVL_CPM.ConIn_Ready и запись той же ячейки в одной схеме CODESYS при
    # импорте терял вход блока (выгрузка показывала AND с ОДНИМ входом, и
    # кодогенерация падала: "C23: Для 'AND' необходимо как минимум '2'
    # операндов"). Через защёлку схема импортируется целиком.
    n.outvar(u"cin_rdy", I(n, u"GVL_CPM.ConIn_Ready"))
    # take = cons_in И cin_rdy. Записано через SEL, а НЕ через блок AND:
    # блок AND с входом-переменной, которая в этой же схеме ещё и пишется,
    # CODESYS при импорте оставлял с ОДНИМ входом (локальная переменная перед
    # блоком исчезала вместе со связью), и кодогенерация падала:
    #   C23: Для 'AND' необходимо как минимум '2' операндов
    # SEL(G, IN0, IN1) возвращает IN1 при G=TRUE, то есть cin_rdy ? cons_in : FALSE.
    n.outvar(u"take", SEL(n, I(n, u"cin_rdy"), I(n, u"FALSE"),
                          I(n, u"cons_in"), fbd_xml.COL_BLK + 560))
    # символа нет - отдаём FFh (тот же признак "нет данных", что у порта без
    # канала): программа CP/M отличает "нет символа" от символа 00h
    n.outvar(u"cons_data", IF(n, I(n, u"take"), I(n, u"GVL_CPM.ConIn_Char"),
                              I(n, H % 0xFF), fbd_xml.COL_BLK + 680))
    n.outvar(u"GVL_CPM.ConIn_Ready", IF(n, I(n, u"take"), I(n, u"FALSE"),
                                        I(n, u"cin_rdy"),
                                        fbd_xml.COL_BLK + 820))
    n.outvar(u"GVL_CPM.ConOut_Char", IF(n, I(n, u"cons_out"), I(n, u"WData"),
                                        I(n, u"GVL_CPM.ConOut_Char"),
                                        fbd_xml.COL_BLK + 960))
    n.outvar(u"GVL_CPM.ConOut_Ready", IF(n, I(n, u"cons_out"), I(n, u"TRUE"),
                                         I(n, u"GVL_CPM.ConOut_Ready"),
                                         fbd_xml.COL_BLK + 1100))
    # Маска AND(., INT#255) над INT недопустима: C32 'INT' -> 'ANY_BIT'.
    # Для неотрицательных значений MOD(x, 256) даёт тот же индекс кольцевого
    # журнала (тот же приём применён в emit_char из pou_cpm_defs.py).
    # Журнал пишет FB_ConLog по ПОСТОЯННЫМ индексам: здесь только запрос.
    n.outvar(u"GVL_CPM.LogWr", I(n, u"cons_out"))
    n.outvar(u"GVL_CPM.LogCh", I(n, u"WData"))
    n.outvar(u"Kind", I(n, u"kind_l"))
    n.outvar(u"Index", I(n, u"idx"))

    # ---- 7. порт без канала: STUB / DIAG_ONLY / FAULT ----
    # ВОССТАНОВЛЕНО: эта сеть была вырезана неаккуратной правкой (вместе с
    # ней пропали p_stub/p_diag/p_fault, счётчик Unmapped_Cnt, код аварии
    # и подстановка FFh), из-за чего проверки 5-8 набора I/O падали.
    n = p.network(u"СЕТЬ 7. Порт без канала: STUB / DIAG_ONLY / FAULT")
    n.outvar(u"miss", AND(n, I(n, u"ready"),
                          OR(n, I(n, u"is_none"), I(n, u"is_bad"),
                             fbd_xml.COL_BLK + 200),
                          fbd_xml.COL_BLK + 320))
    n.outvar(u"p_stub", AND(n, I(n, u"miss"), I(n, u"m_stub"),
                             fbd_xml.COL_BLK + 440))
    n.outvar(u"p_diag", AND(n, I(n, u"miss"), I(n, u"m_diag"),
                             fbd_xml.COL_BLK + 560))
    n.outvar(u"p_fault", AND(n, I(n, u"miss"), I(n, u"m_fault"),
                              fbd_xml.COL_BLK + 680))
    n.outvar(u"hdl", ORL(n, [I(n, u"p_stub"), I(n, u"p_diag"),
                             I(n, u"p_fault")], x0=fbd_xml.COL_BLK + 760))
    n.outvar(u"hdl_d", I(n, u"hdl"))
    # Счётчик обращений к портам без канала (режим STUB)
    n.outvar(u"GVL_IO.Diag.Unmapped_Cnt",
             IF(n, I(n, u"p_stub"),
                ADD(n, I(n, u"GVL_IO.Diag.Unmapped_Cnt"), I(n, u"UDINT#1"),
                    fbd_xml.COL_BLK + 800),
                I(n, u"GVL_IO.Diag.Unmapped_Cnt"), fbd_xml.COL_BLK + 920))
    # Код аварии: порт без канала в режиме FAULT
    n.outvar(u"GVL_IO.Diag.Err_Code",
             IF(n, I(n, u"p_fault"), I(n, u"BYTE#1"),
                I(n, u"GVL_IO.Diag.Err_Code"), fbd_xml.COL_BLK + 1040))

    # ---- 8. результат обращения: байт для IN и квитанция ----
    n = p.network(u"СЕТЬ 8. Результат: RData (для порта без канала FFh), Fault, Halt_Req")
    # Ack и RData выровнены по скану: оба берутся из защёлок,
    # накопленных в этом же скане, поэтому байт приходит вместе
    # с квитанцией (без этого проверки 1-3 читали старый ответ).
    n.outvar(u"Fault", ORL(n, [I(n, u"ad_fault"), I(n, u"p_fault")],
                            x0=fbd_xml.COL_BLK + 400))
    n.outvar(u"Halt_Req", I(n, u"p_fault"), fbd_xml.COL_BLK + 540)

    # ---- 9. запись состояния канала в дескриптор ----
    n = p.network(u"СЕТЬ 9. Состояние канала обратно в дескриптор (для HMI)")
    tgt = u"GVL_IO_Map.Map[Port].Fault"
    n.outvar(tgt, IF(n, I(n, u"ad_en"), I(n, u"ad_fault"), I(n, tgt)))

    # ---- 10. квитанция и журнал событий ----
    n = p.network(u"СЕТЬ 10. Квитанция процессору и запись события в журнал")
    # ВНИМАНИЕ: адаптер читает ready через переменную POU (задержка 1 скан),
    # его выход RData виден ещё через скан. Поэтому квитанция выдаётся
    # через ДВА скана - тогда байт и квитанция приходят одновременно
    # (иначе проверки 1-3 читали предыдущий ответ).
    # Байт УДЕРЖИВАЕТСЯ до следующего обращения: когда запроса нет,
    # адаптер отдаёт 0, и проверки 1-3 читали 0 вместо значения.
    # Защёлка срабатывает на rdy_d2 - в этот момент ad_rdata уже верен.
    n.outvar(u"rdata_h",
             IF(n, I(n, u"rdy_d2"),
                SEL(n, I(n, u"hdl_d"), I(n, u"ad_rdata"), I(n, H % 0xFF),
                    fbd_xml.COL_BLK + 60),
                I(n, u"rdata_h"), fbd_xml.COL_BLK + 120))
    n.outvar(u"RData", I(n, u"rdata_h"), fbd_xml.COL_BLK + 220)
    n.outvar(u"Ack", I(n, u"rdy_d2"))
    n.outvar(u"ev", I(n, H % EV_NONE))
    n.outvar(u"ev", IF(n, I(n, u"cons"), I(n, H % EV_CONSOLE), I(n, u"ev"),
                       fbd_xml.COL_BLK + 140))
    n.outvar(u"ev", IF(n, I(n, u"p_diag"), I(n, H % EV_DIAG), I(n, u"ev"),
                       fbd_xml.COL_BLK + 280))
    n.outvar(u"ev", IF(n, I(n, u"p_stub"), I(n, H % EV_UNMAPPED), I(n, u"ev"),
                       fbd_xml.COL_BLK + 420))
    n.outvar(u"ev", IF(n, I(n, u"ovf_hit"), I(n, H % EV_RANGE), I(n, u"ev"),
                       fbd_xml.COL_BLK + 560))
    n.outvar(u"ev", IF(n, I(n, u"chf_hit"), I(n, H % EV_FAULT), I(n, u"ev"),
                       fbd_xml.COL_BLK + 700))
    n.outvar(u"ev", IF(n, I(n, u"bad_kind"), I(n, H % EV_KIND), I(n, u"ev"),
                       fbd_xml.COL_BLK + 840))
    log_event(p, n, NE(n, I(n, u"ev"), I(n, H % EV_NONE), fbd_xml.COL_BLK + 980),
              u"ev")
    return p


# ======================================================================
# ИНИЦИАЛИЗАЦИЯ КАРТЫ ПОРТОВ
# ======================================================================
def make_io_map_init():
    p = Pou(u"FB_IO_MapInit", u"functionBlock",
            doc=u"Заливка карты портов GVL_IO_Map на ПЕРВОМ скане.\n"
                u"\tКарта - это данные: её пишет схема (демонстрационная карта из\n"
                u"\tMAP_DEMO), а в реальном проекте она задаётся из HMI/online.\n"
                u"\tГейт 'первый скан' - не GVL_CPM.Init_Done (его выставляет\n"
                u"\tFB_CPM_MemInit в том же скане, поэтому гейт был бы всегда FALSE),\n"
                u"\tа собственный признак GVL_IO_Map.Map_Ready.\n"
                u"\tПараметры защит задаются здесь же и дальше только читаются, если\n"
                u"\tпользователь не изменит их из HMI.")
    p.var_in(u"Enable", u"BOOL", u"выполнять инициализацию")
    p.var_out(u"Done", u"BOOL", u"инициализация выполнена в этом скане")
    p.var(u"notdone", u"BOOL", u"карта ещё не инициализирована")

    n = p.network(u"СЕТЬ 1. Гейт первого скана (признак готовности карты)")
    n.outvar(u"notdone", AND(n, I(n, u"Enable"),
                             NOT(n, I(n, u"GVL_IO_Map.Map_Ready"),
                                 fbd_xml.COL_BLK + 200), fbd_xml.COL_BLK + 320))

    n = p.network(u"СЕТЬ 2. Дескрипторы демонстрационных портов (MAP_DEMO)")
    for port, kind, idx, num, den, inv, _txt in MAP_DEMO:
        t = lambda f: u"GVL_IO_Map.Map[%d].%s" % (port, f)
        n.outvar(t(u"Kind"), IF(n, I(n, u"notdone"), I(n, H % kind), I(n, t(u"Kind"))))
        n.outvar(t(u"Index"), IF(n, I(n, u"notdone"), I(n, u"INT#%d" % idx),
                                 I(n, t(u"Index")), fbd_xml.COL_BLK + 160))
        if num != 1 or den != 1:
            n.outvar(t(u"ScaleNum"), IF(n, I(n, u"notdone"), I(n, u"INT#%d" % num),
                                        I(n, t(u"ScaleNum")), fbd_xml.COL_BLK + 320))
            n.outvar(t(u"ScaleDen"), IF(n, I(n, u"notdone"), I(n, u"INT#%d" % den),
                                        I(n, t(u"ScaleDen")), fbd_xml.COL_BLK + 480))
        if inv:
            n.outvar(t(u"Invert"), IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                                      I(n, t(u"Invert")), fbd_xml.COL_BLK + 640))
        n.outvar(t(u"Fault"), IF(n, I(n, u"notdone"), I(n, u"FALSE"),
                                 I(n, t(u"Fault")), fbd_xml.COL_BLK + 800))

    n = p.network(u"СЕТЬ 3. Параметры защит и признак готовности карты")
    n.outvar(u"GVL_IO_Map.MissingPortMode",
             IF(n, I(n, u"notdone"), I(n, H % MODE_STUB),
                I(n, u"GVL_IO_Map.MissingPortMode")))
    n.outvar(u"GVL_IO_Map.Adapter_Enable",
             IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                I(n, u"GVL_IO_Map.Adapter_Enable"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO_Map.Watchdog_Enable",
             IF(n, I(n, u"notdone"), I(n, u"TRUE"),
                I(n, u"GVL_IO_Map.Watchdog_Enable"), fbd_xml.COL_BLK + 200))
    n.outvar(u"GVL_IO_Map.Limit_Scans",
             IF(n, I(n, u"notdone"), I(n, u"UDINT#100"),
                I(n, u"GVL_IO_Map.Limit_Scans"), fbd_xml.COL_BLK + 400))
    n.outvar(u"GVL_IO_Map.Limit_Scans_Per_Tact",
             IF(n, I(n, u"notdone"), I(n, u"UDINT#100"),
                I(n, u"GVL_IO_Map.Limit_Scans_Per_Tact"), fbd_xml.COL_BLK + 600))
    n.outvar(u"GVL_IO_Map.Tacts_Per_Scan",
             IF(n, I(n, u"notdone"), I(n, u"WORD#1"),
                I(n, u"GVL_IO_Map.Tacts_Per_Scan"), fbd_xml.COL_BLK + 800))
    n.outvar(u"GVL_IO_Map.Map_Ready", I(n, u"TRUE"))
    n.outvar(u"Done", I(n, u"notdone"))
    return p


# ======================================================================
# WATCHDOG
# ======================================================================
def make_watchdog():
    p = Pou(u"FB_Watchdog", u"functionBlock",
            doc=u"Сторожевой таймер эмулятора (без таймеров: время = СКАНЫ).\n"
                u"\tПервый счётчик - Busy_Scans: сколько сканов подряд такт начат и\n"
                u"\tне завершён (Tact_Busy = TRUE). Как только такт завершён или\n"
                u"\tпроцессор стоит, счётчик обнуляется. Если он превысил Limit_Scans:\n"
                u"\t  * Timeout := TRUE (защёлкивается до РУЧНОГО сброса Reset с HMI);\n"
                u"\t  * Error_Code := E_TIMEOUT;\n"
                u"\t  * снимок PC/IR/PSW запоминается В МОМЕНТ срабатывания;\n"
                u"\t  * Halted := TRUE - программа останавливает эмулятор.\n"
                u"\tТакт, ожидающий ответа аппаратного слоя (команда IN/OUT), считается\n"
                u"\tзанятым: неответившее устройство останавливает эмулятор - ровно то,\n"
                u"\tчего от watchdog и ждут. Ожидание функции CP/M (трап) тактом НЕ\n"
                u"\tсчитается: там процессор не выполняется, иначе CONIN, ждущий\n"
                u"\tоператора, снимал бы эмулятор в аварию.\n"
                u"\tВторой счётчик - контроль Tacts_Per_Scan: если за сканы подряд\n"
                u"\tвыполняется МЕНЬШЕ тактов, чем запрошено настройкой, значит\n"
                u"\tнастройка нереалистична: Tacts_Per_Scan сбрасывается в 1\n"
                u"\t(безопасный режим), событие EV_SAFE пишется в журнал.\n"
                u"\tВРЕМЯ СКАНА НЕ ИЗМЕРЯЕТСЯ через CAA TickUtil: считается число\n"
                u"\tсканов счётчиком - так результат детерминирован и не зависит от\n"
                u"\tрантайма (план 04_ПЛАН_CPM.md, раздел 5.5).")
    p.var_in(u"Enable", u"BOOL", u"наблюдение за тактом включено")
    p.var_in(u"Tact_Busy", u"BOOL", u"такт начался и не завершён")
    p.var_in(u"Tact_Done", u"BOOL", u"такт завершён в этом скане")
    p.var_in(u"Limit_Scans", u"UDINT", u"предел сканов на один такт")
    p.var_in(u"Limit_Scans_Per_Tact", u"UDINT", u"предел для 2-го счётчика")
    p.var_in(u"Tacts_Per_Scan", u"WORD", u"сколько тактов за скан запрошено")
    p.var_in(u"Step_Cnt", u"WORD", u"номер выполненного такта (из GVL_CPU)")
    p.var_in(u"Reset", u"BOOL", u"ручной сброс с HMI")
    p.var_in(u"PC", u"WORD", u"PC для снимка")
    p.var_in(u"IR", u"BYTE", u"регистр команды для снимка")
    p.var_in(u"PSW", u"BYTE", u"флаги для снимка")
    p.var_out(u"Timeout", u"BOOL", u"сработал тайм-аут такта")
    p.var_out(u"Halted", u"BOOL", u"требование остановить эмулятор")
    p.var_out(u"Error_Code", u"BYTE", u"код аварии (E_TIMEOUT / E_NONE после сброса)")
    p.var_out(u"Scan_Cnt", u"UDINT", u"счётчик сканов задачи")
    p.var_out(u"Busy_Scans", u"UDINT", u"сканов в текущем незавершённом такте")
    p.var_out(u"Tact_Cnt", u"UDINT", u"счётчик завершённых тактов (по Tact_Done)")
    p.var_out(u"Snapshot_PC", u"WORD", u"PC на момент аварии")
    p.var_out(u"Snapshot_IR", u"BYTE", u"регистр команды на момент аварии")
    p.var_out(u"Snapshot_PSW", u"BYTE", u"флаги на момент аварии")
    p.var_out(u"Snapshot_Valid", u"BOOL", u"снимок достоверен")
    p.var_out(u"Timeout_Cnt", u"UDINT", u"число срабатываний watchdog")
    p.var_out(u"Slow_Cnt", u"UDINT", u"число срабатываний 2-го счётчика")
    p.var_out(u"Safe_Mode", u"BOOL", u"Tacts_Per_Scan сброшен в 1")
    p.var_out(u"Tacts_Per_Scan_Out", u"WORD", u"значение для GVL_IO_Map.Tacts_Per_Scan")
    p.var(u"scan_n", u"UDINT", u"следующее значение счётчика сканов")
    p.var(u"busy", u"BOOL", u"такт занят (с учётом разрешения наблюдения)")
    p.var(u"done_g", u"BOOL", u"такт завершён (с учётом разрешения наблюдения)")
    p.var(u"c0", u"UDINT", u"счётчик занятости: обнуление")
    p.var(u"c1", u"UDINT", u"счётчик занятости: инкремент")
    p.var(u"over", u"BOOL", u"предел сканов превышен")
    p.var(u"trip", u"BOOL", u"момент срабатывания watchdog")
    p.var(u"to_l", u"BOOL", u"защёлка тайм-аута")
    p.var(u"to_n", u"BOOL", u"новое значение защёлки")
    p.var(u"tc_inc", u"UDINT", u"счётчик срабатываний + 1")
    p.var(u"tact_c", u"UDINT", u"счётчик завершённых тактов")
    p.var(u"snap_pc", u"WORD", u"снимок PC")
    p.var(u"snap_ir", u"BYTE", u"снимок IR")
    p.var(u"snap_psw", u"BYTE", u"снимок PSW")
    p.var(u"snap_ok", u"BOOL", u"снимок сделан")
    p.var(u"err_l", u"BYTE", u"защёлка кода аварии")
    p.var(u"step_prev", u"WORD", u"номер такта на прошлом скане")
    p.var(u"got_w", u"WORD", u"сколько тактов выполнено за этот скан")
    p.var(u"want", u"WORD", u"сколько тактов запрошено (не меньше 1)")
    p.var(u"short", u"BOOL", u"выполнено меньше запрошенного")
    p.var(u"sc0", u"UDINT", u"счётчик 'коротких' сканов")
    p.var(u"sc1", u"UDINT", u"счётчик 'коротких' сканов + 1")
    p.var(u"Short_Cnt_l", u"UDINT", u"сканов подряд с недостатком тактов")
    p.var(u"saf_n", u"BOOL", u"сработал второй счётчик")
    p.var(u"safe_l", u"BOOL", u"защёлка безопасного режима")
    p.var(u"slow_c", u"UDINT", u"счётчик срабатываний 2-го порога")
    p.var(u"ev", u"BYTE", u"код события")
    p.var(u"ev_i", u"INT", u"индекс журнала событий")

    # ---- 1. счётчик сканов ----
    n = p.network(u"СЕТЬ 1. Счётчик сканов задачи (время считаем сканами, не таймером)")
    n.outvar(u"scan_n", ADD(n, I(n, u"Scan_Cnt"), I(n, U1)))
    n.outvar(u"Scan_Cnt", I(n, u"scan_n"))

    # ---- 2. счётчик незавершённого такта ----
    n = p.network(u"СЕТЬ 2. Сканов в текущем такте: обнуляется, как только такт завершён")
    n.outvar(u"busy", AND(n, I(n, u"Enable"), I(n, u"Tact_Busy")))
    n.outvar(u"done_g", AND(n, I(n, u"Enable"), I(n, u"Tact_Done"),
                            fbd_xml.COL_BLK + 200))
    n.outvar(u"c0", IF(n, I(n, u"busy"), I(n, u"Busy_Scans"), I(n, u"UDINT#0"),
                       fbd_xml.COL_BLK + 340))
    n.outvar(u"c1", IF(n, I(n, u"busy"), ADD(n, I(n, u"c0"), I(n, U1),
                                             fbd_xml.COL_BLK + 480),
                       I(n, u"c0"), fbd_xml.COL_BLK + 620))
    n.outvar(u"Busy_Scans", I(n, u"c1"))
    n.outvar(u"tact_c", IF(n, I(n, u"done_g"), ADD(n, I(n, u"Tact_Cnt"), I(n, U1),
                                                   fbd_xml.COL_BLK + 760),
                           I(n, u"Tact_Cnt"), fbd_xml.COL_BLK + 900))
    n.outvar(u"Tact_Cnt", I(n, u"tact_c"))

    # ---- 3. тайм-аут и снимок ----
    n = p.network(u"СЕТЬ 3. Тайм-аут такта: защёлка, снимок PC/IR/PSW, счётчик")
    n.outvar(u"over", GT(n, I(n, u"Busy_Scans"), I(n, u"Limit_Scans")))
    n.outvar(u"trip", AND(n, I(n, u"over"), AND(n, I(n, u"Enable"),
                                                NOT(n, I(n, u"to_l"),
                                                    fbd_xml.COL_BLK + 200),
                                                fbd_xml.COL_BLK + 340),
                          fbd_xml.COL_BLK + 480))
    n.outvar(u"snap_pc", IF(n, I(n, u"trip"), I(n, u"PC"), I(n, u"snap_pc"),
                            fbd_xml.COL_BLK + 620))
    n.outvar(u"snap_ir", IF(n, I(n, u"trip"), I(n, u"IR"), I(n, u"snap_ir"),
                            fbd_xml.COL_BLK + 760))
    n.outvar(u"snap_psw", IF(n, I(n, u"trip"), I(n, u"PSW"), I(n, u"snap_psw"),
                             fbd_xml.COL_BLK + 900))
    n.outvar(u"snap_ok", IF(n, I(n, u"trip"), I(n, u"TRUE"), I(n, u"snap_ok"),
                            fbd_xml.COL_BLK + 1040))
    n.outvar(u"tc_inc", ADD(n, I(n, u"Timeout_Cnt"), I(n, U1), fbd_xml.COL_BLK + 1180))
    n.outvar(u"Timeout_Cnt", IF(n, I(n, u"trip"), I(n, u"tc_inc"),
                                I(n, u"Timeout_Cnt"), fbd_xml.COL_BLK + 1320))
    n.outvar(u"to_n", IF(n, I(n, u"Reset"), I(n, u"FALSE"),
                         OR(n, I(n, u"to_l"), I(n, u"trip"), fbd_xml.COL_BLK + 1460),
                         fbd_xml.COL_BLK + 1600))
    n.outvar(u"to_l", I(n, u"to_n"))
    n.outvar(u"Timeout", I(n, u"to_n"))
    n.outvar(u"Halted", I(n, u"to_n"))
    n.outvar(u"err_l", IF(n, I(n, u"Reset"), I(n, H % E_NONE),
                          IF(n, I(n, u"to_n"), I(n, H % E_TIMEOUT), I(n, u"err_l"),
                             fbd_xml.COL_BLK + 1740), fbd_xml.COL_BLK + 1880))
    n.outvar(u"Error_Code", I(n, u"err_l"))
    n.outvar(u"Snapshot_PC", I(n, u"snap_pc"))
    n.outvar(u"Snapshot_IR", I(n, u"snap_ir"))
    n.outvar(u"Snapshot_PSW", I(n, u"snap_psw"))
    n.outvar(u"Snapshot_Valid", I(n, u"snap_ok"))

    # ---- 4. второй счётчик: контроль Tacts_Per_Scan ----
    n = p.network(u"СЕТЬ 4. Второй счётчик: сколько тактов реально даёт скан")
    n.outvar(u"got_w", IF(n, GE(n, I(n, u"Step_Cnt"), I(n, u"step_prev")),
                          SUB(n, I(n, u"Step_Cnt"), I(n, u"step_prev")),
                          I(n, u"WORD#0"), fbd_xml.COL_BLK + 200))
    n.outvar(u"want", IF(n, GT(n, I(n, u"Tacts_Per_Scan"), I(n, u"WORD#0")),
                         I(n, u"Tacts_Per_Scan"), I(n, u"WORD#1"),
                         fbd_xml.COL_BLK + 340))
    n.outvar(u"short", AND(n, I(n, u"Enable"),
                           GT(n, I(n, u"want"), I(n, u"got_w"), fbd_xml.COL_BLK + 480),
                           fbd_xml.COL_BLK + 620))
    n.outvar(u"sc0", IF(n, I(n, u"short"), I(n, u"Short_Cnt_l"), I(n, u"UDINT#0"),
                        fbd_xml.COL_BLK + 760))
    n.outvar(u"sc1", IF(n, I(n, u"short"), ADD(n, I(n, u"sc0"), I(n, U1),
                                               fbd_xml.COL_BLK + 900),
                        I(n, u"sc0"), fbd_xml.COL_BLK + 1040))
    n.outvar(u"Short_Cnt_l", I(n, u"sc1"))
    n.outvar(u"saf_n", AND(n, GT(n, I(n, u"sc1"), I(n, u"Limit_Scans_Per_Tact"),
                                 fbd_xml.COL_BLK + 1180),
                           NOT(n, I(n, u"safe_l"), fbd_xml.COL_BLK + 1320),
                           fbd_xml.COL_BLK + 1460))
    n.outvar(u"safe_l", IF(n, I(n, u"Reset"), I(n, u"FALSE"),
                           OR(n, I(n, u"safe_l"), I(n, u"saf_n"),
                              fbd_xml.COL_BLK + 1600), fbd_xml.COL_BLK + 1740))
    n.outvar(u"slow_c", IF(n, I(n, u"saf_n"), ADD(n, I(n, u"Slow_Cnt"), I(n, U1),
                                                  fbd_xml.COL_BLK + 1880),
                           I(n, u"Slow_Cnt"), fbd_xml.COL_BLK + 2020))
    n.outvar(u"Slow_Cnt", I(n, u"slow_c"))
    n.outvar(u"Safe_Mode", I(n, u"safe_l"))
    n.outvar(u"Tacts_Per_Scan_Out", IF(n, I(n, u"safe_l"), I(n, u"WORD#1"),
                                       I(n, u"want"), fbd_xml.COL_BLK + 2160))
    n.outvar(u"step_prev", I(n, u"Step_Cnt"))

    # ---- 5. события ----
    n = p.network(u"СЕТЬ 5. События watchdog: тайм-аут, безопасный режим, сброс")
    n.outvar(u"ev", I(n, H % EV_NONE))
    n.outvar(u"ev", IF(n, I(n, u"Reset"), I(n, H % EV_RESET), I(n, u"ev"),
                       fbd_xml.COL_BLK + 140))
    n.outvar(u"ev", IF(n, I(n, u"saf_n"), I(n, H % EV_SAFE), I(n, u"ev"),
                       fbd_xml.COL_BLK + 280))
    n.outvar(u"ev", IF(n, I(n, u"trip"), I(n, H % EV_WATCHDOG), I(n, u"ev"),
                       fbd_xml.COL_BLK + 420))
    log_event(p, n, NE(n, I(n, u"ev"), I(n, H % EV_NONE), fbd_xml.COL_BLK + 560),
              u"ev")
    return p

# ======================================================================
# HMI
# ======================================================================
def make_hmi_update():
    p = Pou(u"FB_HMI_Update", u"functionBlock",
            doc=u"Обновление переменных HMI (последняя сеть программы).\n"
                u"\t1) публикует состояние процессора (PC, SP, A, IR, флаги, такт);\n"
                u"\t2) переносит символ с клавиатуры HMI в консоль CP/M\n"
                u"\t   (GVL_CPM.ConIn_Char/ConIn_Ready) - и снимает признак готовности,\n"
                u"\t   чтобы символ не был принят дважды; кнопка ВВОД посылает CR;\n"
                u"\t3) зеркалит журнал консоли и журнал событий в GVL_HMI -\n"
                u"\t   ПО ОДНОМУ БАЙТУ ЗА СКАН по кругу (полное обновление за 256\n"
                u"\t   сканов): копировать массив целиком в FBD нечем, а MEMCPY в этом\n"
                u"\t   проекте не проверен и не используется;\n"
                u"\t4) собирает аварийную информацию (код, порт, счётчик аварий).\n"
                u"\tКнопки ПУСК/СТОП/ШАГ/СБРОС обрабатываются отдельной сетью\n"
                u"\tпрограммы (аварийный останов), потому что они управляют\n"
                u"\tGVL_CPM.CPU_Run и GVL_CPU.Halted.")
    p.var_in(u"Enable", u"BOOL", u"обновлять HMI")
    p.var_out(u"Done", u"BOOL", u"обновление выполнено")
    p.var(u"en", u"BOOL", u"обновление включено")
    p.var(u"key", u"BOOL", u"есть символ для консоли (клавиша или ВВОД)")
    p.var(u"ent", u"BOOL", u"кнопка ВВОД нажата в этом скане (фронт)")
    p.var(u"ent_prev", u"BOOL", u"кнопка ВВОД была нажата на прошлом скане")
    p.var(u"ch", u"BYTE", u"символ для консоли")
    p.var(u"i", u"INT", u"индекс зеркалирования (0..255, по кругу)")
    p.var(u"i_n", u"INT", u"индекс зеркалирования + 1")
    p.var(u"a_code", u"BYTE", u"код аварии из диагностики I/O")
    p.var(u"a_new", u"BOOL", u"авария появилась в этом скане")
    p.var(u"a_prev", u"BOOL", u"авария была в прошлом скане")
    p.var(u"a_cnt", u"UDINT", u"счётчик аварий + 1")
    p.var(u"ev_last_i", u"INT", u"индекс последнего события")
    p.var(u"cnt", u"UDINT", u"счётчик переданных символов + 1 (UDINT: сумма Key_Cnt)")

    n = p.network(u"СЕТЬ 1. Состояние процессора для HMI")
    n.outvar(u"en", I(n, u"Enable"))
    n.outvar(u"GVL_HMI.Cpu_Run", I(n, u"GVL_CPM.CPU_Run"))
    n.outvar(u"GVL_HMI.Cpu_Halted", I(n, u"GVL_CPU.Halted"))
    n.outvar(u"GVL_HMI.Cpu_Step", I(n, u"GVL_CPU.Step_Cnt"))
    n.outvar(u"GVL_HMI.Cpu_PC", I(n, u"GVL_CPM.Reg_PC"))
    n.outvar(u"GVL_HMI.Cpu_SP", I(n, u"GVL_CPM.Reg_SP"))
    n.outvar(u"GVL_HMI.Cpu_A", I(n, u"GVL_CPM.Reg_A"))
    n.outvar(u"GVL_HMI.Cpu_IR", I(n, u"GVL_CPU.Bus_IR"))
    n.outvar(u"GVL_HMI.Cpu_PSW", I(n, u"GVL_CPM.Reg_PSW"))
    n.outvar(u"GVL_HMI.Cpu_Trap", I(n, u"GVL_CPM.Trap_Active"))
    n.outvar(u"GVL_HMI.Cpu_Wait", I(n, u"GVL_IO.Wait"))

    n = p.network(u"СЕТЬ 2. Клавиатура HMI -> консоль CP/M (и кнопка ВВОД = CR)")
    # ВВОД берётся по ФРОНТУ: пока кнопку держат, посылается ровно один CR
    n.outvar(u"ent", AND(n, I(n, u"GVL_HMI.Btn_Enter"),
                         NOT(n, I(n, u"ent_prev"), fbd_xml.COL_BLK + 200),
                         fbd_xml.COL_BLK + 340))
    n.outvar(u"ent_prev", I(n, u"GVL_HMI.Btn_Enter"))
    n.outvar(u"key", OR(n, I(n, u"GVL_HMI.Key_Ready"), I(n, u"ent"),
                        fbd_xml.COL_BLK + 480))
    n.outvar(u"ch", IF(n, I(n, u"ent"), I(n, H % 0x0D),
                       I(n, u"GVL_HMI.Key_Char"), fbd_xml.COL_BLK + 620))
    n.outvar(u"GVL_CPM.ConIn_Char", IF(n, I(n, u"key"), I(n, u"ch"),
                                       I(n, u"GVL_CPM.ConIn_Char"),
                                       fbd_xml.COL_BLK + 480))
    n.outvar(u"GVL_CPM.ConIn_Ready", IF(n, I(n, u"key"), I(n, u"TRUE"),
                                        I(n, u"GVL_CPM.ConIn_Ready"),
                                        fbd_xml.COL_BLK + 620))
    n.outvar(u"GVL_HMI.Key_Ready", I(n, u"FALSE"))
    n.outvar(u"GVL_HMI.Key_Last", IF(n, I(n, u"key"), I(n, u"ch"),
                                     I(n, u"GVL_HMI.Key_Last"),
                                     fbd_xml.COL_BLK + 760))
    n.outvar(u"cnt", ADD(n, I(n, u"GVL_HMI.Key_Cnt"), I(n, U1), fbd_xml.COL_BLK + 900))
    n.outvar(u"GVL_HMI.Key_Cnt", IF(n, I(n, u"key"), I(n, u"cnt"),
                                    I(n, u"GVL_HMI.Key_Cnt"), fbd_xml.COL_BLK + 1040))

    n = p.network(u"СЕТЬ 3. Зеркало журналов: консоль и события (один байт за скан)")
    # MOD вместо маски INT#255 - см. пояснение выше.
    n.outvar(u"i", MOD(n, I(n, u"GVL_HMI.Con_Idx"), I(n, u"INT#256")))
    n.outvar(u"i_n", MOD(n, ADD(n, I(n, u"i"), I(n, u"INT#1"), fbd_xml.COL_BLK + 200),
                         I(n, u"INT#256"), fbd_xml.COL_BLK + 340))
    cb = u"GVL_HMI.Con_Buffer[i]"
    cl = u"GVL_CPM.Con_Log[i]"
    n.outvar(cb, IF(n, I(n, u"GVL_HMI.Btn_Clear_Log"), I(n, H % 0x00), I(n, cl),
                    fbd_xml.COL_BLK + 480))
    eb = u"GVL_HMI.Event_Log[i]"
    el = u"GVL_IO.Event_Log[i]"
    n.outvar(eb, IF(n, I(n, u"GVL_HMI.Btn_Clear_Log"), I(n, H % 0x00), I(n, el),
                    fbd_xml.COL_BLK + 620))
    n.outvar(u"GVL_HMI.Con_Idx", I(n, u"i_n"))
    n.outvar(u"GVL_HMI.Con_Len", I(n, u"GVL_CPM.Con_Log_Len"))
    n.outvar(u"GVL_HMI.Event_Idx", I(n, u"GVL_IO.Event_Idx"))
    n.outvar(u"ev_last_i", IF(n, GT(n, I(n, u"GVL_IO.Event_Idx"), I(n, u"INT#0")),
                              SUB(n, I(n, u"GVL_IO.Event_Idx"), I(n, u"INT#1")),
                              I(n, u"INT#%d" % EV_IDX_MAX), fbd_xml.COL_BLK + 760))
    n.outvar(u"GVL_HMI.Event_Last", I(n, u"GVL_IO.Event_Log[ev_last_i]"))
    n.outvar(u"GVL_HMI.Event_Cnt", I(n, u"GVL_IO.Diag.Event_Cnt"))

    n = p.network(u"СЕТЬ 4. Индикаторы ввода-вывода и аварии")
    n.outvar(u"GVL_HMI.Io_Last_Port", I(n, u"GVL_IO.Diag.Last_Port"))
    n.outvar(u"GVL_HMI.Io_Last_Kind", I(n, u"GVL_IO.Diag.Last_Kind"))
    n.outvar(u"GVL_HMI.Io_Last_Index", I(n, u"GVL_IO.Diag.Last_Index"))
    n.outvar(u"GVL_HMI.Io_Last_Value", I(n, u"GVL_IO.Diag.Last_Value"))
    n.outvar(u"GVL_HMI.Io_Last_RW", I(n, u"GVL_IO.Diag.Last_RW"))
    n.outvar(u"GVL_HMI.Io_Read_Cnt", I(n, u"GVL_IO.Diag.Read_Cnt"))
    n.outvar(u"GVL_HMI.Io_Write_Cnt", I(n, u"GVL_IO.Diag.Write_Cnt"))
    n.outvar(u"GVL_HMI.Io_Unmapped_Cnt", I(n, u"GVL_IO.Diag.Unmapped_Cnt"))
    n.outvar(u"GVL_HMI.Io_Diag_Cnt", I(n, u"GVL_IO.Diag.Diag_Cnt"))
    n.outvar(u"GVL_HMI.Io_Fault_Cnt", I(n, u"GVL_IO.Diag.Fault_Cnt"))
    n.outvar(u"GVL_HMI.Io_Range_Cnt", I(n, u"GVL_IO.Diag.Range_Cnt"))
    n.outvar(u"GVL_HMI.Io_Console_Cnt", I(n, u"GVL_IO.Diag.Console_Cnt"))
    n.outvar(u"GVL_HMI.Io_Mode", I(n, u"GVL_IO_Map.MissingPortMode"))
    n.outvar(u"GVL_HMI.Io_Wait", I(n, u"GVL_IO.Wait"))

    n = p.network(u"СЕТЬ 5. Аварийная информация: код, порт, счётчик срабатываний")
    n.outvar(u"a_code", I(n, u"GVL_IO.Diag.Err_Code"))
    n.outvar(u"a_new", AND(n, NE(n, I(n, u"a_code"), I(n, H % 0x00)),
                           NOT(n, I(n, u"a_prev"), fbd_xml.COL_BLK + 200),
                           fbd_xml.COL_BLK + 340))
    n.outvar(u"a_prev", NE(n, I(n, u"a_code"), I(n, H % 0x00),
                           fbd_xml.COL_BLK + 480))
    n.outvar(u"a_cnt", ADD(n, I(n, u"GVL_HMI.Alarm_Cnt"), I(n, U1),
                           fbd_xml.COL_BLK + 620))
    n.outvar(u"GVL_HMI.Alarm_Cnt", IF(n, I(n, u"a_new"), I(n, u"a_cnt"),
                                      I(n, u"GVL_HMI.Alarm_Cnt"),
                                      fbd_xml.COL_BLK + 760))
    n.outvar(u"GVL_HMI.Alarm_Code", I(n, u"a_code"))
    n.outvar(u"GVL_HMI.Alarm_Port", I(n, u"GVL_IO.Diag.Err_Port"))
    n.outvar(u"GVL_HMI.Alarm_Active", NE(n, I(n, u"a_code"), I(n, H % 0x00),
                                         fbd_xml.COL_BLK + 900))
    n.outvar(u"Done", I(n, u"en"))
    return p


ALL = (make_io_read, make_io_write, make_io_analog_in, make_io_analog_out,
       make_adapter_sim, make_adapter_softplc, make_io_dispatch,
       make_io_map_init, make_watchdog, make_hmi_update)

NAMES = (u"FB_IO_Read", u"FB_IO_Write", u"FB_IO_AnalogIn", u"FB_IO_AnalogOut",
         u"FB_IO_Adapter_Sim", u"FB_IO_Adapter_SoftPLC", u"FB_IO_Dispatch",
         u"FB_IO_MapInit", u"FB_Watchdog", u"FB_HMI_Update")
