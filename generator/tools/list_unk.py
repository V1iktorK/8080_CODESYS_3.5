# -*- coding: utf-8 -*-
u"""ПЕРЕЧЕНЬ НЕРАЗОБРАННЫХ СВЯЗЕЙ (этап A5) - там, где ещё может прятаться C32.

ЗАЧЕМ. tools/check_types.py теперь проверяет 13 090 связей и НИЧЕГО не находит,
но 348 связей остаются неразобранными: тип источника не вычисляется, а
compatible(UNK, ...) всегда истинна, то есть эти связи НЕ проверяются.
Именно в них и может жить ошибка C32 'BYTE' -> 'BOOL'.

Скрипт печатает КАЖДУЮ такую связь с текстом выражения источника, именем POU,
типом блока, именем пина и ОЖИДАЕМЫМ типом - чтобы их можно было просмотреть
глазами, а не гадать.

Запуск:  python tools\\list_unk.py
Отчёт:   C:\\dsh8080\\work\\emu_s4\\list_unk.txt
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

OUT = u"C:/dsh8080/work/emu_s4/list_unk.txt"


def build_ctx():
    u"""Повторить подготовку контекста из CT.main() (структуры, GVL, интерфейсы)."""
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


def walk(p, env_all, structs, ifaces, rec):
    env = dict(env_all)
    for v in p.inputs + p.outputs + p.locals:
        env[v.name.upper()] = v.type

    items = []
    for net_i, net in enumerate(p.networks):
        for it in net._items:
            items.append((net_i, it))
    by_id = dict([(it[1], it) for _, it in items])

    def out_type(it, pin=None, depth=0):
        if it is None or depth > 12:
            return CT.UNK
        k = it[0]
        if k == u"invar":
            return CT.resolve(it[2], env, structs, ifaces)
        if k == u"outvar":
            return out_type(by_id.get(it[3].eid), None, depth + 1)
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
            return out_type(by_id.get(src.eid), None, depth + 1) if src else CT.UNK
        if b == u"SEL":
            src = dict(ins).get(u"IN0")
            return out_type(by_id.get(src.eid), None, depth + 1) if src else CT.UNK
        ifc = ifaces.get(b)
        if ifc is not None:
            outs_map = dict([(k.upper(), v) for k, v in ifc[1].items()])
            if pin and pin.upper() in outs_map:
                return CT.parse_type(outs_map[pin.upper()], structs)
            if len(outs_map) == 1:
                return CT.parse_type(list(outs_map.values())[0], structs)
        return CT.UNK

    for net_i, it in items:
        if it[0] == u"invar":
            continue
        if it[0] == u"outvar":
            tgt = CT.resolve(it[2], env, structs, ifaces)
            src_it = by_id.get(it[3].eid)
            st = out_type(src_it, it[3].pin)
            if st.kind == u"unk":
                ex = (u"%s" % src_it[2]) if (src_it and src_it[0] == u"invar") \
                    else u"<%s>" % (src_it[2] if src_it else u"?",)
                rec.append((p.name, net_i, u"ПРИЁМНИК %s" % it[2],
                            u"%s" % (tgt.name if tgt.kind == u"el" else tgt), ex))
            continue
        _, lid, tname, ins, outs, _x, _y = it
        b = tname.upper()
        pins = CT.std_pins(b)
        if pins is None:
            ifc = ifaces.get(b)
            if ifc is None:
                continue
            pins = dict([(k.upper(), v) for k, v in ifc[0].items()])
        for pin, src in ins:
            if not pin:
                continue
            exp = pins.get(pin.upper())
            if exp is None:
                continue
            src_it = by_id.get(src.eid)
            at = out_type(src_it, src.pin)
            if at.kind == u"unk":
                ex = (u"%s" % src_it[2]) if (src_it and src_it[0] == u"invar") \
                    else u"<%s>" % (src_it[2] if src_it else u"?",)
                rec.append((p.name, net_i, u"ВХОД %s.%s" % (tname, pin),
                            u"%s" % exp, ex))


def main():
    structs, ifaces, env_all = build_ctx()
    rec = []
    for grp, makers in CT.GROUPS:
        for mk in makers:
            walk(mk(), env_all, structs, ifaces, rec)
    for nm in pou_deps.all_names():
        p = pou_deps.make(nm)
        if p is not None:
            walk(p, env_all, structs, ifaces, rec)

    f = io.open(OUT, u"w", encoding=u"utf-8")
    f.write(u"ВСЕГО неразобранных связей: %d\n\n" % len(rec))
    bypou = collections.Counter([r[0] for r in rec])
    f.write(u"по POU: %s\n\n" % bypou.most_common())
    f.write(u"%-24s %5s %-34s %-22s %s\n"
            % (u"POU", u"сеть", u"куда", u"ожидается", u"источник (выражение)"))
    for r in sorted(rec):
        f.write(u"%-24s %5d %-34s %-22s %s\n" % r)
    f.close()
    print(u"ВСЕГО неразобранных: %d -> %s" % (len(rec), OUT))
    print(u"по POU: %s" % bypou.most_common(25))


main()
