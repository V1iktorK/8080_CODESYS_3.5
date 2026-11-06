# -*- coding: utf-8 -*-
u"""Единый источник ВСЕХ зависимостей ядра (этап A3/A4 - устранение рассинхрона имён).

Зачем этот модуль. Раньше зависимости брались из СНИМКА C:\\dsh8080\\work\\dep_ccp,
сделанного прошлыми сборками, а POU этапа 4 генерировались заново. Два разных
источника означали, что определения могли отставать от потребителей - отсюда
C0046 'FB_Reg16 не задан' и рассинхрон имён R/Rx, S/Sx, Sel/SELx.

Теперь ВСЕ зависимости порождаются из своих первоисточников:
  * gen_core.py   - FB_Reg8, FB_Reg16, FB_UnpackByte, FB_PackByte, FB_FullAdder
  * gen_alu.py    - FB_ALU8, FB_Mux8x8, FB_Mux8x16, FB_Memory64K
  * pou_decode.py - FB_CtrlUnit
  * pou_extra.py, pou_decode_full.py - остальные (у них есть список ALL)

Модули gen_core.py и gen_alu.py импортируют scriptengine и ПРИ ИМПОРТЕ выполняют
сборку проекта (побочный код в конце файла), поэтому целиком их импортировать
нельзя - на этапе генерации схем scriptengine недоступен. Здесь их исходники
ИСПОЛНЯЮТСЯ ТОЛЬКО ДО определения последней нужной функции: берём текст модуля,
обрезаем по маркеру начала побочного кода и выполняем в отдельном пространстве имён.
"""

import io
import os
import sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
if BASE not in sys.path:
    sys.path.insert(0, BASE)

import fbd_xml
from fbd_xml import Pou

import pou_extra
import pou_decode_full


def _load_prefix(filename, stop_marker):
    u"""Выполнить исходник модуля ДО строки с маркером побочного кода.

    Возвращает пространство имён с определениями функций.
    """
    path = os.path.join(BASE, filename)
    # Явная кодировка UTF-8: исходники содержат русские комментарии, а IronPython
    # и CPython под Windows по умолчанию берут cp1251 и падают на декодировании.
    f = io.open(path, u"r", encoding=u"utf-8")
    text = f.read()
    f.close()
    idx = text.find(stop_marker)
    if idx < 0:
        raise RuntimeError(u"%s: маркер %r не найден" % (filename, stop_marker))
    head = text[:idx]
    # Выкидываем строки, зависящие от scriptengine и codesys_build: они нужны
    # только побочному коду (сборке проекта), а нам требуются лишь определения
    # функций-построителей.
    keep = []
    for line in head.split(u"\n"):
        s = line.strip()
        if s.startswith(u"import scriptengine"):
            continue
        if s.startswith(u"import codesys_build"):
            continue
        if s.startswith(u"ROOT = cb.") or s.startswith(u"BASE = cb.") or s.startswith(u"L = cb."):
            continue
        # строки, использующие логгер L(...) - они относятся к побочной сборке
        if s.startswith(u"L(u") or s.startswith(u"L("):
            continue
        keep.append(line)
    head = u"\n".join(keep)
    ns = {
        u"__name__": u"_deps_" + filename.replace(u".py", u""),
        u"__file__": path,
        u"os": os,
        u"sys": sys,
        u"io": io,
        u"fbd_xml": fbd_xml,
        u"Pou": Pou,
    }
    exec(compile(head, path, u"exec"), ns)
    return ns


_gen_core = _load_prefix(u"gen_core.py", u"POUS = [make_fb_reg8()")
_gen_alu = _load_prefix(u"gen_alu.py", u"POUS = [make_decode_regsel()")
_pou_decode = _load_prefix(u"pou_decode.py", u"# ====") if False else None

# pou_decode.py вообще не имеет побочного кода - его можно импортировать целиком
import pou_decode


# Имя POU -> функция-построитель из первоисточника
BUILDERS = {
    # gen_core.py - базовые элементы
    u"FB_Reg8": _gen_core[u"make_fb_reg8"],
    u"FB_Reg16": _gen_core[u"make_fb_reg16"],
    u"FB_UnpackByte": _gen_core[u"make_fb_unpack"],
    u"FB_PackByte": _gen_core[u"make_fb_pack"],
    u"FB_FullAdder": _gen_core[u"make_fb_adder"],
    # gen_alu.py - АЛУ, коммутация, память
    u"FB_ALU8": _gen_alu[u"make_alu8"],
    u"FB_Mux8x8": _gen_alu[u"make_mux8x8"],
    u"FB_Mux8x16": _gen_alu[u"make_mux8x16"],
    u"FB_Memory64K": _gen_alu[u"make_memory"],
    # pou_decode.py - блок управления
    u"FB_CtrlUnit": pou_decode.make_ctrl_unit,
}

# Модули с готовым списком ALL
for _mod in (pou_extra, pou_decode_full):
    for _mk in _mod.ALL:
        _p = _mk()
        BUILDERS[_p.name] = _mk


def all_names():
    u"""Имена всех POU, которые может выдать этот модуль."""
    return sorted(BUILDERS.keys())


def make(name):
    u"""Создать POU по имени. Возвращает объект Pou или None."""
    fn = BUILDERS.get(name)
    if fn is None:
        return None
    return fn()
