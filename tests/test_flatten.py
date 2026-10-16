"""Every annotation type is flattened into the exported PNG, and Copy uses the same bytes as Save."""
import io
import types

import pytest

cairo = pytest.importorskip("cairo", reason="requires GTK/Wayland: pycairo (Linux GTK build) not installed")

pytestmark = pytest.mark.gtk
W, H = 320, 200


def _px(sf, x, y):
    d = sf.get_data(); i = y * sf.get_stride() + x * 4
    return d[i + 2], d[i + 1], d[i]


def _fake_win(m):
    base = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H)
    cr = cairo.Context(base); cr.set_source_rgb(1, 1, 1); cr.paint()
    doc = m.core.Doc(m.text_bbox)
    doc.add({"tool": "pen", "color": (1, 0, 0), "width": 6, "points": [(10, 20), (150, 20)]})
    doc.add({"tool": "highlighter", "color": (1, .92, 0), "width": 6, "points": [(10, 60), (150, 60)],
             "alpha": .55, "blend": "multiply"})
    doc.add({"tool": "shape", "kind": "rect", "color": (0, 0, 1), "width": 4, "points": [(170, 10), (310, 80)]})
    doc.add({"tool": "shape", "kind": "ellipse", "color": (1, 0, 1), "width": 5, "points": [(170, 100), (310, 190)]})
    doc.add({"tool": "shape", "kind": "arrow", "color": (0, .5, 0), "width": 4, "points": [(10, 180), (150, 180)]})
    doc.add({"tool": "pen", "color": (0, 1, 1), "width": 8, "points": [(20, 140), (60, 140)]})
    doc.erase([5])
    doc.add_text((10, 120), "HI", (0, 0, 0), 30)
    w = types.SimpleNamespace(base=base, doc=doc, said=[])
    w.say = w.said.append
    w.export_surface = lambda: m.Win.export_surface(w)
    w.export_png_bytes = lambda: m.Win.export_png_bytes(w)
    return w


def test_export_png_contains_every_annotation_type(m):
    w = _fake_win(m)
    out = cairo.ImageSurface.create_from_png(io.BytesIO(w.export_png_bytes()))
    assert (out.get_width(), out.get_height()) == (W, H)            # full resolution
    assert _px(out, 80, 20) == (255, 0, 0)                          # pen
    r, g, b = _px(out, 80, 60); assert r > 240 and g > 200 and b < 160   # highlighter
    assert _px(out, 170, 45) == (0, 0, 255)                         # rect
    assert _px(out, 170, 145) == (255, 0, 255)                      # ellipse / circle
    assert _px(out, 80, 180)[1] > 100 and _px(out, 80, 180)[0] < 50  # arrow
    assert _px(out, 40, 140) == (255, 255, 255)                     # erased stroke gone
    tb = m.text_bbox(w.doc.objs[-1])
    dark = sum(1 for y in range(int(tb[1]), int(tb[1] + tb[3])) for x in range(int(tb[0]), int(tb[0] + tb[2]))
               if _px(out, x, y)[0] < 100)
    assert dark > 30                                                # text
    assert _px(out, 315, 195) == (255, 255, 255)                    # untouched


def test_copy_uses_same_flattened_png_as_save(m, monkeypatch):
    w = _fake_win(m)
    got = []
    monkeypatch.setattr(m, "copy_png_wl", lambda png: got.append(png) or True)
    assert m.Win.copy(w) is True
    assert got and got[0] == w.export_png_bytes()
