# -*- coding: utf-8 -*-
u"""ЭТАП 4: КОНФИГУРАЦИЯ ЗАДАЧ (главный блокер этапа - снят здесь).

ЧТО БЫЛО. Приложение создавалось с нуля (`proj.add(name='Device', ...)`), и
конфигурации задач в проекте не было: ни одна программа не вызывалась, поэтому
поведение во времени не могло быть проверено вообще (docs/03, п. 10.4).

ЧТО ПРОВЕРЕНО ФАКТИЧЕСКИ (пробы gen_probe_stage4.py и gen_probe4b.py):
  * app.create_task_configuration()  -> объект TaskConfiguration;
  * tc.create_task('MainTask')       -> объект задачи;
  * task.kind_of_task по умолчанию = KindOfTask.Cyclic (присваивать СТРОКУ
    нельзя: TypeError: expected KindOfTask, got str; enum принимается);
  * task.priority = '1', task.interval = 'T#5ms', task.interval_unit = 'ms';
  * task.pous.add(имя, комментарий) и task.pous.insert(индекс, имя, комментарий)
    РАБОТАЮТ: в дереве проекта появляется TaskConfiguration -> MainTask ->
    PLC_PRG_CPM. Именно этого вызова не хватало проекту.

ПОРЯДОК ВЫЗОВА ПРОГРАММ В ЗАДАЧЕ - ЧАСТЬ СХЕМЫ, А НЕ ФОРМАЛЬНОСТЬ:
  1. TEST_8080     - ИДЁТ ПЕРВЫМ: он управляет процессором через порт CP/M,
                     и запись регистров должна попасть в процессор ДО того, как
                     PLC_PRG_CPM его вызовет (процессор применяет запись в том
                     же скане, если она выставлена раньше по программе);
  2. PLC_PRG_CPM   - эмулятор: инициализация, такт, трап, диспетчеры CP/M, I/O;
  3. TEST_CPM      - ИДЁТ ПОСЛЕ: он НАБЛЮДАЕТ результат работы слоя CP/M в этом
                     же скане (журнал консоли, счётчики) и набирает команды;
  4. TEST_IO       - тоже после: проверяет аппаратный слой по шине GVL_IO.

Все четыре программы в ОДНОЙ задаче - это принципиально: два экземпляра
процессора в одном скане недопустимы (декодер FB_CPU8080_FULL пишет
управляющее слово в GVL_CPU без гейта), поэтому тесты работают ИМЕННО с тем
экземпляром, который вызывает главная программа, а не со своей копией.
"""

import scriptengine

TASK_NAME = u"MainTask"
# порядок вызова программ в задаче (см. разбор выше)
TASK_POUS = (
    (u"TEST_8080", u"тесты ядра 8080 (табличный прогон)"),
    (u"PLC_PRG_CPM", u"эмулятор 8080 + CP/M 2.2"),
    (u"TEST_CPM", u"тесты слоя CP/M (консоль, каталог, файл)"),
    (u"TEST_IO", u"тесты аппаратного ввода-вывода"),
)
DEFAULT_INTERVAL = u"T#2ms"
DEFAULT_PRIORITY = u"1"


def setup_tasks(app, proj, L, interval=DEFAULT_INTERVAL):
    u"""Создать конфигурацию задач и вставить в задачу вызовы программ.

    Возвращает объект задачи или None. Все шаги логируются: если какая-то
    часть API в этой версии ведёт себя иначе, это будет видно в протоколе.
    """
    tc = None
    try:
        tc = app.create_task_configuration()
        L(u"[OK] app.create_task_configuration() -> %s" % _s(tc))
    except Exception, e:
        L(u"[FAIL] create_task_configuration: %s" % _s(e))
        return None

    task = None
    try:
        task = tc.create_task(TASK_NAME)
        L(u"[OK] tc.create_task('%s')" % TASK_NAME)
    except Exception, e:
        L(u"[FAIL] create_task: %s" % _s(e))
        return None

    try:
        L(u"    kind_of_task по умолчанию = %r" % task.kind_of_task)
    except Exception:
        pass
    for attr, val in ((u"priority", DEFAULT_PRIORITY), (u"interval", interval)):
        try:
            setattr(task, attr, val)
            L(u"[OK] task.%s := %r -> %r" % (attr, val, getattr(task, attr)))
        except Exception, e:
            L(u"[FAIL] task.%s := %r : %s" % (attr, val, _s(e)))
    try:
        task.kind_of_task = scriptengine.KindOfTask.Cyclic
        L(u"[OK] task.kind_of_task := KindOfTask.Cyclic")
    except Exception, e:
        L(u"[WARN] kind_of_task через enum: %s" % _s(e))

    for idx, (pou, comment) in enumerate(TASK_POUS):
        try:
            task.pous.insert(idx, pou, comment)
            L(u"[OK] задача[%d] = %s (%s)" % (idx, pou, comment))
        except Exception, e:
            L(u"[FAIL] вставка %s: %s" % (pou, _s(e)))
            try:
                task.pous.add(pou, comment)
                L(u"[OK] (add) задача += %s" % pou)
            except Exception, e2:
                L(u"[FAIL] add %s: %s" % (pou, _s(e2)))
    try:
        L(u"    в задаче %d программ" % len(task.pous))
        for k in range(len(task.pous)):
            L(u"      [%d] %s" % (k, task.pous[k]))
    except Exception:
        pass
    try:
        proj.save()
        L(u"[OK] проект сохранён с конфигурацией задач")
    except Exception, e:
        L(u"[WARN] save: %s" % _s(e))
    return task


def _s(v):
    try:
        return u"%s" % v
    except Exception:
        return u"<нет repr>"
