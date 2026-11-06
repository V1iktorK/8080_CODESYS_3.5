# -*- coding: utf-8 -*-
u"""Пошаговая проверка: где именно встаёт сборка декодера."""
import os, sys

BASE = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
sys.path.insert(0, BASE)

import codesys_build as cb
L = cb.make_log(u"step_check2.log")
L(u"[1] старт, python %s" % sys.version)

import fbd_xml
L(u"[2] fbd_xml импортирован")

import scriptengine
L(u"[3] scriptengine импортирован")

import pou_decode
L(u"[4] pou_decode импортирован")

L(u"[5] собираю FB_FlagsReg")
p = pou_decode.make_flags_reg()
L(u"[6] FB_FlagsReg собран, сетей=%d" % len(p.networks))

L(u"[7] рендер")
txt = p.render()
L(u"[8] render ok, %d символов" % len(txt))

L(u"[9] ещё блоки")
for name in (u"make_decode_mov", u"make_decode_mvi", u"make_decode_alu",
             u"make_decode_jmp", u"make_decode_hlt"):
    q = getattr(pou_decode, name)()
    L(u"    %s ок, сетей=%d" % (name, len(q.networks)))

import time
for name in (u"make_decoder", u"make_ctrl_unit"):
    t0 = time.time()
    L(u"[9] собираю %s" % name)
    q = getattr(pou_decode, name)()
    L(u"    %s ок, сетей=%d" % (name, len(q.networks)))
    t1 = time.time()
    txt = q.render()
    L(u"    render ок, %d символов, %.1f с" % (len(txt), time.time() - t1))

L(u"[10] КОНЕЦ")
L.close()
