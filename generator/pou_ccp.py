# -*- coding: utf-8 -*-
u"""FB_CCP - консольный процессор CP/M 2.2 на FBD (этап 3.4).

ЧТО ЭТО. CCP настоящего CP/M - это 8080-код в системной области, который
печатает приглашение "A>". Здесь CCP - НАБОР СХЕМ FBD: он делает то же самое,
но не занимает память эмулируемой машины. Для программы разница не видна: она
видит приглашение, буфер командной строки 0080h, FCB первого аргумента по
005Ch и получает управление на 0100h.

ПОЧЕМУ НЕ ЧЕРЕЗ ТРАП BDOS. Задание требует, чтобы DIR работал "через BDOS
17/18". Встроенные команды обращаются к ТОМУ ЖЕ дисковому движку
FB_CPM_DirEngine с теми же операциями OP_SEARCH_FIRST / OP_SEARCH_NEXT, что и
FB_BDOS_SEARCHFIRST / FB_BDOS_SEARCHNEXT. Вызвать FB_BDOS_* из CCP нельзя: они
работают только по трапу (PC на 0F000h), а CCP уже работает по своему трапу.

КАРТА ПАМЯТИ, КОТОРУЮ ИСПОЛЬЗУЕТ CCP:
  005Ch..007Fh - FCB первого аргумента команды (как в настоящем CP/M);
  0080h        - длина хвоста команды; 0081h.. - текст хвоста;
  0F300h       - FCB, которым загрузчик ищет и грузит имя.COM;
  0F340h..     - 11-байтовое поле разбираемого слова (буфер CCP).

ПОСЛЕДОВАТЕЛЬНОСТЬ РАБОТЫ (поле GVL_CPM.CCP_Phase):
  0  инициализация;  1-2 приглашение;  3 ввод строки (CR, ^C, BS);
  5-6 CR и LF;  7-16 разбор строки (имя команды, аргумент -> FCB, хвост);
  20-21 диспетчер;  30-34 DIR; 40-44 TYPE; 50-51 ERA; 60-61 REN;
  70-75 SAVE; 80 USER; 85-86 EXIT; 90-92 внешняя команда;
  33 "NO FILE"; 93 "<ИМЯ>?".

ПРИЁМЫ, БЕЗ КОТОРЫХ ЭТА СХЕМА НЕ РАБОТАЕТ:
  * все выборы написаны через IF(cond, A, B) - обёртку над SEL с явной
    полярностью (перепутанные IN0/IN1 в FBD не видит ни компилятор, ни
    проверка связей);
  * один выход = одна связь, выходы вызовов FB защёлкиваются (правила 4.3,
    8.2, 9.1, 11.2 журнала сборки);
  * переходы фаз собраны в ОДНУ таблицу TRANS и одну цепочку SEL: так
    состояние автомата видно целиком, а не размазано по сетям.

ЦЕНА РЕШЕНИЯ (честно). Консоль - однобайтовый порт: за скан выводится ОДИН
знак. Приглашение - 2 скана, имя файла в DIR - 14 сканов, TYPE - по знаку за
скан, проход по каталогу - по записи за скан.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou
import pou_cpm_defs as D
from pou_cpm_defs import (I, NOT, AND, OR, EQ, NE, LT, GT, GE, LE, IF, SEL, ADD,
                          SUB, MUL, SHL, SHR, W2B, ORL, ANDL, CHAIN, UPCH,
                          emit_char, B, H, W, WH, U1)

# ---- фазы CCP ----
PH_INIT, PH_DRV, PH_PROMPT, PH_READ = 0, 1, 2, 3
PH_CR, PH_LF = 5, 6
PH_PINIT, PH_SKIP, PH_TOK, PH_ENDTOK, PH_TAILINI, PH_TAIL = 7, 8, 9, 13, 14, 16
PH_DISP, PH_ROUTE = 20, 21
PH_DIR_S, PH_DIR_W, PH_DIR_P, PH_DIR_N = 30, 31, 32, 34
PH_TYP_S, PH_TYP_W, PH_TYP_R, PH_TYP_RW, PH_TYP_P = 40, 41, 42, 43, 44
PH_ERA_S, PH_ERA_W = 50, 51
PH_REN_S, PH_REN_W = 60, 61
PH_SAV_S, PH_SAV_M, PH_SAV_W, PH_SAV_X, PH_SAV_XW = 70, 72, 73, 74, 75
PH_USER = 80
PH_EXIT, PH_EXIT2 = 85, 86
PH_EXT_S, PH_EXT_W, PH_EXT_J = 90, 91, 92
PH_ERR, PH_ERRU = 33, 93

# ---- коды команд ----
A_NONE, A_DIR, A_TYPE, A_ERA, A_REN = 0, 1, 2, 3, 4
A_SAVE, A_USER, A_EXIT, A_EXT = 5, 6, 7, 8

CR = 0x0D
LF = 0x0A
BS = 0x08
CTRLC = 0x03
SP = 0x20
EOF_TXT = 0x1A           # Ctrl-Z - конец текстового файла (как в CP/M)
WILD = 0x3F              # '?'
ZERO = 0x30              # '0'

LINEBUF = 0x0080         # буфер командной строки: [0]=длина, [1..]=текст
FCB1 = 0x005C            # FCB первого аргумента
FCB1_NAME = FCB1 + 1
FCB1_EXT = FCB1 + 9
FCB1_NEW = FCB1 + 16     # новое имя для BDOS 23 (RENAME)
DIRBUF = 0x0080          # куда движок кладёт найденную запись каталога
DIR_CHARS = 14           # 8 имя + '.' + 3 расширение + CR + LF

# Таблица переходов автомата фаз: (фаза, признак, куда перейти).
# "always" - безусловный переход; "zero" - фаза 0; "ret" - переменная ret_ph;
# "rt" - фаза выбранной команды. Для одной фазы безусловный переход идёт
# ПЕРВЫМ: в цепочке CHAIN последний шаг имеет приоритет.
TRANS = (
    (PH_INIT, u"always", PH_DRV),
    (PH_DRV, u"always", PH_PROMPT),
    (PH_PROMPT, u"always", PH_READ),
    (PH_READ, u"always", PH_READ),
    (PH_READ, u"is_cr", PH_CR),
    (PH_READ, u"is_cc", u"zero"),
    (PH_CR, u"always", PH_LF),
    (PH_LF, u"always", PH_PINIT),
    (PH_PINIT, u"always", PH_SKIP),
    (PH_SKIP, u"always", PH_TOK),
    (PH_SKIP, u"at_end", u"ret"),
    (PH_TOK, u"always", PH_TOK),
    (PH_TOK, u"end_word", PH_ENDTOK),
    # ПОРЯДОК ПРАВИЛ РЕШАЕТ (фаза B), и решает ОБРАТНО тому, что кажется:
    # CHAIN строит ЦЕПОЧКУ SEL, поэтому приоритет имеет ПОСЛЕДНЕЕ правило,
    # а не первое. Пока в таблице стояло
    #     (ENDTOK, always, TAILINI), (ENDTOK, tok_p0, SKIP), (ENDTOK, only_arg, ret)
    # побеждало ПОСЛЕДНЕЕ (only_arg), а "always" не срабатывало никогда -
    # CCP застревал в фазе 13 (наблюдалось CCP_Phase = 13, CCP_Cnt = 0..1).
    # Правильный порядок: сначала УСЛОВНЫЕ, последним - безусловное.
    (PH_ENDTOK, u"tok_p0", PH_SKIP),
    (PH_ENDTOK, u"only_arg", u"ret"),
    (PH_ENDTOK, u"always", PH_TAILINI),
    (PH_TAILINI, u"always", PH_TAIL),
    (PH_TAILINI, u"at_end", u"ret"),
    (PH_TAIL, u"always", PH_TAIL),
    (PH_TAIL, u"tl_end", u"ret"),
    (PH_DISP, u"always", PH_ROUTE),
    (PH_ROUTE, u"always", u"rt"),
    (PH_DIR_S, u"always", PH_DIR_W),
    (PH_DIR_W, u"always", PH_DIR_W),
    (PH_DIR_W, u"e_ok", PH_DIR_P),
    (PH_DIR_W, u"e_ff", u"zero"),
    (PH_DIR_W, u"e_ff_nf", PH_ERR),
    (PH_DIR_P, u"always", PH_DIR_P),
    (PH_DIR_P, u"cend32", PH_DIR_N),
    (PH_DIR_N, u"always", PH_DIR_W),
    (PH_TYP_S, u"always", PH_TYP_W),
    (PH_TYP_W, u"always", PH_TYP_W),
    (PH_TYP_W, u"e_ok", PH_TYP_R),
    (PH_TYP_W, u"e_ff", PH_ERR),
    (PH_TYP_R, u"always", PH_TYP_RW),
    (PH_TYP_RW, u"always", PH_TYP_RW),
    # ПОРЯДОК ВАЖЕН: в CHAIN последний шаг имеет приоритет, поэтому общее
    # условие ("движок ответил") идёт РАНЬШЕ уточняющего ("ответ = конец
    # файла"). Иначе уточнение никогда не сработает.
    (PH_TYP_RW, u"e_done", PH_TYP_P),
    (PH_TYP_RW, u"e_bad", u"zero"),
    (PH_TYP_P, u"always", PH_TYP_P),
    (PH_TYP_P, u"eof_p", u"zero"),
    (PH_TYP_P, u"cend44", PH_TYP_R),
    (PH_ERA_S, u"always", PH_ERA_W),
    (PH_ERA_W, u"always", PH_ERA_W),
    (PH_ERA_W, u"e_done", u"zero"),
    (PH_ERA_W, u"e_ff", PH_ERR),
    (PH_REN_S, u"always", PH_REN_W),
    (PH_REN_W, u"always", PH_REN_W),
    (PH_REN_W, u"e_done", u"zero"),
    (PH_REN_W, u"e_ff", PH_ERR),
    (PH_SAV_S, u"always", PH_PINIT),
    (PH_SAV_M, u"always", PH_SAV_W),
    (PH_SAV_W, u"always", PH_SAV_W),
    (PH_SAV_W, u"e_done", PH_SAV_X),
    (PH_SAV_W, u"e_ff", u"zero"),
    (PH_SAV_X, u"always", PH_SAV_XW),
    (PH_SAV_XW, u"always", PH_SAV_XW),
    (PH_SAV_XW, u"e_done", PH_SAV_X),
    (PH_SAV_XW, u"tend", u"zero"),
    (PH_USER, u"always", u"zero"),
    (PH_EXIT, u"always", PH_EXIT2),
    (PH_EXIT2, u"always", u"zero"),
    (PH_EXT_S, u"always", PH_EXT_W),
    (PH_EXT_W, u"always", PH_EXT_W),
    (PH_EXT_W, u"ld_done", PH_EXT_J),
    (PH_EXT_J, u"always", u"zero"),
    (PH_ERR, u"always", PH_ERR),
    (PH_ERR, u"cend33", u"zero"),
    (PH_ERRU, u"always", PH_ERRU),
    (PH_ERRU, u"cend93", u"zero"),
)


def _at(n, code):
    u"""Признак текущей фазы CCP."""
    return EQ(n, I(n, u"ph"), I(n, B % code))


def _cmd_is(n, name, base):
    u"""Сравнение 8 байт имени команды с образцом (образец дополняется пробелами)."""
    parts = []
    for i in range(8):
        c = name[i] if i < len(name) else u" "
        parts.append(EQ(n, I(n, u"GVL_MEM.Memory[%s]" % (WH % (base + i))),
                        I(n, H % ord(c)), fbd_xml.COL_BLK + 200 + 120 * i))
    return ANDL(n, parts, x0=fbd_xml.COL_BLK + 1400)


def make_ccp():
    p = Pou(u"FB_CCP", u"functionBlock",
            doc=u"Консольный процессор CP/M 2.2 (этап 3.4).\n"
                u"\tВход Enable - активен трап CCP (PC = 0F100h, куда ведёт\n"
                u"\tWBOOT). Пока Enable держится, автомат фаз проходит весь путь:\n"
                u"\tприглашение -> ввод строки -> разбор -> выполнение команды.\n"
                u"\tВСТРОЕННЫЕ КОМАНДЫ: DIR (через тот же дисковый движок, что\n"
                u"\tBDOS 17/18), TYPE (OPEN + READ SEQ), ERA (DELETE), REN\n"
                u"\t(RENAME), SAVE (MAKE + WRITE SEQ), USER, EXIT.\n"
                u"\tВНЕШНИЕ КОМАНДЫ: имя.COM ищется в каталоге и грузится в TPA\n"
                u"\tблоком FB_COM_Loader; затем SP := 0F200h, обнуление регистров\n"
                u"\tбутстрап-заглушкой (0F380h) и переход на 0100h.\n"
                u"\tОбрабатываются: пустая строка, Ctrl-C, забои, неизвестная\n"
                u"\tкоманда ('<ИМЯ>?'), отсутствие файла ('NO FILE').")
    p.var_in(u"Enable", u"BOOL", u"трап CCP активен")
    p.var_out(u"Done", u"BOOL", u"команда выполнена (квитанция трапу)")
    p.var_out(u"Busy", u"BOOL", u"CCP занят")
    loc = (
        (u"hit", u"BOOL", u"CCP работает (то же, что Enable)"),
        (u"ph", u"BYTE", u"фаза автомата CCP"),
        (u"ph_next", u"BYTE", u"следующая фаза"),
        (u"done_gate", u"BOOL", u"команда выполнена"),
        (u"ch", u"BYTE", u"текущий знак"),
        (u"out_ch", u"BYTE", u"выводимый знак"),
        (u"out_i", u"INT", u"индекс в журнале консоли"),
        (u"linelen", u"WORD", u"длина введённой строки"),
        (u"ll_b", u"BYTE", u"длина строки как байт"),
        (u"got", u"BOOL", u"знак получен от консоли"),
        (u"is_cr", u"BOOL", u"получен CR"),
        (u"is_bs", u"BOOL", u"получен забои"),
        (u"is_cc", u"BOOL", u"получен Ctrl-C"),
        (u"room", u"BOOL", u"в буфере строки есть место"),
        (u"store", u"BOOL", u"знак запоминается"),
        (u"bs_ok", u"BOOL", u"забои убирает знак"),
        (u"lv1", u"WORD", u"длина строки, шаг 1"),
        (u"lv2", u"WORD", u"длина строки, шаг 2"),
        (u"drv_ch", u"BYTE", u"буква текущего диска"),
        (u"echo_g", u"BOOL", u"эхо введённого знака"),
        (u"echo_c", u"BYTE", u"знак эха"),
        (u"tb", u"WORD", u"куда писать разбираемое слово"),
        (u"pp", u"WORD", u"указатель разбора в буфере строки"),
        (u"pend", u"WORD", u"конец строки"),
        (u"at_end", u"BOOL", u"строка разобрана до конца"),
        (u"fpos", u"BYTE", u"позиция в 11-байтовом поле имени"),
        (u"fp_w", u"WORD", u"позиция как слово"),
        (u"fp_a", u"BYTE", u"позиция, шаг 1"),
        (u"fp_b", u"BYTE", u"позиция, шаг 2"),
        (u"fp_c", u"BYTE", u"позиция, шаг 3"),
        (u"arglen", u"BYTE", u"сколько знаков набрано в текущем слове"),
        (u"tokno", u"BYTE", u"номер разбираемого слова (0 - команда)"),
        (u"tok_p", u"BYTE", u"номер слова до увеличения"),
        (u"tok_p0", u"BOOL", u"разбиралось имя команды"),
        (u"in_skip", u"BOOL", u"фаза 8 активна"),
        (u"in_tok", u"BOOL", u"фаза 9 активна"),
        (u"in_ti", u"BOOL", u"фаза 14 активна"),
        (u"in_unk", u"BOOL", u"фаза 93 активна"),
        (u"eq_done", u"BOOL", u"знак '=' уже обработан (REN)"),
        (u"only_arg", u"BOOL", u"разобрать только одно слово"),
        (u"ret_ph", u"BYTE", u"фаза, куда вернуться после разбора"),
        (u"is_blank", u"BOOL", u"пробел"),
        (u"is_dot", u"BOOL", u"точка"),
        (u"is_star", u"BOOL", u"звёздочка"),
        (u"is_eq", u"BOOL", u"знак '='"),
        (u"do_char", u"BOOL", u"обычный знак имени"),
        (u"fld_ok", u"BOOL", u"поле имени не переполнено"),
        (u"at_eq", u"BOOL", u"обрабатывается знак '='"),
        (u"adv", u"BOOL", u"указатель разбора сдвигается"),
        (u"end_word", u"BOOL", u"слово закончилось"),
        (u"tl", u"WORD", u"длина хвоста команды"),
        (u"tl_b", u"BYTE", u"длина хвоста как байт"),
        (u"tl_ok", u"BOOL", u"хвост ещё копируется"),
        (u"tl_end", u"BOOL", u"хвост перенесён"),
        (u"act", u"BYTE", u"код команды"),
        (u"cmd_empty", u"BOOL", u"имя команды пустое"),
        (u"cmd_cnt", u"UDINT", u"счётчик выполненных команд"),
        (u"rt", u"BYTE", u"фаза выбранной команды"),
        (u"ebase", u"WORD", u"адрес записи каталога в буфере DMA"),
        (u"cpos", u"BYTE", u"номер печатаемого знака"),
        (u"cpos_w", u"WORD", u"номер знака как слово"),
        (u"c1", u"BYTE", u"знак, выбор 1"),
        (u"c2", u"BYTE", u"знак, выбор 2"),
        (u"c3", u"BYTE", u"знак, выбор 3"),
        (u"pc_g", u"BOOL", u"знак печатается"),
        (u"pc_c", u"BYTE", u"печатаемый знак"),
        (u"ec", u"BYTE", u"номер знака сообщения"),
        (u"ech", u"BYTE", u"знак сообщения"),
        (u"found", u"BOOL", u"в DIR что-то найдено"),
        (u"eof_p", u"BOOL", u"встретился конец текста"),
        (u"cend32", u"BOOL", u"имя файла в DIR напечатано"),
        (u"cend44", u"BOOL", u"запись текста в TYPE напечатана"),
        (u"cend33", u"BOOL", u"сообщение NO FILE напечатано"),
        (u"cend93", u"BOOL", u"сообщение о неизвестной команде напечатано"),
        (u"v0", u"BYTE", u"первый знак числа"),
        (u"v1", u"BYTE", u"второй знак числа"),
        (u"v2", u"BYTE", u"третий знак числа"),
        (u"d0", u"WORD", u"первая цифра"),
        (u"d1", u"WORD", u"вторая цифра"),
        (u"d2", u"WORD", u"третья цифра"),
        (u"k0", u"BOOL", u"первый знак - цифра"),
        (u"k1", u"BOOL", u"второй знак - цифра или пробел"),
        (u"k2", u"BOOL", u"третий знак - цифра или пробел"),
        (u"n_ok", u"BOOL", u"число разобрано верно"),
        (u"pages", u"WORD", u"число страниц для SAVE"),
        (u"nrecs", u"WORD", u"сколько записей записать"),
        (u"srec", u"WORD", u"номер записываемой записи"),
        (u"tdma", u"WORD", u"адрес DMA для SAVE"),
        (u"s75", u"BOOL", u"идёт запись очередной записи SAVE"),
        (u"unum", u"WORD", u"номер пользователя для USER"),
        (u"un_ok", u"BOOL", u"номер пользователя допустим"),
        (u"tend", u"BOOL", u"SAVE записал все записи"),
        (u"eng_start", u"BOOL", u"запуск операции дискового движка"),
        (u"eng_op", u"BYTE", u"код операции движка"),
        (u"eng_ent", u"WORD", u"начальная запись каталога"),
        (u"eng_done", u"BOOL", u"защёлка Done движка"),
        (u"eng_res", u"BYTE", u"защёлка кода возврата движка"),
        (u"eng_idx", u"WORD", u"защёлка номера найденной записи"),
        (u"e_done", u"BOOL", u"движок завершил операцию"),
        (u"e_ff", u"BOOL", u"движок сообщил 'не найдено'"),
        (u"e_ok", u"BOOL", u"движок завершил операцию успешно"),
        (u"e_bad", u"BOOL", u"движок не прочитал запись"),
        (u"e_ff_nf", u"BOOL", u"каталог кончился, ничего не найдено"),
        (u"ld_start", u"BOOL", u"запуск загрузчика .COM"),
        (u"ld_done", u"BOOL", u"загрузка закончена"),
        (u"ld_ok", u"BOOL", u"файл найден и прочитан"),
        (u"ld_size", u"WORD", u"сколько байт загружено"),
        (u"eng", u"FB_CPM_DirEngine", u"дисковый движок CCP"),
        (u"ldr", u"FB_COM_Loader", u"загрузчик .COM"),
    )
    for nm, t, c in loc:
        p.var(nm, t, c)

    # ==================================================================
    # СЕТЬ 1. Признак работы и разбор числа (читается ДО чистки FCB)
    # ==================================================================
    n = p.network(u"СЕТЬ 2. Признак работы CCP и разбор числа страниц SAVE/USER")
    n.outvar(u"hit", I(n, u"Enable"))
    n.outvar(u"Busy", I(n, u"Enable"))
    for k in range(3):
        n.outvar(u"v%d" % k, I(n, u"GVL_MEM.Memory[%s]"
                               % (WH % (FCB1_NAME + k))))
    n.outvar(u"k0", ANDL(n, [GE(n, I(n, u"v0"), I(n, H % ZERO),
                              fbd_xml.COL_BLK + 200),
                            LE(n, I(n, u"v0"), I(n, H % 0x39),
                               fbd_xml.COL_BLK + 320)],
                         x0=fbd_xml.COL_BLK + 440))
    for k in (1, 2):
        n.outvar(u"k%d" % k,
                 OR(n, ANDL(n, [GE(n, I(n, u"v%d" % k), I(n, H % ZERO),
                                   fbd_xml.COL_BLK + 560),
                                LE(n, I(n, u"v%d" % k), I(n, H % 0x39),
                                   fbd_xml.COL_BLK + 680)],
                           x0=fbd_xml.COL_BLK + 800),
                     EQ(n, I(n, u"v%d" % k), I(n, H % SP), fbd_xml.COL_BLK + 920),
                     fbd_xml.COL_BLK + 1040))
    n.outvar(u"n_ok", ANDL(n, [I(n, u"k0"), I(n, u"k1"), I(n, u"k2")],
                           x0=fbd_xml.COL_BLK + 1160))
    for k in range(3):
        n.outvar(u"d%d" % k, IF(n, I(n, u"k%d" % k),
                                SUB(n, I(n, u"v%d" % k), I(n, H % ZERO),
                                    fbd_xml.COL_BLK + 1280),
                                I(n, u"WORD#0"), fbd_xml.COL_BLK + 1400))
    n.outvar(u"pages", ADD(n, ADD(n, MUL(n, I(n, u"d0"), I(n, u"WORD#100"),
                                         fbd_xml.COL_BLK + 1520),
                                 MUL(n, I(n, u"d1"), I(n, u"WORD#10"),
                                     fbd_xml.COL_BLK + 1640), fbd_xml.COL_BLK + 1760),
                           I(n, u"d2"), fbd_xml.COL_BLK + 1880))
    n.outvar(u"unum", ADD(n, MUL(n, I(n, u"d0"), I(n, u"WORD#10"),
                                 fbd_xml.COL_BLK + 2000),
                          I(n, u"d1"), fbd_xml.COL_BLK + 2120))
    n.outvar(u"un_ok", AND(n, I(n, u"n_ok"),
                           LT(n, I(n, u"unum"), I(n, u"WORD#16"),
                              fbd_xml.COL_BLK + 2240), fbd_xml.COL_BLK + 2360))

    # ==================================================================
    # СЕТЬ 3. Дисковый движок CCP (вызывается РАНЬШЕ всех сетей команд:
    # его выходы нужны им в ТОМ ЖЕ скане - ссылка на переменную в FBD
    # читается по порядку элементов, поэтому сети команд ниже видят
    # свежие е_done/e_ok, а не значения прошлого скана)
    # ==================================================================
    n = p.network(u"СЕТЬ 4. Дисковый движок CCP: поиск, открытие, удаление, "
                  u"переименование, создание, запись")
    eng_states = (PH_DIR_S, PH_DIR_N, PH_TYP_S, PH_TYP_R, PH_ERA_S, PH_REN_S,
                  PH_SAV_M, PH_SAV_X)
    n.outvar(u"eng_start", ORL(n, [AND(n, I(n, u"hit"), _at(n, k),
                                       fbd_xml.COL_BLK + 130 * i)
                                   for i, k in enumerate(eng_states)],
                               x0=fbd_xml.COL_BLK + 1200))
    n.outvar(u"eng_op", CHAIN(n, I(n, B % D.OP_SEARCH_FIRST), [
        (AND(n, I(n, u"hit"), _at(n, PH_DIR_N), fbd_xml.COL_BLK + 1400),
         I(n, B % D.OP_SEARCH_NEXT)),
        (AND(n, I(n, u"hit"), _at(n, PH_TYP_S), fbd_xml.COL_BLK + 1520),
         I(n, B % D.OP_OPEN)),
        (AND(n, I(n, u"hit"), _at(n, PH_TYP_R), fbd_xml.COL_BLK + 1640),
         I(n, B % D.OP_READSEQ)),
        (AND(n, I(n, u"hit"), _at(n, PH_ERA_S), fbd_xml.COL_BLK + 1760),
         I(n, B % D.OP_DELETE)),
        (AND(n, I(n, u"hit"), _at(n, PH_REN_S), fbd_xml.COL_BLK + 1880),
         I(n, B % D.OP_RENAME)),
        (AND(n, I(n, u"hit"), _at(n, PH_SAV_M), fbd_xml.COL_BLK + 2000),
         I(n, B % D.OP_MAKE)),
        (AND(n, I(n, u"hit"), _at(n, PH_SAV_X), fbd_xml.COL_BLK + 2120),
         I(n, B % D.OP_WRITESEQ)),
    ], x0=fbd_xml.COL_BLK + 2240))
    n.outvar(u"eng_ent", IF(n, AND(n, I(n, u"hit"), _at(n, PH_DIR_N),
                                   fbd_xml.COL_BLK + 2800),
                            I(n, u"GVL_CPM.Search_Idx"), I(n, u"WORD#0"),
                            fbd_xml.COL_BLK + 2920))
    eng = n.block(u"FB_CPM_DirEngine", [
        (u"Start", I(n, u"eng_start")),
        (u"Op", I(n, u"eng_op")),
        (u"Entry", I(n, u"eng_ent")),
        (u"FCB", I(n, u"WORD#%d" % FCB1)),
        (u"ZeroFill", I(n, u"FALSE")),
    ], [u"Busy", u"Done", u"Result", u"Out_HL", u"Out_Idx"], instance=u"eng",
        x=fbd_xml.COL_BLK + 3100)
    n.outvar(u"eng_done", eng.out(u"Done"))
    n.outvar(u"eng_res", eng.out(u"Result"))
    n.outvar(u"eng_idx", eng.out(u"Out_Idx"))

    # ==================================================================
    # СЕТЬ 5. Загрузчик .COM
    # ==================================================================
    n = p.network(u"СЕТЬ 6. Загрузчик .COM: поиск файла и чтение его в TPA")
    n.outvar(u"ld_start", ANDL(n, [I(n, u"hit"),
                                   OR(n, _at(n, PH_EXT_S), _at(n, PH_EXT_W),
                                      fbd_xml.COL_BLK + 200)],
                               x0=fbd_xml.COL_BLK + 320))
    ldr = n.block(u"FB_COM_Loader", [
        (u"Start", I(n, u"ld_start")),
        (u"FCB", I(n, u"WORD#%d" % D.CCP_FCB)),
    ], [u"Busy", u"Done", u"Ok", u"Size"], instance=u"ldr",
        x=fbd_xml.COL_BLK + 540)
    n.outvar(u"ld_done", ldr.out(u"Done"))
    n.outvar(u"ld_ok", ldr.out(u"Ok"))
    n.outvar(u"ld_size", ldr.out(u"Size"))

    # ==================================================================
    # СЕТЬ 7. Признаки завершения операций дискового движка
    # ==================================================================
    n = p.network(u"СЕТЬ 8. Признаки завершения операций дискового движка")
    n.outvar(u"e_done", AND(n, I(n, u"hit"), I(n, u"eng_done"),
                            fbd_xml.COL_BLK + 120))
    n.outvar(u"e_ff", AND(n, I(n, u"e_done"),
                          EQ(n, I(n, u"eng_res"), I(n, H % 0xFF),
                             fbd_xml.COL_BLK + 240), fbd_xml.COL_BLK + 360))
    # ВАЖНО: движок возвращает в A КОД КАТАЛОГА 0..3 (как настоящий BDOS), а не
    # ноль. Поэтому "успех" - это "не FFh": проверка res = 0 отбросила бы все
    # записи каталога, кроме первой, и DIR зациклился бы на второй.
    n.outvar(u"e_ok", AND(n, I(n, u"e_done"),
                          NE(n, I(n, u"eng_res"), I(n, H % 0xFF),
                             fbd_xml.COL_BLK + 480), fbd_xml.COL_BLK + 600))
    n.outvar(u"e_bad", AND(n, I(n, u"e_done"),
                           NE(n, I(n, u"eng_res"), I(n, H % 0),
                              fbd_xml.COL_BLK + 720), fbd_xml.COL_BLK + 840))
    n.outvar(u"e_ff_nf", AND(n, I(n, u"e_ff"),
                             NOT(n, I(n, u"found"), fbd_xml.COL_BLK + 960),
                             fbd_xml.COL_BLK + 1080))

    # ==================================================================
    # СЕТЬ 9. Чистка буфера строки, FCB и буфера имени (фазы 0 и SAVE)
    # ==================================================================
    n = p.network(u"СЕТЬ 10. Чистка буфера строки, FCB первого аргумента и "
                  u"буфера имени команды")
    clr_g = ANDL(n, [I(n, u"hit"),
                     OR(n, _at(n, PH_INIT), _at(n, PH_SAV_S),
                        fbd_xml.COL_BLK + 200)], x0=fbd_xml.COL_BLK + 340)
    tgt = u"GVL_MEM.Memory[%s]" % (WH % FCB1)
    n.outvar(tgt, IF(n, clr_g, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 580))
    for k in range(8):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1_NAME + k))
        n.outvar(tgt, IF(n, clr_g, I(n, H % SP), I(n, tgt), fbd_xml.COL_BLK + 700))
    for k in range(3):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1_EXT + k))
        n.outvar(tgt, IF(n, clr_g, I(n, H % SP), I(n, tgt), fbd_xml.COL_BLK + 820))
    for k in range(4):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1 + 12 + k))
        n.outvar(tgt, IF(n, clr_g, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 940))
    for k in range(11):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1_NEW + k))
        n.outvar(tgt, IF(n, clr_g, I(n, H % SP), I(n, tgt),
                         fbd_xml.COL_BLK + 1060))
    for k in (FCB1_NEW + 11, FCB1_NEW + 12, FCB1 + 32):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % k)
        n.outvar(tgt, IF(n, clr_g, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 1180))
    for k in range(11):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_WORK + k))
        n.outvar(tgt, IF(n, clr_g, I(n, H % SP), I(n, tgt),
                         fbd_xml.COL_BLK + 1300))
    tgt = u"GVL_MEM.Memory[%s]" % (WH % LINEBUF)
    n.outvar(tgt, IF(n, clr_g, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 1420))
    init0 = AND(n, I(n, u"hit"), _at(n, PH_INIT), fbd_xml.COL_BLK + 1540)
    n.outvar(u"linelen", IF(n, init0, I(n, u"WORD#0"), I(n, u"linelen"),
                            fbd_xml.COL_BLK + 1660))
    n.outvar(u"tokno", IF(n, init0, I(n, B % 0), I(n, u"tokno"),
                          fbd_xml.COL_BLK + 1780))
    n.outvar(u"arglen", IF(n, init0, I(n, B % 0), I(n, u"arglen"),
                           fbd_xml.COL_BLK + 1900))
    n.outvar(u"eq_done", IF(n, init0, I(n, u"FALSE"), I(n, u"eq_done"),
                            fbd_xml.COL_BLK + 2020))
    n.outvar(u"only_arg", IF(n, init0, I(n, u"FALSE"), I(n, u"only_arg"),
                             fbd_xml.COL_BLK + 2140))
    n.outvar(u"ret_ph", IF(n, init0, I(n, B % PH_DISP), I(n, u"ret_ph"),
                           fbd_xml.COL_BLK + 2260))
    n.outvar(u"tb", IF(n, init0, I(n, u"WORD#%d" % D.CCP_WORK), I(n, u"tb"),
                       fbd_xml.COL_BLK + 2380))
    n.outvar(u"found", IF(n, init0, I(n, u"FALSE"), I(n, u"found"),
                          fbd_xml.COL_BLK + 2500))

    # ==================================================================
    # СЕТЬ 11. Приглашение: буква диска и '>' (фазы 1-2)
    # ==================================================================
    n = p.network(u"СЕТЬ 12. Фазы 1-2: приглашение вида A>")
    n.outvar(u"drv_ch", AND(n, ADD(n, I(n, H % 0x41), I(n, u"GVL_CPM.CurDisk"),
                                  fbd_xml.COL_BLK + 120), I(n, H % 0xFF),
                            fbd_xml.COL_BLK + 240))
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_DRV), fbd_xml.COL_BLK + 360),
              I(n, u"drv_ch"), note=u"буква текущего диска")
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_PROMPT), fbd_xml.COL_BLK + 360),
              I(n, H % 0x3E), note=u"'>'")

    # ==================================================================
    # СЕТЬ 13. Ввод строки (фаза 3)
    # ==================================================================
    n = p.network(u"СЕТЬ 14. Фаза 3: ввод командной строки, CR, ^C, забои")
    n.outvar(u"ch", I(n, u"GVL_CPM.ConIn_Char"))
    n.outvar(u"got", ANDL(n, [I(n, u"hit"), _at(n, PH_READ),
                              I(n, u"GVL_CPM.ConIn_Ready")],
                          x0=fbd_xml.COL_BLK + 120))
    n.outvar(u"is_cr", EQ(n, I(n, u"ch"), I(n, H % CR), fbd_xml.COL_BLK + 360))
    n.outvar(u"is_bs", EQ(n, I(n, u"ch"), I(n, H % BS), fbd_xml.COL_BLK + 480))
    n.outvar(u"is_cc", EQ(n, I(n, u"ch"), I(n, H % CTRLC), fbd_xml.COL_BLK + 600))
    n.outvar(u"room", LT(n, I(n, u"linelen"),
                         I(n, u"WORD#%d" % (D.CCP_TAIL_MAX + 0x40)),
                         fbd_xml.COL_BLK + 720))
    n.outvar(u"store", ANDL(n, [I(n, u"got"),
                                NOT(n, I(n, u"is_cr"), fbd_xml.COL_BLK + 840),
                                NOT(n, I(n, u"is_bs"), fbd_xml.COL_BLK + 960),
                                NOT(n, I(n, u"is_cc"), fbd_xml.COL_BLK + 1080),
                                I(n, u"room")], x0=fbd_xml.COL_BLK + 1200))
    n.outvar(u"bs_ok", ANDL(n, [I(n, u"got"), I(n, u"is_bs"),
                                GT(n, I(n, u"linelen"), I(n, u"WORD#0"),
                                   fbd_xml.COL_BLK + 1320)],
                            x0=fbd_xml.COL_BLK + 1440))
    n.outvar(u"ll_b", W2B(n, I(n, u"linelen"), fbd_xml.COL_BLK + 1560))
    n.outvar(u"lv1", IF(n, I(n, u"store"),
                        ADD(n, I(n, u"linelen"), I(n, u"WORD#1"),
                            fbd_xml.COL_BLK + 1680),
                        I(n, u"linelen"), fbd_xml.COL_BLK + 1800))
    n.outvar(u"lv2", IF(n, I(n, u"bs_ok"),
                        SUB(n, I(n, u"lv1"), I(n, u"WORD#1"),
                            fbd_xml.COL_BLK + 1920),
                        I(n, u"lv1"), fbd_xml.COL_BLK + 2040))
    n.outvar(u"linelen", I(n, u"lv2"))
    tgt = u"GVL_MEM.Memory[%s + ll_b]" % (WH % (LINEBUF + 1))
    n.outvar(tgt, IF(n, I(n, u"store"), UPCH(n, I(n, u"ch")), I(n, tgt),
                     fbd_xml.COL_BLK + 2160))
    tgt = u"GVL_MEM.Memory[%s]" % (WH % LINEBUF)
    n.outvar(tgt, IF(n, I(n, u"got"), I(n, u"ll_b"), I(n, tgt),
                     fbd_xml.COL_BLK + 2280))
    n.outvar(u"echo_g", OR(n, I(n, u"store"), I(n, u"bs_ok"),
                           fbd_xml.COL_BLK + 2400))
    n.outvar(u"echo_c", IF(n, I(n, u"store"), UPCH(n, I(n, u"ch")), I(n, H % BS),
                           fbd_xml.COL_BLK + 2520))
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_READ), fbd_xml.COL_BLK + 2640),
              I(n, u"echo_c"), note=u"эхо введённого знака")
    n.outvar(u"GVL_CPM.ConIn_Ready",
             IF(n, I(n, u"got"), I(n, u"FALSE"), I(n, u"GVL_CPM.ConIn_Ready"),
                 fbd_xml.COL_BLK + 2760))

    # ==================================================================
    # СЕТЬ 15. CR и LF после ввода (фазы 5-6)
    # ==================================================================
    n = p.network(u"СЕТЬ 16. Фазы 5-6: перевод строки после ввода команды")
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_CR), fbd_xml.COL_BLK + 120),
              I(n, H % CR), note=u"CR")
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_LF), fbd_xml.COL_BLK + 120),
              I(n, H % LF), note=u"LF")

    # ==================================================================
    # СЕТЬ 17. Подготовка разбора (фаза 7)
    # ==================================================================
    n = p.network(u"СЕТЬ 18. Фаза 7: подготовка разбора - указатели и счётчики")
    pin = AND(n, I(n, u"hit"), _at(n, PH_PINIT), fbd_xml.COL_BLK + 120)
    n.outvar(u"pp", IF(n, pin, I(n, u"WORD#%d" % (LINEBUF + 1)), I(n, u"pp"),
                       fbd_xml.COL_BLK + 240))
    n.outvar(u"pend", IF(n, pin,
                         ADD(n, I(n, u"WORD#%d" % (LINEBUF + 1)),
                             I(n, u"linelen"), fbd_xml.COL_BLK + 360),
                         I(n, u"pend"), fbd_xml.COL_BLK + 480))
    n.outvar(u"fpos", IF(n, pin, I(n, B % 0), I(n, u"fpos"),
                         fbd_xml.COL_BLK + 600))
    n.outvar(u"arglen", IF(n, pin, I(n, B % 0), I(n, u"arglen"),
                           fbd_xml.COL_BLK + 720))
    n.outvar(u"eq_done", IF(n, pin, I(n, u"FALSE"), I(n, u"eq_done"),
                            fbd_xml.COL_BLK + 840))
    n.outvar(u"at_end", GE(n, I(n, u"pp"), I(n, u"pend"), fbd_xml.COL_BLK + 960))

    # ==================================================================
    # СЕТЬ 19. Пропуск пробелов (фаза 8)
    # ==================================================================
    n = p.network(u"СЕТЬ 20. Фаза 8: пропуск пробелов между словами")
    n.outvar(u"in_skip", AND(n, I(n, u"hit"), _at(n, PH_SKIP), fbd_xml.COL_BLK + 120))
    n.outvar(u"at_end", GE(n, I(n, u"pp"), I(n, u"pend"), fbd_xml.COL_BLK + 240))
    n.outvar(u"is_blank", ANDL(n, [NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 360),
                                   EQ(n, I(n, u"GVL_MEM.Memory[pp]"),
                                      I(n, H % SP), fbd_xml.COL_BLK + 480)],
                               x0=fbd_xml.COL_BLK + 600))
    n.outvar(u"adv", AND(n, I(n, u"in_skip"), I(n, u"is_blank"),
                         fbd_xml.COL_BLK + 720))
    n.outvar(u"pp", IF(n, I(n, u"adv"),
                       ADD(n, I(n, u"pp"), I(n, u"WORD#1"),
                           fbd_xml.COL_BLK + 840),
                       I(n, u"pp"), fbd_xml.COL_BLK + 960))

    # ==================================================================
    # СЕТЬ 21. Разбор слова (фаза 9)
    # ==================================================================
    n = p.network(u"СЕТЬ 22. Фаза 9: разбор слова - знаки, '.', '*', '='")
    n.outvar(u"in_tok", AND(n, I(n, u"hit"), _at(n, PH_TOK), fbd_xml.COL_BLK + 120))
    n.outvar(u"at_end", GE(n, I(n, u"pp"), I(n, u"pend"), fbd_xml.COL_BLK + 240))
    n.outvar(u"ch", I(n, u"GVL_MEM.Memory[pp]"))
    n.outvar(u"is_blank", ANDL(n, [NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 360),
                                   EQ(n, I(n, u"ch"), I(n, H % SP),
                                      fbd_xml.COL_BLK + 480)],
                               x0=fbd_xml.COL_BLK + 600))
    n.outvar(u"is_dot", EQ(n, I(n, u"ch"), I(n, H % 0x2E), fbd_xml.COL_BLK + 720))
    n.outvar(u"is_star", EQ(n, I(n, u"ch"), I(n, H % 0x2A), fbd_xml.COL_BLK + 840))
    n.outvar(u"is_eq", EQ(n, I(n, u"ch"), I(n, H % 0x3D), fbd_xml.COL_BLK + 960))
    n.outvar(u"fld_ok", LT(n, I(n, u"fpos"), I(n, B % 11),
                           fbd_xml.COL_BLK + 1080))
    n.outvar(u"do_char", ANDL(n, [I(n, u"in_tok"),
                                  NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 1200),
                                  NOT(n, I(n, u"is_blank"), fbd_xml.COL_BLK + 1320),
                                  NOT(n, I(n, u"is_dot"), fbd_xml.COL_BLK + 1440),
                                  NOT(n, I(n, u"is_star"), fbd_xml.COL_BLK + 1560),
                                  NOT(n, I(n, u"is_eq"), fbd_xml.COL_BLK + 1680)],
                             x0=fbd_xml.COL_BLK + 1800))
    n.outvar(u"at_eq", ANDL(n, [I(n, u"do_char"), I(n, u"is_eq"),
                                EQ(n, I(n, u"tokno"), I(n, B % 1),
                                   fbd_xml.COL_BLK + 2100),
                                NOT(n, I(n, u"eq_done"), fbd_xml.COL_BLK + 2220)],
                            x0=fbd_xml.COL_BLK + 2340))
    n.outvar(u"fp_w", I(n, u"fpos"))
    # ЗАПИСЬ ЗНАКА ИМЕНИ ПО КОНСТАНТНЫМ АДРЕСАМ.
    # Раньше здесь стояло GVL_MEM.Memory[tb + fp_w] - запись по ВЫЧИСЛЯЕМОМУ
    # адресу, а такие записи импортёр PLCopenXML МОЛЧА ТЕРЯЕТ. Из-за этого
    # имя команды в CCP_WORK не появлялось, сравнение с "DIR" давало
    # пустую команду, и CCP уходил в ветку A_NONE (замер: фазы доходили до
    # 20, но DIR (30) не достигался).
    # Пишем в ОБА возможных места: CCP_WORK (+0..10) и FCB1_NAME (+0..10),
    # выбирая нужное по tb - так оба варианта остаются рабочими.
    wr_ch = ANDL(n, [I(n, u"do_char"), I(n, u"fld_ok")],
                 x0=fbd_xml.COL_BLK + 2460)
    for k in range(11):
        for base_nm, base_val in ((u"CCP_WORK", D.CCP_WORK),
                                  (u"FCB1_NAME", FCB1_NAME)):
            tgt = u"GVL_MEM.Memory[%s]" % (WH % (base_val + k))
            hit = ANDL(n, [EQ(n, I(n, u"tb"),
                                  I(n, u"WORD#%d" % base_val),
                                  fbd_xml.COL_BLK + 2500),
                           EQ(n, I(n, u"fp_w"), I(n, u"BYTE#%d" % k),
                              fbd_xml.COL_BLK + 2620)],
                        x0=fbd_xml.COL_BLK + 2740)
            n.outvar(tgt, IF(n, AND(n, wr_ch, hit, fbd_xml.COL_BLK + 2860),
                             UPCH(n, I(n, u"ch")), I(n, tgt),
                             fbd_xml.COL_BLK + 2980))
    # звёздочка заполняет остаток поля знаками '?' - как настоящий CCP
    for k in range(11):
        for base_val in (D.CCP_WORK, FCB1_NAME):
            tgt = u"GVL_MEM.Memory[%s]" % (WH % (base_val + k))
            hit = ANDL(n, [I(n, u"is_star"),
                           EQ(n, I(n, u"tb"), I(n, u"WORD#%d" % base_val),
                              fbd_xml.COL_BLK + 3100),
                           GE(n, I(n, u"fpos"), I(n, B % k),
                              fbd_xml.COL_BLK + 3220)],
                        x0=fbd_xml.COL_BLK + 3340)
            n.outvar(tgt, IF(n, hit, I(n, H % WILD), I(n, tgt),
                             fbd_xml.COL_BLK + 3460))
    n.outvar(u"fp_a", IF(n, AND(n, I(n, u"do_char"), I(n, u"fld_ok"),
                                fbd_xml.COL_BLK + 3060),
                         ADD(n, I(n, u"fpos"), I(n, B % 1),
                             fbd_xml.COL_BLK + 3180),
                         I(n, u"fpos"), fbd_xml.COL_BLK + 3300))
    n.outvar(u"fp_b", IF(n, I(n, u"is_dot"), I(n, B % 8), I(n, u"fp_a"),
                         fbd_xml.COL_BLK + 3420))
    n.outvar(u"fp_c", IF(n, AND(n, I(n, u"is_star"), LT(n, I(n, u"fpos"),
                                                        I(n, B % 8),
                                                        fbd_xml.COL_BLK + 3540),
                               fbd_xml.COL_BLK + 3660),
                         I(n, B % 11), I(n, u"fp_b"), fbd_xml.COL_BLK + 3780))
    n.outvar(u"fpos", IF(n, I(n, u"at_eq"), I(n, B % 0), I(n, u"fp_c"),
                         fbd_xml.COL_BLK + 3900))
    n.outvar(u"arglen", IF(n, AND(n, I(n, u"do_char"), I(n, u"fld_ok"),
                                  fbd_xml.COL_BLK + 4020),
                           ADD(n, I(n, u"arglen"), I(n, B % 1),
                               fbd_xml.COL_BLK + 4140),
                           I(n, u"arglen"), fbd_xml.COL_BLK + 4260))
    n.outvar(u"eq_done", OR(n, I(n, u"eq_done"), I(n, u"at_eq"),
                            fbd_xml.COL_BLK + 4380))
    # '=' при первом аргументе: набранное имя переносится в FCB+16 (новое имя)
    for k in range(12):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1_NEW + k))
        n.outvar(tgt, IF(n, I(n, u"at_eq"),
                         I(n, u"GVL_MEM.Memory[%s]" % (WH % (FCB1 + k))),
                         I(n, tgt), fbd_xml.COL_BLK + 4500))
    n.outvar(u"adv", ANDL(n, [I(n, u"in_tok"),
                              NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 4620),
                              ORL(n, [I(n, u"do_char"), I(n, u"is_dot"),
                                      I(n, u"is_star"), I(n, u"is_eq")],
                                  x0=fbd_xml.COL_BLK + 4740)],
                          x0=fbd_xml.COL_BLK + 5040))
    n.outvar(u"pp", IF(n, I(n, u"adv"),
                       ADD(n, I(n, u"pp"), I(n, u"WORD#1"),
                           fbd_xml.COL_BLK + 5160),
                       I(n, u"pp"), fbd_xml.COL_BLK + 5280))
    n.outvar(u"end_word", OR(n, I(n, u"at_end"), I(n, u"is_blank"),
                             fbd_xml.COL_BLK + 5400))

    # ФАЗА B. ПЕРЕХОД ИЗ ENDTOK НАЗАД В РАЗБОР ДОЛЖЕН ПРОДВИГАТЬ УКАЗАТЕЛЬ.
    #
    # ЗДЕСЬ БЫЛ ЗАМОК: команда набиралась, но CCP навсегда застревал в фазе
    # ENDTOK (13) - наблюдалось CCP_Phase = 13, ConIn_Ready = FALSE, журнал
    # консоли 5 знаков ("A>"), CCP_Cnt = 1.
    #
    # Причина: слово, которое разбиралось, - ИМЯ КОМАНДЫ (tokno = 0), поэтому
    # tok_p0 = TRUE, и переход идёт в SKIP (фаза 8 - пропуск пробелов). Но в
    # SKIP продвижение указателя разрешено ТОЛЬКО при пробеле:
    #     adv = in_skip AND is_blank
    # а на конце слова стоит не пробел, а следующий знак команды или конец
    # строки. Указатель не двигался, at_end оставался FALSE, is_blank FALSE,
    # end_word FALSE - и переход SKIP -> TOK не срабатывал НИКОГДА.
    #
    # Исправление: шаг указателя перекрывается в фазе ENDTOK по тому же
    # признаку at_end, что и в фазах SKIP/TOK/TAILINI, поэтому условие
    # `at_end : ret` в фазе SKIP становится достижимым.
    n.outvar(u"pp",
             IF(n, AND(n, I(n, u"hit"), _at(n, PH_ENDTOK),
                       fbd_xml.COL_BLK + 5520),
                IF(n, NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 5640),
                   ADD(n, I(n, u"pp"), I(n, u"WORD#1"), fbd_xml.COL_BLK + 5760),
                   I(n, u"pp"), fbd_xml.COL_BLK + 5880),
                I(n, u"pp"), fbd_xml.COL_BLK + 6000))

    # ==================================================================
    # СЕТЬ 23. Конец слова (фаза 13)
    # ==================================================================
    n = p.network(u"СЕТЬ 24. Фаза 13: слово разобрано - куда писать следующее")
    n.outvar(u"tok_p", I(n, u"tokno"))
    n.outvar(u"tok_p0", EQ(n, I(n, u"tok_p"), I(n, B % 0), fbd_xml.COL_BLK + 120))
    n.outvar(u"tokno", IF(n, AND(n, I(n, u"hit"), _at(n, PH_ENDTOK),
                                 fbd_xml.COL_BLK + 240),
                          ADD(n, I(n, u"tokno"), I(n, B % 1),
                              fbd_xml.COL_BLK + 360),
                          I(n, u"tokno"), fbd_xml.COL_BLK + 480))
    n.outvar(u"tb", IF(n, I(n, u"tok_p0"), I(n, u"WORD#%d" % FCB1_NAME),
                       I(n, u"tb"), fbd_xml.COL_BLK + 600))

    # ==================================================================
    # СЕТЬ 25. Хвост команды (фазы 14 и 16)
    # ==================================================================
    n = p.network(u"СЕТЬ 26. Фазы 14 и 16: перенос хвоста команды в 0080h")
    n.outvar(u"in_ti", AND(n, I(n, u"hit"), _at(n, PH_TAILINI), fbd_xml.COL_BLK + 120))
    n.outvar(u"at_end", GE(n, I(n, u"pp"), I(n, u"pend"), fbd_xml.COL_BLK + 240))
    n.outvar(u"is_blank", ANDL(n, [NOT(n, I(n, u"at_end"), fbd_xml.COL_BLK + 360),
                                   EQ(n, I(n, u"GVL_MEM.Memory[pp]"),
                                      I(n, H % SP), fbd_xml.COL_BLK + 480)],
                               x0=fbd_xml.COL_BLK + 600))
    n.outvar(u"adv", AND(n, I(n, u"in_ti"), I(n, u"is_blank"),
                         fbd_xml.COL_BLK + 720))
    n.outvar(u"pp", IF(n, I(n, u"adv"),
                       ADD(n, I(n, u"pp"), I(n, u"WORD#1"),
                           fbd_xml.COL_BLK + 840),
                       I(n, u"pp"), fbd_xml.COL_BLK + 960))
    n.outvar(u"tl", IF(n, I(n, u"in_ti"), I(n, u"WORD#0"), I(n, u"tl"),
                       fbd_xml.COL_BLK + 1080))
    n.outvar(u"tl_ok", ANDL(n, [AND(n, I(n, u"hit"), _at(n, PH_TAIL),
                                    fbd_xml.COL_BLK + 1200),
                                LT(n, I(n, u"pp"), I(n, u"pend"),
                                   fbd_xml.COL_BLK + 1320),
                                LT(n, I(n, u"tl"),
                                   I(n, u"WORD#%d" % D.CCP_TAIL_MAX),
                                   fbd_xml.COL_BLK + 1440)],
                            x0=fbd_xml.COL_BLK + 1560))
    n.outvar(u"tl_b", W2B(n, I(n, u"tl"), fbd_xml.COL_BLK + 1680))
    tgt = u"GVL_MEM.Memory[%s + tl_b]" % (WH % (LINEBUF + 1))
    n.outvar(tgt, IF(n, I(n, u"tl_ok"), I(n, u"GVL_MEM.Memory[pp]"), I(n, tgt),
                     fbd_xml.COL_BLK + 1800))
    n.outvar(u"tl", IF(n, I(n, u"tl_ok"),
                       ADD(n, I(n, u"tl"), I(n, u"WORD#1"),
                           fbd_xml.COL_BLK + 1920),
                       I(n, u"tl"), fbd_xml.COL_BLK + 2040))
    n.outvar(u"pp", IF(n, I(n, u"tl_ok"),
                       ADD(n, I(n, u"pp"), I(n, u"WORD#1"),
                           fbd_xml.COL_BLK + 2160),
                       I(n, u"pp"), fbd_xml.COL_BLK + 2280))
    n.outvar(u"linelen", IF(n, I(n, u"tl_ok"), I(n, u"tl"), I(n, u"linelen"),
                            fbd_xml.COL_BLK + 2400))
    n.outvar(u"ll_b", W2B(n, I(n, u"linelen"), fbd_xml.COL_BLK + 2520))
    tgt = u"GVL_MEM.Memory[%s]" % (WH % LINEBUF)
    n.outvar(tgt, IF(n, I(n, u"tl_ok"), I(n, u"ll_b"), I(n, tgt),
                     fbd_xml.COL_BLK + 2640))
    n.outvar(u"tl_end", ANDL(n, [I(n, u"hit"), _at(n, PH_TAIL),
                                 NOT(n, I(n, u"tl_ok"), fbd_xml.COL_BLK + 2760)],
                             x0=fbd_xml.COL_BLK + 2880))

    # ==================================================================
    # СЕТЬ 27. Диспетчер (фаза 20) и маршрут (фаза 21)
    # ==================================================================
    n = p.network(u"СЕТЬ 28. Фазы 20-21: сравнение имени команды и выбор "
                  u"обработчика")
    n.outvar(u"cmd_empty", _cmd_is(n, u"", D.CCP_WORK))
    is_dir = _cmd_is(n, u"DIR", D.CCP_WORK)
    is_type = _cmd_is(n, u"TYPE", D.CCP_WORK)
    is_era = _cmd_is(n, u"ERA", D.CCP_WORK)
    is_ren = _cmd_is(n, u"REN", D.CCP_WORK)
    is_save = _cmd_is(n, u"SAVE", D.CCP_WORK)
    is_user = _cmd_is(n, u"USER", D.CCP_WORK)
    is_exit = _cmd_is(n, u"EXIT", D.CCP_WORK)
    act0 = IF(n, I(n, u"cmd_empty"), I(n, B % A_NONE), I(n, B % A_EXT),
              fbd_xml.COL_BLK + 2200)
    n.outvar(u"act", CHAIN(n, act0, [
        (is_dir, I(n, B % A_DIR)), (is_type, I(n, B % A_TYPE)),
        (is_era, I(n, B % A_ERA)), (is_ren, I(n, B % A_REN)),
        (is_save, I(n, B % A_SAVE)), (is_user, I(n, B % A_USER)),
        (is_exit, I(n, B % A_EXIT)),
    ], x0=fbd_xml.COL_BLK + 2400))
    n.outvar(u"rt", CHAIN(n, I(n, B % 0), [
        (EQ(n, I(n, u"act"), I(n, B % A_DIR)), I(n, B % PH_DIR_S)),
        (EQ(n, I(n, u"act"), I(n, B % A_TYPE)), I(n, B % PH_TYP_S)),
        (EQ(n, I(n, u"act"), I(n, B % A_ERA)), I(n, B % PH_ERA_S)),
        (EQ(n, I(n, u"act"), I(n, B % A_REN)), I(n, B % PH_REN_S)),
        (EQ(n, I(n, u"act"), I(n, B % A_SAVE)), I(n, B % PH_SAV_S)),
        (EQ(n, I(n, u"act"), I(n, B % A_USER)), I(n, B % PH_USER)),
        (EQ(n, I(n, u"act"), I(n, B % A_EXIT)), I(n, B % PH_EXIT)),
        (EQ(n, I(n, u"act"), I(n, B % A_EXT)), I(n, B % PH_EXT_S)),
    ], x0=fbd_xml.COL_BLK + 3600))
    n.outvar(u"cmd_cnt", ADD(n, I(n, u"GVL_CPM.CCP_Cnt"), I(n, U1),
                             fbd_xml.COL_BLK + 4800))
    n.outvar(u"GVL_CPM.CCP_Cnt",
             IF(n, AND(n, I(n, u"hit"), _at(n, PH_DISP), fbd_xml.COL_BLK + 4920),
                 I(n, u"cmd_cnt"), I(n, u"GVL_CPM.CCP_Cnt"),
                 fbd_xml.COL_BLK + 5040))
    n.outvar(u"GVL_CPM.CCP_Phase", I(n, u"ph"))

    # ==================================================================
    # СЕТЬ 29. DIR: запуск поиска и приём найденной записи (фазы 30-31, 34)
    # ==================================================================
    n = p.network(u"СЕТЬ 30. Фазы 30-31 и 34: DIR - поиск записей каталога")
    d30 = AND(n, I(n, u"hit"), _at(n, PH_DIR_S), fbd_xml.COL_BLK + 120)
    n.outvar(u"GVL_CPM.DMA", IF(n, d30, I(n, u"WORD#%d" % DIRBUF),
                                I(n, u"GVL_CPM.DMA"), fbd_xml.COL_BLK + 240))
    # без аргумента ищем по маске '???????????' - как DIR без параметров
    for k in range(11):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (FCB1_NAME + k))
        n.outvar(tgt, IF(n, AND(n, d30, EQ(n, I(n, u"arglen"), I(n, B % 0),
                                           fbd_xml.COL_BLK + 360),
                                       fbd_xml.COL_BLK + 480),
                         I(n, H % WILD), I(n, tgt), fbd_xml.COL_BLK + 600))
    n.outvar(u"found", IF(n, d30, I(n, u"FALSE"), I(n, u"found"),
                          fbd_xml.COL_BLK + 720))
    d34 = AND(n, I(n, u"hit"), _at(n, PH_DIR_N), fbd_xml.COL_BLK + 840)
    n.outvar(u"cpos", IF(n, d34, I(n, B % 0), I(n, u"cpos"),
                         fbd_xml.COL_BLK + 960))
    d31 = AND(n, I(n, u"hit"), _at(n, PH_DIR_W), fbd_xml.COL_BLK + 1080)
    n.outvar(u"ebase", IF(n, AND(n, d31, I(n, u"e_ok"), fbd_xml.COL_BLK + 1200),
                          ADD(n, I(n, u"WORD#%d" % DIRBUF),
                              SHL(n, AND(n, I(n, u"eng_idx"), I(n, u"WORD#3"),
                                         fbd_xml.COL_BLK + 1320),
                                  I(n, u"WORD#5"), fbd_xml.COL_BLK + 1440),
                              fbd_xml.COL_BLK + 1560),
                          I(n, u"ebase"), fbd_xml.COL_BLK + 1680))
    n.outvar(u"found", IF(n, AND(n, d31, I(n, u"e_ok"), fbd_xml.COL_BLK + 1800),
                          I(n, u"TRUE"), I(n, u"found"), fbd_xml.COL_BLK + 1920))
    n.outvar(u"GVL_CPM.Search_Idx",
             IF(n, AND(n, d31, I(n, u"e_ok"), fbd_xml.COL_BLK + 2040),
                 ADD(n, I(n, u"eng_idx"), I(n, u"WORD#1"),
                     fbd_xml.COL_BLK + 2160),
                 I(n, u"GVL_CPM.Search_Idx"), fbd_xml.COL_BLK + 2280))

    # ==================================================================
    # СЕТЬ 31. DIR: печать имени (фаза 32)
    # ==================================================================
    n = p.network(u"СЕТЬ 32. Фаза 32: печать имени файла из записи каталога")
    in_p = AND(n, I(n, u"hit"), _at(n, PH_DIR_P), fbd_xml.COL_BLK + 120)
    n.outvar(u"cpos_w", I(n, u"cpos"))
    n.outvar(u"c1", IF(n, LT(n, I(n, u"cpos"), I(n, B % 8), fbd_xml.COL_BLK + 240),
                       AND(n, I(n, u"GVL_MEM.Memory[ebase + cpos_w + 1]"),
                           I(n, H % 0x7F), fbd_xml.COL_BLK + 360),
                       I(n, H % 0x2E), fbd_xml.COL_BLK + 480))
    n.outvar(u"c2", IF(n, AND(n, GE(n, I(n, u"cpos"), I(n, B % 9),
                                  fbd_xml.COL_BLK + 600),
                             LT(n, I(n, u"cpos"), I(n, B % 12),
                                fbd_xml.COL_BLK + 720), fbd_xml.COL_BLK + 840),
                       AND(n, I(n, u"GVL_MEM.Memory[ebase + cpos_w]"),
                           I(n, H % 0x7F), fbd_xml.COL_BLK + 960),
                       I(n, u"c1"), fbd_xml.COL_BLK + 1080))
    n.outvar(u"c3", IF(n, EQ(n, I(n, u"cpos"), I(n, B % 12),
                             fbd_xml.COL_BLK + 1200),
                       I(n, H % CR), I(n, u"c2"), fbd_xml.COL_BLK + 1320))
    n.outvar(u"pc_c", IF(n, EQ(n, I(n, u"cpos"), I(n, B % 13),
                               fbd_xml.COL_BLK + 1440),
                         I(n, H % LF), I(n, u"c3"), fbd_xml.COL_BLK + 1560))
    n.outvar(u"pc_g", AND(n, in_p, LT(n, I(n, u"cpos"), I(n, B % DIR_CHARS),
                                      fbd_xml.COL_BLK + 1680),
                          fbd_xml.COL_BLK + 1800))
    emit_char(p, I(n, u"pc_g"), I(n, u"pc_c"), note=u"знак имени файла в DIR")
    n.outvar(u"cend32", AND(n, in_p, GE(n, I(n, u"cpos"), I(n, B % DIR_CHARS),
                                        fbd_xml.COL_BLK + 1920),
                            fbd_xml.COL_BLK + 2040))
    n.outvar(u"cpos", IF(n, in_p, ADD(n, I(n, u"cpos"), I(n, B % 1),
                                      fbd_xml.COL_BLK + 2160),
                         I(n, u"cpos"), fbd_xml.COL_BLK + 2280))

    # ==================================================================
    # СЕТЬ 33. TYPE (фазы 40-44)
    # ==================================================================
    n = p.network(u"СЕТЬ 34. Фазы 40-44: TYPE - открыть файл и печатать его")
    t40 = AND(n, I(n, u"hit"), _at(n, PH_TYP_S), fbd_xml.COL_BLK + 120)
    n.outvar(u"GVL_CPM.DMA", IF(n, t40, I(n, u"WORD#%d" % DIRBUF),
                                I(n, u"GVL_CPM.DMA"), fbd_xml.COL_BLK + 240))
    t44 = AND(n, I(n, u"hit"), _at(n, PH_TYP_P), fbd_xml.COL_BLK + 360)
    n.outvar(u"cpos_w", I(n, u"cpos"))
    n.outvar(u"pc_c", I(n, u"GVL_MEM.Memory[%s + cpos_w]" % (WH % DIRBUF)))
    n.outvar(u"eof_p", AND(n, t44, EQ(n, I(n, u"pc_c"), I(n, H % EOF_TXT),
                                       fbd_xml.COL_BLK + 480),
                           fbd_xml.COL_BLK + 600))
    n.outvar(u"pc_g", AND(n, t44, NOT(n, I(n, u"eof_p"),
                                      fbd_xml.COL_BLK + 720),
                          fbd_xml.COL_BLK + 840))
    emit_char(p, I(n, u"pc_g"), I(n, u"pc_c"),
              note=u"знак текстового файла в TYPE")
    n.outvar(u"cend44", AND(n, t44, EQ(n, I(n, u"cpos"), I(n, B % 127),
                                       fbd_xml.COL_BLK + 960),
                            fbd_xml.COL_BLK + 1080))
    n.outvar(u"cpos", IF(n, t44,
                         IF(n, I(n, u"cend44"), I(n, B % 0),
                            ADD(n, I(n, u"cpos"), I(n, B % 1),
                                fbd_xml.COL_BLK + 1200), fbd_xml.COL_BLK + 1320),
                         I(n, u"cpos"), fbd_xml.COL_BLK + 1440))

    # ==================================================================
    # СЕТЬ 35. SAVE: подготовка (фаза 70)
    # ==================================================================
    n = p.network(u"СЕТЬ 36. Фаза 70: SAVE - число страниц и повторный разбор "
                  u"имени файла")
    s70 = AND(n, I(n, u"hit"), _at(n, PH_SAV_S), fbd_xml.COL_BLK + 120)
    n.outvar(u"ret_ph", IF(n, s70, I(n, B % PH_SAV_M), I(n, u"ret_ph"),
                           fbd_xml.COL_BLK + 240))
    n.outvar(u"only_arg", IF(n, s70, I(n, u"TRUE"), I(n, u"only_arg"),
                             fbd_xml.COL_BLK + 360))
    n.outvar(u"tokno", IF(n, s70, I(n, B % 1), I(n, u"tokno"),
                          fbd_xml.COL_BLK + 480))
    n.outvar(u"tb", IF(n, s70, I(n, u"WORD#%d" % FCB1_NAME), I(n, u"tb"),
                       fbd_xml.COL_BLK + 600))
    n.outvar(u"nrecs", IF(n, s70, MUL(n, I(n, u"pages"), I(n, u"WORD#2"),
                                      fbd_xml.COL_BLK + 720),
                          I(n, u"nrecs"), fbd_xml.COL_BLK + 840))

    # ==================================================================
    # СЕТЬ 37. SAVE: создание файла и запись страниц (фазы 72-75)
    # ==================================================================
    n = p.network(u"СЕТЬ 38. Фазы 72-75: SAVE - создать файл и записать страницы")
    s72 = AND(n, I(n, u"hit"), _at(n, PH_SAV_M), fbd_xml.COL_BLK + 120)
    n.outvar(u"GVL_CPM.DMA", IF(n, s72, I(n, u"WORD#%d" % D.TPA_ENTRY),
                                I(n, u"GVL_CPM.DMA"), fbd_xml.COL_BLK + 240))
    n.outvar(u"srec", IF(n, s72, I(n, u"WORD#0"), I(n, u"srec"),
                         fbd_xml.COL_BLK + 360))
    s73 = AND(n, I(n, u"hit"), _at(n, PH_SAV_W), fbd_xml.COL_BLK + 480)
    n.outvar(u"srec", IF(n, AND(n, s73, I(n, u"e_done"), fbd_xml.COL_BLK + 600),
                         I(n, u"WORD#0"), I(n, u"srec"), fbd_xml.COL_BLK + 720))
    n.outvar(u"s75", AND(n, I(n, u"hit"), _at(n, PH_SAV_XW),
                         fbd_xml.COL_BLK + 840))
    n.outvar(u"srec", IF(n, AND(n, I(n, u"s75"), I(n, u"e_done"),
                                fbd_xml.COL_BLK + 960),
                         ADD(n, I(n, u"srec"), I(n, u"WORD#1"),
                             fbd_xml.COL_BLK + 1080),
                         I(n, u"srec"), fbd_xml.COL_BLK + 1200))
    n.outvar(u"tend", ANDL(n, [I(n, u"s75"),
                               GE(n, I(n, u"srec"), I(n, u"nrecs"),
                                  fbd_xml.COL_BLK + 1320)],
                           x0=fbd_xml.COL_BLK + 1440))
    n.outvar(u"tdma", ADD(n, I(n, u"WORD#%d" % D.TPA_ENTRY),
                          SHL(n, I(n, u"srec"), I(n, u"WORD#7"),
                              fbd_xml.COL_BLK + 1560), fbd_xml.COL_BLK + 1680))
    n.outvar(u"GVL_CPM.DMA", IF(n, I(n, u"s75"), I(n, u"tdma"),
                                I(n, u"GVL_CPM.DMA"), fbd_xml.COL_BLK + 1800))

    # ==================================================================
    # СЕТЬ 39. USER и EXIT (фазы 80, 85-86)
    # ==================================================================
    n = p.network(u"СЕТЬ 40. Фазы 80, 85-86: USER и останов эмулятора")
    u80 = AND(n, I(n, u"hit"), _at(n, PH_USER), fbd_xml.COL_BLK + 120)
    n.outvar(u"GVL_CPM.CurUser",
             IF(n, AND(n, u80, I(n, u"un_ok"), fbd_xml.COL_BLK + 240),
                 W2B(n, I(n, u"unum"), fbd_xml.COL_BLK + 360),
                 I(n, u"GVL_CPM.CurUser"), fbd_xml.COL_BLK + 480))
    n.outvar(u"GVL_CPM.CCP_Err",
             IF(n, u80, IF(n, I(n, u"un_ok"), I(n, B % 0), I(n, B % 6),
                           fbd_xml.COL_BLK + 600),
                 I(n, u"GVL_CPM.CCP_Err"), fbd_xml.COL_BLK + 720))
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_EXIT), fbd_xml.COL_BLK + 840),
              I(n, H % CR), note=u"CR перед остановом")
    emit_char(p, AND(n, I(n, u"hit"), _at(n, PH_EXIT2), fbd_xml.COL_BLK + 840),
              I(n, H % LF), note=u"LF перед остановом")
    n.outvar(u"GVL_CPM.CPU_Run",
             IF(n, AND(n, I(n, u"hit"), _at(n, PH_EXIT2), fbd_xml.COL_BLK + 960),
                 I(n, u"FALSE"), I(n, u"GVL_CPM.CPU_Run"), fbd_xml.COL_BLK + 1080))

    # ==================================================================
    # СЕТЬ 41. Внешняя команда: сборка FCB имени.COM (фаза 90)
    # ==================================================================
    n = p.network(u"СЕТЬ 42. Фаза 90: CCP_FCB := имя команды + расширение COM")
    e90 = AND(n, I(n, u"hit"), _at(n, PH_EXT_S), fbd_xml.COL_BLK + 120)
    tgt = u"GVL_MEM.Memory[%s]" % (WH % D.CCP_FCB)
    n.outvar(tgt, IF(n, e90, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 240))
    for k in range(8):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_FCB + 1 + k))
        n.outvar(tgt, IF(n, e90, I(n, u"GVL_MEM.Memory[%s]"
                                   % (WH % (D.CCP_WORK + k))), I(n, tgt),
                         fbd_xml.COL_BLK + 360))
    for k, c in enumerate((0x43, 0x4F, 0x4D)):     # 'C','O','M'
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_FCB + 9 + k))
        n.outvar(tgt, IF(n, e90, I(n, H % c), I(n, tgt), fbd_xml.COL_BLK + 480))
    for k in range(4):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_FCB + 12 + k))
        n.outvar(tgt, IF(n, e90, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 600))
    for k in range(16):
        tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_FCB + 16 + k))
        n.outvar(tgt, IF(n, e90, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 720))
    tgt = u"GVL_MEM.Memory[%s]" % (WH % (D.CCP_FCB + 32))
    n.outvar(tgt, IF(n, e90, I(n, B % 0), I(n, tgt), fbd_xml.COL_BLK + 840))
    n.outvar(u"ld_start", ANDL(n, [I(n, u"hit"),
                                   OR(n, _at(n, PH_EXT_S), _at(n, PH_EXT_W),
                                      fbd_xml.COL_BLK + 960)],
                               x0=fbd_xml.COL_BLK + 1080))

    # ==================================================================
    # СЕТЬ 43. Переход внешней команды (фаза 92)
    # ==================================================================
    n = p.network(u"СЕТЬ 44. Фаза 92: запуск загруженной .COM-программы")
    e92 = AND(n, I(n, u"hit"), _at(n, PH_EXT_J), fbd_xml.COL_BLK + 120)
    n.outvar(u"GVL_CPM.DMA", IF(n, e92, I(n, u"WORD#%d" % DIRBUF),
                                I(n, u"GVL_CPM.DMA"), fbd_xml.COL_BLK + 240))
    n.outvar(u"GVL_CPM.Jump_Req", IF(n, e92, I(n, u"TRUE"),
                                     I(n, u"GVL_CPM.Jump_Req"),
                                     fbd_xml.COL_BLK + 360))
    n.outvar(u"GVL_CPM.Jump_PC", IF(n, e92, I(n, u"WORD#%d" % D.BOOT_STUB),
                                    I(n, u"GVL_CPM.Jump_PC"),
                                    fbd_xml.COL_BLK + 480))
    n.outvar(u"GVL_CPM.Jump_SP", IF(n, e92, I(n, u"WORD#%d" % D.STACK_TOP),
                                    I(n, u"GVL_CPM.Jump_SP"),
                                    fbd_xml.COL_BLK + 600))
    n.outvar(u"GVL_CPM.Ret_Val", IF(n, e92, I(n, B % 0), I(n, u"GVL_CPM.Ret_Val"),
                                    fbd_xml.COL_BLK + 720))

    # ==================================================================
    # СЕТЬ 45. Сообщение "NO FILE" (фаза 33)
    # ==================================================================
    n = p.network(u"СЕТЬ 46. Фаза 33: сообщение NO FILE")
    in_err = AND(n, I(n, u"hit"), _at(n, PH_ERR), fbd_xml.COL_BLK + 120)
    n.outvar(u"ech", CHAIN(n, I(n, H % SP), [
        (EQ(n, I(n, u"ec"), I(n, B % 0)), I(n, H % 0x4E)),
        (EQ(n, I(n, u"ec"), I(n, B % 1)), I(n, H % 0x4F)),
        (EQ(n, I(n, u"ec"), I(n, B % 2)), I(n, H % SP)),
        (EQ(n, I(n, u"ec"), I(n, B % 3)), I(n, H % 0x46)),
        (EQ(n, I(n, u"ec"), I(n, B % 4)), I(n, H % 0x49)),
        (EQ(n, I(n, u"ec"), I(n, B % 5)), I(n, H % 0x4C)),
        (EQ(n, I(n, u"ec"), I(n, B % 6)), I(n, H % 0x45)),
        (EQ(n, I(n, u"ec"), I(n, B % 7)), I(n, H % CR)),
        (EQ(n, I(n, u"ec"), I(n, B % 8)), I(n, H % LF)),
    ], x0=fbd_xml.COL_BLK + 240))
    emit_char(p, in_err, I(n, u"ech"), note=u"сообщение NO FILE")
    n.outvar(u"cend33", AND(n, in_err, GE(n, I(n, u"ec"), I(n, B % 9),
                                          fbd_xml.COL_BLK + 1400),
                            fbd_xml.COL_BLK + 1520))
    n.outvar(u"ec", IF(n, in_err,
                       ADD(n, I(n, u"ec"), I(n, B % 1), fbd_xml.COL_BLK + 1640),
                       I(n, B % 0), fbd_xml.COL_BLK + 1760))

    # ==================================================================
    # СЕТЬ 47. Неизвестная команда: "<ИМЯ>?" (фаза 93)
    # ==================================================================
    n = p.network(u"СЕТЬ 48. Фаза 93: неизвестная команда - имя и знак '?'")
    n.outvar(u"in_unk", AND(n, I(n, u"hit"), _at(n, PH_ERRU), fbd_xml.COL_BLK + 120))
    n.outvar(u"cpos_w", I(n, u"cpos"))
    n.outvar(u"c1", IF(n, LT(n, I(n, u"cpos"), I(n, B % 8), fbd_xml.COL_BLK + 240),
                       I(n, u"GVL_MEM.Memory[%s + cpos_w]" % (WH % D.CCP_WORK)),
                       I(n, H % 0x3F), fbd_xml.COL_BLK + 360))
    n.outvar(u"c2", IF(n, EQ(n, I(n, u"cpos"), I(n, B % 8), fbd_xml.COL_BLK + 480),
                       I(n, H % CR), I(n, u"c1"), fbd_xml.COL_BLK + 600))
    n.outvar(u"pc_c", IF(n, EQ(n, I(n, u"cpos"), I(n, B % 9),
                               fbd_xml.COL_BLK + 720),
                         I(n, H % LF), I(n, u"c2"), fbd_xml.COL_BLK + 840))
    n.outvar(u"pc_g", ANDL(n, [I(n, u"in_unk"),
                               LT(n, I(n, u"cpos"), I(n, B % 8),
                                  fbd_xml.COL_BLK + 960),
                               NOT(n, EQ(n, I(n, u"c1"), I(n, H % SP),
                                         fbd_xml.COL_BLK + 1080),
                                   fbd_xml.COL_BLK + 1200)],
                           x0=fbd_xml.COL_BLK + 1320))
    n.outvar(u"pc_g", OR(n, I(n, u"pc_g"),
                         ANDL(n, [I(n, u"in_unk"),
                                  GE(n, I(n, u"cpos"), I(n, B % 8),
                                     fbd_xml.COL_BLK + 1440),
                                  LE(n, I(n, u"cpos"), I(n, B % 9),
                                     fbd_xml.COL_BLK + 1560)],
                              x0=fbd_xml.COL_BLK + 1680), fbd_xml.COL_BLK + 1800))
    emit_char(p, I(n, u"pc_g"), I(n, u"pc_c"), note=u"неизвестная команда")
    n.outvar(u"cend93", AND(n, I(n, u"in_unk"), GE(n, I(n, u"cpos"), I(n, B % 10),
                                          fbd_xml.COL_BLK + 1920),
                            fbd_xml.COL_BLK + 2040))
    n.outvar(u"cpos", IF(n, I(n, u"in_unk"),
                         ADD(n, I(n, u"cpos"), I(n, B % 1),
                             fbd_xml.COL_BLK + 2160),
                         I(n, B % 0), fbd_xml.COL_BLK + 2280))

    # ==================================================================
    # СЕТЬ 49. Автомат фаз: таблица переходов и квитанция
    # ==================================================================
    n = p.network(u"СЕТЬ 50. Автомат фаз CCP: таблица переходов и квитанция трапу")
    # ================= ПРИОРИТЕТ ПРАВИЛ ПЕРЕХОДА (фаза B) =================
    # CHAIN строит цепочку SEL, где КАЖДЫЙ следующий шаг ПЕРЕКРЫВАЕТ
    # предыдущий: приоритет у ПОСЛЕДНЕГО совпавшего. Поэтому правила одной
    # фазы надо подавать так, чтобы УСЛОВНЫЕ шли ПОСЛЕ безусловного:
    #     (X, always, A), (X, cond1, B)  ->  сработает cond1, иначе A.
    # В таблице TRANS порядок обратный (условные идут после "always"), из-за
    # чего условные переходы подавлялись, а безусловные не срабатывали:
    # CCP застревал в фазах 5 (CR) и 13 (ENDTOK) - наблюдалось
    # CCP_Phase = 5/13, CCP_Cnt = 1, приглашение "A>" и больше ничего.
    # Здесь правила ГРУППИРУЮТСЯ ПО ФАЗЕ и внутри группы сортируются так,
    # чтобы безусловное правило оказалось ПЕРВЫМ в списке (то есть младшим
    # по приоритету). Порядок фаз между собой сохраняется.
    _order = []
    for _ph, _flag, _tgt in TRANS:
        if _ph not in _order:
            _order.append(_ph)
    _by_ph = {}
    for _ph, _flag, _tgt in TRANS:
        _by_ph.setdefault(_ph, []).append((_flag, _tgt))
    TRANS_SORTED = []
    for _ph in _order:
        _grp = _by_ph[_ph]
        # безусловные - в начало (низший приоритет), условные - в конец
        _alw = [x for x in _grp if x[0] == u"always"]
        _cnd = [x for x in _grp if x[0] != u"always"]
        for _flag, _tgt in _alw + _cnd:
            TRANS_SORTED.append((_ph, _flag, _tgt))
    trans = []
    for ph_k, flag, tgt in TRANS_SORTED:
        if flag == u"always":
            cond = AND(n, I(n, u"hit"), _at(n, ph_k), fbd_xml.COL_BLK + 240)
        else:
            cond = ANDL(n, [I(n, u"hit"), _at(n, ph_k), I(n, flag)],
                        x0=fbd_xml.COL_BLK + 360)
        if tgt == u"zero":
            val = I(n, B % 0)
        elif tgt == u"ret":
            val = I(n, u"ret_ph")
        elif tgt == u"rt":
            val = I(n, u"rt")
        else:
            val = I(n, B % tgt)
        trans.append((cond, val))
    n.outvar(u"ph_next", CHAIN(n, I(n, u"ph"), trans, x0=fbd_xml.COL_BLK + 600))
    # ================= КВИТАНЦИЯ «КОМАНДА ОТРАБОТАНА» (фаза B) =================
    # ЗДЕСЬ БЫЛА ПРИЧИНА, ПО КОТОРОЙ CP/M НЕ РАБОТАЛ ВООБЩЕ.
    # Раньше квитанция трапу (done_gate) выставлялась по условию
    #     done_gate = hit AND (ph_next = 0)
    # но PH_INIT = 0! То есть CCP в САМОЙ ПЕРВОЙ фазе (сброс буферов перед
    # разбором) немедленно сообщал «функция выполнена», и трап возвращал
    # управление на адрес из стека, не дав CCP прочитать строку и выполнить
    # команду. Наблюдалось: CCP_Phase так и оставался 0 или 1, CCP_Cnt = 1,
    # журнал 10 знаков (два приглашения "A>"), каталог не печатался.
    # Теперь квитанция выдаётся ТОЛЬКО на возврате в фазу 0 из фазы РАЗБОРА
    # (то есть когда разбор строки завершён и команда выполнена) - условие
    # `ph` сейчас НЕ 0, а `ph_next` = 0.
    n.outvar(u"done_gate",
             AND(n, I(n, u"hit"),
                 AND(n, NOT(n, _at(n, PH_INIT), fbd_xml.COL_BLK + 800),
                     EQ(n, I(n, u"ph_next"), I(n, B % 0), fbd_xml.COL_BLK + 900),
                     fbd_xml.COL_BLK + 1000),
                 fbd_xml.COL_BLK + 1100))
    n.outvar(u"ph", I(n, u"ph_next"))
    n.outvar(u"Done", I(n, u"done_gate"))
    n.outvar(u"GVL_CPM.Func_Done",
             IF(n, I(n, u"done_gate"), I(n, u"TRUE"), I(n, u"GVL_CPM.Func_Done"),
                 fbd_xml.COL_BLK + 1500))
    return p


ALL = (make_ccp,)
NAMES = (u"FB_CCP",)
