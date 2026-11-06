# -*- coding: utf-8 -*-
u"""Пробник диалекта: какие стандартные FBD-блоки понимает CODESYS и как называются их выводы.

Что делает:
  1) генерирует PLCopenXML с одним POU, в котором ~30 стандартных блоков
     (AND/OR/XOR/NOT/ADD/SUB/MUL/DIV/MOD/SHL/SHR/ROL/ROR/EQ/NE/GT/LT/GE/LE/SEL/MUX/MOVE
      + прямое присваивание переменной переменной);
  2) создаёт проект с устройством CODESYS Control Win V3;
  3) создаёт GVL и DUT через scripting API и пытается задать им текст объявления;
  4) импортирует сгенерированный XML;
  5) выгружает импортированное обратно в XML (видно, что CODESYS сохранил);
  6) собирает проект и печатает ошибки.
"""
import io, os, sys, traceback
import scriptengine

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
ROOT = BASE.rsplit("/", 1)[0]
sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

LOG = BASE + "/probe_dialect.log"
f = io.open(LOG, "w", encoding="utf-8")

def L(m):
    f.write(u"%s\n" % (m,)); f.flush()

def nm(o):
    try:
        return o.get_name()
    except Exception:
        return u"?"

def close_all():
    for p in list(projects.all):
        try:
            p.close()
        except Exception:
            pass

L(u"[0] скрипт запущен, python %s" % sys.version)
L(u"[0] BASE=%s ROOT=%s" % (BASE, ROOT))

# ======================================================================
# 1. ГЕНЕРАЦИЯ ПРОБНОГО POU
# ======================================================================
DECL = u"""FUNCTION_BLOCK FB_OP_PROBE
(* Пробник стандартных FBD-блоков CODESYS. Ничего не вычисляет по смыслу -
   проверяет, какие блоки и какие имена выводов принимает импортёр PLCopenXML. *)
VAR_INPUT
\tA, B : BOOL;
\tX, Y : BYTE;
\tW : WORD;
END_VAR
VAR_OUTPUT
\tQ_AND, Q_OR, Q_XOR, Q_NOT : BOOL;
\tR_ADD, R_SUB, R_MUL, R_DIV, R_MOD : BYTE;
\tR_BAND, R_BOR, R_BXOR, R_SHL, R_SHR, R_ROL, R_ROR : BYTE;
\tB_EQ, B_NE, B_GT, B_LT, B_GE, B_LE : BOOL;
\tR_MOVE, R_ASSIGN : BYTE;
\tR_SEL, R_MUX : BYTE;
END_VAR
"""

pou = Pou(u"FB_OP_PROBE", DECL)

# --- сеть 1: логика BOOL ---
n = pou.network(u"СЕТЬ 1. Логика BOOL: AND / OR / XOR / NOT")
a = n.invar(u"A"); b = n.invar(u"B")
n.outvar(u"Q_AND", n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
n.outvar(u"Q_OR", n.block(u"OR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
n.outvar(u"Q_XOR", n.block(u"XOR", [(u"IN1", a), (u"IN2", b)], [u"OUT"]))
n.outvar(u"Q_NOT", n.block(u"NOT", [(u"IN", a)], [u"OUT"]))

# --- сеть 2: арифметика BYTE ---
n = pou.network(u"СЕТЬ 2. Арифметика BYTE: ADD / SUB / MUL / DIV / MOD")
x = n.invar(u"X"); y = n.invar(u"Y")
for out, op in ((u"R_ADD", u"ADD"), (u"R_SUB", u"SUB"), (u"R_MUL", u"MUL"),
                (u"R_DIV", u"DIV"), (u"R_MOD", u"MOD")):
    n.outvar(out, n.block(op, [(u"IN1", x), (u"IN2", y)], [u"OUT"]))

# --- сеть 3: битовые операции BYTE ---
n = pou.network(u"СЕТЬ 3. Битовые операции BYTE: AND / OR / XOR / SHL / SHR / ROL / ROR")
x = n.invar(u"X"); y = n.invar(u"Y")
for out, op in ((u"R_BAND", u"AND"), (u"R_BOR", u"OR"), (u"R_BXOR", u"XOR"),
                (u"R_SHL", u"SHL"), (u"R_SHR", u"SHR"), (u"R_ROL", u"ROL"), (u"R_ROR", u"ROR")):
    n.outvar(out, n.block(op, [(u"IN1", x), (u"IN2", y)], [u"OUT"]))

# --- сеть 4: сравнения ---
n = pou.network(u"СЕТЬ 4. Сравнения: EQ / NE / GT / LT / GE / LE")
x = n.invar(u"X"); y = n.invar(u"Y")
for out, op in ((u"B_EQ", u"EQ"), (u"B_NE", u"NE"), (u"B_GT", u"GT"),
                (u"B_LT", u"LT"), (u"B_GE", u"GE"), (u"B_LE", u"LE")):
    n.outvar(out, n.block(op, [(u"IN1", x), (u"IN2", y)], [u"OUT"]))

# --- сеть 5: SEL / MUX / MOVE ---
n = pou.network(u"СЕТЬ 5. SEL / MUX / MOVE")
a = n.invar(u"A"); x = n.invar(u"X"); y = n.invar(u"Y")
n.outvar(u"R_SEL", n.block(u"SEL", [(u"G", a), (u"IN0", x), (u"IN1", y)], [u"OUT"]))
n.outvar(u"R_MUX", n.block(u"MUX", [(u"K", x), (u"IN0", x), (u"IN1", y), (u"IN2", x), (u"IN3", y)], [u"OUT"]))
n.outvar(u"R_MOVE", n.block(u"MOVE", [(u"IN", x)], [u"OUT"]))

# --- сеть 6: прямое присваивание переменной переменной ---
n = pou.network(u"СЕТЬ 6. Прямое присваивание: R_ASSIGN := X")
x = n.invar(u"X")
n.outvar(u"R_ASSIGN", x)

# --- сеть 7: две ступени (каскад) ---
n = pou.network(u"СЕТЬ 7. Каскад: (A AND B) OR NOT A")
a = n.invar(u"A"); b = n.invar(u"B")
g1 = n.block(u"AND", [(u"IN1", a), (u"IN2", b)], [u"OUT"])
g2 = n.block(u"NOT", [(u"IN", a)], [u"OUT"])
n.outvar(u"Q_OR", n.block(u"OR", [(u"IN1", g1), (u"IN2", g2)], [u"OUT"]))

src_path = ROOT + u"/src/probe_dialect.plcopenxml"
size = fbd_xml.write_project(src_path, [pou], u"probe_dialect")
L(u"[1] PLCopenXML записан: %s (%d символов)" % (src_path, size))

# ======================================================================
# 2. ПРОЕКТ С УСТРОЙСТВОМ
# ======================================================================
close_all()
work = ROOT + u"/build/probe_dialect.project"
if os.path.exists(work):
    os.remove(work)

proj = projects.create(work)
L(u"[2] projects.create OK")
try:
    proj.add(name=u"Device", type=4096, id=u"0000 0001", version=u"3.5.17.30")
    L(u"[2] proj.add(device) OK")
except Exception:
    L(u"[2] proj.add FAILED: %s" % traceback.format_exc().splitlines()[-1])

app = proj.active_application
L(u"[3] application = %s" % nm(app))

# ======================================================================
# 3. GVL и DUT через scripting API
# ======================================================================
GVL_TEXT = u"""VAR_GLOBAL
\t(* Общая шина данных эмулятора Intel 8080 *)
\tBus_Data : BYTE;
\tBus_Addr : WORD;
END_VAR
"""
try:
    gvl = app.create_gvl(u"GVL_PROBE")
    L(u"[4] create_gvl OK -> %s  has_textual_declaration=%s"
      % (nm(gvl), getattr(gvl, u"has_textual_declaration", u"?")))
    td = gvl.textual_declaration
    L(u"[4] textual_declaration -> %r" % (td,))
    ok = False
    for label, fn in ((u"replace", lambda: td.replace(GVL_TEXT)),
                      (u"text=setter", lambda: setattr(td, u"text", GVL_TEXT)),
                      (u"insert(0)", lambda: td.insert(GVL_TEXT, 0, 0, 0)),
                      (u"append", lambda: td.append(GVL_TEXT))):
        try:
            fn()
            L(u"[4] %s -> OK; text now: %r" % (label, td.text[:120]))
            ok = True
            break
        except Exception:
            L(u"[4] %s -> %s" % (label, traceback.format_exc().splitlines()[-1]))
    if not ok:
        L(u"[4] НЕ УДАЛОСЬ задать текст объявления GVL")
except Exception:
    L(u"[4] GVL FAILED\n" + traceback.format_exc())

DUT_TEXT = u"""TYPE ST_PROBE :
STRUCT
\t(* Пробная структура *)
\tA : BYTE;
\tB : WORD;
END_STRUCT
END_TYPE
"""
try:
    dut = app.create_dut(u"ST_PROBE", type=scriptengine.DutType.Structure)
    L(u"[5] create_dut OK -> %s" % nm(dut))
    td = dut.textual_declaration
    ok = False
    for label, fn in ((u"replace", lambda: td.replace(DUT_TEXT)),
                      (u"text=setter", lambda: setattr(td, u"text", DUT_TEXT)),
                      (u"insert(0)", lambda: td.insert(DUT_TEXT, 0, 0, 0))):
        try:
            fn()
            L(u"[5] %s -> OK; text now: %r" % (label, td.text[:120]))
            ok = True
            break
        except Exception:
            L(u"[5] %s -> %s" % (label, traceback.format_exc().splitlines()[-1]))
except Exception:
    L(u"[5] DUT FAILED\n" + traceback.format_exc())

# ======================================================================
# 4. ИМПОРТ FBD
# ======================================================================
try:
    app.import_xml(src_path)
    L(u"[6] import_xml OK")
except Exception:
    L(u"[6] import_xml FAILED\n" + traceback.format_exc())

# ======================================================================
# 5. ОБРАТНАЯ ВЫГРУЗКА + ПРОВЕРКА, ЧТО СВЯЗИ НЕ ПОТЕРЯЛИСЬ
# ======================================================================
def counts(path):
    t = io.open(path, "r", encoding="utf-8").read()
    return (t.count(u"<block "), t.count(u"<inVariable "), t.count(u"<outVariable "),
            t.count(u"<connection "), t.count(u"<connectionPointIn />"))

L(u"[7] ГЕНЕРАЦИЯ   : блоков=%d вход.перем=%d выход.перем=%d связей=%d пустых.входов=%d" % counts(src_path))

def walk(o, ind=0, depth=5, acc=None):
    if acc is None:
        acc = []
    L(u"%s- %s [%s]" % (u"  " * ind, nm(o), type(o).__name__))
    try:
        acc.append((nm(o), o))
    except Exception:
        pass
    if ind >= depth:
        return acc
    try:
        kids = o.get_children()
    except Exception:
        kids = []
    for k in kids:
        walk(k, ind + 1, depth, acc)
    return acc


def find_anywhere(root, name):
    for n, o in walk(root, 0, 6, []):
        if n == name:
            return o
    return None


try:
    L(u"[7] --- ДЕРЕВО ПРОЕКТА ПОСЛЕ ИМПОРТА ---")
    found = find_anywhere(app, u"FB_OP_PROBE")
    L(u"[7] поиск FB_OP_PROBE -> %r" % (found,))
    if found is not None:
        outp = ROOT + u"/src/probe_dialect_reexport.xml"
        proj.export_xml([found], path=outp, declarations_as_plaintext=True)
        c = counts(outp)
        L(u"[7] ПОСЛЕ ИМПОРТА: блоков=%d вход.перем=%d выход.перем=%d связей=%d пустых.входов=%d" % c)
        if c[0] == 28 and c[4] == 0:
            L(u"[7] ПРОВЕРКА СВЯЗЕЙ: OK (28 блоков, ни одного пустого входа)")
        else:
            L(u"[7] ПРОВЕРКА СВЯЗЕЙ: РАСХОЖДЕНИЕ (ожидалось 28 блоков и 0 пустых входов)")
except Exception:
    L(u"[7] FAILED\n" + traceback.format_exc())

# ======================================================================
# 6. СБОРКА
# ======================================================================
try:
    proj.save()
    L(u"[8] saved")
except Exception:
    L(u"[8] save FAILED: %s" % traceback.format_exc().splitlines()[-1])

try:
    r = app.build()
    L(u"[9] build() -> %r" % (r,))
except Exception:
    L(u"[9] build FAILED\n" + traceback.format_exc())

close_all()
L(u"=== DONE ===")
f.close()
