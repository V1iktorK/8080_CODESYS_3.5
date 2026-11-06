# -*- coding: utf-8 -*-
u"""Инфраструктура сборки проекта CODESYS из скрипта (библиотека для сборщиков).

Здесь собрано всё, что выяснено экспериментально и нужно каждому шагу сборки:
создание проекта с устройством, добавление GVL/DUT, импорт FBD, проверка связей,
сборка и разбор сообщений компилятора.

Устройство: CODESYS Control Win V3 = type 4096, id '0000 0001', version '3.5.17.30'.
"""

import io, os, sys, traceback
import scriptengine


DEVICE_TYPE = 4096
DEVICE_ID = u"0000 0001"
DEVICE_VERSION = u"3.5.17.30"


def resolve_root():
    u"""Корень проекта (папка 8080_EMU).

    Скрипты запускаются из локальной «сцены» (см. tools/run_codesys.ps1), потому
    что CODESYS не читает .py напрямую из папки OneDrive. Настоящий корень
    передаётся переменной окружения DSH_EMU_ROOT.
    """
    r = os.environ.get(u"DSH_EMU_ROOT")
    if r:
        return unicode(r).replace(u"\\", u"/")
    return os.path.dirname(os.path.dirname(os.path.abspath(__file__))).replace(u"\\", u"/")


ROOT = resolve_root()


def log_open(path):
    d = os.path.dirname(path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    # Бинарный режим + fsync: CODESYS при зависании убивают через taskkill, и
    # буферизованный текст в этом случае теряется целиком (лог остаётся нулевым,
    # хотя скрипт успел проработать минуты). Пишем сразу на диск.
    return io.open(path, "wb")


class Log(object):
    u"""Логгер в файл (лог пишется в <корень проекта>/log).

    Каждая строка пишется отдельным дескриптором «открыть-записать-закрыть».
    Это медленнее, но только так запись гарантированно доходит до диска:
    CODESYS при зависании убивают через taskkill, и любой буфер теряется целиком
    (лог остаётся нулевой длины, хотя скрипт успел проработать минуты).
    """

    def __init__(self, path):
        d = os.path.dirname(path)
        if d and not os.path.isdir(d):
            # ОСОБЕННОСТЬ ОКРУЖЕНИЯ (найдено на этапе 4): в IronPython-скрипте
            # CODESYS os.path.isdir иногда отвечает False для СУЩЕСТВУЮЩЕГО
            # каталога, и тогда os.makedirs уходит в рекурсию до "C:" и падает с
            # OSError "Данный формат пути не поддерживается" - скрипт не
            # запускается вообще, а лог остаётся пустым. Поэтому mkdir здесь
            # необязателен: каталог log создаёт раннер, а если его нет -
            # пробуем создать и в любом случае продолжаем.
            try:
                os.makedirs(d)
            except Exception:
                pass
        f = io.open(path, "wb")
        f.close()
        self.path = path

    def __call__(self, msg):
        line = unicode(msg)
        f = io.open(self.path, "ab")
        f.write((line + u"\n").encode("utf-8"))
        f.close()

    def close(self):
        pass


def make_log(name):
    u"""Логгер с РЕЗЕРВНЫМИ путями (найдено на этапе 4).

    Если путь основного лога по какой-то причине не принимается (IronPython в
    CODESYS на такой путь отвечает SystemError/OSError «Данный формат пути не
    поддерживается»), прогон теряется целиком: скрипт падает на первой же
    строке, лог остаётся пустым, а раннер считает попытку неудачной и
    повторяет запуск. Поэтому путей несколько, и в первый же удачный
    пишется диагностика (какой корень, какая переменная окружения, какой CWD).
    """
    env_root = u""
    try:
        env_root = unicode(os.environ.get(u"DSH_EMU_ROOT") or u"")
    except Exception:
        pass
    cands = [ROOT + u"/log/" + name,
             u"C:/dsh8080/work/emu_s4/log/" + name,
             os.path.dirname(os.path.abspath(__file__)) + u"/" + name]
    last = None
    for p in cands:
        try:
            lg = Log(p)
        except Exception, e:
            last = e
            continue
        try:
            lg(u"[diag] лог=%s ROOT=%r DSH_EMU_ROOT=%r CWD=%r python=%s"
               % (p, ROOT, env_root, os.getcwd(), sys.version))
        except Exception:
            pass
        return lg
    raise last


def nm(o):
    try:
        return o.get_name()
    except Exception:
        return u"?"


def close_all():
    # ВАЖНО: глобальные objects (projects, system, online) инжектируются только
    # в namespace ГЛАВНОГО скрипта. В импортированном модуле их надо брать
    # из модуля scriptengine: scriptengine.projects и т. д.
    for p in list(scriptengine.projects.all):
        try:
            p.close()
        except Exception:
            pass


def clean_locks(path):
    u"""Убрать lock-файлы CODESYS (<проект>.project.~u и прочие *.~*).

    Если headless-процесс был убит, файл блокировки остаётся на диске, и
    следующий projects.create() ждёт освобождения ВЕЧНО (процесс висит, ничего
    не выполняя и ничего не пишет в лог). Проверено экспериментально.
    """
    for p in (path + u".~u", path + u".~" , path[:-8] + u".~u" if path.endswith(u".project") else path):
        try:
            if os.path.exists(p):
                os.remove(p)
        except Exception:
            pass
    d = os.path.dirname(path)
    if d and os.path.isdir(d):
        try:
            for n in os.listdir(d):
                if u".~" in n:
                    try:
                        os.remove(os.path.join(d, n))
                    except Exception:
                        pass
        except Exception:
            pass


def new_project(path, L):
    u"""Создать проект с нуля и добавить устройство. Возвращает (proj, app)."""
    close_all()
    clean_locks(path)
    if os.path.exists(path):
        os.remove(path)
    proj = scriptengine.projects.create(path)
    L(u"    projects.create OK -> %s" % path)
    proj.add(name=u"Device", type=DEVICE_TYPE, id=DEVICE_ID, version=DEVICE_VERSION)
    L(u"    устройство добавлено: type=%d id=%s version=%s"
      % (DEVICE_TYPE, DEVICE_ID, DEVICE_VERSION))
    app = proj.active_application
    L(u"    application = %s" % nm(app))
    return proj, app


def add_gvl(app, name, text, L):
    u"""Создать GVL и задать её текст объявления."""
    gvl = app.create_gvl(name)
    gvl.textual_declaration.replace(text)
    L(u"    GVL %s создана (%d символов объявления)" % (name, len(text)))
    return gvl


def add_dut(app, name, text, L):
    u"""Создать DUT (структуру) и задать её текст объявления."""
    dut = app.create_dut(name, type=scriptengine.DutType.Structure)
    dut.textual_declaration.replace(text)
    L(u"    DUT %s создан" % name)
    return dut


def import_pou(app, xml_path, L):
    u"""Импортировать PLCopenXML в приложение."""
    app.import_xml(xml_path)
    L(u"    import_xml OK: %s" % os.path.basename(xml_path))


def walk(o, ind=0, depth=6, acc=None, L=None):
    if acc is None:
        acc = []
    if L is not None:
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
        walk(k, ind + 1, depth, acc, L)
    return acc


def find_deep(root, name):
    u"""Поиск объекта по имени по всему поддереву (app.find ведёт себя нестабильно)."""
    for n, o in walk(root, 0, 8, [], None):
        if n == name:
            return o
    return None


def import_pous_one_by_one(app, pous, src_dir, L):
    u"""Импортировать POU ПООЧЕРЁДНО, каждый своим файлом.

    Пакетный импорт нескольких POU одним XML иногда молча теряет часть объектов
    (проверено: из 5 POU доехали 3). Пофайловый импорт детерминирован и сразу
    показывает, какой именно POU не принят.

    ЗДЕСЬ ЖЕ - ЕДИНСТВЕННАЯ ТОЧКА ПЕРЕИМЕНОВАНИЯ ЗАРЕЗЕРВИРОВАННЫХ ИМЁН.
    IEC не различает регистр и запрещает ключевые слова (S, R, SEL, LD, ST, ...)
    в роли идентификаторов: компиляция даёт C0007/C0009/C0046/C0004/C0037/C0022.
    Переименование ОБЯЗАНО применяться ко ВСЕМ POU скопом - и к определениям,
    и к потребителям. Если переименовать только часть (как было раньше: отдельно
    папку зависимостей), определения становятся Rx/Sx/SELx, а вызовы остаются
    R/S/Sel - и получается тот самый рассинхрон.
    """
    import fbd_xml
    import pou_rename
    if not os.path.isdir(src_dir):
        os.makedirs(src_dir)
    paths = []
    for p in pous:
        one = u"%s/%s.plcopenxml" % (src_dir, p.name)
        fbd_xml.write_project(one, [p], p.name)
        try:
            pou_rename.fix_file(one)
        except Exception, e:
            L(u"      ВНИМАНИЕ: переименование %s не выполнено: %r" % (p.name, e))
        L(u"      импорт %s ..." % p.name)
        app.import_xml(one)
        L(u"      импорт %s OK" % p.name)
        paths.append(one)
    L(u"    импортировано по одному файлу: %d POU" % len(pous))
    return paths


def verify_import(proj, app, pou_names, gen_path, reexport_path, L):
    u"""Проверить, что POU доехали и связи не потерялись.

    Сравниваем число блоков в сгенерированном XML и в выгрузке обратно,
    а также требуем отсутствия пустых входов (<connectionPointIn />).
    """
    gen = _counts(gen_path)
    L(u"    СГЕНЕРИРОВАНО : блоков=%d связей=%d пустых.входов=%d" % (gen[0], gen[3], gen[4]))

    L(u"    --- дерево Application после импорта ---")
    walk(app, 1, 3, [], L)

    found = []
    missing = []
    for n in pou_names:
        o = find_deep(app, n)
        if o is None:
            o = find_deep(proj, n)
        if o is None:
            missing.append(n)
        else:
            found.append(o)

    if missing:
        L(u"    ОШИБКА: не найдены POU: %s" % u", ".join(missing))
    if not found:
        return False

    proj.export_xml(found, path=reexport_path, declarations_as_plaintext=True)
    rex = _counts(reexport_path)
    L(u"    ПОСЛЕ ИМПОРТА: блоков=%d связей=%d пустых.входов=%d" % (rex[0], rex[3], rex[4]))

    ok = True
    if missing:
        ok = False
    if rex[0] != gen[0]:
        L(u"    ОШИБКА: блоков %d вместо %d — часть схемы потерялась" % (rex[0], gen[0]))
        ok = False
    if rex[4] != 0:
        L(u"    ОШИБКА: %d входов без связи" % rex[4])
        ok = False
    if ok:
        L(u"    ПРОВЕРКА СВЯЗЕЙ: OK (%d блоков, все входы подключены)" % rex[0])
    return ok


def _counts(path):
    import fbd_xml
    return fbd_xml.count_elements(path)


def build(app, L):
    u"""Собрать приложение. Сообщения компилятора CODESYS пишет в stdout процесса."""
    app.build()
    L(u"    build() выполнен (сообщения компилятора — в <скрипт>.stdout.txt)")
