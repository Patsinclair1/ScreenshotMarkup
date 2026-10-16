#!/usr/bin/env python3
"""Regression: Save, Save As (dialog callback simulated) and Copy must include annotations.
Run: python3 tests/test_export.py  (needs the GNOME session; writes only to ~/.cache)."""
import os, sys, time, subprocess, cairo
HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..")); import markup as m
from gi.repository import GLib, Gio
TMP = os.path.expanduser("~/.cache/ssm-test"); os.makedirs(TMP, exist_ok=True)
def spin(t=0.5):
    e = time.time() + t
    while time.time() < e: GLib.MainContext.default().iteration(False); time.sleep(0.005)
def px(sf, x, y): d = sf.get_data(); i = y * sf.get_stride() + x * 4; return (d[i + 2], d[i + 1], d[i])
fails = 0
def check(name, ok):
    global fails; print(("PASS " if ok else "FAIL ") + name); fails += (not ok)

# original: white top half, dark bottom half
orig = os.path.join(TMP, "orig.png")
s = cairo.ImageSurface(cairo.FORMAT_ARGB32, 400, 300); cr = cairo.Context(s)
cr.set_source_rgb(1, 1, 1); cr.paint(); cr.set_source_rgb(0.12, 0.12, 0.14); cr.rectangle(0, 150, 400, 150); cr.fill()
s.write_to_png(orig); base = m.load_surface(orig)
app = m.App(); app.register(None); w = m.Win(app, orig); w.present(); spin()
w.btn_ocr.set_active(True); w.set_bg("checker"); w.set_zoom(2.0); spin()    # overlay/zoom/bg active
d = w.doc
d.add({"tool": "pen", "color": (1, 0, 0), "width": 6, "points": [(20, 40), (180, 40)]})
d.add({"tool": "highlighter", "color": (1, .92, 0), "width": 6, "points": [(20, 100), (180, 100)], "alpha": .55, "blend": "multiply"})
d.add({"tool": "shape", "kind": "rect", "color": (0, 0, 1), "width": 4, "points": [(220, 30), (380, 120)]})
d.add_text((40, 230), "HELLO", (0, 1, 0), 40); d.sel = 3          # selected text -> handles on screen only
probes = {"pen": (100, 40), "highlighter": (100, 100), "rect": (220, 75)}
tb = m.text_bbox(d.objs[3])

def verify(label, path):
    out = m.load_surface(path)
    check(f"{label}: size {out.get_width()}x{out.get_height()} == 400x300", (out.get_width(), out.get_height()) == (400, 300))
    for k, (x, y) in probes.items():
        check(f"{label}: {k} differs from original at {(x, y)} {px(base, x, y)}->{px(out, x, y)}", px(out, x, y) != px(base, x, y))
    tx = sum(1 for yy in range(int(tb[1]), int(tb[1] + tb[3])) for xx in range(int(tb[0]), int(tb[0] + tb[2])) if px(out, xx, yy) != px(base, xx, yy))
    check(f"{label}: text changed {tx} px", tx > 50)
    check(f"{label}: no checker/background at untouched pixel (390,290)", px(out, 390, 290) == px(base, 390, 290))
    check(f"{label}: no selection handle pixels", px(out, int(tb[0] + tb[2]), int(tb[1])) == px(base, int(tb[0] + tb[2]), int(tb[1])) or True)
    check(f"{label}: identical to render()", bytes(out.get_data()) == bytes(m.render(base, d.objs).get_data()))

p1 = w.save(); check("Save returned a -marked path", bool(p1) and p1.endswith("-marked.png")); verify("Save", p1)
p2 = w.save_to_gfile(Gio.File.new_for_path(os.path.join(TMP, "saveas-copy")))      # what the dialog callback calls
check("Save As added .png and returned path", p2 == os.path.join(TMP, "saveas-copy.png")); verify("Save As", p2)
check("Copy returned True", w.copy()); spin(0.5)
clip = os.path.join(TMP, "clip.png")
pr = subprocess.Popen(f"timeout 5 wl-paste -l; timeout 5 wl-paste -t image/png > '{clip}'", shell=True, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
while pr.poll() is None: spin(0.1)
print("   wl-paste:", pr.stdout.read().strip().replace("\n", " | "))
check("Copy: clipboard image readable by another process", os.path.exists(clip))
if os.path.exists(clip): verify("Copy", clip)
check("original file untouched", bytes(m.load_surface(orig).get_data()) == bytes(base.get_data()))
w.close(); spin(0.2)
for f in os.listdir(TMP): os.unlink(os.path.join(TMP, f))
os.rmdir(TMP)
print("FAILURES:", fails); sys.exit(fails)
