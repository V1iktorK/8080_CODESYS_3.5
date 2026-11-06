# -*- coding: utf-8 -*-
u"""ЛОКАЛЬНАЯ ПРОВЕРКА ТИПОВ FBD-СХЕМ (без CODESYS).

ЗАЧЕМ. Кодогенератор CODESYS сообщает только код и текст ошибки (C32, C18, C0)
без имени POU: позиция в stderr не печатается, а C181 - «Относительная позиция» -
подробностей не содержит. Поэтому типы проверяются здесь: скрипт строит таблицу
типов (GVL + DUT + интерфейсы POU), проходит по всем сетям всех POU и ищет ровно
те несоответствия, на которые жалуется компилятор:

  * вход блока BOOL <- значение BYTE/WORD/INT (C32 'BYTE' -> 'BOOL');
  * приёмник BYTE <- значение BOOL (C32 'BOOL' -> 'BYTE');
  * вход битовой операции (AND/OR/NOT/SHL) <- INT/USINT/... (C32 'INT' -> 'ANY_BIT');
  * вызов FB без экземпляра (C80);
  * вызов FB без входов (C0 «недостаточно входов для параметров EN/ENO»);
  * приёмник - литерал (C18 «не является допустимым значением перечисления»).

Запуск (CPython 3):
    python tools\\check_types.py
"""
import builtins
import io
import os
import re
import sys
import collections

builtins.unicode = str

GEN = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WORK = u"C:/dsh8080/work/emu_s4"
sys.path.insert(0, GEN)

import fbd_xml
import pou_cpm_defs as D
import pou_io_defs as IOD
import pou_decode_full
import pou_cpu_io
import pou_cpm_trap
import pou_bios
import pou_bdos
import pou_com_loader
import pou_ccp
import pou_io
import pou_io_hw
import pou_prg_io
import pou_test_defs as TD
import pou_test8080
import pou_testcpm
import pou_testio

EL = (u"BOOL", u"BYTE", u"WORD", u"DWORD", u"SINT", u"USINT", u"INT", u"UINT",
      u"DINT", u"UDINT", u"LINT", u"ULINT", u"REAL", u"LREAL", u"TIME",
      u"STRING", u"WSTRING", u"CHAR", u"BYTE")
BIT = (u"BOOL", u"BYTE", u"WORD", u"DWORD", u"LWORD")
NUM = (u"SINT", u"USINT", u"INT", u"UINT", u"DINT", u"UDINT", u"LINT", u"ULINT",
       u"REAL", u"LREAL")
CONV = re.compile(u"^([A-Z0-9]+)_TO_([A-Z0-9]+)$")

GROUPS = ((u"процессор", pou_cpu_io.ALL),
          (u"трапы", pou_cpm_trap.ALL),
          (u"BIOS", pou_bios.ALL),
          (u"BDOS", pou_bdos.ALL),
          (u"CCP", pou_ccp.ALL),
          (u"загрузчик", pou_com_loader.ALL),
          (u"ввод-вывод", pou_io.ALL),
          (u"адаптер C", pou_io_hw.ALL),
          (u"главная", pou_prg_io.ALL),
          (u"ТЕСТ 8080", pou_test8080.ALL),
          (u"ТЕСТ CP/M", pou_testcpm.ALL),
          (u"ТЕСТ IO", pou_testio.ALL))

GVL_TEXTS = ((u"GVL_CPU", pou_decode_full.gvl_cpu_text()),
             (u"GVL_MEM", u"VAR_GLOBAL\n\tMemory : ARRAY[0..65535] OF BYTE;\nEND_VAR\n"),
             (u"GVL_CPM", D.gvl_cpm_text()),
             (u"GVL_DISK", D.gvl_disk_text()),
             (u"GVL_IO_HW", pou_io_hw.gvl_io_hw_text()),
             (u"GVL_TEST", TD.gvl_test_text())) + \
            tuple([(nm, fn()) for nm, fn in IOD.GVL_ALL])


# --------------------------------------------------------------- типы
class T(object):
    u"""Тип переменной/выражения. kind: el | arr | st | fb | unk."""

    def __init__(self, kind, name, base=None, dims=0, st=None):
        self.kind = kind
        self.name = name
        self.base = base
        self.dims = dims
        self.st = st

    def __repr__(self):
        return self.name if self.kind != u"arr" else u"%s[%d]" % (self.name, self.dims)

    def elem(self, n=1):
        t = self
        for _ in range(n):
            if t.kind == u"arr":
                t = t.base
        return t


UNK = T(u"unk", u"?")
BOOL = T(u"el", u"BOOL")
# СТАТИСТИКА ОХВАТА (этап A5). Проверка типов бесполезна, если почти все
# источники разрешаются в UNK: compatible(UNK, ...) всегда True, то есть связь
# молча пропускается. Поэтому считаем, СКОЛЬКО входов реально проверено.
STATS = collections.Counter()
# Что именно пропущено (этап A5): имя блока, тип которого неизвестен, и пары
# «блок.вывод», которых нет в интерфейсе. Обе категории - «слепые зоны»: связь
# в них не проверяется вообще, поэтому они должны быть ВИДНЫ, а не молчать.
UNKNOWN_BLOCKS = collections.Counter()
UNKNOWN_PINS = collections.Counter()
# Связи, где источник не разрешился, а приёмник - BOOL: прямые кандидаты в C32.
UNK_BOOL = collections.Counter()
ARR = re.compile(u"^ARRAY\\s*\\[(.*?)\\]\\s*OF\\s+(.+)$", re.I)


def parse_type(text, structs):
    t = text.strip()
    m = ARR.match(t)
    if m:
        dims = m.group(1).count(u",") + 1
        base = parse_type(m.group(2), structs)
        return T(u"arr", t + u"[]", base, dims)
    up = t.upper()
    for e in EL:
        if up == e:
            return T(u"el", up)
    if up in structs:
        return T(u"st", t, st=up)
    # kind='fb' означает «известный функциональный блок», и compatible() для него
    # отвечает False. Поэтому «типом» его объявляем ТОЛЬКО если текст похож на
    # идентификатор: иначе неразобранная строка объявления превращалась в
    # ложное срабатывание C32 (см. разбор в parse_decl).
    if re.match(u"^[A-Za-z_][A-Za-z0-9_]*$", t):
        return T(u"fb", t)
    return UNK


DECL_VAR = re.compile(u"^\\s*(?:AT\\s+%[IQ][XBDW]*\\d+(?:\\.\\d+)?\\s+)?"
                      u"([A-Za-z_][A-Za-z0-9_]*)\\s*:\\s*(.+)$")


def parse_decl(text, structs):
    u"""Имя -> тип из текста объявления (GVL/DUT).

    ИСПРАВЛЕНО на этапе A5. Прежний шаблон брал тип как `[^;(*)[]+?` и требовал
    сразу за ним `;`. Из этого следовали ДВЕ ошибки:

      * НАЧАЛЬНОЕ ЗНАЧЕНИЕ ПОПАДАЛО В ТИП: в GVL_TEST есть `Mode : BYTE := 1;`,
        и типом становилось "BYTE := 1". Такой «тип» не совпадал ни с одним
        элементом EL, объявлялся как kind='fb', а compatible() для kind='fb'
        отвечает False - и получалось 18 ЛОЖНЫХ срабатываний C32 в TEST_8080,
        TEST_CPM, TEST_IO;
      * МАССИВЫ НЕ РАЗБИРАЛИСЬ ВООБЩЕ: `Memory : ARRAY[0..65535] OF BYTE;`
        не подходил под шаблон (в классе исключён `[`), поэтому ARRAY всегда
        разрешался в UNK и связи через память не проверялись.

    Теперь строка разбирается по существу: отбрасываем комментарий `(* ... *)`,
    концевое `;`, затем ВСЁ до первого `:=` (тип), и только потом разбираем тип.
    """
    out = {}
    for line in text.split(u"\n"):
        s = line.split(u"(*")[0].strip()
        if s.endswith(u";"):
            s = s[:-1].strip()
        m = DECL_VAR.match(s)
        if not m:
            continue
        rhs = m.group(2)
        if u":=" in rhs:
            rhs = rhs.split(u":=")[0]
        out[m.group(1).upper()] = parse_type(rhs.strip(), structs)
    return out


def parse_duts():
    u"""Структуры (DUT) и их поля."""
    structs = {}
    raw = {}
    for nm, t in D.DUT_ALL + IOD.DUT_ALL + TD.DUT_ALL:
        raw[nm.upper()] = t
        structs[nm.upper()] = {}
    for nm, t in raw.items():
        structs[nm] = parse_decl(t, structs)
    return structs


def parse_pou_xml(path):
    u"""Интерфейс POU из PLCopenXML: (in, out, local) -> имя -> тип."""
    t = io.open(path, u"r", encoding=u"utf-8", errors=u"replace").read()
    res = {u"in": {}, u"out": {}, u"loc": {}}
    cur = None
    for m in re.finditer(u"<(inputVars|outputVars|localVars|inOutVars)>|"
                         u"<variable name=\"([^\"]+)\">(.*?)</variable>", t, re.S):
        if m.group(1):
            cur = {u"inputVars": u"in", u"outputVars": u"out",
                   u"localVars": u"loc", u"inOutVars": u"loc"}[m.group(1)]
            continue
        if cur is None:
            continue
        tname = re.search(u"<([A-Za-z_][A-Za-z0-9_]*)\\s*/>|"
                          u"<derived name=\"([^\"]+)\"\\s*/>|"
                          u"<array>(.*?)</array>", m.group(3), re.S)
        if not tname:
            continue
        if tname.group(1):
            res[cur][m.group(2)] = tname.group(1)
        elif tname.group(2):
            res[cur][m.group(2)] = tname.group(2)
        else:
            arr = tname.group(3)
            lo = len(re.findall(u"<dimension", arr))
            base = re.search(u"<([A-Za-z_][A-Za-z0-9_]*)\\s*/>|"
                             u"<derived name=\"([^\"]+)\"\\s*/>", arr)
            res[cur][m.group(2)] = u"ARRAY[%s] OF %s" % (
                u", ".join([u"0..0"] * lo), base.group(1) or base.group(2))
    return res


def collect_fb_interfaces():
    u"""Типы входов/выходов всех FB проекта (наши POU + зависимости)."""
    ifaces = {}
    for grp, makers in GROUPS:
        for mk in makers:
            p = mk()
            ifaces[p.name.upper()] = (
                dict([(v.name.upper(), v.type) for v in p.inputs]),
                dict([(v.name.upper(), v.type) for v in p.outputs]))
    # ВАЖНО (найдено на этапе A5): 27 ЗАВИСИМОСТЕЙ ЯДРА (FB_Reg8, FB_Reg16,
    # FB_ALU8, FB_Memory64K, FB_Mux8x8/16, FB_CtrlUnit, ...) в GROUPS НЕ входят -
    # они генерируются модулем pou_deps. Раньше их типы попадали сюда только из
    # СНИМКА src/dep_fix, а снимок удалён (он рассинхронивал имена), поэтому
    # интерфейсы зависимостей вообще не проверялись. Берём их из того же
    # первоисточника, что и сборка: pou_deps.make(). Имена здесь ДО переименования
    # (как и у GROUPS) - это согласовано, потому что переименование меняет только
    # идентификаторы, а не типы (BOOL/BYTE/WORD в RESERVED не входят).
    try:
        import pou_deps
        n_dep = 0
        for nm in pou_deps.all_names():
            p = pou_deps.make(nm)
            if p is None:
                continue
            ifaces[p.name.upper()] = (
                dict([(v.name.upper(), v.type) for v in p.inputs]),
                dict([(v.name.upper(), v.type) for v in p.outputs]))
            n_dep += 1
        print(u"интерфейсы зависимостей: %d" % n_dep)
    except Exception as e:
        print(u"НЕ УДАЛОСЬ загрузить pou_deps: %r" % (e,))
    # СНИМОК XML - ТОЛЬКО РЕЗЕРВ (найдено на этапе A5). Файлы в src/dep_fix
    # УЖЕ ПЕРЕИМЕНОВАНЫ (LDx, SELx, Sx), а Pou-объекты из GROUPS и pou_deps -
    # ещё НЕТ. Раньше этот блок ЗАТИРАЛ интерфейсы зависимостей
    # переименованными именами, и получалась СМЕСЬ двух систем имён: пять
    # связей (FB_Reg16.LD, FB_Mux8x8.Sel, FB_Mux8x16.Sel, FB_CtrlUnit.S во
    # FB_CPU8080_FULL) объявлялись «пином не из интерфейса» и НЕ проверялись,
    # а все обращения к выводам зависимостей разрешались в UNK. Теперь
    # первоисточник (pou_deps) главнее, а XML добавляется только для имён,
    # которых там нет, - тогда вся проверка идёт в ОДНОЙ системе имён.
    dep = WORK + u"/src/dep_fix"
    if os.path.isdir(dep):
        for fn in os.listdir(dep):
            if not fn.endswith(u".plcopenxml"):
                continue
            nm = fn[:-len(u".plcopenxml")]
            if nm.upper() in ifaces:
                continue
            r = parse_pou_xml(os.path.join(dep, fn))
            ifaces[nm.upper()] = (r[u"in"], r[u"out"])
    return ifaces


def const_type(e):
    s = e.strip()
    m = re.match(u"^([A-Za-z]+)#", s)
    if m:
        up = m.group(1).upper()
        if up in EL:
            return T(u"el", up)
        if up == u"16":
            return T(u"el", u"BYTE")
        if up == u"2":
            return T(u"el", u"BYTE")
    if s.upper() in (u"TRUE", u"FALSE"):
        return BOOL
    return None


ID_RE = re.compile(u"^[A-Za-z_][A-Za-z0-9_]*")


def _skip_brackets(s, i):
    u"""Индекс от i (s[i] == '['): вернуть позицию ЗА парной ']' или -1.

    Балансировка обязательна: в схемах есть ВЛОЖЕННАЯ индексация и обращение к
    полю после индекса - GVL_TEST.Tests[idx].Code[0].
    """
    depth = 0
    while i < len(s):
        if s[i] == u"[":
            depth += 1
        elif s[i] == u"]":
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return -1


def resolve(e, env, structs, ifaces):
    u"""Тип выражения схемы - РАЗБОР СЛЕВА НАПРАВО.

    ПЕРЕПИСАНО на этапе A5. Прежняя версия разбирала выражение шаблонами
    «целиком»: отдельно `имя.поле`, отдельно `имя[индекс]`. На составном
    выражении GVL_TEST.Tests[idx].Code[0] шаблон индекса захватывал
    `GVL_TEST.Tests` как базу (жадное `.*` внутри скобок), возвращал тип
    ЭЛЕМЕНТА массива - ST_TestCase - и получалось 16 ложных C32
    («приёмник BYTE <- ST_TestCase») в TEST_8080.

    Здесь выражение разбирается последовательно: имя, затем цепочка шагов
    `.поле`, `.бит`, `[индекс]`, и на каждом шаге тип преобразуется по смыслу.
    """
    s = unicode(e).strip()
    c = const_type(s)
    if c is not None:
        return c
    if re.match(u"^-?\\d+$", s):
        return UNK
    if re.search(u"[+\\-*/]", s) and not s.startswith(u"-"):
        return UNK

    m = ID_RE.match(s)
    if not m:
        return UNK
    t = env.get(m.group(0).upper())
    if t is None:
        return UNK
    if not isinstance(t, T):
        t = parse_type(t, structs)
    i = m.end()

    while i < len(s):
        ch = s[i]
        if ch == u".":
            mb = re.match(u"^\\.(\\d+)", s[i:])
            if mb:
                # битовый доступ W.0 .. W.15
                if t.kind == u"el" and t.name in BIT:
                    t = BOOL
                else:
                    return UNK
                i += mb.end()
                continue
            mb = re.match(u"^\\.([A-Za-z_][A-Za-z0-9_]*)", s[i:])
            if not mb:
                return UNK
            f = mb.group(1).upper()
            if t.kind == u"st":
                fld = structs.get(t.st, {}).get(f)
                if fld is None:
                    return UNK
                t = fld
            elif t.kind == u"fb":
                # ЗАПИСЬ В ВХОД ЭКЗЕМПЛЯРА FB / ЧТЕНИЕ ЕГО ВЫВОДА: inst.Pin.
                # Раньше такие имена разрешались в UNK, и связь не проверялась.
                ifc = ifaces.get(t.name.upper())
                if ifc is None:
                    return UNK
                pin = None
                for src_map in (ifc[0], ifc[1]):
                    for k in src_map:
                        if k.upper() == f:
                            pin = src_map[k]
                            break
                    if pin is not None:
                        break
                if pin is None:
                    return UNK
                t = parse_type(pin, structs)
            else:
                return UNK
            i += mb.end()
            continue
        if ch == u"[":
            j = _skip_brackets(s, i)
            if j < 0:
                return UNK
            i = j
            if t.kind == u"arr":
                t = t.base
            else:
                return UNK
            continue
        # любой другой символ - выражение не из нашего словаря
        return UNK
    return t


STD_ANY = u"ANY"


def std_pins(bname):
    u"""Ожидаемые типы входов стандартного блока: pin -> категория."""
    b = bname.upper()
    m = CONV.match(b)
    if m:
        return {u"IN": m.group(1)}
    if b in (u"NOT",):
        # ПРОВЕРЕНО ЭКСПЕРИМЕНТАЛЬНО (этап A5): NOT у CODESYS принимает ANY_BIT,
        # то есть BYTE на входе NOT - это НЕ ошибка. Гипотеза «NOT принимает
        # только BOOL» была проверена правкой этого места на 'BOOL': она дала
        # 21 срабатывание вида "NOT.IN: BYTE -> BOOL", но опровергается сборкой
        # ШАГ0 (все тела 67 POU опустошены, 27 зависимостей ядра целы) -
        # она прошла с 0 ошибок, а среди зависимостей есть FB_ALU8, у которого
        # ровно такая связь (localId=14, вход B). Значит, NOT(BYTE) законен.
        return {u"IN": u"BIT"}
    if b in (u"AND", u"OR", u"XOR"):
        return {u"IN1": u"BIT", u"IN2": u"BIT"}
    if b in (u"EQ", u"NE", u"LT", u"GT", u"LE", u"GE"):
        return {u"IN1": STD_ANY, u"IN2": STD_ANY}
    if b == u"MOVE":
        return {u"IN": STD_ANY}
    if b == u"SEL":
        return {u"G": u"BOOL", u"IN0": STD_ANY, u"IN1": STD_ANY}
    if b in (u"ADD", u"SUB", u"MUL", u"DIV", u"MOD"):
        return {u"IN1": u"NUM", u"IN2": u"NUM"}
    if b in (u"SHL", u"SHR", u"ROL", u"ROR"):
        return {u"IN1": u"BIT", u"IN2": u"NUM"}
    if b == u"LIMIT":
        return {u"MN": u"NUM", u"IN": u"NUM", u"MX": u"NUM"}
    if b in (u"MAX", u"MIN"):
        return {u"IN1": u"NUM", u"IN2": u"NUM"}
    return None


def compatible(actual, expected, strict=True):
    u"""Проверка «можно ли подать actual на вход типа expected» РОВНО теми
    правилами, которые применяет CODESYS (проверено на его сообщениях):

      * BOOL несовместим ни с каким другим типом (ни туда, ни обратно);
      * битовая операция (ANY_BIT) не принимает INT/USINT/UDINT/DINT/...;
      * широкий целый (UDINT/DINT/LINT/ULINT) не влезает в INT/UINT/BYTE/WORD.

    Всё остальное CODESYS принимает (WORD в ADD, BYTE в сравнении, DINT<->UDINT
    только с предупреждением C195/C196), поэтому здесь НЕ помечается: цель
    проверки - найти настоящие ошибки, а не выдать лишние.
    """
    if actual is None or actual.kind == u"unk":
        return True
    if actual.kind in (u"arr", u"st", u"fb"):
        return False
    if expected in (None, u"?", STD_ANY):
        return True
    if expected == u"BIT":
        return actual.name in BIT
    if expected == u"NUM":
        return actual.name in NUM or actual.name in BIT
    if expected == u"BOOL":
        return actual.name == u"BOOL"
    if actual.name == expected:
        return True
    if actual.name == u"BOOL" or expected == u"BOOL":
        return False
    WIDE = (u"UDINT", u"DINT", u"LINT", u"ULINT")
    NARROW = (u"INT", u"UINT", u"SINT", u"USINT", u"BYTE", u"WORD")
    if actual.name in WIDE and expected in NARROW:
        return False
    return True


def check_pou(p, env_all, structs, ifaces, report):
    # ВАЖНО (найдено на этапе A5): раньше здесь было env = {}, то есть
    # ГЛОБАЛЬНЫЕ ПЕРЕМЕННЫЕ (GVL_MEM.Memory, GVL_CPU.*, GVL_CPM.*, GVL_IO.*)
    # в схему НЕ ПОПАДАЛИ, и любая ссылка на них разрешалась в UNK. А
    # incompatible(UNK, ...) всегда True - значит все связи через GVL молча
    # пропускались. Ровно там и жила ошибка C32 'BYTE' -> 'BOOL': Memory -
    # это ARRAY OF BYTE, её биты/значения уходят в BOOL-входы. Теперь таблица
    # глобалов накладывается ПЕРВОЙ, локальные переменные POU - поверх неё.
    env = dict(env_all)
    for v in p.inputs + p.outputs + p.locals:
        env[v.name.upper()] = v.type
    items = []
    for net in p.networks:
        for it in net._items:
            items.append((net, it))
    by_id = dict([(it[1], it) for _, it in items])

    def out_type(it, pin=None, depth=0):
        if it is None or depth > 12:
            return UNK
        k = it[0]
        if k == u"invar":
            return resolve(it[2], env, structs, ifaces)
        if k == u"outvar":
            return out_type(by_id.get(it[3].eid), None, depth + 1)
        _, _id, tname, ins, outs, _x, _y = it
        return resolve_std_out(tname, ins, pin, depth)

    def resolve_std_out(tname, ins, pin, depth):
        b = tname.upper()
        m = CONV.match(b)
        if m:
            return T(u"el", m.group(2))
        if b in (u"EQ", u"NE", u"LT", u"GT", u"LE", u"GE"):
            return BOOL
        if b in (u"NOT", u"AND", u"OR", u"XOR", u"SHL", u"SHR", u"ROL", u"ROR"):
            src = dict(ins).get(u"IN1") or dict(ins).get(u"IN")
            return out_type(by_id.get(src.eid), None, depth + 1) if src else UNK
        if b == u"SEL":
            src = dict(ins).get(u"IN0")
            return out_type(by_id.get(src.eid), None, depth + 1) if src else UNK
        if b in (u"ADD", u"SUB", u"MUL", u"DIV", u"MOD", u"LIMIT", u"MAX", u"MIN"):
            src = dict(ins).get(u"IN1") or dict(ins).get(u"IN")
            return out_type(by_id.get(src.eid), None, depth + 1) if src else UNK
        if b == u"MOVE":
            src = dict(ins).get(u"IN")
            return out_type(by_id.get(src.eid), None, depth + 1) if src else UNK
        # пользовательский FB: тип ИМЕННО ЭТОГО вывода из интерфейса
        ifc = ifaces.get(b)
        if ifc is not None:
            outs_map = dict([(k.upper(), v) for k, v in ifc[1].items()])
            if pin and pin.upper() in outs_map:
                return parse_type(outs_map[pin.upper()], structs)
            if len(outs_map) == 1:
                return parse_type(list(outs_map.values())[0], structs)
        return UNK

    for net, it in items:
        if it[0] == u"invar":
            continue
        if it[0] == u"outvar":
            if re.match(u"^-?\\d+$", unicode(it[2]).strip()):
                report(p.name, u"C18 приёмник-литерал", u"localId=%d" % it[1], it[2])
                continue
            tgt = resolve(it[2], env, structs, ifaces)
            src_it = by_id.get(it[3].eid)
            st = out_type(src_it, it[3].pin)
            if not compatible(st, tgt.name if tgt.kind == u"el" else u"?"):
                report(p.name, u"C32 приёмник %s <- %s" % (tgt, st),
                       u"localId=%d" % it[1], it[2])
            continue
        # блок
        _, lid, tname, ins, outs, _x, _y = it
        b = tname.upper()
        if b.startswith(u"FB_") and b in ifaces and not p._inst.get(lid):
            report(p.name, u"C80 вызов FB без экземпляра", u"localId=%d" % lid, tname)
        pins = std_pins(b)
        if pins is None:
            ifc = ifaces.get(b)
            if ifc is None:
                # ТИП БЛОКА НЕИЗВЕСТЕН -> вся сеть этого блока не проверяется.
                # Раньше здесь стоял молчаливый continue, и такая «слепая зона»
                # никак себя не проявляла.
                UNKNOWN_BLOCKS[tname] += 1
                STATS[u"блок_неизвестного_типа"] += 1
                continue
            if not ins:
                report(p.name, u"C0 блок без входов", u"localId=%d" % lid, tname)
                continue
            pins = dict([(k.upper(), v) for k, v in ifc[0].items()])
        for pin, src in ins:
            if not pin:
                continue
            exp = pins.get(pin.upper())
            if exp is None:
                UNKNOWN_PINS[u"%s|%s|%s.%s" % (p.name, it[0], tname, pin)] += 1
                STATS[u"pin_нет_в_интерфейсе"] += 1
                continue
            src_it = by_id.get(src.eid)
            at = out_type(src_it, src.pin)
            STATS[u"проверено_входов"] += 1
            if at is None or at.kind == u"unk":
                STATS[u"источник_UNK"] += 1
                # ГЛАВНЫЙ КАНДИДАТ НА C32 'BYTE' -> 'BOOL': источник НЕ
                # РАЗРЕШИЛСЯ, а приёмник - BOOL. Именно такие связи проверка
                # молча пропускает, и именно так выглядит ненайденная ошибка
                # этапа 4. Печатаем выражение источника, чтобы его можно было
                # разобрать руками.
                if exp.upper() == u"BOOL":
                    _ex = (u"%s" % src_it[2]) if (src_it and src_it[0] == u"invar") \
                        else u"<%s>" % (tname,)
                    UNK_BOOL[u"%s | %s | %s.%s <- %s"
                             % (p.name, it[0], tname, pin, _ex)] += 1
            if not compatible(at, exp.upper()):
                ex = (u"%s" % src_it[2]) if src_it and src_it[0] == u"invar" else u"<блок>"
                report(p.name, u"C32 вход %s.%s: %s -> %s" % (tname, pin, at, exp),
                       u"localId=%d" % lid, ex)

        # ---- СОГЛАСОВАННОСТЬ ОПЕРАНДОВ СТАНДАРТНОГО БЛОКА (этап A5) ----
        # ЗАЧЕМ. std_pins() для SEL/ADD/... возвращает ANY, а compatible(_, ANY)
        # всегда истинна - то есть СООТНОШЕНИЕ ТИПОВ МЕЖДУ ВХОДАМИ не
        # проверялось ВООБЩЕ. Между тем CODESYS требует, чтобы операнды были
        # одного типа, и при расхождении выдаёт ровно C32. Самый вероятный
        # источник сообщения "Невозможно конвертировать тип 'BYTE' в тип 'BOOL'" -
        # это SEL, у которого IN0 имеет тип BOOL (тип выхода SEL берётся именно
        # с IN0), а IN1 - BYTE.
        _bin = {u"SEL": (u"IN0", u"IN1"),
                # AND/OR/XOR ДОБАВЛЕНЫ на этапе A5. Причина: в IEC BOOL НЕ входит
                # в ANY_BIT (ANY_BIT = BYTE/WORD/DWORD/LWORD). Поэтому смешение
                # BOOL и BYTE в одном AND - это НЕ безобидное совпадение типов,
                # а необходимость преобразования, и CODESYS выдаёт ровно
                # "C32: Невозможно конвертировать тип 'BYTE' в тип 'BOOL'".
                # Прежняя проверка этого не видела: std_pins() для AND/OR/XOR
                # объявляет входы как 'BIT', а BOOL и BYTE одинаково ей подходят.
                # Хуже того, тип ВЫХОДА здесь вычисляется как тип IN1, поэтому
                # AND(BOOL, BYTE) считался BOOL - и связь молча проходила.
                u"AND": (u"IN1", u"IN2"), u"OR": (u"IN1", u"IN2"),
                u"XOR": (u"IN1", u"IN2"),
                u"ADD": (u"IN1", u"IN2"), u"SUB": (u"IN1", u"IN2"),
                u"MUL": (u"IN1", u"IN2"), u"DIV": (u"IN1", u"IN2"),
                u"MOD": (u"IN1", u"IN2"), u"MAX": (u"IN1", u"IN2"),
                u"MIN": (u"IN1", u"IN2"), u"LIMIT": (u"MN", u"IN", u"MX"),
                u"EQ": (u"IN1", u"IN2"), u"NE": (u"IN1", u"IN2"),
                u"LT": (u"IN1", u"IN2"), u"GT": (u"IN1", u"IN2"),
                u"LE": (u"IN1", u"IN2"), u"GE": (u"IN1", u"IN2")}
        _pins_ops = _bin.get(b)
        if _pins_ops:
            _srcs = dict(ins)
            _ts = []
            for _p in _pins_ops:
                _s = _srcs.get(_p)
                if _s is None:
                    continue
                _t = out_type(by_id.get(_s.eid), _s.pin)
                if _t is not None and _t.kind == u"el":
                    _ts.append((_p, _t.name))
            _nm = set([x[1] for x in _ts])
            if len(_nm) > 1:
                # УТОЧНЕНИЕ (проверено компилятором): IEC допускает СМЕШЕНИЕ
                # РАЗМЕРОВ в арифметике и сравнении - WORD+BYTE, GE(INT,WORD),
                # SEL(0, BYTE) и т. п. компилируются БЕЗ ошибок (проект
                # собирается с 0 ошибок). Ошибкой является только смешение
                # BOOL с числовым типом (и наоборот): BOOL не входит в ANY_BIT
                # и не приводится к числам неявно.
                # Поэтому срабатывание засчитывается ТОЛЬКО при наличии BOOL
                # рядом с числовым типом. Иначе проверка давала 7 ложных
                # срабатываний на вполне корректных схемах.
                if u"BOOL" in _nm and len(_nm - set([u"BOOL"])) > 0:
                    STATS[u"несогласованные_операнды"] += 1
                    report(p.name,
                           u"C32 операнды %s: %s"
                           % (tname, u", ".join([u"%s=%s" % (a, c2) for a, c2 in _ts])),
                           u"localId=%d" % lid,
                           u", ".join([u"%s<-%s" % (a, (by_id.get(_srcs[a].eid) or [u"?", u"?", u"?"])[2])
                                       for a, _ in _ts if a in _srcs]))


def main():
    structs = parse_duts()
    ifaces = collect_fb_interfaces()
    env_all = {}
    for nm, text in GVL_TEXTS:
        for k, v in parse_decl(text, structs).items():
            env_all[k] = v

    # КВАЛИФИКАЦИЯ ПО ИМЕНИ GVL (найдено на этапе A5). В схемах есть записи
    # вида GVL_CPM.CPM_WE, GVL_HMI.Btn_Reset, GVL_IO.Tact_Busy, GVL_IO_Map.*.
    # ИМЯ GVL - это не переменная, поэтому resolve() упирался в UNK, и все такие
    # связи (20 из 26 кандидатов в C32) не проверялись вообще. Регистрируем
    # каждый GVL как СТРУКТУРУ с полями: тогда разбор «имя.поле» идёт тем же
    # кодом, что и для DUT, и тип поля виден.
    for nm, text in GVL_TEXTS:
        structs[nm.upper()] = parse_decl(text, structs)
        env_all[nm.upper()] = T(u"st", nm, st=nm.upper())

    errs = []

    def report(pou, kind, where, expr):
        errs.append((pou, kind, where, expr))

    for grp, makers in GROUPS:
        for mk in makers:
            check_pou(mk(), env_all, structs, ifaces, report)

    # ЗАВИСИМОСТИ ЯДРА ПРОВЕРЯЮТСЯ ТОЖЕ (найдено на этапе A5). Раньше 27
    # зависимостей использовались только как справочник типов входов/выходов, а
    # ИХ СОБСТВЕННЫЕ СЕТИ не проверялись вообще - то есть FB_ALU8, FB_Memory64K,
    # FB_Mux8x8/16, FB_CtrlUnit, FB_Reg8/16 были вне проверки. Именно в них
    # выполнялось переименование R->Rx, S->Sx, LD->LDx, и именно там могла
    # остаться связь BYTE -> BOOL.
    try:
        import pou_deps
        for nm in pou_deps.all_names():
            p = pou_deps.make(nm)
            if p is None:
                continue
            check_pou(p, env_all, structs, ifaces, report)
    except Exception as e:
        print(u"НЕ УДАЛОСЬ проверить pou_deps: %r" % (e,))

    out = io.open(WORK + u"/check_types.txt", u"w", encoding=u"utf-8")
    cnt = collections.Counter([e[1].split(u" ")[0] for e in errs])
    out.write(u"ВСЕГО подозрительных мест: %d\n" % len(errs))
    out.write(u"по классам: %s\n\n" % cnt.most_common())
    bypou = collections.Counter([e[0] for e in errs])
    out.write(u"по POU: %s\n\n" % bypou.most_common())
    for e in errs:
        out.write(u"%-22s %-58s %-16s %s\n" % (e[0], e[1], e[2], e[3]))
    out.close()
    print(u"ВСЕГО: %d" % len(errs))
    print(u"классы: %s" % cnt.most_common())
    print(u"POU: %s" % bypou.most_common())
    print(u"ОХВАТ: %s" % STATS.most_common())
    print(u"СЛЕПЫЕ ЗОНЫ - блоки неизвестного типа: %s" % UNKNOWN_BLOCKS.most_common(40))
    print(u"СЛЕПЫЕ ЗОНЫ - пины не из интерфейса: %s" % UNKNOWN_PINS.most_common(40))
    print(u"КАНДИДАТЫ C32 (источник UNK -> приёмник BOOL): %d" % len(UNK_BOOL))
    for k in list(UNK_BOOL.most_common(60)):
        print(u"    %s  x%d" % (k[0], k[1]))


main()
