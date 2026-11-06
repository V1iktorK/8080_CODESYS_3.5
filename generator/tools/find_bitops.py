# -*- coding: utf-8 -*-
u"""НАЙТИ БИТОВЫЕ БЛОКИ (AND/OR/XOR/NOT) С ОПЕРАНДАМИ НЕ-BOOL - этап A5.

ГИПОТЕЗА, КОТОРУЮ ЭТО ПРОВЕРЯЕТ. Компилятор сообщает
"C32: Невозможно конвертировать тип 'BYTE' в тип 'BOOL'" в сети
"СЕТЬ 18 (ФАЗА 6). Флаги S/Z/P результата DAA" (POU FB_CPU8080_FULL).
Единственное, что отличает эту сеть от всех остальных, - это блоки

    AND(IN1 := regs.A, IN2 := BYTE#8)      (regs.A - BYTE)
    AND(IN1 := bval,   IN2 := BYTE#8)      (bval   - BYTE)

То есть битовый блок AND получает на вход BYTE, тогда как во ВСЕХ остальных
местах проекта AND/OR/NOT работают с BOOL. Если CODESYS разрешает имя "AND"
в булев вариант (BOOL-входы), то BYTE на входе - это ровно то самое
преобразование 'BYTE' -> 'BOOL'.

Прежняя проверка типов этого НЕ видела: std_pins() объявляет входы AND/OR/XOR
как 'BIT', а BYTE входит в BIT (ANY_BIT), поэтому связь считалась законной.

Скрипт печатает ВСЕ места, где AND/OR/XOR/NOT получают операнд не-BOOL, -
чтобы оценить полный объём правки, а не только одну сеть.
"""
import builtins
import collections
import io
import os
import sys

builtins.unicode = str

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GEN)
sys.path.insert(0, os.path.join(GEN, u"tools"))

import check_types as CT   # noqa: E402
import pou_deps            # noqa: E402

OUT = u"C:/dsh8080/work/emu_s4/bitops.txt"
BITOPS = (u"AND", u"OR", u"XOR", u"NOT")


def build_ctx():
    structs = CT.parse_duts()
    ifaces = CT.collect_fb_interfaces()
    env_all = {}
    for nm, text in CT.GVL_TEXTS:
        for k, v in CT.parse_decl(text, structs).items():
            env_all[k] = v
    for nm, text in CT.GVL_TEXTS:
        structs[nm.upper()] = CT.parse_decl(text, structs)
        env_all[nm.upper()] = CT.T(u"st", nm, st=nm.upper())
    return structs, ifaces, env_all


def otype(it, by_id, env, structs, ifaces, pin=None, d=0):
    if it is None or d > 12:
        return CT.UNK
    k = it[0]
    if k == u"invar":
        return CT.resolve(it[2], env, structs, ifaces)
    if k == u"outvar":
        return otype(by_id.get(it[3].eid), by_id, env, structs, ifaces, None, d + 1)
    tname, ins = it[2], it[3]
    b = tname.upper()
    m = CT.CONV.match(b)
    if m:
        return CT.T(u"el", m.group(2))
    if b in (u"EQ", u"NE", u"LT", u"GT", u"LE", u"GE"):
        return CT.BOOL
    if b in (u"NOT", u"AND", u"OR", u"XOR", u"SHL", u"SHR", u"ROL", u"ROR",
             u"ADD", u"SUB", u"MUL", u"DIV", u"MOD", u"LIMIT", u"MAX",
             u"MIN", u"MOVE"):
        src = dict(ins).get(u"IN1") or dict(ins).get(u"IN")
        return otype(by_id.get(src.eid), by_id, env, structs, ifaces, None, d + 1) if src else CT.UNK
    if b == u"SEL":
        src = dict(ins).get(u"IN0")
        return otype(by_id.get(src.eid), by_id, env, structs, ifaces, None, d + 1) if src else CT.UNK
    ifc = ifaces.get(b)
    if ifc is not None:
        om = dict([(k.upper(), v) for k, v in ifc[1].items()])
        if pin and pin.upper() in om:
            return CT.parse_type(om[pin.upper()], structs)
        if len(om) == 1:
            return CT.parse_type(list(om.values())[0], structs)
    return CT.UNK


NFOUND = 0


def scan(p, env_all, structs, ifaces, f):
    global NFOUND
    env = dict(env_all)
    for v in p.inputs + p.outputs + p.locals:
        env[v.name.upper()] = v.type
    items = []
    for net_i, net in enumerate(p.networks):
        for it in net._items:
            items.append((net_i, it))
    by_id = dict([(it[1], it) for _, it in items])
    for net_i, it in items:
        if it[0] != u"block":
            continue
        _, lid, tname, ins, outs, _x, _y = it
        b = tname.upper()
        if b not in BITOPS:
            continue
        bad = []
        for pin, src in ins:
            if not pin:
                continue
            src_it = by_id.get(src.eid)
            t = otype(src_it, by_id, env, structs, ifaces, src.pin)
            if t.kind == u"el" and t.name != u"BOOL":
                ex = (u"%s" % src_it[2]) if (src_it and src_it[0] == u"invar") else u"<блок>"
                bad.append(u"%s=%s(%s)" % (pin, t.name, ex))
        if bad:
            NFOUND += 1
            f.write(u"%-22s сеть %2d localId=%-5d %-4s  %s\n"
                    % (p.name, net_i, lid, tname, u", ".join(bad)))


def main():
    structs, ifaces, env_all = build_ctx()
    f = io.open(OUT, u"w", encoding=u"utf-8")
    f.write(u"БИТОВЫЕ БЛОКИ С ОПЕРАНДОМ НЕ-BOOL (AND/OR/XOR/NOT)\n\n")
    for grp, makers in CT.GROUPS:
        for mk in makers:
            scan(mk(), env_all, structs, ifaces, f)
    for nm in pou_deps.all_names():
        p = pou_deps.make(nm)
        if p is not None:
            scan(p, env_all, structs, ifaces, f)
    f.write(u"\nВСЕГО мест: %d\n" % NFOUND)
    f.close()
    print(u"ВСЕГО мест с не-BOOL операндом в AND/OR/XOR/NOT: %d -> %s" % (NFOUND, OUT))


main()
