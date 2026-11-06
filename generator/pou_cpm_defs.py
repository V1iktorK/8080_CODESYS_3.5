# -*- coding: utf-8 -*-
u"""Слой CP/M 2.2 (HLE): ОБЩИЕ ОПРЕДЕЛЕНИЯ для BIOS, BDOS, трапов и диска.

Этот модуль - единственное место, где заданы:
  * карта памяти CP/M (адреса ловушек, таблиц, каталога, DPB);
  * номера функций BDOS и BIOS;
  * тексты DUT: ST_FCB, ST_DPB, ST_DirEntry, ST_CpmDiag;
  * тексты GVL: GVL_CPM, GVL_DISK;
  * конструкторы элементов FBD (I, AND, OR, EQ, SEL, CHAIN, ORL, ...).

ПРАВИЛА ДИАЛЕКТА, обязательные для всего слоя (docs/03_ЖУРНАЛ_СБОРКИ.md):
  * один выход = ровно одна связь (генератор размножает источники сам);
  * выход вызова FB ЗАЩЁЛКИВАЕТСЯ в переменную POU и никогда не идёт на вход
    блока напрямую (п. 9.1 и 11.2) - в этом модуле для этого есть latch();
  * байт перед 16-разрядным сдвигом переносится в переменную WORD (п. 10.1);
  * порядок сетей = порядок выполнения, ссылки только "назад".
"""

import fbd_xml
from fbd_xml import Pou

# ======================================================================
# КАРТА ПАМЯТИ CP/M 2.2 (совпадает с docs/04_ПЛАН_CPM.md, раздел 3.2)
# ======================================================================
BDOS_ENTRY = 0xF000      # точка входа BDOS (ловушка)
CCP_ENTRY = 0xF100       # точка входа CCP (ловушка), сюда ведёт WBOOT
BIOS_TABLE = 0xE000      # таблица переходов BIOS: 17 записей по 3 байта
BIOS_TRAP = 0xFE00       # ловушка BIOS: запись i -> FE00h + i*3
BIOS_COUNT = 17          # число функций BIOS
DPB_ADDR = 0xFF00        # таблица параметров диска (её читают STAT и др.)
DPH_ADDR = 0xFF10        # заголовок параметров диска (возвращает SELDSK)
DIRBUF_ADDR = 0xFF80     # буфер каталога (как в настоящем CP/M - 128 байт)
SCRATCH = 0xF200         # мусорный буфер: сюда уходят отключённые копии
TPA_ENTRY = 0x0100       # начало TPA, сюда грузится .COM
STACK_TOP = 0xF200       # вершина системного стека
TPA_TOP = 0xDFFF         # верхняя граница TPA
DMA_DEF = 0x0080         # адрес DMA по умолчанию
ZERO_PAGE = 0x0000       # страница нулевого адреса
FCB1_DEF = 0x005C        # FCB первого аргумента команды (как в настоящем CCP)
SYS_SCRATCH = 0xF300     # системная рабочая область выше стека (загрузчик .COM)
CCP_FCB = 0xF300         # FCB, которым CCP ищет и грузит .COM-файл
CCP_WORK = 0xF340        # рабочая область CCP: имя команды, счётчики
CCP_TAIL_MAX = 0x3E      # предел длины хвоста команды в буфере 0080h
BOOT_STUB = 0xF380       # бутстрап-заглушка: обнуление регистров + JMP 0100h

# ======================================================================
# ДИСКОВЫЙ ОБРАЗ CP/M 2.2 - ДВА ПРОФИЛЯ, выбор ОДНОЙ КОНСТАНТОЙ
# ======================================================================
# Профиль задаёт таблицу параметров диска (DPB) целиком: от неё считаются
# размер блока, раскладка каталога, карта занятости блоков и адресация в
# BIOS. Формат - НАСТОЯЩИЙ CP/M 2.2, а не упрощённый 64-килобайтный образ
# этапа 3.2 (см. docs/04_ПЛАН_CPM.md, раздел 4.1: в задании смешаны два
# разных формата - дискета 8" SSSD и винчестер 8 МБ, поэтому их два).
PROFILE_FLOPPY_256K = {
    u"name": u"FLOPPY_256K",
    u"doc": u"дискета 8\" SSSD 256 КБ (профиль по умолчанию)",
    u"SPT": 26, u"BSH": 3, u"BLM": 7, u"EXM": 1,
    u"DSM": 242, u"DRM": 63, u"AL0": 0xC0, u"AL1": 0x00,
    u"CKS": 16, u"OFF": 2, u"TRACKS": 77, u"IMAGE": 262144,
}
PROFILE_HARD_8M = {
    u"name": u"HARD_8M",
    u"doc": u"винчестер 8 МБ (только x64/RPi: 8 МБ ОЗУ под образ)",
    u"SPT": 128, u"BSH": 5, u"BLM": 31, u"EXM": 1,
    u"DSM": 2047, u"DRM": 1023, u"AL0": 0xFF, u"AL1": 0xFF,
    u"CKS": 0, u"OFF": 0, u"TRACKS": 512, u"IMAGE": 8388608,
}

# >>> ВЫБОР ПРОФИЛЯ: поменяйте на PROFILE_HARD_8M и пересоберите проект <<<
DISK_PROFILE = PROFILE_FLOPPY_256K

_P = DISK_PROFILE

# ---- параметры DPB выбранного профиля (ровно те, что видит программа) ----
SPT = _P[u"SPT"]         # секторов на дорожку
BSH = _P[u"BSH"]         # сдвиг размера блока: блок = 128 << BSH
BLM = _P[u"BLM"]         # маска размера блока: блок = BLM + 1 записей
EXM = _P[u"EXM"]         # маска экстента
DSM = _P[u"DSM"]         # общее число блоков минус 1
DRM = _P[u"DRM"]         # число записей каталога минус 1
AL0 = _P[u"AL0"]         # биты занятости первых 8 блоков (каталог)
AL1 = _P[u"AL1"]         # биты занятости блоков 8..15
CKS = _P[u"CKS"]         # размер контрольной суммы каталога
OFF = _P[u"OFF"]         # число резервных дорожек (системная область)
TRACKS = _P[u"TRACKS"]   # дорожек в образе

REC_SIZE = 128                       # запись CP/M - всегда 128 байт
BLOCK_SIZE = REC_SIZE << BSH         # блок данных: 1 КБ (дискета), 4 КБ (винт)
SEC_PER_BLK = 1 << BSH               # секторов по 128 байт в блоке
RECS_PER_BLOCK = 1 << BSH            # записей по 128 байт в блоке
DIR_ENTRIES = DRM + 1                # записей каталога: 64 или 1024
ENT_SIZE = 32                        # размер записи каталога - 32 байта
DIR_BYTES = DIR_ENTRIES * ENT_SIZE   # 2048 или 32768 байт
DIR_BLOCKS = DIR_BYTES // BLOCK_SIZE # сколько блоков занимает каталог
ENT_PER_SEC = REC_SIZE // ENT_SIZE   # 4 записи каталога в одном секторе
DIR_SECT = OFF * SPT                 # первый сектор каталога (после OFF дорожек)
TOTAL_BLOCKS = DSM + 1               # 243 или 2048 блоков
LAST_BLOCK = DSM
DATA_BASE_SECT = DIR_SECT            # блок 0 начинается с этого сектора


def _first_used_free(profile):
    u"""Первый блок, свободный по битовой карте AL0/AL1.

    Именно эта карта (а не догадки) говорит CP/M, какие блоки заняты
    системной областью: у дискеты AL0=C0h - заняты блоки 0 и 1 (каталог),
    у винчестера AL0=AL1=FFh - заняты блоки 0..15.
    """
    bits = profile[u"AL0"] | (profile[u"AL1"] << 8)
    for i in range(16):
        if not ((bits >> i) & 1):
            return i
    return 16


# первый блок, который можно отдавать файлам: каталог + системная область
FIRST_DATA_BLOCK = max(DIR_BLOCKS, _first_used_free(_P))
RESERVED_BLOCKS = max(DIR_BLOCKS, _first_used_free(_P))

# Секторов в образе: каталог + все блоки данных. Дискета: 52 + 243*8 = 1996,
# винчестер: 0 + 2048*32 = 65536 (индекс сектора WORD доходит ровно до 65535).
DISK_SECTORS = DIR_SECT + TOTAL_BLOCKS * SEC_PER_BLK
# Массив образа округляется вверх до степени двойки: так последняя пара
# секторов остаётся заведомо внутри массива и служит «мусорным» сектором
# для отключённого направления переноса (запись в никуда - не авария ПЛК).
_arr = 1
while _arr < max(DISK_SECTORS, TRACKS * SPT):
    _arr <<= 1
DISK_ARR_SEC = _arr                  # 2048 или 65536 секторов в объявлении
DISK_BYTES = DISK_ARR_SEC * REC_SIZE # 256 КБ или 8 МБ
DISK_SCRATCH_SEC = DISK_ARR_SEC - 1  # сектор-«мусорка» (индекс всегда в границах)
ALLOC_BYTES = (TOTAL_BLOCKS + 7) // 8  # байт в битовой карте занятости блоков
# Записей, адресуемых одной записью каталога: 16 байт карты блоков, по 1 байту
# на блок при DSM<256 и по 2 байта при DSM>255 (правило самого BDOS CP/M 2.2).
BLK_BYTES = 1 if DSM < 256 else 2
BLOCKS_PER_ENTRY = 16 // BLK_BYTES
RECS_PER_ENTRY = BLOCKS_PER_ENTRY * RECS_PER_BLOCK   # 128 или 256 записей
RECS_PER_EXTENT = RECS_PER_ENTRY     # синоним для читаемости

# ======================================================================
# ФУНКЦИИ BDOS (номер -> мнемоника). Реализованы все, что есть в задании.
# ======================================================================
BDOS_NAMES = (
    (1, u"CONIN", u"ввод символа с консоли (ждёт готовности)"),
    (2, u"CONOUT", u"вывод символа из E на консоль"),
    (9, u"PRINTSTR", u"вывод строки по DE до символа '$'"),
    (10, u"READLINE", u"ввод строки в буфер по DE (ждёт CR)"),
    (11, u"CONST", u"состояние консоли: E=FFh - есть ли символ"),
    (12, u"VERSION", u"версия CP/M: HL = 0022h"),
    (13, u"RESETDISK", u"сброс диска: DMA := 0080h, диск A"),
    (14, u"SELDSK", u"выбор диска по E"),
    (15, u"OPEN", u"открыть файл по FCB (DE)"),
    (16, u"CLOSE", u"закрыть файл, записать FCB в каталог"),
    (17, u"SEARCHFIRST", u"поиск первой записи каталога по FCB"),
    (18, u"SEARCHNEXT", u"поиск следующей записи каталога"),
    (19, u"DELETE", u"удалить файл (все совпавшие записи)"),
    (20, u"READSEQ", u"чтение записи 128 Б по FCB в DMA"),
    (21, u"WRITESEQ", u"запись записи 128 Б из DMA в файл"),
    (22, u"MAKE", u"создать файл (свободная запись каталога)"),
    (23, u"RENAME", u"переименовать файл: старое имя в FCB+0, новое в FCB+16"),
    (24, u"LOGINVEC", u"вектор входа - заглушка"),
    (25, u"CURDISK", u"номер текущего диска в A"),
    (26, u"SETDMA", u"установить адрес DMA из DE"),
    (30, u"ATTRIB", u"атрибуты файла: старшие биты t1/t2/t3 записи каталога"),
    (32, u"USER", u"установить номер пользователя из E"),
    (33, u"READRAND", u"чтение записи по случайному номеру (r0..r2)"),
    (34, u"WRITERAND", u"запись записи по случайному номеру (r0..r2)"),
    (35, u"FILESIZE", u"размер файла: r0..r2 := номер последней записи + 1"),
    (36, u"SETRANDREC", u"вычислить случайный номер записи из ex и cr"),
    (40, u"WRITERANDZF", u"запись по случайному номеру с забивкой нулями"),
)

# ======================================================================
# ФУНКЦИИ BIOS (номер -> имя FB и мнемоника)
# ======================================================================
BIOS_NAMES = (
    (0, u"BOOT", u"холодный старт системы"),
    (1, u"WBOOT", u"тёплый старт: перезагрузка CCP"),
    (2, u"CONST", u"состояние консоли: A=FFh, если есть символ"),
    (3, u"CONIN", u"ввод символа с консоли в A"),
    (4, u"CONOUT", u"вывод символа из C на консоль"),
    (5, u"LIST", u"вывод символа из C на устройство LIST"),
    (6, u"PUNCH", u"вывод символа из C на перфоратор"),
    (7, u"READER", u"ввод символа с устройства READER"),
    (8, u"HOME", u"установить дорожку 0"),
    (9, u"SELDSK", u"выбрать диск из C, HL = адрес DPH"),
    (10, u"SETTRK", u"установить дорожку из BC"),
    (11, u"SETSEC", u"установить сектор из BC"),
    (12, u"SETDMA", u"установить адрес DMA из BC"),
    (13, u"READ", u"чтение 128 Б в DMA с дорожки/сектора"),
    (14, u"WRITE", u"запись 128 Б из DMA на дорожку/сектор"),
    (15, u"LISTST", u"состояние LIST: A=FFh (готов)"),
    (16, u"SECTRAN", u"трансляция сектора (без перекоса)"),
)

# ======================================================================
# ОПЕРАЦИИ ДИСКОВОГО ДВИЖКА (поле Op у FB_CPM_DirEngine)
# ======================================================================
OP_SEARCH_FIRST = 0
OP_SEARCH_NEXT = 1
OP_OPEN = 2
OP_CLOSE = 3
OP_MAKE = 4
OP_DELETE = 5
OP_READSEQ = 6
OP_WRITESEQ = 7
OP_RENAME = 8       # RENAME: новое имя берётся из FCB+16
OP_ATTRIB = 9       # ATTRIB: атрибуты - старшие биты t1/t2/t3
OP_FINDEXT = 10     # найти запись каталога с заданным номером экстента (ex)
OP_FILESIZE = 11    # проход по всему каталогу: максимальный размер файла
OP_FREEBLK = 12     # освободить блоки удаляемой записи в битовой карте
OP_MARKDIR = 13     # пометить блоки записи каталога занятыми (MAKE/CLOSE)

# ======================================================================
# ТЕКСТЫ DUT
# ======================================================================
DUT_FCB = u"""TYPE ST_FCB :
STRUCT
    (* Блок управления файлом CP/M 2.2 - РОВНО 36 байт.
       Смещения заданы стандартом CP/M, программа работает с FCB побайтно. *)
    dr  : BYTE;            (* 0  номер диска: 0..15, '?' = текущий *)
    f1  : BYTE;            (* 1  имя, 8 байт, старший бит = атрибут *)
    f2  : BYTE;
    f3  : BYTE;
    f4  : BYTE;
    f5  : BYTE;
    f6  : BYTE;
    f7  : BYTE;
    f8  : BYTE;            (* 8  *)
    t1  : BYTE;            (* 9  расширение, 3 байта *)
    t2  : BYTE;
    t3  : BYTE;            (* 11 *)
    ex  : BYTE;            (* 12 номер экстента 0..31 *)
    s1  : BYTE;            (* 13 зарезервировано *)
    s2  : BYTE;            (* 14 номер экстента, старшая часть *)
    rc  : BYTE;            (* 15 число записей в экстенте 0..128 *)
    d0  : BYTE;            (* 16 карта блоков: 16 байт *)
    d1  : BYTE;
    d2  : BYTE;
    d3  : BYTE;
    d4  : BYTE;
    d5  : BYTE;
    d6  : BYTE;
    d7  : BYTE;
    d8  : BYTE;
    d9  : BYTE;
    d10 : BYTE;
    d11 : BYTE;
    d12 : BYTE;
    d13 : BYTE;
    d14 : BYTE;
    d15 : BYTE;            (* 31 *)
    cr  : BYTE;            (* 32 текущая запись 0..127 *)
    r0  : BYTE;            (* 33 *)
    r1  : BYTE;            (* 34 *)
    r2  : BYTE;            (* 35 *)
END_STRUCT
END_TYPE
"""

DUT_DPB = u"""TYPE ST_DPB :
 STRUCT
     (* Параметры диска CP/M 2.2 (15 байт в памяти, здесь - по полям).
        Профиль задаётся константой DISK_PROFILE в генераторе:
         FLOPPY_256K - SPT=26 BSH=3 BLM=7 EXM=1 DSM=242 DRM=63 AL0=C0h CKS=16 OFF=2
         HARD_8M     - SPT=128 BSH=5 BLM=31 EXM=1 DSM=2047 DRM=1023 AL0=AL1=FFh CKS=0 OFF=0
        Значения полей дублируются в память по адресу 0FF00h - их читают
        программы CP/M (STAT и другие). *)
     SPT : WORD;            (* секторов на дорожку *)
     BSH : BYTE;            (* сдвиг размера блока: блок = 128 << BSH *)
     BLM : BYTE;            (* маска размера блока: блок = BLM + 1 записей *)
     EXM : BYTE;            (* маска экстента *)
     DSM : WORD;            (* общее число блоков минус 1 *)
     DRM : WORD;            (* число записей каталога минус 1 *)
     AL0 : BYTE;            (* биты занятости блоков 0..7 (системная область) *)
     AL1 : BYTE;            (* биты занятости блоков 8..15 *)
     CKS : WORD;            (* размер контрольной суммы каталога, в секторах *)
     OFF : WORD;            (* число резервных дорожек *)
 END_STRUCT
 END_TYPE
 """

DUT_DIRENTRY = u"""TYPE ST_DirEntry :
STRUCT
    (* Запись каталога CP/M - РОВНО 32 байта. *)
    st     : BYTE;         (* 0  номер пользователя 0..15, E5h = удалена *)
    name1  : BYTE;         (* 1  имя, 8 байт; старший бит = атрибут *)
    name2  : BYTE;
    name3  : BYTE;
    name4  : BYTE;
    name5  : BYTE;
    name6  : BYTE;
    name7  : BYTE;
    name8  : BYTE;         (* 8  *)
    ext1   : BYTE;         (* 9  расширение, 3 байта *)
    ext2   : BYTE;
    ext3   : BYTE;         (* 11 *)
    ex     : BYTE;         (* 12 номер экстента *)
    s1     : BYTE;         (* 13 *)
    s2     : BYTE;         (* 14 *)
    rc     : BYTE;         (* 15 число записей в экстенте *)
    blocks : ARRAY[0..15] OF BYTE;   (* 16 карта блоков файла *)
END_STRUCT
END_TYPE
"""

DUT_DIAG = u"""TYPE ST_CpmDiag :
STRUCT
    (* Диагностика слоя CP/M: коды ошибок и счётчики событий. *)
    Last_Err   : BYTE;     (* код последней ошибки (см. коды E_* в GVL_CPM) *)
    Last_Func  : BYTE;     (* номер последней функции BDOS *)
    Last_BIOS  : BYTE;     (* номер последней функции BIOS *)
    Trap_Cnt   : UDINT;    (* сколько раз срабатывали ловушки *)
    BDOS_Cnt   : UDINT;    (* вызовов BDOS *)
    BIOS_Cnt   : UDINT;    (* вызовов BIOS *)
    Unimpl_Cnt : UDINT;    (* обращений к нереализованным функциям *)
    Search_Cnt : UDINT;    (* проходов по каталогу *)
END_STRUCT
END_TYPE
"""

DUT_ALL = ((u"ST_FCB", DUT_FCB), (u"ST_DPB", DUT_DPB),
           (u"ST_DirEntry", DUT_DIRENTRY), (u"ST_CpmDiag", DUT_DIAG))


# ======================================================================
# ТЕКСТ GVL_CPM
# ======================================================================
def gvl_cpm_text():
    u"""Объявление GVL_CPM: состояние CP/M, трапы, порт записи регистров."""
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* CP/M 2.2 (HLE-слой): СОСТОЯНИЕ СИСТЕМЫ                            *)")
    L.append(u"\t(* BIOS/BDOS/CCP - это НЕ машинный код 8080, а нативные FBD-блоки.  *)")
    L.append(u"\t(* В эмулируемой памяти лежат только ТОЧКИ ВХОДА (команды JMP),     *)")
    L.append(u"\t(* поэтому программы CP/M видят привычные адреса.                   *)")
    L.append(u"\t(* ================================================================ *)")
    state = (
        (u"IOBYTE", u"BYTE", u"байт IOBYTE, копия ячейки 0003h"),
        (u"CurDisk", u"BYTE", u"текущий диск: 0=A, 1=B"),
        (u"CurUser", u"BYTE", u"текущий номер пользователя 0..15"),
        (u"DMA", u"WORD", u"адрес прямого доступа к памяти, по умолчанию 0080h"),
        (u"TPA_Top", u"WORD", u"верхняя граница TPA (DFFFh)"),
        (u"Disk_Track", u"WORD", u"текущая дорожка BIOS"),
        (u"Disk_Sector", u"WORD", u"текущий сектор BIOS"),
        (u"Disk_Sel", u"BYTE", u"последний выбранный BIOS-диск"),
        (u"Next_Block", u"BYTE", u"подсказка распределения: с этого блока искать свободный"),
        (u"Search_Idx", u"WORD", u"номер записи каталога для SEARCH NEXT"),
        (u"IO_Result", u"BYTE", u"последний код возврата файловой операции"),
        (u"LogWr", u"BOOL", u"запрос записи символа в журнал консоли"),
    (u"LogCh", u"BYTE", u"символ для журнала консоли"),
    (u"Init_Done", u"BOOL", u"память и таблицы CP/M инициализированы"),
        (u"CPU_Run", u"BOOL", u"разрешение работы эмулятора (FALSE = пауза)"),
        (u"CCP_Phase", u"BYTE", u"фаза CCP (для HMI и диагностики)"),
        (u"CCP_Cnt", u"UDINT", u"сколько команд выполнено консольным процессором"),
        (u"CCP_Err", u"BYTE", u"код последней ошибки CCP (0 - нет)"),
        (u"Last_Block", u"BYTE", u"последний выданный блок (диагностика размещения)"),
    )
    for n, t, c in state:
        L.append(u"\t%-12s : %-6s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== ТРАПЫ: куда попал PC и чем это обрабатывается ==== *)")
    L.append(u"\t(* 0F000h - BDOS, 0FE00h+3*i - BIOS-функция i, 0F100h - CCP *)")
    trap = (
        (u"Trap_BDOS", u"BOOL", u"PC попал на точку входа BDOS (0F000h)"),
        (u"Trap_BIOS", u"BOOL", u"PC попал на точку входа функции BIOS (0FE00h+3*i)"),
        (u"Trap_CCP", u"BOOL", u"PC попал на точку входа CCP (0F100h)"),
        (u"Trap_Active", u"BOOL", u"трап обрабатывается, процессор остановлен"),
        (u"Trap_Phase", u"BYTE", u"фаза автомата трапа (см. FB_CPM_Trap)"),
        (u"CPU_Enable", u"BOOL", u"разрешение такта процессора (FALSE на время трапа)"),
        (u"BDOS_Func", u"BYTE", u"номер вызванной функции BDOS (регистр C)"),
        (u"BIOS_Func", u"BYTE", u"номер вызванной функции BIOS 0..16"),
        (u"Func_Done", u"BOOL", u"вызванная функция выполнена (квитанция диспетчеру)"),
        (u"Jump_Req", u"BOOL", u"возврат не на адрес со стека, а на Jump_PC"),
        (u"Jump_PC", u"WORD", u"адрес, куда вернуться (загрузчик, WBOOT)"),
        (u"Jump_SP", u"WORD", u"указатель стека при таком возврате"),
    )
    for n, t, c in trap:
        L.append(u"\t%-12s : %-6s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== ВОЗВРАТ ИЗ ФУНКЦИИ (снимается со стека в момент трапа) ==== *)")
    ret = (
        (u"Ret_Addr", u"WORD", u"адрес возврата, снятый со стека"),
        (u"Ret_SP", u"WORD", u"SP после снятия адреса возврата (SP+2)"),
        (u"Ret_Val", u"BYTE", u"значение, возвращаемое в аккумуляторе A"),
        (u"Ret_HL", u"WORD", u"значение, возвращаемое в паре HL"),
        (u"Ret_HL_En", u"BOOL", u"функция вернула значение в HL (иначе HL сохраняется)"),
        (u"Param_DE", u"WORD", u"пара DE на момент вызова (FCB, буфер, строка)"),
        (u"Param_BC", u"WORD", u"пара BC на момент вызова (дорожка, сектор, DMA)"),
    )
    for n, t, c in ret:
        L.append(u"\t%-12s : %-6s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== РЕГИСТРЫ ПРОЦЕССОРА, ПУБЛИКУЕМЫЕ ЯДРОМ ==== *)")
    L.append(u"\t(* Процессор выкладывает их каждый скан: слой CP/M читает их здесь. *)")
    regs = ((u"Reg_A", u"BYTE"), (u"Reg_B", u"BYTE"), (u"Reg_C", u"BYTE"),
            (u"Reg_D", u"BYTE"), (u"Reg_E", u"BYTE"), (u"Reg_H", u"BYTE"),
            (u"Reg_L", u"BYTE"), (u"Reg_PC", u"WORD"), (u"Reg_SP", u"WORD"),
            (u"Reg_PSW", u"BYTE"))
    for n, t in regs:
        L.append(u"\t%-12s : %-6s;" % (n, t))
    L.append(u"")
    L.append(u"\t(* ==== ПОРТ ЗАПИСИ РЕГИСТРОВ СО СТОРОНЫ CP/M ==== *)")
    L.append(u"\t(* Два канала. CPM_Selk: 0=A 1=B 2=C 3=D 4=E 5=H 6=L 7=PC 8=SP 9=Flags. *)")
    L.append(u"\t(* Запись выполняется, когда CPM_WE и CPM_LDk истинны. Значение      *)")
    L.append(u"\t(* CPM_Data1/2 - слово: для регистров A..L и флагов берётся младший     *)")
    L.append(u"\t(* байт, для PC/SP - всё слово. Процессор применяет запись на         *)")
    L.append(u"\t(* следующем скане: сначала он выкладывает регистры, потом патчит их.  *)")
    port = ((u"CPM_WE", u"BOOL", u"общее разрешение записи со стороны CP/M"),
            (u"CPM_Sel1", u"BYTE", u"номер регистра, канал 1"),
            (u"CPM_Data1", u"WORD", u"записываемое значение, канал 1"),
            (u"CPM_LD1", u"BOOL", u"строб записи, канал 1"),
            (u"CPM_Sel2", u"BYTE", u"номер регистра, канал 2"),
            (u"CPM_Data2", u"WORD", u"записываемое значение, канал 2"),
            (u"CPM_LD2", u"BOOL", u"строб записи, канал 2"))
    for n, t, c in port:
        L.append(u"\t%-12s : %-6s; (* %s *)" % (n, t, c))
    L.append(u"")
    L.append(u"\t(* ==== КОНСОЛЬ (вход - от HMI, выход - в журнал и на HMI) ==== *)")
    con = ((u"ConIn_Char", u"BYTE", u"символ, введённый с консоли"),
           (u"ConIn_Ready", u"BOOL", u"символ готов (ставит HMI)"),
           (u"ConOut_Char", u"BYTE", u"символ, выводимый на консоль"),
           (u"ConOut_Ready", u"BOOL", u"импульс: символ выведен"),
           (u"Con_Log", u"ARRAY[0..255] OF BYTE", u"журнал вывода консоли (для HMI)"),
           (u"Con_Log_Len", u"INT", u"число выведенных символов"))
    for n, t, c in con:
        L.append(u"\t%-12s : %-24s (* %s *)" % (n, t + u";", c))
    L.append(u"")
    L.append(u"\t(* ==== ФАЙЛЫ И ДИАГНОСТИКА ==== *)")
    misc = ((u"FCB_Addr", u"WORD", u"адрес текущего FCB (пара DE)"),
            (u"Dir_Result", u"BYTE", u"код возврата операций с каталогом"),
            (u"Diag", u"ST_CpmDiag", u"диагностика: коды ошибок и счётчики"))
    for n, t, c in misc:
        L.append(u"\t%-12s : %-24s (* %s *)" % (n, t + u";", c))
    L.append(u"")
    L.append(u"\t(* ==== КОДЫ ОШИБОК (Diag.Last_Err) ==== *)")
    for code, txt in ((u"0", u"нет ошибки"), (u"1", u"конец файла (не записано)"),
                      (u"2", u"файл не найден"), (u"3", u"нет места в каталоге"),
                      (u"4", u"нет свободных блоков"), (u"5", u"функция не реализована"),
                      (u"6", u"недопустимый параметр")):
        L.append(u"\t(* %s - %s *)" % (code, txt))
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


# ======================================================================
# ТЕКСТ GVL_DISK
# ======================================================================
def gvl_disk_text():
    u"""Объявление GVL_DISK: образ RAM-диска в НАСТОЯЩЕМ формате CP/M 2.2."""
    L = [u"VAR_GLOBAL"]
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\t(* ОБРАЗ ДИСКА CP/M 2.2 - НАСТОЯЩИЙ ФОРМАТ (этап 3.5).               *)")
    L.append(u"\t(* Профиль: %-15s (DPB задан в генераторе).        *)" % _P[u"name"])
    L.append(u"\t(* Раскладка (байтовые адреса считаются от начала образа):           *)")
    L.append(u"\t(*   OFF x SPT x 128 = %-6d Б - резервные дорожки (системная      *)"
             % (OFF * SPT * REC_SIZE))
    L.append(u"\t(*                              область, как в настоящем CP/M)      *)")
    L.append(u"\t(*   далее %-5d Б - каталог: %d записей по 32 байта              *)"
             % (DIR_BYTES, DIR_ENTRIES))
    L.append(u"\t(*   далее - блоки данных по %d Б; блок N начинается с сектора    *)"
             % BLOCK_SIZE)
    L.append(u"\t(*   DIR_SECT + N x %d, где DIR_SECT = OFF x SPT = %d            *)"
             % (SEC_PER_BLK, DIR_SECT))
    L.append(u"\t(* Блоки 0..%d заняты каталогом и системной областью (карта AL0/AL1).*)"
             % (FIRST_DATA_BLOCK - 1))
    L.append(u"\t(* Доступ - по СЕКТОРАМ по 128 байт: Disk[сектор, байт]. Двумерный   *)")
    L.append(u"\t(* массив выбран потому, что индекс сектора остаётся 16-разрядным     *)")
    L.append(u"\t(* (WORD) даже для образа 8 МБ: 65536 секторов - это 0..65535.        *)")
    L.append(u"\t(* ФОРМА ОБЪЯВЛЕНИЯ - ТОЛЬКО С ЗАПЯТОЙ: ARRAY[a, b] OF BYTE.          *)")
    L.append(u"\t(* Вложенная форма ARRAY[a] OF ARRAY[b] OF BYTE разбор объявлений     *)")
    L.append(u"\t(* принимает, но КОДОГЕНЕРАТОР её не понимает: он считает Disk         *)")
    L.append(u"\t(* одномерным, а тип элемента называет 'ARRAY [0..127] OF BYTE'.      *)")
    L.append(u"\t(* Каждое обращение Disk[сектор, байт] давало тогда C48 (нужен ровно 1 *)")
    L.append(u"\t(* индекс) и C32 на приёмнике - 2500 ошибок на весь проект (проба     *)")
    L.append(u"\t(* gen_probe_decl.py: вложенная форма 5 ошибок, форма с запятой 0).   *)")
    L.append(u"\t(* Синтаксис обращений при этом НЕ меняется: Disk[сектор, байт].       *)")
    L.append(u"\t(* ================================================================ *)")
    L.append(u"\tDisk      : ARRAY[0..%d, 0..%d] OF BYTE; "
             u"(* образ: сектор x байт *)\n"
             % (DISK_ARR_SEC - 1, REC_SIZE - 1))
    L.append(u"\tDisk_Ready: BOOL;   (* образ готов к работе *)")
    L.append(u"\tDir_Used  : WORD;   (* сколько записей каталога занято *)")
    L.append(u"\tAlloc     : ARRAY[0..%d] OF BYTE; (* битовая карта занятости блоков *)"
             % (ALLOC_BYTES - 1))
    L.append(u"\tDPB       : ST_DPB; (* параметры диска (профиль %s) *)" % _P[u"name"])
    L.append(u"")
    L.append(u"\t(* ==== ПРОФИЛЬ %s, значения полей DPB ==== *)" % _P[u"name"])
    L.append(u"\t(* SPT=%d BSH=%d BLM=%d EXM=%d DSM=%d DRM=%d *)"
             % (SPT, BSH, BLM, EXM, DSM, DRM))
    L.append(u"\t(* AL0=%02Xh AL1=%02Xh CKS=%d OFF=%d *)" % (AL0, AL1, CKS, OFF))
    L.append(u"\t(* Блок %d Б, записей в блоке %d, записей каталога %d, всего блоков %d *)"
             % (BLOCK_SIZE, RECS_PER_BLOCK, DIR_ENTRIES, TOTAL_BLOCKS))
    L.append(u"END_VAR")
    L.append(u"")
    return u"\n".join(L)


# ======================================================================
# КОНСТРУКТОРЫ ЭЛЕМЕНТОВ FBD
# ======================================================================
B = u"BYTE#%d"
H = u"BYTE#16#%02X"
W = u"WORD#%d"
WH = u"WORD#16#%04X"
D32 = u"DWORD#%d"
U1 = u"UDINT#1"


def _x(x):
    return fbd_xml.COL_BLK if x is None else x


def I(n, e):
    u"""Входная переменная / константа / выражение (источник сигнала)."""
    return n.invar(e)


def K(n, lit, x=None, y=None):
    u"""Константа."""
    return n.const(lit, _x(x), y)


def NOT(n, a, x=None, y=None):
    return n.block(u"NOT", [(u"IN", a)], [u"OUT"], _x(x), y)


def AND(n, a, b, x=None, y=None):
    return n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def OR(n, a, b, x=None, y=None):
    return n.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def EQ(n, a, b, x=None, y=None):
    return n.block(u"EQ", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def NE(n, a, b, x=None, y=None):
    return n.block(u"NE", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def LT(n, a, b, x=None, y=None):
    return n.block(u"LT", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def SEL(n, g, a, b, x=None, y=None):
    u"""SEL(G, IN0, IN1): при G=TRUE результат IN1, иначе IN0."""
    return n.block(u"SEL", [(u"G", g), (u"IN0", a), (u"IN1", b)], [u"OUT"], _x(x), y)


def IF(n, cond, a, b, x=None, y=None):
    u"""IF(cond, a, b) = cond ? a : b.

    Обёртка над SEL, у которой ПОЛЯРНОСТЬ НЕ ПУТАЕТСЯ: SEL(G, IN0, IN1) даёт
    IN1 при G=TRUE, то есть "если cond то a иначе b" - это SEL(cond, b, a).
    Все схемы CCP и загрузчика написаны через IF именно поэтому: перепутанный
    IN0/IN1 в FBD не виден ни компилятору, ни проверке связей.
    """
    return SEL(n, cond, b, a, x, y)


def ADD(n, a, b, x=None, y=None):
    return n.block(u"ADD", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def SHL(n, a, b, x=None, y=None):
    return n.block(u"SHL", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def SHR(n, a, b, x=None, y=None):
    u"""Логический сдвиг вправо. Нужен для деления на степень двойки:
    запись каталога = 32 байта, сектор = 128, значит сектор = idx >> 2."""
    return n.block(u"SHR", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def W2B(n, a, x=None, y=None):
    return n.block(u"WORD_TO_BYTE", [(u"IN", a)], [u"OUT"], _x(x), y)


def ORL(n, items, x0=None, dx=110, y=None):
    u"""Дерево OR по списку источников (каждый используется один раз)."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    lvl, xx = list(items), x0
    while len(lvl) > 1:
        nxt = []
        for k in range(0, len(lvl), 2):
            if k + 1 < len(lvl):
                nxt.append(OR(n, lvl[k], lvl[k + 1], xx, y))
            else:
                nxt.append(lvl[k])
        lvl, xx = nxt, xx + dx
    return lvl[0]


def ANDL(n, items, x0=None, dx=110, y=None):
    u"""Дерево AND по списку источников."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    lvl, xx = list(items), x0
    while len(lvl) > 1:
        nxt = []
        for k in range(0, len(lvl), 2):
            if k + 1 < len(lvl):
                nxt.append(AND(n, lvl[k], lvl[k + 1], xx, y))
            else:
                nxt.append(lvl[k])
        lvl, xx = nxt, xx + dx
    return lvl[0]


def CHAIN(n, acc, steps, x0=None, dx=115, y=None):
    u"""Цепочка SEL: [(условие, значение)]. Последний шаг имеет приоритет."""
    if x0 is None:
        x0 = fbd_xml.COL_BLK
    for k, st in enumerate(steps):
        xx = st[2] if len(st) > 2 else x0 + dx * k
        acc = SEL(n, st[0], acc, st[1], xx, y)
    return acc


def latch(n, name, src, comment=None):
    u"""Защёлкнуть значение в переменную POU и вернуть ссылку на неё.

    Правило 9.1 журнала: выход вызова FB нельзя читать из другой сети и нельзя
    разветвлять - его надо немедленно защёлкнуть. Этот помощник делает ровно
    это: один outvar + один invar для дальнейшего использования.
    """
    n.outvar(name, src)
    return I(n, name)


def rw(n, target, gate, val, old=None):
    u"""Условная запись "по месту": target := gate ? val : target (3 элемента).

    Применяется там, где запись должна произойти только в одном такте, а
    отдельного строб-сигнала в языке нет: старое значение читается, выбирается
    блоком SEL и записывается обратно.
    """
    if old is None:
        old = I(n, target)
    n.outvar(target, SEL(n, gate, old, val))


def bytes_of(text):
    u"""Строка -> список байтов (для загрузки программ в память)."""
    return [ord(ch) for ch in text]


def fmt16(v):
    return u"WORD#16#%04X" % v


# ======================================================================
# ДОПОЛНИТЕЛЬНЫЕ КОНСТРУКТОРЫ (нужны CCP, загрузчику и дисковому движку)
# ======================================================================
def GT(n, a, b, x=None, y=None):
    return n.block(u"GT", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def GE(n, a, b, x=None, y=None):
    return n.block(u"GE", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def LE(n, a, b, x=None, y=None):
    return n.block(u"LE", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def SUB(n, a, b, x=None, y=None):
    return n.block(u"SUB", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def MUL(n, a, b, x=None, y=None):
    return n.block(u"MUL", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def MASK(n, a, b, x=None, y=None):
    u"""AND с маской: нужен там, где важно привести результат к BYTE.

    В FBD ADD над BYTE даёт BYTE, но полагаться на переполнение по модулю 256
    без явной маски не стоит: AND с 0FFh делает усечение безусловным.

    ВНИМАНИЕ (этап 4): маскировать можно ТОЛЬКО битовые типы (BOOL/BYTE/WORD/
    DWORD). Для INT/UDINT (счётчик длины журнала, номер события) маска - это
    ошибка кодогенерации C32 'INT' -> 'ANY_BIT': операция AND определена в
    CODESYS только для битовых типов. Там применяется MOD (см. ниже).
    """
    return AND(n, a, b, x, y)


def MOD(n, a, b, x=None, y=None):
    u"""Остаток от деления - ЗАМЕНА МАСКИ ДЛЯ ЦЕЛЫХ ТИПОВ (найдено на этапе 4).

    `AND(Con_Log_Len, INT#255)` и подобные маски над INT давали 36 ошибок
    C32 'INT' -> 'ANY_BIT' во всём проекте. Для НЕОТРИЦАТЕЛЬНЫХ значений
    результат MOD(x, 2^n) совпадает с маской AND(2^n - 1), поэтому логика
    схемы НЕ меняется - так же считается индекс КОЛЬЦЕВОГО буфера журнала
    консоли (Con_Log) и номер бита в модуле ввода-вывода.
    """
    return n.block(u"MOD", [(u"IN1", a), (u"IN2", b)], [u"OUT"], _x(x), y)


def UPCH(n, ch, x=None, y=None):
    u"""Перевод строчной латинской буквы в прописную (как делает CCP).

    Прописная = строчная - 20h. Вычитание делается маской AND 0FFh, чтобы
    результат гарантированно остался байтом даже при вычитании из 'a'.
    """
    is_low = ANDL(n, [GE(n, ch, I(n, H % 0x61), _x(x)),
                      LE(n, ch, I(n, H % 0x7A), _x(x))])
    shifted = AND(n, ADD(n, ch, I(n, H % 0xE0), _x(x)), I(n, H % 0xFF))
    return SEL(n, is_low, ch, shifted, _x(x), y)


def SEC_OF_BLK_EXPR(blk):
    u"""Выражение "сектор первого сектора блока blk" (blk - имя переменной BYTE/WORD)."""
    return u"(%s * %d + %d)" % (blk, SEC_PER_BLK, DIR_SECT)


def emit_char(p, gate, ch_expr, log=True, note=u""):
    u"""Вывести ОДИН символ на консоль CP/M и в журнал Con_Log.

    Консоль в этом проекте - однобайтовый порт: за скан выводится ровно один
    символ (GVL_CPM.ConOut_Char + импульс ConOut_Ready). Именно поэтому все
    печатающие состояния CCP идут по одному символу за скан.

    Требует, чтобы в POU были объявлены переменные out_ch : BYTE и, если
    log=True, out_i : INT (объявляются один раз в самом POU).
    """
    n = p.network(u"СЕТЬ: вывод символа на консоль%s" % (u" - " + note if note else u""))
    n.outvar(u"out_ch", ch_expr)
    n.outvar(u"GVL_CPM.ConOut_Char",
             SEL(n, gate, I(n, u"GVL_CPM.ConOut_Char"), I(n, u"out_ch")))
    n.outvar(u"GVL_CPM.ConOut_Ready", gate)
    if log:
        n.outvar(u"GVL_CPM.Con_Log_Len",
                 SEL(n, gate, I(n, u"GVL_CPM.Con_Log_Len"),
                     ADD(n, I(n, u"GVL_CPM.Con_Log_Len"), I(n, u"INT#1"),
                         fbd_xml.COL_BLK + 460), fbd_xml.COL_BLK + 580))
        # МАССИВ ЖУРНАЛА пишется ЗДЕСЬ и только по КОНСТАНТНЫМ индексам:
        # запись по вычисляемому индексу импортёр теряет, а запись через
        # GVL-сигнал из другой сети не срабатывала (замер: LogWr ни разу
        # не был TRUE, хотя длина росла - значит сигнал читался не в том
        # скане). Здесь gate и out_ch - локальные величины этого POU.
        # РАЗМЕР БУФЕРА (фаза B): было 256 байт, и этого НЕ ХВАТАЛО. Каталог
        # DIR (4 записи по 32 байта плюс приглашения) затирал начало журнала,
        # поэтому в отчёте был виден только хвост из "A>", и содержимое
        # каталога проверить было невозможно. Теперь буфер 1024 байта
        # (32 банка по 32 индекса), и весь вывод DIR и TYPE сохраняется.
        LOG_SIZE = 256
        for bank in range(LOG_SIZE // 32):
            nx = p.network(u"СЕТЬ: журнал консоли, индексы %d..%d"
                           % (bank * 32, bank * 32 + 31))
            idx = MOD(nx, ADD(nx, I(nx, u"GVL_CPM.Con_Log_Len"),
                               I(nx, u"INT#%d" % (LOG_SIZE - 1)),
                               fbd_xml.COL_BLK + 60),
                      I(nx, u"INT#%d" % LOG_SIZE), fbd_xml.COL_BLK + 120)
            for k in range(bank * 32, bank * 32 + 32):
                e = u"GVL_CPM.Con_Log[%d]" % k
                hit = AND(nx, gate,
                          EQ(nx, idx, I(nx, u"INT#%d" % k),
                             x=fbd_xml.COL_BLK + 130 * (k % 8),
                             y=40 + 30 * (k % 32)),
                          x=fbd_xml.COL_BLK + 1100 + 130 * (k % 8),
                          y=40 + 30 * (k % 32))
                nx.outvar(e, SEL(nx, hit, I(nx, e), I(nx, u"out_ch"),
                                x=fbd_xml.COL_BLK + 2100 + 130 * (k % 8),
                                y=40 + 30 * (k % 32)))
    return n


def dir_entry_bytes(name, ext, blocks, rc, user=0):
    u"""Собрать 32 байта записи каталога CP/M 2.2 по правилам формата.

    Имя и расширение дополняются пробелами, номера блоков пишутся по 1 байту
    (DSM < 256) или по 2 байта младшим-вперёд (DSM > 255) - ровно так, как их
    читает BDOS CP/M 2.2.
    """
    ent = [0] * ENT_SIZE
    ent[0] = user & 0xFF
    nm = (name.upper() + u"        ")[:8]
    ex = (ext.upper() + u"   ")[:3]
    for i in range(8):
        ent[1 + i] = ord(nm[i]) & 0x7F
    for i in range(3):
        ent[9 + i] = ord(ex[i]) & 0x7F
    ent[12] = 0                 # ex  - номер экстента
    ent[13] = 0                 # s1
    ent[14] = 0                 # s2
    ent[15] = rc & 0xFF         # rc  - число записей в экстенте
    for i, b in enumerate(blocks[:BLOCKS_PER_ENTRY]):
        if BLK_BYTES == 1:
            ent[16 + i] = b & 0xFF
        else:
            ent[16 + 2 * i] = b & 0xFF
            ent[17 + 2 * i] = (b >> 8) & 0xFF
    return ent


def alloc_bitmap_seed(used_blocks):
    u"""Начальное содержимое битовой карты занятости блоков.

    Бит N байта N/8 = блок N занят. Возвращает словарь {индекс байта: значение},
    в котором учтены и системная область (AL0/AL1), и блоки демонстрационных
    файлов, залитых в образ при инициализации.
    """
    arr = {}
    bits = AL0 | (AL1 << 8)
    for i in range(16):
        if (bits >> i) & 1:
            arr[i >> 3] = arr.get(i >> 3, 0) | (1 << (i & 7))
    for b in used_blocks:
        arr[b >> 3] = arr.get(b >> 3, 0) | (1 << (b & 7))
    return arr

# ======================================================================
# ЖУРНАЛ КОНСОЛИ CP/M (постоянные индексы)
# ======================================================================

# ======================================================================
# ЖУРНАЛ КОНСОЛИ CP/M (запись по ПОСТОЯННЫМ индексам)
# ======================================================================
def make_conlog():
    u"""FB_ConLog - журнал консоли CP/M по ПОСТОЯННЫМ индексам.

    Запись Con_Log[MOD(len,256)] идёт по ВЫЧИСЛЯЕМОМУ индексу, импортёр
    такие записи теряет. Блок делает 256 условных присваиваний.
    Источник - консольный канал I/O: он выставляет GVL_CPM.LogWr/LogCh.
    """
    p = Pou(u"FB_ConLog", u"functionBlock",
            doc=u"Журнал консоли: 256 присваиваний по константным индексам.")
    p.var(u"idx", u"INT", u"индекс кольцевого журнала")
    p.var(u"wcnt", u"UDINT", u"счётчик записей")
    p.var_out(u"Done", u"BOOL", u"символ записан")
    p.var_out(u"Writes", u"UDINT", u"сколько символов записано")

    n = p.network(u"СЕТЬ 1. Индекс, счётчик и счётчик записей")
    n.outvar(u"idx", MOD(n, I(n, u"GVL_CPM.Con_Log_Len"), I(n, u"INT#256")))
    n.outvar(u"Done", I(n, u"GVL_CPM.LogWr"))
    n.outvar(u"wcnt", IF(n, I(n, u"GVL_CPM.LogWr"),
                          ADD(n, I(n, u"wcnt"), I(n, u"UDINT#1"),
                              fbd_xml.COL_BLK + 120),
                          I(n, u"wcnt"), fbd_xml.COL_BLK + 240))
    n.outvar(u"Writes", I(n, u"wcnt"))
    n.outvar(u"GVL_CPM.Con_Log_Len",
             IF(n, I(n, u"GVL_CPM.LogWr"),
                ADD(n, I(n, u"GVL_CPM.Con_Log_Len"), I(n, u"INT#1"),
                    fbd_xml.COL_BLK + 360),
                I(n, u"GVL_CPM.Con_Log_Len"), fbd_xml.COL_BLK + 480))

    # ЗАМЕР: только первые 8 индексов - проверяем сам механизм записи
    # глобального массива по константному индексу из FB.
    n = p.network(u"СЕТЬ 2. Журнал: индексы 0..7")
    for k in range(8):
        e = u"GVL_CPM.Con_Log[%d]" % k
        hit = AND(n, I(n, u"GVL_CPM.LogWr"),
                  EQ(n, I(n, u"idx"), I(n, u"INT#%d" % k),
                     x=fbd_xml.COL_BLK + 130 * k, y=40 + 30 * k),
                  x=fbd_xml.COL_BLK + 1100 + 130 * k, y=40 + 30 * k)
        n.outvar(e, SEL(n, hit, I(n, e), I(n, u"GVL_CPM.LogCh"),
                        x=fbd_xml.COL_BLK + 2100 + 130 * k, y=40 + 30 * k))
    return p

