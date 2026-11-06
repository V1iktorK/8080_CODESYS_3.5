# -*- coding: utf-8 -*-
u"""Извлечение интерфейсов и таблиц из модулей генератора (обычный Python 3)."""
import io, os, re, sys

G = os.path.join(os.path.dirname(os.path.abspath(__file__)), u"..")


def read(name):
    return io.open(os.path.join(G, name), encoding="utf-8").read()


def iface(fname, func, upto=6000):
    t = read(fname)
    i = t.find(func)
    if i < 0:
        print("!! %s not found in %s" % (func, fname))
        return
    seg = t[i:i + upto]
    print("==== %s / %s ====" % (fname, func))
    for m in re.finditer(r'var_(in|out)\(u"([^"]+)", u"([^"]+)"', seg):
        print("  %-4s %-22s %s" % (m.group(1), m.group(2), m.group(3)))


def demo_files():
    t = read(u"pou_demo.py")
    print("==== имена файлов в образе диска ====")
    for m in sorted(set(re.findall(r'u"([A-Z0-9_]{1,8}\.[A-Z]{3})"', t))):
        print("  ", m)


def hmi_vars():
    t = read(u"pou_io_defs.py")
    i = t.find(u"def gvl_hmi_text")
    seg = t[i:i + 9000]
    print("==== GVL_HMI ====")
    for m in re.finditer(r'L\.append\(u"\t([^"\\]+)', seg):
        print("  ", m.group(1).rstrip())


def io_gvl():
    t = read(u"pou_io_defs.py")
    for fn in (u"KIND_NAMES", u"MODE_NAMES", u"ERR_NAMES", u"EVENT_NAMES"):
        m = re.search(fn + r"\s*=\s*\((.*?)\n\)", t, re.S)
        print("==== %s ====" % fn)
        if m:
            for mm in re.finditer(r'\((\d+),\s*u"([^"]*)"\)', m.group(1)):
                print("   %3s = %s" % (mm.group(1), mm.group(2)))


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    if which in ("all", "iface"):
        iface(u"pou_io.py", u"def make_io_dispatch")
        iface(u"pou_io.py", u"def make_watchdog")
        iface(u"pou_prg_cpm.py", u"def make_plc_prg_cpm")
    if which in ("all", "files"):
        demo_files()
    if which in ("all", "hmi"):
        hmi_vars()
    if which in ("all", "codes"):
        io_gvl()
