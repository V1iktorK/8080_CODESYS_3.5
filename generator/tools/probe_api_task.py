# -*- coding: utf-8 -*-
u"""Разбор дампа scripting API: методы конфигурации задач и online-доступа.

Запускается ОБЫЧНЫМ Python 3 (не внутри CODESYS) - это анализ файла
generator/probe/api_dump.json, снятого через system.dump_scripting_api().

Использование:
    python probe_api_task.py                 -> сводка по интересным типам
    python probe_api_task.py list [фильтр]   -> список типов
    python probe_api_task.py type <ИмяТипа>  -> все члены типа
"""
import io, json, os, sys

HERE = os.path.dirname(os.path.abspath(__file__))
CAND = [os.path.join(HERE, u"..", u"probe", u"api_dump.json"),
        os.path.join(HERE, u"..", u"probe", u"api_dump.json")]
PATH = None
for c in CAND:
    if os.path.exists(c):
        PATH = c
        break

WANT = [u"TaskConfig", u"TaskObject", u"ScriptTask", u"Online", u"ApplicationState",
        u"DeviceObject", u"ApplicationObject"]


def load():
    with io.open(PATH, "r", encoding="utf-8") as f:
        return json.load(f)


def typename(t):
    return t.get("Name") or t.get("Id")


def members(t):
    out = []
    for key in (u"Members", u"Properties", u"Methods", u"Fields", u"Events"):
        for m in (t.get(key) or []):
            out.append((key, m))
    return out


def mname(m):
    return m.get("Name") or m.get("Id")


def show_type(t):
    print(u"\n###### %s  Kind=%s" % (typename(t), t.get("Kind")))
    print(u"  Id: %s" % t.get("Id"))
    if t.get("EffectiveType"):
        print(u"  EffectiveType: %s" % t.get("EffectiveType"))
    if t.get("BaseTypes"):
        print(u"  BaseTypes: %s" % t.get("BaseTypes"))
    if t.get("Interfaces"):
        print(u"  Interfaces: %s" % t.get("Interfaces"))
    for k, m in members(t):
        s = u"  [%s] %s" % (k, mname(m))
        if m.get("Id") and m.get("Id") != m.get("Name"):
            s = u"  [%s] %s" % (k, m.get("Id"))
        print(s)


def main():
    data = load()
    types = {typename(t): t for t in data["Types"]}
    argv = sys.argv[1:]
    if argv and argv[0] == "list":
        flt = argv[1].lower() if len(argv) > 1 else u""
        for nm in sorted(types):
            if flt in nm.lower():
                t = types[nm]
                print(u"%-46s %-12s members=%d" % (nm, t.get("Kind"), len(members(t))))
        return
    if argv and argv[0] == "type":
        nm = argv[1]
        if nm not in types:
            for k in types:
                if nm.lower() in k.lower():
                    show_type(types[k])
            return
        show_type(types[nm])
        return
    # сводка по умолчанию
    for w in WANT:
        for nm in sorted(types):
            if w.lower() in nm.lower():
                show_type(types[nm])


if __name__ == "__main__":
    main()
