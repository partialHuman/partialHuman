"""Strip everything except the 3D contribution bars from the generated profile SVGs.

Removes: background rect, radar chart, stats panel, title/labels.
Keeps:   <defs> and the isometric contribution bars (first top-level <g>), growing animation included.
Also:    changes the viewing angle (VIEW_ANGLE) and crops the canvas to the bars so there is no empty margin.

VIEW_ANGLE is the isometric camera angle in degrees. The generator always draws 30.
Lower value  -> flatter ground, shorter image (bar heights are kept).
Higher value -> taller image. Use 30 to keep the original look.
You can also override it per run:  SKYLINE_ANGLE=15 python3 clean_profile_svgs.py file.svg
"""
import math
import os
import re
import sys
from pathlib import Path

VIEW_ANGLE = 15.0   # <-- change this number to change the viewing angle
PAD = 60


def top_level(body):
    """Yield (start, end, tag_text) for each top-level element in `body`."""
    depth, start, name = 0, 0, ""
    for m in re.finditer(r"<(/?)(\w+)([^>]*?)(/?)>", body):
        close, tag, attrs, selfclose = m.groups()
        if close:
            depth -= 1
            if depth == 0:
                yield start, m.end(), name
        else:
            if depth == 0:
                start, name = m.start(), tag + attrs
                if selfclose:
                    yield start, m.end(), name
                    continue
            if not selfclose:
                depth += 1


def fmt(v):
    return f"{v:.2f}".rstrip("0").rstrip(".")


GROUP_RE = re.compile(r'<g transform="translate\(([\d.\-]+)[ ,]+([\d.\-]+)\)">(.*?)</g>', re.S)
ANIM_RE = re.compile(r'(<animateTransform[^>]*?values=")([\d.\-]+)[ ,]+([\d.\-]+);([\d.\-]+)[ ,]+([\d.\-]+)(")')


def change_angle(bars, target):
    """Re-project the bars from the generator's angle to `target` degrees. Returns (bars, ratio)."""
    m = re.search(r'skewY\((-?[\d.]+)\) skewX', bars)
    if not m:
        return bars, 1.0
    cur = abs(float(m.group(1)))
    if abs(cur - target) < 0.01:
        return bars, 1.0
    r = math.tan(math.radians(target)) / math.tan(math.radians(cur))

    # ground position of every bar (baseY) and its height
    info = []
    for g in GROUP_RE.finditer(bars):
        x, y, inner = float(g.group(1)), float(g.group(2)), g.group(3)
        a = ANIM_RE.search(inner)
        base_y = float(a.group(3)) + 3 if a else y + 3
        info.append((base_y, base_y - y))
    pivot = min(b for b, _ in info)

    it = iter(info)

    def fix(g):
        base_y, cal_h = next(it)
        x, inner = g.group(1), g.group(3)
        new_base = pivot + (base_y - pivot) * r
        new_y = new_base - cal_h

        def anim(a):
            return (f'{a.group(1)}{a.group(2)} {fmt(new_base - 3)};'
                    f'{a.group(4)} {fmt(new_base - cal_h)}{a.group(6)}')
        inner = ANIM_RE.sub(anim, inner)

        # top face: skewY(-a) skewX(t) scale(sx sy)
        def top(t):
            tx = math.degrees(math.atan(math.tan(math.radians(float(t.group(2)))) / r))
            return (f'skewY({fmt(-target)}) skewX({fmt(tx)}) '
                    f'scale({t.group(3)} {fmt(float(t.group(4)) * r)})')
        inner = re.sub(r'skewY\((-[\d.]+)\) skewX\(([\d.\-]+)\) scale\(([\d.]+) ([\d.]+)\)', top, inner)
        # right face: translate(dxx dyy) skewY(-a)
        inner = re.sub(r'translate\(([\d.]+) ([\d.]+)\) skewY\(-[\d.]+\)',
                       lambda t: f'translate({t.group(1)} {fmt(float(t.group(2)) * r)}) skewY({fmt(-target)})', inner)
        # left face: skewY(a) scale
        inner = re.sub(r'skewY\([\d.]+\) scale', f'skewY({fmt(target)}) scale', inner)
        return f'<g transform="translate({x} {fmt(new_y)})">{inner}</g>'

    return GROUP_RE.sub(fix, bars), r


def clean(path):
    s = Path(path).read_text(encoding="utf-8")
    head_end = s.index("</style>") + len("</style>")
    head, body = s[:head_end], s[head_end:-len("</svg>")]

    # the bars are the first top-level <g> with no attributes
    elems = list(top_level(body))
    bars = next(body[a:b] for a, b, n in elems if n == "g")
    # keep <defs> (the bitmap/city theme paints its faces with patterns defined here)
    defs = "".join(body[a:b] for a, b, n in elems if n.startswith("defs"))

    target = float(os.environ.get("SKYLINE_ANGLE", VIEW_ANGLE))
    bars, _ = change_angle(bars, target)
    k = math.tan(math.radians(target)) / math.tan(math.radians(30))  # crop margins scale with the angle

    # bounding box from bar transforms
    xs, ys, hs = [], [], []
    for m in re.finditer(r'<g transform="translate\(([\d.\-]+)[ ,]+([\d.\-]+)\)">', bars):
        xs.append(float(m.group(1)))
        ys.append(float(m.group(2)))
    for m in re.finditer(r'<animate attributeName="height" values="[\d.]+;([\d.]+)"', bars):
        hs.append(float(m.group(1)))
    x0, x1 = min(xs) - PAD, max(xs) + 36 + PAD
    y0, y1 = min(ys) - 20 * k - PAD, max(ys) + 20 * k + (max(hs) if hs else 0) + PAD
    w, h = round(x1 - x0), round(y1 - y0)

    head = re.sub(r'<svg[^>]*>',
                  f'<svg xmlns="http://www.w3.org/2000/svg" width="{w}" height="{h}" '
                  f'viewBox="{x0:.0f} {y0:.0f} {w} {h}">', head, count=1)
    Path(path).write_text(head + defs + bars + "</svg>", encoding="utf-8")
    print(f"{path}: {len(s)//1024} KB -> {(len(head)+len(defs)+len(bars))//1024} KB, "
          f"angle {target:g}, viewBox {w}x{h}")


if __name__ == "__main__":
    for p in sys.argv[1:]:
        clean(p)