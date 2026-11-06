# -*- coding: utf-8 -*-
"""Проверка декодера 8080 БЕЗ CODESYS: прогон всех 256 кодов через модель схемы.

Модель повторяет уравнения FBD из pou_decode_full.py один в один: те же маски,
та же таблица младшей тетрады, тот же приоритет распознавателей. Смысл проверки:
  * найти коды, которые ловят ДВА распознавателя сразу (конфликт масок);
  * убедиться, что все 244 документированных кода распознаны;
  * увидеть итоговую таблицу «код -> класс -> мнемоника -> длина».

Именно так был найден конфликт масок C7h/CFh у PUSH/POP: с C7h код E9h (PCHL)
попадал и в POP.
"""

import io, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)
import builtins
builtins.unicode = str
from pou_decode_full import CLASSES

CLS = dict((c, n) for c, n, _d in CLASSES)

# мнемоники для 244 документированных кодов (None = недокументированный)
REG = (u'B', u'C', u'D', u'E', u'H', u'L', u'M', u'A')
RP = (u'B', u'D', u'H', u'SP')
COND = (u'NZ', u'Z', u'NC', u'C', u'PO', u'PE', u'P', u'M')


def hits(ir):
    """Возвращает список (имя распознавателя, cls) - как в FB_Decoder_Full."""
    out = []
    grp = ir & 0xC0
    f3 = (ir >> 3) & 7
    if grp == 0x40 and ir != 0x76:
        out.append((u'MOV', 1))
    if (ir & 0xC7) == 0x06:
        out.append((u'MVI', 2))
    if grp == 0x80:
        out.append((u'ALU', 3))
    if (ir & 0xC7) == 0xC6:
        out.append((u'ALUI', 4))
    if grp == 0x00:
        out.append((u'DATA', data_cls(ir)))
    m = ir & 0xC7
    if m in (0xC2, 0xC4, 0xC0) or ir in (0xC3, 0xCD, 0xC9):
        out.append((u'JMP', 26 if ir in (0xC3,) or m == 0xC2 else
                    (27 if ir == 0xCD or m == 0xC4 else 28)))
    if (ir & 0xCF) == 0xC5:
        out.append((u'STACK', 29))
    if (ir & 0xCF) == 0xC1:
        out.append((u'STACK', 30))
    if ir in (0xEB, 0xE3, 0xF9, 0xE9, 0xFB, 0xF3, 0xDB, 0xD3):
        out.append((u'SPEC', {0xEB: 17, 0xE3: 18, 0xF9: 19, 0xE9: 20,
                              0xFB: 24, 0xF3: 25, 0xDB: 33, 0xD3: 34}[ir]))
    if (ir & 0xC7) == 0xC7:
        out.append((u'SPEC', 31))
    if ir == 0x76:
        out.append((u'HLT', 32))
    return out


def data_cls(ir):
    """Таблица группы 00h: lo + исключения по hi2 (как в FB_DecodeFull_DATA)."""
    lo = ir & 0x0F
    h = (ir >> 4) & 3
    if lo == 1:
        return 16                      # LXI
    if lo == 2:
        return 15 if h == 2 else (13 if h == 3 else 11)      # SHLD / STA / STAX
    if lo == 3:
        return 7                       # INX
    if lo == 4 or lo == 0xC:
        return 5                       # INR
    if lo == 5 or lo == 0xD:
        return 6                       # DCR
    if lo == 6 or lo == 0xE:
        return 2                       # MVI
    if lo == 7:
        return 23 if h == 2 else (22 if h == 3 else 21)      # DAA / STC / ROT
    if lo == 9:
        return 9                       # DAD
    if lo == 0xA:
        return 14 if h == 2 else (12 if h == 3 else 10)      # LHLD / LDA / LDAX
    if lo == 0xB:
        return 8                       # DCX
    if lo == 0xF:
        return 22 if h >= 2 else 21                          # CMA/CMC / ROT
    return 0                           # NOP (lo=0 и lo=8)


def length(ir, cls):
    if cls in (2, 4, 33, 34):
        return 2
    if cls in (16, 12, 13, 14, 15, 26, 27):
        return 3
    return 1


def mnem(ir, cls):
    f3 = (ir >> 3) & 7
    src = ir & 7
    rp = (ir >> 4) & 3
    if cls == 0:
        return u'NOP' + (u'' if ir in (0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38)
                         else u' (недокументированный)')
    if cls == 1:
        return u'MOV %s,%s' % (REG[f3], REG[src])
    if cls == 2:
        return u'MVI %s' % REG[f3]
    if cls == 3:
        return u'%s %s' % ((u'ADD', u'ADC', u'SUB', u'SBB', u'ANA', u'XRA', u'ORA', u'CMP')[f3],
                           REG[src])
    if cls == 4:
        return u'%s d8' % (u'ADI', u'ACI', u'SUI', u'SBI', u'ANI', u'XRI', u'ORI', u'CPI')[f3]
    if cls == 5:
        return u'INR %s' % REG[f3]
    if cls == 6:
        return u'DCR %s' % REG[f3]
    if cls == 7:
        return u'INX %s' % RP[rp]
    if cls == 8:
        return u'DCX %s' % RP[rp]
    if cls == 9:
        return u'DAD %s' % RP[rp]
    if cls == 10:
        return u'LDAX %s' % RP[rp]
    if cls == 11:
        return u'STAX %s' % RP[rp]
    if cls == 12:
        return u'LDA a16'
    if cls == 13:
        return u'STA a16'
    if cls == 14:
        return u'LHLD a16'
    if cls == 15:
        return u'SHLD a16'
    if cls == 16:
        return u'LXI %s,d16' % RP[rp]
    if cls == 17:
        return u'XCHG'
    if cls == 18:
        return u'XTHL'
    if cls == 19:
        return u'SPHL'
    if cls == 20:
        return u'PCHL'
    if cls == 21:
        return (u'RLC', u'RRC', u'RAL', u'RAR')[{0x07: 0, 0x0F: 1, 0x17: 2, 0x1F: 3}[ir]]
    if cls == 22:
        return {0x2F: u'CMA', 0x37: u'STC', 0x3F: u'CMC'}[ir]
    if cls == 23:
        return u'DAA'
    if cls == 24:
        return u'EI'
    if cls == 25:
        return u'DI'
    if cls == 26:
        return u'JMP' if ir == 0xC3 else u'J%s a16' % COND[f3]
    if cls == 27:
        return u'CALL' if ir == 0xCD else u'C%s a16' % COND[f3]
    if cls == 28:
        return u'RET' if ir == 0xC9 else u'R%s' % COND[f3]
    if cls == 29:
        return u'PUSH %s' % (u'PSW' if rp == 3 else RP[rp])
    if cls == 30:
        return u'POP %s' % (u'PSW' if rp == 3 else RP[rp])
    if cls == 31:
        return u'RST %d' % f3
    if cls == 32:
        return u'HLT'
    if cls == 33:
        return u'IN d8 (зарезервировано 3.6)'
    if cls == 34:
        return u'OUT d8 (зарезервировано 3.6)'
    return u'?'


def main():
    conflicts, undocumented, table = [], [], []
    for ir in range(256):
        hs = hits(ir)
        if len(hs) > 1:
            conflicts.append((ir, hs))
        cls = hs[0][1] if hs else 0
        table.append((ir, cls, mnem(ir, cls), length(ir, cls)))
        if cls == 0 and ir not in (0x00, 0x08, 0x10, 0x18, 0x20, 0x28, 0x30, 0x38):
            undocumented.append(ir)
    print(u"кодов всего: 256")
    print(u"распознано (не NOP): %d" % sum(1 for _i, c, _m, _l in table if c != 0))
    print(u"NOP-кодов: %d (из них документированный NOP 00h и 7 недокументированных)"
          % sum(1 for _i, c, _m, _l in table if c == 0))
    print(u"недокументированные коды: %s"
          % u", ".join(u'%02Xh' % i for i in undocumented))
    print(u"\nКОНФЛИКТЫ МАСОК (код ловят два распознавателя): %d" % len(conflicts))
    for ir, hs in conflicts:
        print(u"  %02Xh -> %s" % (ir, hs))
    print(u"\nТаблица по группам (код : класс : мнемоника : длина):")
    for lo in range(0, 256, 16):
        row = []
        for ir in range(lo, lo + 16):
            c, m, L = table[ir][1], table[ir][2], table[ir][3]
            row.append(u'%02X %-22s c=%-2d L=%d' % (ir, m, c, L))
        print(u"  " + u" | ".join(row))
    # проверка: все ли мнемоники из задания покрыты
    print(u"\nКлассы, встреченные в таблице: %s"
          % u", ".join(u'%d=%s' % (c, CLS[c]) for c in sorted(set(t[1] for t in table))))


if __name__ == '__main__':
    main()
