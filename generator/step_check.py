# -*- coding: utf-8 -*-
u"""Минимальная проверка конвейера: пишем метки по шагам и смотрим, где встанет."""
import os, sys, io, traceback

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import codesys_build as cb

L = cb.make_log(u"step_check.log")
ROOT = cb.ROOT
L(u"[1] старт, python %s" % sys.version)
L(u"[2] BASE=%s" % BASE)
L(u"[3] ROOT=%s" % ROOT)

import fbd_xml
L(u"[4] fbd_xml импортирован")

import scriptengine
L(u"[5] scriptengine импортирован")

p = fbd_xml.Pou(u"T_TINY", u"functionBlock", doc=u"крошечный тест")
p.var_in(u"A", u"BOOL"); p.var_out(u"Q", u"BOOL")
n = p.network(u"сеть 1")
a = n.invar(u"A")
n.outvar(u"Q", n.block(u"NOT", [(u"IN", a)], [u"OUT"]))
L(u"[6] POU собран")

txt = p.render()
L(u"[7] render OK, %d символов" % len(txt))

size = fbd_xml.write_project(ROOT + u"/src/tiny.plcopenxml", [p], u"tiny")
L(u"[8] файл записан, %d символов" % size)

try:
    proj, app = cb.new_project(ROOT + u"/build/tiny.project", L)
    app.import_xml(ROOT + u"/src/tiny.plcopenxml")
    L(u"[9] импорт выполнен")
    found = cb.find_deep(app, u"T_TINY")
    L(u"[10] поиск POU: %s" % (u"ЕСТЬ" if found is not None else u"НЕТ"))
    proj.save()
    cb.build(app, L)
    L(u"[11] сборка выполнена")
except Exception:
    L(u"[X] ОШИБКА:\n" + traceback.format_exc())

L(u"[12] КОНЕЦ")
L.close()
