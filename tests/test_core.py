"""Pure drawing/geometry logic of markup.py (needs GTK 4 only to import the module)."""
import math, re, shutil
import pytest

pytestmark = pytest.mark.gtk


def test_constrain_square_and_45(m):
    assert m.constrain("rect", (0, 0), (10, 4)) == (10, 10)
    x, y = m.constrain("line", (0, 0), (10, 9))
    assert math.isclose(x, y, rel_tol=1e-9)


def test_arrow_head_ends_at_tip(m):
    head = m.arrow_head((0, 0), (100, 0), 4)
    assert head[1] == (100, 0) and len(head) == 3


def test_eraser_hit_test(m):
    pen = {"tool": "pen", "width": 4, "points": [(0, 0), (100, 0)]}
    assert m.touches(pen, (50, 3), 2)
    assert not m.touches(pen, (50, 40), 2)


def test_find_urls(m):
    urls = m.find_urls("see https://example.com/a. and www.test.org, mail me@x.com")
    assert "https://example.com/a" in urls
    assert m.normalise_url("www.test.org").startswith("https://")


def test_default_save_path(m, tmp_path):
    p = tmp_path / "shot.png"
    assert m.default_save_path(str(p)).endswith("shot-marked.png")
    (tmp_path / "shot-marked.png").write_bytes(b"x")
    assert m.default_save_path(str(p)).endswith("shot-marked-2.png")


def test_render_draws_marks_and_keeps_size(m):
    import cairo
    base = cairo.ImageSurface(cairo.FORMAT_ARGB32, 200, 100)
    cr = cairo.Context(base); cr.set_source_rgb(1, 1, 1); cr.paint(); base.flush()
    out = m.render(base, [{"tool": "pen", "color": (1, 0, 0), "width": 6, "points": [(10, 50), (190, 50)]}])
    assert (out.get_width(), out.get_height()) == (200, 100)
    assert bytes(out.get_data()) != bytes(base.get_data())
    assert m.render(base, []).get_data().tobytes() == base.get_data().tobytes()  # nothing drawn = untouched


@pytest.mark.ocr
@pytest.mark.skipif(shutil.which("tesseract") is None, reason="requires tesseract (OCR) on PATH")
def test_find_tesseract(m):
    assert m.find_tesseract()
