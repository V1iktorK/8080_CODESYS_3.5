# -*- coding: utf-8 -*-
"""render_fbd.py - рендер FBD-схемы из PLCopenXML в SVG (для README и документации).

Зачем это нужно. Схемы проекта генерируются из Python в PLCopenXML, и
посмотреть на них можно только в редакторе CODESYS. Для портфолио и для
читателя документации нужна КАРТИНКА, которая: а) соответствует тому, что
лежит в репозитории (рендерится из тех же plcopenxml-файлов), б) не требует
запуска CODESYS, в) воспроизводима одной командой.

Почему не скриншот из CODESYS. В CODESYS 3.5 SP17 картинку POU отдаёт только
внутренний компонент редактора (POUImage.dll; интерфейс IPOUImageProperty в
скриптовый API не входит), поэтому скриншот возможен только глазами из GUI.
Этот рендер - честная альтернатива: он рисует ровно те блоки, позиции и связи,
что записаны в PLCopenXML.

ЗАПУСК (Python 3, никаких сторонних библиотек):

    python render_fbd.py <файл.plcopenxml> <сеть|all> <выход.svg> [--title TEXT]

    python render_fbd.py ..\\src\\s4_pous\\FB_IO_Dispatch.plcopenxml 0 out.svg
    python render_fbd.py ..\\src\\s4_pous\\FB_IO_Dispatch.plcopenxml all all.svg

Формат: один SVG на сеть; для all - все сети в одной картинке (подписи сетей,
разделители). Координаты блоков берутся из PLCopenXML (те же x/y, что в
редакторе), связи - по localId.
"""

import sys
import xml.etree.ElementTree as ET

C_BG = "#ffffff"
C_GRID = "#eef1f5"
C_BLOCK = "#dbe8f6"
C_BLOCK_LINE = "#4a76a8"
C_NAME = "#1f3a5f"
C_VAR = "#ffffff"
C_VAR_LINE = "#b8c4d0"
C_WIRE = "#8a97a5"
C_TITLE = "#25384d"

FONT = "Segoe UI, Arial, sans-serif"
PAD = 28
BLOCK_FONT = 9
VAR_FONT = 9
TITLE_FONT = 12
NET_TITLE_FONT = 11


def _local(tag):
    return tag.split("}")[-1] if "}" in tag else tag


def _num(v, dflt=0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return dflt


def _text_of(el, tag):
    for ch in el:
        if _local(ch.tag) == tag:
            return (ch.text or u"").strip()
    return u""


def _pos(el):
    for ch in el:
        if _local(ch.tag) == "position":
            return _num(ch.get("x")), _num(ch.get("y"))
    return 0.0, 0.0


def _elements(root):
    """Все элементы FBD (блоки и переменные) в порядке документа."""
    out = []
    for el in root.iter():
        if _local(el.tag) in ("inVariable", "outVariable", "block"):
            out.append(el)
    return out


def split_networks(path):
    """Разбить POU на сети по комментариям '<!-- СЕТЬ ... -->'.

    В PLCopenXML сети не обёрнуты в <network>: перед каждой сетью стоит
    комментарий, а элементы идут подряд. ElementTree теряет комментарии,
    поэтому границы берём из сырого текста, а элементы - из ET (в том же
    порядке документа).
    """
    raw = open(path, "rb").read()
    root = ET.parse(path).getroot()
    items = _elements(root)

    marks = []
    frompos = 0
    tag = "<!-- СЕТЬ".encode("utf-8")
    while True:
        i = raw.find(tag, frompos)
        if i < 0:
            break
        j = raw.find(b"-->", i)
        title = raw[i + 4:j].decode("utf-8", "replace").strip()
        marks.append((i, j + 3, title))
        frompos = j + 3
    if not marks:
        return [(u"", items)]

    counts = []
    for k, (a, b, _t) in enumerate(marks):
        end = marks[k + 1][0] if k + 1 < len(marks) else len(raw)
        seg = raw[a:end]
        n = (seg.count(b"<inVariable") + seg.count(b"<outVariable")
             + seg.count(b"<block"))
        counts.append(n)
    if sum(counts) != len(items):
        # не смогли сопоставить - отдаём всё одной сетью (не теряем схему)
        return [(u"POU (сети не разделились)", items)]
    out = []
    p = 0
    for k, (a, b, title) in enumerate(marks):
        out.append((title, items[p:p + counts[k]]))
        p += counts[k]
    return out


def geometry(items):
    geo = {}
    for el in items:
        t = _local(el.tag)
        lid = el.get("localId")
        x, y = _pos(el)
        if t == "inVariable":
            h, w = _num(el.get("height")), _num(el.get("width"))
            geo[lid] = ("in", x, y, w, h, _text_of(el, "expression"))
        elif t == "outVariable":
            h, w = _num(el.get("height")), _num(el.get("width"))
            geo[lid] = ("out", x, y, w, h, _text_of(el, "expression"))
        else:
            h, w = _num(el.get("height")), _num(el.get("width"))
            geo[lid] = ("blk", x, y, w, h, el.get("typeName") or u"")
    return geo


def wires_of(items, geo):
    out = []
    for el in items:
        lid = el.get("localId")
        if lid is None:
            continue
        for ch in el.iter():
            if _local(ch.tag) != "connection":
                continue
            src = ch.get("refLocalId")
            if src in geo and lid in geo:
                out.append((src, lid))
    return out


def esc(s):
    return (s or u"").replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def render_svg(nets, main_title=u""):
    """Собрать один SVG: все сети подряд с подписями. Возвращает строку."""
    # 1) смета размеров: сеть = свои x/y, сдвигаем по вертикали
    laid = []          # [(title, geo, wires, y_off)]
    y_off = 40.0
    max_x = 0.0
    for title, items in nets:
        geo = geometry(items)
        if not geo:
            continue
        wr = wires_of(items, geo)
        h = max([g[2] + g[4] for g in geo.values()] + [0]) + 30
        laid.append((title, geo, wr, y_off))
        y_off += h + 18
        max_x = max(max_x, max([g[1] + g[3] for g in geo.values()] + [0]))
    if not laid:
        return u'<svg xmlns="http://www.w3.org/2000/svg" width="10" height="10"></svg>'
    W = int(max_x + PAD * 2)
    H = int(y_off + PAD)
    step = 20
    svg = [u'<svg xmlns="http://www.w3.org/2000/svg" width="%d" height="%d" viewBox="0 0 %d %d" '
           u'font-family="%s">' % (W, H, W, H, FONT)]
    svg.append(u'<rect width="100%%" height="100%%" fill="%s"/>' % C_BG)
    for gx in range(0, W, step):
        svg.append(u'<line x1="%d" y1="0" x2="%d" y2="%d" stroke="%s" stroke-width="1"/>'
                   % (gx, gx, H, C_GRID))
    for gy in range(0, H, step):
        svg.append(u'<line x1="0" y1="%d" x2="%d" y2="%d" stroke="%s" stroke-width="1"/>'
                   % (gy, W, gy, C_GRID))
    if main_title:
        svg.append(u'<text x="%d" y="24" font-size="%d" font-weight="700" fill="%s">%s</text>'
                   % (PAD, TITLE_FONT, C_TITLE, esc(main_title)))

    for title, geo, wr, yo in laid:
        svg.append(u'<text x="%d" y="%.1f" font-size="%d" font-weight="600" fill="%s">%s</text>'
                   % (PAD, yo - 8.0, NET_TITLE_FONT, C_TITLE, esc(title)))

        def X(v):
            return v + PAD

        def Y(v):
            return v + yo

        for src, dst in wr:
            s, d = geo[src], geo[dst]
            sx = X(s[1] + s[3])
            sy = Y(s[2] + s[4] / 2.0)
            dx = X(d[1])
            dy = Y(d[2] + (7.0 if d[0] == "blk" else d[4] / 2.0))
            svg.append(u'<path d="M %.1f %.1f L %.1f %.1f L %.1f %.1f" fill="none" '
                       u'stroke="%s" stroke-width="1.4"/>' % (sx, sy, dx, sy, dx, dy, C_WIRE))
            svg.append(u'<circle cx="%.1f" cy="%.1f" r="1.8" fill="%s"/>' % (dx, dy, C_WIRE))
        for lid, (kind, x, y, w, h, label) in geo.items():
            px, py = X(x), Y(y)
            if kind == "blk":
                svg.append(u'<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="2" '
                           u'fill="%s" stroke="%s" stroke-width="1.2"/>'
                           % (px, py, w, h, C_BLOCK, C_BLOCK_LINE))
                svg.append(u'<text x="%.1f" y="%.1f" font-size="%d" font-weight="600" '
                           u'fill="%s" text-anchor="middle">%s</text>'
                           % (px + w / 2.0, py + h / 2.0 + 3.5, BLOCK_FONT, C_NAME, esc(label)))
            else:
                svg.append(u'<rect x="%.1f" y="%.1f" width="%.1f" height="%.1f" rx="1.5" '
                           u'fill="%s" stroke="%s" stroke-width="1"/>'
                           % (px, py, w, h, C_VAR, C_VAR_LINE))
                anchor = u"start" if kind == "in" else u"end"
                tx = px + 4 if kind == "in" else px + w - 4
                svg.append(u'<text x="%.1f" y="%.1f" font-size="%d" fill="%s" '
                           u'text-anchor="%s">%s</text>'
                           % (tx, py + h - 2.5, VAR_FONT, C_TITLE, anchor, esc(label)))
    svg.append(u'</svg>')
    return u"\n".join(svg)


def main(argv):
    if len(argv) < 4:
        print(__doc__)
        return 2
    src, which, dst = argv[1], argv[2], argv[3]
    title = u""
    if "--title" in argv:
        title = argv[argv.index("--title") + 1]
    nets = split_networks(src)
    if which != "all":
        nets = [nets[int(which)]]
    svg = render_svg(nets, main_title=title)
    with open(dst, "w", encoding="utf-8") as f:
        f.write(svg)
    print("SVG: %s (%d байт, сетей: %d)" % (dst, len(svg), len(nets)))
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv))
