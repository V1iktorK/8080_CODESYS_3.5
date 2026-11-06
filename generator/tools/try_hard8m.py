# -*- coding: utf-8 -*-
u"""ПРОВЕРКА ПРОФИЛЯ ДИСКА HARD_8M (последний непроверенный пункт ТЗ).

В `pou_cpm_defs.py` описаны ДВА профиля DPB:
    PROFILE_FLOPPY_256K - используется по умолчанию, проверен прогоном;
    PROFILE_HARD_8M     - описан, но НИ РАЗУ не собирался.
Здесь профиль переключается на HARD_8M, проект собирается и прогоняется
заново; ожидается, что все тесты CP/M остаются PASS (формат DPB меняется,
логика CCP/BDOS - нет).

Запуск: python tools\\try_hard8m.py [build|restore]
"""
import io
import sys

GEN = u"C:/Users/Ольга/OneDrive/Рабочий стол/CODESYS/8080_CODESYS_3.5/generator"
P = GEN + u"/pou_cpm_defs.py"
A = u"DISK_PROFILE = PROFILE_FLOPPY_256K"
B = u"DISK_PROFILE = PROFILE_HARD_8M"

what = sys.argv[1] if len(sys.argv) > 1 else u"build"
t = io.open(P, encoding=u"utf-8").read()

if what == u"build":
    if B in t:
        print(u"уже HARD_8M")
    elif A in t:
        io.open(P, u"w", encoding=u"utf-8").write(t.replace(A, B))
        print(u"профиль переключён на HARD_8M")
    else:
        print(u"НЕ НАЙДЕНА строка выбора профиля")
else:
    if B in t:
        io.open(P, u"w", encoding=u"utf-8").write(t.replace(B, A))
        print(u"профиль возвращён на FLOPPY_256K")
    else:
        print(u"уже FLOPPY_256K")
