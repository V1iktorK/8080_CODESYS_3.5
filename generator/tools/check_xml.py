# -*- coding: utf-8 -*-
u"""Проверка PLCopenXML: блоки AND/SEL/ADD с недостатком входов и
необъявленные экземпляры FB (instanceName без объявления)."""
import io, os, re, sys

D = sys.argv[1] if len(sys.argv) > 1 else r"C:\dsh8080\work\emu_s4\src\s4_pous"


def main():
    n_and = n_inst = 0
    for fn in sorted(os.listdir(D)):
        if not fn.endswith(u".plcopenxml"):
            continue
        t = io.open(os.path.join(D, fn), encoding=u"utf-8").read()
        for m in re.finditer(u'<block ([^>]*)>(.*?)</block>', t, re.S):
            attrs, body = m.group(1), m.group(2)
            tn = re.search(u'typeName="([^"]+)"', attrs)
            tn = tn.group(1) if tn else u"?"
            k = len(re.findall(u"<variable formalParameter=", body))
            if tn in (u"AND", u"OR", u"MUL", u"ADD", u"SUB", u"DIV") and k < 2:
                print(u"%s: %s с %d входами" % (fn, tn, k))
                n_and += 1
            if tn == u"SEL" and k < 3:
                print(u"%s: SEL с %d входами" % (fn, k))
                n_and += 1
        # экземпляры FB
        decl = set(re.findall(u'<variable name="([^"]+)">', t))
        for m in re.finditer(u'<block [^>]*typeName="(FB_[^"]+)" instanceName="([^"]+)"',
                             t):
            if m.group(2) not in decl:
                print(u"%s: экземпляр %s (%s) НЕ ОБЪЯВЛЕН"
                      % (fn, m.group(2), m.group(1)))
                n_inst += 1
    print(u"\nитого: проблем с входами %d, необъявленных экземпляров %d"
          % (n_and, n_inst))


if __name__ == u"__main__":
    main()
