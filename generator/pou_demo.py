# -*- coding: utf-8 -*-
u"""Демонстрационные .COM-программы и заливка дискового образа (этап 3.5).

ЧТО ЗДЕСЬ. Ассемблера 8080 в системе нет (docs/04_ПЛАН_CPM.md, раздел 0),
поэтому машинный код демонстрационных программ собирается ЗДЕСЬ, мини-
ассемблером на Python: он умеет ровно те команды, которые нужны трём
программам. Это ДАННЫЕ (тестовый образ диска), а не логика эмулятора -
логика целиком в FBD.

ПРОГРАММЫ (все кладутся в образ диска при инициализации):
  HELLO.COM  - печатает строку через BDOS 9 (PRINT STRING) и делает WBOOT;
  DIR.COM    - обходит каталог через BDOS 17/18 (SEARCH FIRST/NEXT) и печатает
               имена файлов - настоящая .COM-программа, а не встроенная
               команда CCP;
  TYPE.COM   - открывает файл из FCB по 005Ch (BDOS 15), читает записи
               (BDOS 20) и печатает их до символа 1Ah - "TYPE README.TXT";
  README.TXT - текстовый файл, который печатает TYPE.COM.

АДРЕСАЦИЯ. Все программы грузятся в TPA с 0100h (как в настоящем CP/M), FCB
DIR.COM лежит в самой программе после кода и заполнен маской '?' - то есть
DIR.COM показывает каталог целиком.
"""

import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
import pou_cpm_defs as D
from pou_cpm_defs import I, IF, H, W, WH

try:                     # IronPython 2 внутри CODESYS; Python 3 - только для
    unicode              # локальной проверки сборки демонстрационных программ
except NameError:
    unicode = str

# ======================================================================
# МИНИ-АССЕМБЛЕР 8080: ровно те команды, что нужны демонстрационным .COM
# ======================================================================
# (мнемоника -> (опкод, длина, способ кодирования операнда))
SIMPLE = {
    u"NOP": (0x00, 1), u"HLT": (0x76, 1), u"RET": (0xC9, 1),
    u"INR_A": (0x3C, 1), u"DCR_B": (0x05, 1), u"ORA_A": (0xB7, 1),
    u"XRA_A": (0xAF, 1), u"ADD_A": (0x87, 1),
    u"INX_H": (0x23, 1), u"INX_D": (0x13, 1), u"DCX_B": (0x0B, 1),
    u"PUSH_H": (0xE5, 1), u"POP_H": (0xE1, 1),
    u"MOV_A_M": (0x7E, 1), u"MOV_E_M": (0x5E, 1), u"MOV_E_A": (0x5F, 1),
    u"MOV_L_A": (0x6F, 1), u"MOV_A_B": (0x78, 1),
    u"MVI_A": (0x3E, 2), u"MVI_B": (0x06, 2), u"MVI_C": (0x0E, 2),
    u"MVI_E": (0x1E, 2), u"MVI_H": (0x26, 2),
    u"CPI": (0xFE, 2), u"ANI": (0xE6, 2), u"ADI": (0xC6, 2),
    u"LXI_B": (0x01, 3), u"LXI_D": (0x11, 3), u"LXI_H": (0x21, 3),
    u"CALL": (0xCD, 3), u"JMP": (0xC3, 3),
    u"JZ": (0xCA, 3), u"JNZ": (0xC2, 3), u"JC": (0xDA, 3), u"JNC": (0xD2, 3),
    u"STA": (0x32, 3), u"LDA": (0x3A, 3),
}


class Asm(object):
    u"""Мини-ассемблер: две проходки, метки, абсолютные адреса в TPA."""

    def __init__(self, org=0x0100):
        self.org = org
        self.items = []          # (bytes, [(смещение_в_блоке, метка)])
        self.labels = {}

    def label(self, name):
        self.labels[name] = self.org + self.size()

    def size(self):
        return sum([len(b) for b, _ in self.items])

    def op(self, mnem, arg=None):
        code, ln = SIMPLE[mnem]
        fix = []
        if ln == 1:
            self.items.append(([code], fix))
        elif ln == 2:
            self.items.append(([code, arg & 0xFF], fix))
        else:
            if isinstance(arg, int):
                # абсолютный адрес известен сразу (например CALL 0005h)
                self.items.append(([code, arg & 0xFF, (arg >> 8) & 0xFF], []))
            else:
                fix.append((1, arg))
                self.items.append(([code, 0, 0], fix))
        return self

    def db(self, *vals):
        out = []
        for v in vals:
            if isinstance(v, (str, unicode)):
                out.extend([ord(ch) for ch in v])
            else:
                out.append(v & 0xFF)
        self.items.append((out, []))
        return self

    def dw(self, val):
        if isinstance(val, (str, unicode)):
            self.items.append(([0, 0], [(0, val)]))
        else:
            self.items.append(([val & 0xFF, (val >> 8) & 0xFF], []))
        return self

    def text(self, s):
        return self.db(s + u"$")

    def code(self):
        u"""Собрать байты: адреса меток подставляются на втором проходе."""
        base = self.org
        out = []
        for data, fix in self.items:
            off = base + len(out)
            for pos, name in fix:
                if name not in self.labels:
                    raise ValueError(u"метка не определена: %s" % name)
                a = self.labels[name]
                data[pos] = a & 0xFF
                data[pos + 1] = (a >> 8) & 0xFF
            out.extend(data)
            del off
        return out


# BDOS-функции, которыми пользуются демонстрационные программы
F_OPEN, F_CONOUT, F_PRINTSTR = 15, 2, 9
F_SEARCHF, F_SEARCHN, F_READSEQ = 17, 18, 20
F_SETDMA = 26
BDOS_ENTRY = 0x0005
WBOOT = 0x0000
DEF_FCB = 0x005C
DMA = 0x0080


def asm_hello():
    u"""HELLO.COM: строка через BDOS 9, затем тёплый старт (WBOOT)."""
    a = Asm()
    a.op(u"MVI_C", F_PRINTSTR)
    a.op(u"LXI_D", u"msg")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"JMP", WBOOT)
    a.label(u"msg")
    a.text(u"HELLO FROM HELLO.COM - CP/M 2.2 ON CODESYS")
    a.db(0x0D, 0x0A)
    return a


def asm_dir():
    u"""DIR.COM: обход каталога через BDOS 17/18 и печать имён.

    FCB программы заполнен маской '?' - значит печатается весь каталог.
    Адрес найденной записи: BDOS возвращает код каталога 0..3, а сама запись
    лежит в буфере DMA по адресу 0080h + код*32. Умножение на 32 сделано
    пятью сложениями A с самим собой - без таблиц и без регистра B.
    """
    a = Asm()
    a.label(u"start")
    a.op(u"MVI_C", F_SEARCHF)
    a.op(u"LXI_D", u"fcb")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"CPI", 0xFF)
    a.op(u"JZ", u"done")
    a.label(u"show")
    a.op(u"ANI", 0x03)          # код каталога 0..3
    a.op(u"ADD_A")              # *2
    a.op(u"ADD_A")              # *4
    a.op(u"ADD_A")              # *8
    a.op(u"ADD_A")              # *16
    a.op(u"ADD_A")              # *32
    a.op(u"ADI", DMA & 0xFF)    # A = 0080h + код*32 (младший байт)
    a.op(u"MOV_L_A")
    a.op(u"MVI_H", 0x00)
    a.op(u"MVI_B", 8)           # 8 знаков имени
    a.label(u"pl")
    a.op(u"MOV_E_M")
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"PUSH_H")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"POP_H")
    a.op(u"INX_H")
    a.op(u"DCR_B")
    a.op(u"JNZ", u"pl")
    a.op(u"MVI_E", 0x2E)        # '.'
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"MVI_B", 3)           # 3 знака расширения
    a.label(u"pe")
    a.op(u"MOV_E_M")
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"PUSH_H")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"POP_H")
    a.op(u"INX_H")
    a.op(u"DCR_B")
    a.op(u"JNZ", u"pe")
    for ch in (0x0D, 0x0A):
        a.op(u"MVI_E", ch)
        a.op(u"MVI_C", F_CONOUT)
        a.op(u"CALL", BDOS_ENTRY)
    a.op(u"MVI_C", F_SEARCHN)
    a.op(u"LXI_D", u"fcb")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"CPI", 0xFF)
    a.op(u"JNZ", u"show")
    a.label(u"done")
    a.db(0x00)
    a.label(u"fcb")
    # FCB: dr=0, имя '?'x8, расширение '?'x3, ex/s1/s2/rc = 0, карта блоков = 0
    a.db(0x00)
    a.db(0x3F, 0x3F, 0x3F, 0x3F, 0x3F, 0x3F, 0x3F, 0x3F)
    a.db(0x3F, 0x3F, 0x3F)
    a.db(0x00, 0x00, 0x00, 0x00)
    a.db(*([0x00] * 16))
    a.db(0x00, 0x00, 0x00, 0x00)
    return a


def asm_type():
    u"""TYPE.COM: печать файла, имя которого CCP положил в FCB по 005Ch.

    Порядок как в настоящем TYPE: OPEN (15) -> SET DMA (26) -> READ SEQ (20)
    в цикле; печать идёт до символа 1Ah (Ctrl-Z) - признака конца текстового
    файла в CP/M.
    """
    a = Asm()
    a.op(u"MVI_C", F_OPEN)
    a.op(u"LXI_D", DEF_FCB)
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"INR_A")              # A=FFh (не найдено) -> 00h
    a.op(u"JZ", u"nofile")
    a.op(u"MVI_C", F_SETDMA)
    a.op(u"LXI_D", DMA)
    a.op(u"CALL", BDOS_ENTRY)
    a.label(u"rd")
    a.op(u"MVI_C", F_READSEQ)
    a.op(u"LXI_D", DEF_FCB)
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"ORA_A")
    a.op(u"JNZ", u"done")       # A <> 0 - записей больше нет
    a.op(u"MVI_B", 128)
    a.op(u"LXI_H", DMA)
    a.label(u"pl")
    a.op(u"MOV_A_M")
    a.op(u"CPI", 0x1A)          # Ctrl-Z - конец текста
    a.op(u"JZ", u"done")
    a.op(u"MOV_E_A")
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"PUSH_H")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"POP_H")
    a.op(u"INX_H")
    a.op(u"DCR_B")
    a.op(u"JNZ", u"pl")
    a.op(u"JMP", u"rd")
    a.label(u"nofile")
    a.op(u"MVI_C", F_PRINTSTR)
    a.op(u"LXI_D", u"nf")
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"JMP", u"done")
    a.label(u"nf")
    a.text(u"NO FILE")
    a.db(0x0D, 0x0A)
    a.label(u"done")
    a.op(u"MVI_E", 0x0D)
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"MVI_E", 0x0A)
    a.op(u"MVI_C", F_CONOUT)
    a.op(u"CALL", BDOS_ENTRY)
    a.op(u"JMP", WBOOT)
    return a


README = (u"CP/M 2.2 ON CODESYS 8080 EMULATOR\r\n"
          u"-----------------------------------\r\n"
          u"HELLO.COM - hello via BDOS 9\r\n"
          u"DIR.COM   - directory via BDOS 17/18\r\n"
          u"TYPE.COM  - type a file: TYPE README.TXT\r\n"
          u"Built-in CCP commands: DIR TYPE ERA REN SAVE USER EXIT\r\n"
          u"Disk: CP/M 2.2 format, 32-byte directory entries.\r\n"
          u"\x1a")


def readme_bytes():
    u"""README.TXT: текст + признак конца текста 1Ah (как в CP/M)."""
    return [ord(ch) & 0xFF for ch in README]


def files():
    u"""Список файлов образа: (имя, расширение, байты)."""
    return ((u"HELLO", u"COM", asm_hello().code()),
            (u"DIR", u"COM", asm_dir().code()),
            (u"TYPE", u"COM", asm_type().code()),
            (u"README", u"TXT", readme_bytes()))


# ======================================================================
# ЗАЛИВКА ОБРАЗА ДИСКА
# ======================================================================
# Бутстрап-заглушка: обнуляет BC, DE, HL и A, затем передаёт управление
# программе на 0100h. Именно на неё CCP делает Jump_PC при запуске .COM -
# так выполняется требование "обнуление регистров" без единой строки логики
# вне FBD: это данные (машинный код), как и сами .COM-программы.
BOOT_STUB_BYTES = (
    0x01, 0x00, 0x00,      # LXI B,0000h
    0x11, 0x00, 0x00,      # LXI D,0000h
    0x21, 0x00, 0x00,      # LXI H,0000h
    0xAF,                  # XRA A
    0xC3, 0x00, 0x01,      # JMP 0100h
)


def dir_pos(idx):
    u"""Где в образе лежит запись каталога idx: (сектор, байт в секторе)."""
    b = idx * D.ENT_SIZE
    return (D.DIR_SECT + b // D.REC_SIZE, b % D.REC_SIZE)


def file_pos(blk, ofs):
    u"""Где в образе лежит байт ofs блока blk: (сектор, байт в секторе)."""
    lin = blk * D.BLOCK_SIZE + ofs
    return (D.DIR_SECT + lin // D.REC_SIZE, lin % D.REC_SIZE)


def plan():
    u"""Разложить файлы по блокам: [(имя, расширение, блоки, записей, байты)]."""
    out = []
    blk = D.FIRST_DATA_BLOCK
    for name, ext, data in files():
        nrec = (len(data) + D.REC_SIZE - 1) // D.REC_SIZE
        nblk = max(1, (len(data) + D.BLOCK_SIZE - 1) // D.BLOCK_SIZE)
        blocks = [blk + k for k in range(nblk)]
        out.append((name, ext, blocks, nrec, data))
        blk += nblk
    return out


def _wr(n, gate, sec, byt, val):
    u"""Записать байт образа в первом скане (потом образ живёт своей жизнью)."""
    tgt = u"GVL_DISK.Disk[%d, %d]" % (sec, byt)
    n.outvar(tgt, IF(n, gate, I(n, H % (val & 0xFF)), I(n, tgt)))


def build_image(p, gate):
    u"""Сети заливки образа: каталог, файлы, карта занятости блоков, заглушка."""
    layout = plan()
    used = []
    for _n, _e, blocks, _r, _d in layout:
        used.extend(blocks)

    # ---- 1. записи каталога ----
    n = p.network(u"СЕТЬ: каталог диска - записи демонстрационных файлов, "
                  u"остальные свободны (E5h)")
    for i in range(D.DIR_ENTRIES):
        sec, off = dir_pos(i)
        if i < len(layout):
            name, ext, blocks, nrec, _data = layout[i]
            ent = D.dir_entry_bytes(name, ext, blocks, nrec)
            for k, v in enumerate(ent):
                _wr(n, gate, sec, off + k, v)
        else:
            _wr(n, gate, sec, off, 0xE5)

    # ---- 2. данные файлов ----
    n = p.network(u"СЕТЬ: содержимое .COM-программ и README.TXT в блоках данных")
    for _name, _ext, blocks, _nrec, data in layout:
        for j, v in enumerate(data):
            blk = blocks[j // D.BLOCK_SIZE]
            sec, byt = file_pos(blk, j % D.BLOCK_SIZE)
            _wr(n, gate, sec, byt, v)

    # ---- 3. карта занятости блоков (AL0/AL1 + занятые файлами) ----
    n = p.network(u"СЕТЬ: битовая карта занятости блоков - системная область "
                  u"по AL0/AL1 и блоки демонстрационных файлов")
    for k, v in sorted(D.alloc_bitmap_seed(used).items()):
        tgt = u"GVL_DISK.Alloc[%d]" % k
        n.outvar(tgt, IF(n, gate, I(n, H % (v & 0xFF)), I(n, tgt)))

    # ---- 4. бутстрап-заглушка: обнуление регистров и переход на 0100h ----
    n = p.network(u"СЕТЬ: бутстрап-заглушка запуска .COM - обнуление регистров "
                  u"и переход на 0100h")
    for k, v in enumerate(BOOT_STUB_BYTES):
        n.outvar(u"GVL_MEM.Memory[%s]" % (WH % (D.BOOT_STUB + k)), I(n, H % v))
    return layout


def dir_used():
    u"""Сколько записей каталога занято демонстрационными файлами."""
    return len(plan())


def next_block():
    u"""Первый свободный блок после демонстрационных файлов."""
    blk = D.FIRST_DATA_BLOCK
    for _n, _e, blocks, _r, _d in plan():
        blk = max(blk, blocks[-1] + 1)
    return blk
