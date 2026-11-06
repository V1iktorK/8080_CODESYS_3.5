# -*- coding: utf-8 -*-
u"""Генератор PLCopenXML для FBD-схем CODESYS 3.5 SP17.

ЭТО БИБЛИОТЕКА, её импортируют скрипты-сборщики (запускаются внутри CODESYS).

Правила диалекта — всё выяснено экспериментально, каждое правило оплачено
отладочным циклом (см. docs/03_ЖУРНАЛ_СБОРКИ.md):

  1. Тело FBD:  <body><FBD> ...элементы... </FBD></body>
     БЕЗ обёртки <network>. Сети в плоском списке разделяются только связями.

  2. localId должны быть УНИКАЛЬНЫ внутри всего POU, а не внутри сети.
     Иначе <connection refLocalId=N> попадает на чужой элемент и связи
     молча теряются (проверено: из 4 входов выживал 1).

  3. Порядок детей <block> строгий:
        position -> inputVariables -> inOutVariables -> outputVariables
     <inOutVariables/> ОБЯЗАТЕЛЕН, даже пустой. Иначе импорт падает:
     "Элемент block имеет недопустимый дочерний элемент outputVariables".

  4. <interface> НЕ МОЖЕТ быть пустым. Если объявить переменные только текстом
     в addData/InterfaceAsPlainText, CODESYS импорт "выполняет" без ошибки,
     но POU в проекте не появляется. Нужны и структурный <interface>,
     и текстовый дубль.

  5. Связь:  <connectionPointIn><connection refLocalId="N" /></connectionPointIn>
     formalParameter можно не указывать — CODESYS сопоставляет по позиции.
     Для блоков с несколькими выводами имя вывода обязательно.

  6. Координаты x/y CODESYS при импорте игнорирует и раскладывает схему сам
     (в экспорте все позиции обнуляются). Мы их всё равно задаём — XML
     остаётся читаемым и переносимым в другие инструменты.

Стиль схемы: сигналы строго слева направо. Колонки 40 / 200 / 360 / 520,
шаг по вертикали 30 px.
"""

import io

XHTML = u'http://www.w3.org/1999/xhtml'
NS_PLAINTEXT = u'http://www.3s-software.com/plcopenxml/interfaceasplaintext'

COL_IN = 40        # колонка входных переменных
COL_BLK = 200      # колонка блоков
COL_BLK2 = 360     # колонка вторых блоков (каскады)
COL_OUT = 520      # колонка выходных переменных
ROW_H = 30         # шаг по вертикали
ROW0 = 40          # первая строка

ELEMENTARY = (u"BOOL", u"BYTE", u"WORD", u"DWORD", u"SINT", u"USINT", u"INT",
              u"UINT", u"DINT", u"UDINT", u"LINT", u"ULINT", u"REAL", u"LREAL",
              u"TIME", u"STRING", u"WSTRING")


def esc(s):
    u"""Экранирование XML."""
    return (unicode(s).replace(u"&", u"&amp;").replace(u"<", u"&lt;")
            .replace(u">", u"&gt;").replace(u'"', u"&quot;"))


def type_xml(type_text):
    u"""IEC-тип -> XML-описание типа для PLCopenXML."""
    t = type_text.strip().upper()
    if t.startswith(u"ARRAY[") and u" OF " in t:
        rng, base = t[6:].split(u"] OF ", 1)
        lo, hi = rng.split(u"..")
        return (u'<array><dimension lower="%s" upper="%s" />'
                u'<baseType>%s</baseType></array>' % (lo.strip(), hi.strip(), type_xml(base)))
    if t in ELEMENTARY:
        return u'<%s />' % t
    return u'<derived name="%s" />' % esc(type_text.strip())


class Var(object):
    u"""Объявляемая переменная: имя, IEC-тип, необязательный комментарий."""
    __slots__ = (u"name", u"type", u"comment")

    def __init__(self, name, type_text, comment=None):
        self.name = name
        self.type = type_text
        self.comment = comment

    def plain(self):
        if self.comment:
            return u'\t%s : %s; (* %s *)' % (self.name, self.type, self.comment)
        return u'\t%s : %s;' % (self.name, self.type)

    def xml(self):
        return (u'            <variable name="%s"><type>%s</type></variable>'
                % (esc(self.name), type_xml(self.type)))


class Src(object):
    u"""Ссылка на выход элемента схемы: localId + (необязательно) имя вывода."""
    __slots__ = (u"eid", u"pin")

    def __init__(self, eid, pin=None):
        self.eid = eid
        self.pin = pin


class BlockRef(Src):
    u"""Ссылка на блок. Для блока с несколькими выводами имя вывода обязательно,
    поэтому берём его через .out(u"Sum")."""

    def __init__(self, eid, pins):
        Src.__init__(self, eid, pins[0] if len(pins) > 1 else None)
        self.pins = pins

    def out(self, pin):
        return Src(self.eid, pin)


class Network(object):
    u"""Одна сеть FBD.

    Номера элементов берутся у POU-владельца (сквозная нумерация, см. п.2 выше).
    """

    def __init__(self, number, title=u"", owner=None):
        self.number = number
        self.title = title
        self._owner = owner
        self._items = []
        self._auto_y = ROW0

    def _nid(self):
        return self._owner._nid()

    def _y(self, y):
        if y is not None:
            return y
        v = self._auto_y
        self._auto_y += ROW_H
        return v

    # ---------- элементы ----------
    def invar(self, expr, x=COL_IN, y=None):
        u"""Входная переменная (источник сигнала)."""
        i = self._nid()
        self._items.append((u"invar", i, expr, x, self._y(y)))
        return Src(i)

    def const(self, literal, x=COL_IN, y=None):
        u"""Константа — тоже inputVariable, но с литералом вместо имени."""
        return self.invar(literal, x, y)

    def outvar(self, expr, src, x=COL_OUT, y=None):
        u"""Выходная переменная (приёмник)."""
        i = self._nid()
        self._items.append((u"outvar", i, expr, _src(src), x, self._y(y)))
        return Src(i)

    def block(self, type_name, inputs, outputs, x=COL_BLK, y=None, instance=None):
        u"""Блок. inputs — [(pin, Src)]. outputs — [имя вывода].

        instance — имя экземпляра для вызова пользовательского FB
        (при этом сам экземпляр должен быть объявлен в VAR POU).

        Возвращает BlockRef. Для блока с несколькими выводами имя вывода
        берётся через .out(u"Sum").
        """
        i = self._nid()
        yv = self._y(y)
        self._items.append((u"block", i, type_name, inputs, outputs, x, yv))
        if instance:
            self._owner._inst[i] = instance
        return BlockRef(i, outputs)

    def render(self):
        out = []
        if self.title:
            out.append(u'            <!-- %s -->' % esc(self.title))
        for it in self._items:
            kind = it[0]
            if kind == u"invar":
                _, i, expr, x, y = it
                w = 20 + 9 * len(unicode(expr))
                out.append(u'            <inVariable localId="%d" height="10" width="%d">' % (i, w))
                out.append(u'              <position x="%d" y="%d" />' % (x, y))
                out.append(u'              <connectionPointOut><relPosition x="%d" y="5" /></connectionPointOut>' % w)
                out.append(u'              <expression>%s</expression>' % esc(expr))
                out.append(u'            </inVariable>')
            elif kind == u"outvar":
                _, i, expr, src, x, y = it
                w = 20 + 9 * len(unicode(expr))
                out.append(u'            <outVariable localId="%d" height="10" width="%d">' % (i, w))
                out.append(u'              <position x="%d" y="%d" />' % (x, y))
                out.append(u'              <connectionPointIn>')
                out.append(u'                <relPosition x="0" y="5" />')
                out.append(_conn(src, indent=u'                '))
                out.append(u'              </connectionPointIn>')
                out.append(u'              <expression>%s</expression>' % esc(expr))
                out.append(u'            </outVariable>')
            else:
                _, i, tname, inputs, outputs, x, y = it
                w = 40 + 12 * max(len(inputs), len(outputs))
                inst = self._owner._inst.get(i)
                inst_attr = u' instanceName="%s"' % esc(inst) if inst else u''
                out.append(u'            <block localId="%d" typeName="%s"%s height="%d" width="%d">'
                           % (i, esc(tname), inst_attr, 10 + 10 * max(len(inputs), 1), w))
                out.append(u'              <position x="%d" y="%d" />' % (x, y))
                out.append(u'              <inputVariables>')
                for k, (pin, src) in enumerate(inputs):
                    if pin:
                        out.append(u'                <variable formalParameter="%s">' % esc(pin))
                    else:
                        out.append(u'                <variable>')
                    out.append(u'                  <connectionPointIn>')
                    out.append(u'                    <relPosition x="0" y="%d" />' % (5 + 10 * k))
                    out.append(_conn(src, indent=u'                    '))
                    out.append(u'                  </connectionPointIn>')
                    out.append(u'                </variable>')
                out.append(u'              </inputVariables>')
                out.append(u'              <inOutVariables />')
                out.append(u'              <outputVariables>')
                for k, pin in enumerate(outputs):
                    out.append(u'                <variable formalParameter="%s">' % esc(pin))
                    out.append(u'                  <connectionPointOut>')
                    out.append(u'                    <relPosition x="%d" y="%d" />' % (w, 5 + 10 * k))
                    out.append(u'                  </connectionPointOut>')
                    out.append(u'                </variable>')
                out.append(u'              </outputVariables>')
                out.append(u'            </block>')
        return u"\n".join(out)


def _src(src):
    if isinstance(src, Src):
        return src
    return Src(int(src))


def _conn(src, indent=u'                  '):
    src = _src(src)
    if src.pin:
        return (u'%s<connection refLocalId="%d" formalParameter="%s" />'
                % (indent, src.eid, esc(src.pin)))
    return u'%s<connection refLocalId="%d" />' % (indent, src.eid)


class Pou(object):
    u"""POU с телом FBD: структурный <interface> + текстовый дубль объявления.

    name        — имя (IEC-идентификатор)
    pou_type    — 'functionBlock' | 'function' | 'program'
    doc         — текст в шапке объявления (комментарий (* ... *))
    """

    def __init__(self, name, pou_type=u"functionBlock", doc=u""):
        self.name = name
        self.pou_type = pou_type
        self.doc = doc
        self.inputs = []
        self.outputs = []
        self.locals = []
        self.networks = []
        self._next = 0
        self._inst = {}        # localId -> имя экземпляра FB (для вызовов FB)

    # ---------- объявления ----------
    def var_in(self, name, type_text, comment=None):
        self.inputs.append(Var(name, type_text, comment))
        return name

    def var_out(self, name, type_text, comment=None):
        self.outputs.append(Var(name, type_text, comment))
        return name

    def var(self, name, type_text, comment=None):
        self.locals.append(Var(name, type_text, comment))
        return name

    # ---------- схема ----------
    def _nid(self):
        self._next += 1
        return self._next

    def network(self, title=u""):
        n = Network(len(self.networks) + 1, title, owner=self)
        self.networks.append(n)
        return n

    # ---------- отрисовка ----------
    def _prune_outputs(self):
        u"""Оставить в вызове каждого FB ТОЛЬКО те выводы, которые ЧИТАЮТСЯ.

        ЗАЧЕМ (найдено на этапе A5 - это была ПОСЛЕДНЯЯ ошибка компиляции
        проекта, стоившая многих часов поиска). Импортёр PLCopenXML сопоставляет
        выводы вызова с объявлением ПОЗИЦИОННО. Если вызов объявляет шесть
        выводов [R, CY, AC, S, Z, P], а читает только три - S, Z, P, - то
        позиционно они попадают на ПЕРВЫЕ ТРИ, то есть:
            daa_s (BOOL) <- Rx (BYTE)  ->  C32 'BYTE' -> 'BOOL'
        Компилятор сообщал ровно одну ошибку, и загрузка была невозможна.

        Почему дефект не проявлялся больше нигде: ВСЕ остальные вызовы FB в
        проекте читают ВСЕ свои выводы и в порядке объявления (FB_UnpackByte
        B0..B7, FB_PackByte B, FB_FullAdder Sum/Cout, FB_Rotate8 R/CY_Out,
        FB_DAA R/AC_Out/CY_Out, FB_UnpackWord Lo/Hi). Достаточно было одного
        вызова с ПОДМНОЖЕСТВОМ выводов, чтобы проект не собирался.

        ПРАВИЛО: объявлять ровно те выводы, которые читаются, и в том порядке,
        в котором они читаются - тогда и позиционное, и именованное
        сопоставление дают верный результат.

        Проверка этого правила без CODESYS: tools/check_outpins.py.
        """
        items = []
        for net in self.networks:
            items.extend(net._items)
        used = {}
        for it in items:
            if it[0] == u"outvar":
                srcs = [_src(it[3])]
            elif it[0] == u"block":
                srcs = [_src(s) for _, s in it[3]]
            else:
                continue
            for s in srcs:
                if not s.pin:
                    continue
                lst = used.setdefault(s.eid, [])
                if s.pin not in lst:
                    lst.append(s.pin)
        for net in self.networks:
            for k, it in enumerate(net._items):
                if it[0] != u"block":
                    continue
                got = used.get(it[1])
                if not got:
                    continue
                declared = list(it[4])
                if got == declared:
                    continue
                net._items[k] = (it[0], it[1], it[2], it[3], got, it[5], it[6])

    def _expand_fanout(self):
        u"""Развернуть граф схемы в дерево: у каждого выхода — ровно одна связь.

        Причина: CODESYS 3.5 SP17 МОЛЧА выбрасывает POU целиком, если любой выход
        (входная переменная ИЛИ выход блока) питает более одного входа.
        Проверено бисекцией: POU с fan-out теряется, межсетевые ссылки работают.

        Важно: счёт ведётся по паре (элемент, ИМЯ ВЫВОДА) — разные выводы одного
        блока это разные источники. И считается ПО ВСЕМУ POU, а не по сети:
        ссылки между сетями легальны и как раз они и создают fan-out.

        Для каждого лишнего использования создаётся копия элемента вместе со всей
        его входной ветвью, и вставляется непосредственно перед потребителем —
        ссылка всегда идёт «назад», как требует импортёр.

        Вызов пользовательского FB размножать нельзя (экземпляр один) — это
        ошибка проектирования схемы: сигнал надо провести через переменную POU.
        """
        all_items = []
        for net in self.networks:
            all_items.extend(net._items)
        by_id = dict([(it[1], it) for it in all_items])

        def sources(it):
            if it[0] == u"invar":
                return []
            if it[0] == u"outvar":
                return [_src(it[3])]
            return [_src(s) for _, s in it[3]]

        uses = {}
        for it in all_items:
            for s in sources(it):
                k = (s.eid, s.pin)
                uses[k] = uses.get(k, 0) + 1
        if not uses or max(uses.values()) <= 1:
            return

        taken = {}
        pending = []

        def clone(it):
            if it[0] == u"invar":
                cand = (u"invar", self._nid(), it[2], it[3], it[4] + 12)
            else:
                inst = self._inst.get(it[1])
                if inst:
                    raise ValueError(
                        u"Выход вызова FB %s (экземпляр %s) разветвляется на несколько "
                        u"входов, а экземпляр один. Проведите сигнал через переменную POU."
                        % (it[2], inst))
                ins = [(pin, alloc(s)) for pin, s in it[3]]
                cand = (u"block", self._nid(), it[2], ins, it[4], it[5], it[6] + 10)
            by_id[cand[1]] = cand
            pending.append(cand)
            return cand

        def alloc(s):
            s = _src(s)
            key = (s.eid, s.pin)
            k = taken.get(key, 0)
            taken[key] = k + 1
            it = by_id.get(s.eid)
            if it is None or k == 0:
                return Src(s.eid, s.pin)
            new = clone(it)
            return Src(new[1], s.pin)

        for net in self.networks:
            final = []
            for it in net._items:
                if it[0] == u"invar":
                    final.append(it)
                    continue
                if it[0] == u"outvar":
                    built = (u"outvar", it[1], it[2], alloc(it[3]), it[4], it[5])
                else:
                    built = (u"block", it[1], it[2],
                             [(pin, alloc(s)) for pin, s in it[3]], it[4], it[5], it[6])
                if pending:
                    final.extend(pending)
                    pending = []
                final.append(built)
            if pending:
                final.extend(pending)
                pending = []
            net._items = final

    def declaration(self):
        u"""Текстовое объявление (то же, что уходит в InterfaceAsPlainText)."""
        head = {u"functionBlock": u"FUNCTION_BLOCK",
                u"function": u"FUNCTION",
                u"program": u"PROGRAM"}[self.pou_type]
        parts = [u"%s %s" % (head, self.name)]
        if self.doc:
            parts.append(u"(* %s *)" % self.doc)
        for title, vars_ in ((u"VAR_INPUT", self.inputs),
                             (u"VAR_OUTPUT", self.outputs),
                             (u"VAR", self.locals)):
            if not vars_:
                continue
            parts.append(title)
            for v in vars_:
                parts.append(v.plain())
            parts.append(u"END_VAR")
        parts.append(u"")
        return u"\n".join(parts)

    def interface_xml(self):
        if not (self.inputs or self.outputs or self.locals):
            raise ValueError(u"POU %s: пустой <interface> — CODESYS молча пропустит объект" % self.name)
        out = [u'        <interface>']
        for tag, vars_ in ((u"inputVars", self.inputs),
                           (u"outputVars", self.outputs),
                           (u"localVars", self.locals)):
            if not vars_:
                continue
            out.append(u'          <%s>' % tag)
            for v in vars_:
                out.append(v.xml())
            out.append(u'          </%s>' % tag)
        out.append(u'        </interface>')
        return u"\n".join(out)

    def render(self):
        self._prune_outputs()
        self._expand_fanout()
        body = u"\n".join([n.render() for n in self.networks])
        return u"""      <pou name="%(name)s" pouType="%(type)s">
%(iface)s
        <body>
          <FBD>
%(body)s
          </FBD>
        </body>
        <addData>
          <data name="%(ns)s" handleUnknown="implementation">
            <InterfaceAsPlainText>
              <xhtml xmlns="%(xhtml)s">%(decl)s</xhtml>
            </InterfaceAsPlainText>
          </data>
        </addData>
      </pou>""" % {
            u"name": esc(self.name),
            u"type": esc(self.pou_type),
            u"iface": self.interface_xml(),
            u"body": body,
            u"ns": NS_PLAINTEXT,
            u"xhtml": XHTML,
            u"decl": esc(self.declaration()),
        }


HEADER = u"""<?xml version="1.0" encoding="utf-8"?>
<project xmlns="http://www.plcopen.org/xml/tc6_0200">
  <fileHeader companyName="" productName="CODESYS" productVersion="CODESYS V3.5 SP17 Patch 3" creationDateTime="2026-01-01T00:00:00" />
  <contentHeader name="%(content)s">
    <coordinateInfo>
      <fbd><scaling x="1" y="1" /></fbd>
      <ld><scaling x="1" y="1" /></ld>
      <sfc><scaling x="1" y="1" /></sfc>
    </coordinateInfo>
  </contentHeader>
  <types>
    <dataTypes />
    <pous>
"""

FOOTER = u"""    </pous>
  </types>
  <instances>
    <configurations />
  </instances>
</project>
"""


def write_project(path, pous, content_name=u"EMU8080"):
    u"""Записать PLCopenXML со списком POU (тело FBD). Возвращает длину текста."""
    parts = [HEADER % {u"content": esc(content_name)}]
    for p in pous:
        parts.append(p.render())
        parts.append(u"\n")
    parts.append(FOOTER)
    text = u"".join(parts)
    f = io.open(path, "w", encoding="utf-8")
    f.write(text)
    f.close()
    return len(text)


def count_elements(path):
    u"""Статистика XML: (блоков, входных перем., выходных перем., связей, пустых входов)."""
    t = io.open(path, "r", encoding="utf-8").read()
    return (t.count(u"<block "), t.count(u"<inVariable "), t.count(u"<outVariable "),
            t.count(u"<connection "), t.count(u"<connectionPointIn />"))
