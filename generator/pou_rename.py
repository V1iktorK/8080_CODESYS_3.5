# -*- coding: utf-8 -*-
u"""Этап 4: ИСПРАВЛЕНИЕ ЛАТЕНТНЫХ ОШИБОК СЛОЯ ЭТАПОВ 3.2-3.6 (только имена).

ЗАЧЕМ. Пока в проекте не было конфигурации задач, CODESYS только РАЗБИРАЛ
объявления и НЕ ГЕНЕРИРОВАЛ КОД. Первая же задача включила кодогенерацию, и
проявились ошибки, которых разбор не видел (проба gen_probe4d.py: 315 ошибок
на СТАРОМ слое без единой строки этапа 4):

  1. ИМЕНА, СОВПАДАЮЩИЕ С КЛЮЧЕВЫМИ СЛОВАМИ IEC. В сгенерированном тексте
     объявлений они ломают разбор:
        C9: Обнаружен недопустимый символ 'LD'   (FB_Reg8, FB_Reg16, ...)
        C9: Обнаружен недопустимый символ 'S'    (FB_ALU8, FB_CtrlUnit, ...)
        C9: Обнаружен недопустимый символ 'R'    (FB_ALU8, FB_Rotate8, ...)
        C189: ';' требуется вместо 'ARRAY'       (GVL_IO: переменная DO)
        C4: 'DO' не является компонентом 'GVL_IO'
     LD, S, R - операторы языка IL, DO - часть FOR..DO. В объявлении они
     допустимы, в кодогенерации - нет.

  2. ИМЕНА, ОТЛИЧАЮЩИЕСЯ ТОЛЬКО РЕГИСТРОМ (CODESYS не различает регистр):
        C142: Локальная переменная с именем 'raw' уже задана в 'FB_IO_AnalogIn'
        C142: ... 'aout' в 'FB_IO_AnalogOut'
        C142: ... 'kind' в 'FB_IO_Dispatch'

  3. КОММЕНТАРИЙ, ЗАКРЫТЫЙ РАНЬШЕ ВРЕМЕНИ: последовательность "*)" внутри
     комментария обрывает его, и остаток текста разбирается как код.
     Найдено и исправлено в самих модулях: pou_bios.py ("порт CPM_*)"),
     pou_io_defs.py ("код аварии (E_*)"), pou_test8080.py ("GVL_CPM.CPM_*)").

ЧТО ДЕЛАЕТ ЭТОТ МОДУЛЬ. Переименование имён выполняется ТЕКСТОВО, уже на
готовом PLCopenXML: имя меняется и в структурном <interface>, и в текстовом
дубле объявления, и во всех ссылках (formalParameter, <expression>). Схемы
при этом НЕ меняются: связи ссылаются на localId, а не на имена.

ВАЖНО: правки нужны только из-за кодогенерации. Логика слоя не меняется ни
на один блок. После переименования старый слой собирается с 0 ошибок и
впервые в истории проекта запускается на исполнении.
"""

import io, os, re

# имя, совпадающее с ключевым словом -> новое имя.
# СПИСОК СОСТАВЛЕН ПО ФАКТАМ, А НЕ ПО ДОГАДКАМ: имена найдены сканером
# tools/scan_keywords.py по всем объявлениям проекта (67 POU + GVL/DUT +
# 111 зависимостей) и подтверждены ошибками кодогенерации
# "C9: Обнаружен недопустимый символ 'X'":
#     LD  - FB_Reg8, FB_Reg16, FB_FlagsReg            (IL: загрузить)
#     S   - FB_ALU8, FB_CtrlUnit, FB_FlagsReg2, ...    (IL: установить)
#     R   - FB_ALU8, FB_DAA, FB_Rotate8                (IL: сбросить)
#     ST  - FB_CPM_DirEngine, TEST_CPM                 (IL: сохранить)
#     SEL - FB_Mux8x8, FB_Mux8x16, FB_DecodeRegSel     (стандартная функция)
#     BIT - FB_IO_Read, FB_IO_Write, FB_IO_Adapter_HW  (тип CODESYS)
#     EXP - TEST_IO                                    (стандартная функция)
#     TO  - TEST_CPM                                   (FOR..TO)
#     DO  - GVL_IO                                     (FOR..DO)
#     STEP, DATA, EQ, GE, GT, LE, LT, NE - ключевые слова SFC/операторы
#          сравнения; в импортируемых файлах тоже встречаются.
RESERVED = {
    u"LD": u"LDx",
    u"S": u"Sx",
    u"R": u"Rx",
    u"ST": u"STx",
    u"SEL": u"SELx",
    u"BIT": u"BITx",
    u"EXP": u"EXPx",
    u"TO": u"TOx",
    u"DO": u"DOx",
    u"STEP": u"STEPx",
    u"DATA": u"DATAx",
    u"EQ": u"EQx",
    u"GE": u"GEx",
    u"GT": u"GTx",
    u"LE": u"LEx",
    u"LT": u"LTx",
    u"NE": u"NEx",
}


def decl_text(text):
    u"""Переименовать зарезервированные имена в ТЕКСТЕ объявления GVL/DUT.

    Сравнение БЕЗ УЧЁТА РЕГИСТРА: CODESYS не различает регистр, поэтому
    переменная `do` и переменная `DO` - это одно и то же имя.
    """
    out = []
    for line in text.split(u"\n"):
        m = re.match(u"^(\\s*)([A-Za-z_][A-Za-z0-9_]*)(\\s*:)(.*)$", line)
        if m and m.group(2).upper() in RESERVED:
            new = RESERVED[m.group(2).upper()]
            line = u"%s%s%s%s" % (m.group(1), new, m.group(3), m.group(4))
        out.append(line)
    return u"\n".join(out)


_EXPR_RE = re.compile(u"<expression>(.*?)</expression>", re.S)


def _fix_expr(m):
    u"""Переименовать имена внутри выражения (в т.ч. составного).

    В FBD <expression> - это либо имя переменной, либо выражение вида
    "ebase + cpos_w". Поэтому имя ищется по границам слова, а НЕ только как
    всё выражение целиком. Регистр не учитывается.
    """
    e = m.group(1)
    for old, new in RESERVED.items():
        e = re.sub(u"(?<![A-Za-z0-9_.])%s(?![A-Za-z0-9_])" % old, new, e,
                   flags=re.IGNORECASE)
    return u"<expression>%s</expression>" % e


def xml_text(text):
    u"""Переименовать зарезервированные имена в PLCopenXML одного POU.

    Меняются:
      <variable name="LD">            -> имя в структурном интерфейсе;
      formalParameter="LD"            -> имя вывода/входа в вызове блока;
      <expression>...</expression>    -> ссылки (флаги, регистры, GVL);
      строки вида "\\tLD : BOOL;"      -> текстовый дубль объявления.
    Имя типа блока (typeName="SEL") НЕ трогается: это стандартная функция.
    Регистр не учитывается (CODESYS его не различает).
    """
    t = text
    for old, new in RESERVED.items():
        # структурный интерфейс и локальные переменные
        t = re.sub(u'<variable name="%s">' % old,
                   u'<variable name="%s">' % new, t, flags=re.IGNORECASE)
        # вызовы блоков
        t = re.sub(u'formalParameter="%s"' % old,
                   u'formalParameter="%s"' % new, t, flags=re.IGNORECASE)
        # обращения к выводам экземпляров: flags.S, alu.R, GVL_IO.DO[i]
        t = re.sub(u"\\.%s(?![A-Za-z0-9_])" % old, u".%s" % new, t,
                   flags=re.IGNORECASE)
    # выражения целиком
    t = _EXPR_RE.sub(_fix_expr, t)
    # текстовый дубль объявления (xhtml внутри InterfaceAsPlainText)
    out = []
    for line in t.split(u"\n"):
        m = re.match(u"^(\\s*)([A-Za-z_][A-Za-z0-9_]*)(\\s*:)(.*)$", line)
        if m and m.group(2).upper() in RESERVED:
            new = RESERVED[m.group(2).upper()]
            line = u"%s%s%s%s" % (m.group(1), new, m.group(3), m.group(4))
        out.append(line)
    return u"\n".join(out)


def fix_file(src, dst=None):
    u"""Переписать файл PLCopenXML с переименованием (dst=None - на месте).

    ВАЖНО: файл закрывается ЯВНО. В IronPython файл, оставленный сборщику
    мусора, держит дескриптор, и следующий import_xml падает с
    "Процесс не может получить доступ к файлу ... используется другим
    процессом" (проверено прогоном: импорт обрывался на FB_CPU8080_FULL).
    """
    f = io.open(src, "r", encoding="utf-8")
    t = f.read()
    f.close()
    t2 = xml_text(t)
    if dst is None:
        dst = src
    f = io.open(dst, "w", encoding="utf-8")
    f.write(t2)
    f.close()
    return t != t2


def fix_dir(src_dir, dst_dir, names=None):
    u"""Скопировать все *.plcopenxml из src_dir в dst_dir с переименованием."""
    if not os.path.isdir(dst_dir):
        # см. codesys_build.Log.__init__: isdir в IronPython иногда врёт, а
        # makedirs по несуществующему родителю падает с "формат пути".
        try:
            os.makedirs(dst_dir)
        except Exception:
            pass
    n_fix = n_all = 0
    for fn in os.listdir(src_dir):
        if not fn.endswith(u".plcopenxml"):
            continue
        if names is not None and fn[:-len(u".plcopenxml")] not in names:
            continue
        n_all += 1
        if fix_file(os.path.join(src_dir, fn), os.path.join(dst_dir, fn)):
            n_fix += 1
    return n_all, n_fix
