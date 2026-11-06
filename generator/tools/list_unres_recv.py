# -*- coding: utf-8 -*-
u"""ДЫРА В ПРОВЕРКЕ: приёмники outvar, которые НЕ РАЗОБРАЛИСЬ (этап A5).

НАЙДЕНО ПРИ РАЗБОРЕ ОСТАВШЕЙСЯ ОШИБКИ. В check_pou() проверка приёмника
делается так:

    tgt = resolve(it[2], ...)
    ...
    if not compatible(st, tgt.name if tgt.kind == u"el" else u"?"):
        report(...)

то есть если ИМЯ ПРИЁМНИКА не разобралось, ожидаемым типом становится "?",
а compatible(x, "?") ВСЕГДА истинна - связь проверку ПРОХОДИТ МОЛЧА. Значит,
все приёмники, которые resolve() не понял, не проверяются вообще, и именно там
мог спрятаться C32 'BYTE' -> 'BOOL'.

Скрипт печатает по FB_CPU8080_FULL (и по любому POU из аргумента) все outvar,
приёмник которых не разобрался, вместе с типом источника - и отдельно те
случаи, где ТИП ИСТОЧНИКА ИЗВЕСТЕН и не совпадает с разумной догадкой.

Запуск:  python tools\\list_unres_recv.py [ИМЯ_POU]
Отчёт:   C:\\dsh8080\\work\\emu_s4\\unres_recv.txt
"""
import builtins
import io
import os
import sys

builtins.unicode = str

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, GEN)
sys.path.insert(0, os.path.join(GEN, u"tools"))

import check_types as CT   # noqa: E402
import pou_deps            # noqa: E402

OUT = u"C:/dsh8080/work/emu_s4/unres_recv.txt"
TARGET = sys.argv[1] if len(sys.argv) > 1 else u"FB_CPU8080_FULL"


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


def out_type(it, by_id, env, structs, ifaces, depth=0):
    if it is None or depth > 12:
        return CT.UNK
    k = it[0]
    if k == u"invar":
        return CT.resolve(it[2], env, structs, ifaces)
    if k == u"outvar":
        return out_type(by_id.get(it[3].eid), by_id, env, structs, ifaces, depth + 1)
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
        return out_type(by_id.get(src.eid), by_id, env, structs, ifaces, depth + 1) if src else CT.UNK
    if b == u"SEL":
        src = dict(ins).get(u"IN0")
        return out_type(by_id.get(src.eid), by_id, env, structs, ifaces, depth + 1) if src else CT.UNK
    ifc = ifaces.get(b)
    if ifc is not None:
        outs_map = dict([(k.upper(), v) for k, v in ifc[1].items()])
        if len(outs_map) == 1:
            return CT.parse_type(list(outs_map.values())[0], structs)
    return CT.UNK


def main():
    structs, ifaces, env_all = build_ctx()
    f = io.open(OUT, u"w", encoding=u"utf-8")
    n_all = n_un = 0
    for grp, makers in CT.GROUPS:
        for mk in makers:
            p = mk()
            if p.name != TARGET:
                continue
            env = dict(env_all)
            for v in p.inputs + p.outputs + p.locals:
                env[v.name.upper()] = v.type
            items = []
            for net_i, net in enumerate(p.networks):
                for it in net._items:
                    items.append((net_i, it))
            by_id = dict([(it[1], it) for _, it in items])
            f.write(u"POU %s: объявлений=%d сетей=%d элементов=%d\n\n"
                    % (p.name, len(p.inputs + p.outputs + p.locals),
                       len(p.networks), len(items)))
            for net_i, it in items:
                if it[0] != u"outvar":
                    continue
                n_all += 1
                tgt = CT.resolve(it[2], env, structs, ifaces)
                if tgt.kind == u"el":
                    continue
                n_un += 1
                st = out_type(by_id.get(it[3].eid), by_id, env, structs, ifaces)
                f.write(u"  сеть %2d  ПРИЁМНИК НЕ РАЗОБРАН: %-40s тип_приёмника=%-8s"
                        u" источник=%-8s  %s\n"
                        % (net_i, it[2], tgt.name, st.name,
                           (u"%s" % (by_id.get(it[3].eid) or [u"?", u"?", u"?"])[2])))
            f.write(u"\nвсего приёмников: %d, неразобранных: %d\n" % (n_all, n_un))
    f.close()
    print(u"POU=%s приёмников=%d неразобранных=%d -> %s" % (TARGET, n_all, n_un, OUT))


main()
