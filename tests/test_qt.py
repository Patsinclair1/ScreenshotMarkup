"""Qt (PySide6) front end used on Windows/macOS. Skips where PySide6 isn't installed."""
import os, sys
import pytest

pytest.importorskip("PySide6", reason="requires PySide6 (Windows/macOS front end)")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6.QtGui import QImage, QColor, QGuiApplication
from PySide6.QtWidgets import QApplication

pytestmark = pytest.mark.qt


@pytest.fixture(scope="module")
def mq():
    QApplication.instance() or QApplication([])
    import markup_qt
    return markup_qt


def _img(tmp_path, colour=(255, 255, 255), name="b.png"):
    im = QImage(200, 100, QImage.Format_RGB32); im.fill(QColor(*colour)); p = str(tmp_path / name); im.save(p); return p


def test_render_size_and_untouched(mq, tmp_path):
    base = QImage(_img(tmp_path)).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    out = mq.render(base, [{"tool": "pen", "color": (1, 0, 0), "width": 6, "points": [(10, 50), (190, 50)]}])
    assert out.size() == base.size() and out.pixelColor(100, 50).red() > 200 and out.pixelColor(100, 50).green() < 60
    assert mq.render(base, []) == base


def test_highlighter_multiply_matches_core_maths(mq, tmp_path):
    import markup_core as c
    base = QImage(_img(tmp_path, (200, 200, 200))).convertToFormat(QImage.Format_ARGB32_Premultiplied)
    s = {"tool": "highlighter", "color": (1, 0.92, 0), "width": 8, "alpha": 0.5, "blend": "multiply", "points": [(10, 50), (190, 50)]}
    px = mq.render(base, [s]).pixelColor(100, 50)
    exp = c.blend_pixel((200 / 255,) * 3, s["color"], 0.5, "multiply")
    for got, want in zip((px.redF(), px.greenF(), px.blueF()), exp): assert abs(got - want) < 0.03


def test_blend_auto_dark(mq, tmp_path):
    dark = QImage(_img(tmp_path, (20, 20, 25), "d.png"))
    assert mq.pick_blend(dark, [(50, 50)]) == "screen"


def test_window_tools_undo_save_copy(mq, tmp_path):
    w = mq.Win(_img(tmp_path)); mq.demo_annotations(w)
    n = len(w.doc.objs); assert n == 5
    w.doc.erase(range(n)); assert w.doc.objs == []
    assert w.export_image() == w.base                       # eraser never touches the screenshot
    w.undo(); assert len(w.doc.objs) == n
    p = w.save(str(tmp_path / "out.png")); assert p and QImage(p) != QImage(w.path)
    img = w.copy(); assert QGuiApplication.clipboard().image().size() == img.size()
    w.set_zoom(3.0); assert abs(w.zoom - 3.0) < 1e-9; w.set_zoom(99); assert w.zoom == 8.0
    w.set_bg("dark"); w.close()


def test_capture_demo(mq, tmp_path):
    out = str(tmp_path / "demo.png"); assert mq.capture_demo(out)
    assert QImage(out).width() > 500


def test_tray_watcher_detects_new_file(mq, tmp_path):
    import markup_tray
    got = []; wt = markup_tray.Watcher(str(tmp_path)); wt.new_image.connect(got.append)
    (tmp_path / "Screenshot 2026.png").write_bytes(b"x"); wt.scan()
    app = QApplication.instance(); import time
    t0 = time.time()
    while not got and time.time() - t0 < 3: app.processEvents()
    assert got and got[0].endswith("Screenshot 2026.png")
