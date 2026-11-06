# -*- coding: utf-8 -*-
u"""ТОЧНАЯ ДИАГНОСТИКА ФЛАГОВ: ожидаемый PSW против фактического по каждому кейсу.

Отчёт gen_stage4 печатает "Факт (A PC SP)" и НЕ печатает фактический PSW,
поэтому нельзя сказать, какой именно бит S/Z/AC/P/CY неверен. Здесь читаем
GVL_TEST.ActPSW[0..198] и сравниваем с ожиданием по маске кейса:
    для битов из PSWMask - с ExpPSW,
    для остальных          - с InitPSW (флаг не должен был измениться).
Печатаем только расхождения, с указанием неверных битов.
"""
import io
import sys
import traceback

import scriptengine
import pou_test_defs as TD

ROOT = u"C:/dsh8080/work/emu_s4"
PROJ = ROOT + u"/build/EMU8080_STAGE4.project"
LOG = ROOT + u"/log/zz_psw.log"
OUT = ROOT + u"/log/zz_psw.txt"
WAIT = int(__import__("os").environ.get(u"DSH_PSW_WAIT") or u"300")

MASK_MEANING = 0xD7
BITS = ((0x80, u"S"), (0x40, u"Z"), (0x10, u"AC"), (0x04, u"P"), (0x01, u"CY"))


def w(m):
    try:
        h = io.open(OUT, u"ab")
        h.write((u"%s\n" % m).encode(u"utf-8"))
        h.close()
    except Exception:
        pass


def rd_arr(oa, expr, cnt):
    try:
        vals = oa.read_values([u"%s[%d]" % (expr, i) for i in range(cnt)])
        return [num(v) for v in vals]
    except Exception, e:
        w(u"[WARN] чтение %s: %s" % (expr, e))
        return None


def num(v):
    u"""Число из значения CODESYS: 'INT#27' -> 27, 'TRUE' -> 1."""
    s = u"%s" % v
    if u"TRUE" in s.upper():
        return 1
    if u"FALSE" in s.upper():
        return 0
    try:
        return int(s.split(u"#")[-1])
    except Exception:
        return 0


def main():
    import time
    cases = TD.build_all()
    w(u"=== ДИАГНОСТИКА ФЛАГОВ ===")
    proj = scriptengine.projects.open(PROJ)
    app = proj.active_application
    oa = scriptengine.online.create_online_application(app)
    oa.login(scriptengine.OnlineChangeOption.Never, False)
    oa.start()
    oa.set_prepared_value(u"GVL_TEST.Reset", u"TRUE")
    oa.write_prepared_values()
    w(u"[OK] сброс запрошен, ждём прогон %d с" % WAIT)

    # Сброс действует один скан, после него прогон идёт с начала. Даём 30 с
    # на раскрутку, затем ждём завершения набора (Done8080) или Idx >= 197.
    time.sleep(30)
    t0 = time.time()
    idx, sc, done = 0, 0, 0
    while time.time() - t0 < WAIT:
        time.sleep(10)
        try:
            done = num(oa.read_value(u"GVL_TEST.Done8080"))
            idx = num(oa.read_value(u"GVL_TEST.Idx"))
            sc = num(oa.read_value(u"GVL_TEST.Scans"))
        except Exception:
            continue
        if done or idx >= 197:
            break
    w(u"[OK] прогон: Idx=%s Scans=%s Done=%s за %.0f с" % (idx, sc, done, time.time() - t0))

    ps = rd_arr(oa, u"GVL_TEST.ActPSW", 199)
    ac = rd_arr(oa, u"GVL_TEST.ActA", 199)
    pc = rd_arr(oa, u"GVL_TEST.ActPC", 199)
    rs = oa.read_values([u"GVL_TEST.Results[%d]" % i for i in range(199)])
    rs = [u"TRUE" in (u"%s" % x) for x in rs]
    try:
        oa.stop()
        oa.logout()
    except Exception:
        pass
    if ps is None or ac is None or pc is None:
        w(u"[FAIL] массивы не прочитаны")
        return

    npass = sum(1 for x in rs if x)
    w(u"")
    w(u"PASS=%d FAIL=%d" % (npass, 199 - npass))
    w(u"")
    w(u"| ID | Тест | Ожид.PSW | Факт.PSW | Маска | Неверные биты | A | PC |")
    w(u"|---|---|---|---|---|---|---|---|")
    nbad = 0
    for i, c in enumerate(cases):
        if rs[i]:
            continue
        nbad += 1
        m = c[u"mask"] & MASK_MEANING
        ref = ((c[u"exp_psw"] & m) | (c[u"init"][u"PSW"] & (~m & 0xFF))) & MASK_MEANING
        got = ps[i] & MASK_MEANING
        bad = []
        for bit, nm in BITS:
            if (ref & bit) != (got & bit):
                bad.append(nm)
        w(u"| %s | %s | %02X | %02X | %02X | %s | %02X/%02X | %04X/%04X |"
          % (c[u"id"], c[u"name"], ref, got, m, u",".join(bad) or u"-",
             c[u"exp"][u"A"], ac[i], c[u"exp"][u"PC"], pc[i]))
    w(u"")
    w(u"расхождений: %d" % nbad)


try:
    main()
except Exception:
    w(u"НЕОБРАБОТАННОЕ ИСКЛЮЧЕНИЕ:")
    w(traceback.format_exc())
w(u"=== DONE ===")
try:
    h = io.open(LOG, u"wb")
    h.write(u"=== DONE ===\n".encode(u"utf-8"))
    h.close()
except Exception:
    pass
