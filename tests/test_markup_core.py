"""markup_core: toolkit-free logic shared by GTK and Qt. Runs on every OS."""
import math
import markup_core as c


def bbox(o):  # fixed-metric fake: 10 px per char, height = size
    x, y = o["points"][0]; return (x, y - o["size"], 10 * len(o["text"]), o["size"])


def test_constrain_and_arrow():
    assert c.constrain("rect", (0, 0), (10, 4)) == (10, 10)
    x, y = c.constrain("arrow", (0, 0), (10, 9)); assert math.isclose(x, y, rel_tol=1e-9)
    assert c.arrow_head((0, 0), (100, 0), 4)[1] == (100, 0)


def test_touches_shapes_and_text():
    pen = {"tool": "pen", "width": 4, "points": [(0, 0), (100, 0)]}
    assert c.touches(pen, (50, 3), 2, bbox) and not c.touches(pen, (50, 40), 2, bbox)
    rect = {"tool": "shape", "kind": "rect", "width": 2, "points": [(0, 0), (50, 50)]}
    assert c.touches(rect, (50, 25), 1, bbox) and not c.touches(rect, (25, 25), 1, bbox)
    t = {"tool": "text", "text": "hi", "size": 20, "points": [(10, 30)]}
    assert c.touches(t, (15, 20), 0, bbox)


def test_blend_choice_and_maths():
    assert c.pick_blend_from(lambda x, y: (250, 250, 250), 10, 10, [(5, 5)]) == "multiply"
    assert c.pick_blend_from(lambda x, y: (20, 20, 25), 10, 10, [(5, 5)]) == "screen"
    # multiply never brightens, screen never darkens, alpha 0 is identity
    assert c.blend_pixel((0.8,) * 3, (1, 0.9, 0), 0.5, "multiply")[2] < 0.8
    assert c.blend_pixel((0.1,) * 3, (1, 0.9, 0), 0.5, "screen")[0] > 0.1
    assert c.blend_pixel((0.3, 0.4, 0.5), (1, 0, 0), 0, "multiply") == (0.3, 0.4, 0.5)


def test_doc_undo_move_resize_erase():
    d = c.Doc(bbox)
    i = d.add_text((10, 30), "hello", (1, 0, 0), 20)
    assert d.hit(15, 20) == i and d.hit(500, 500) is None
    d.move(i, 5, 5); assert d.objs[i]["points"][0] == (15, 35)
    d.sel = i; assert d.handle_at(15, 15) == "nw"
    d.resize(i, "se", 115, 75); assert d.objs[i]["size"] > 20
    d.edit(i, "bye"); assert d.objs[i]["text"] == "bye"
    d.add({"tool": "pen", "width": 4, "points": [(0, 100), (50, 100)]})
    d.erase(d.hits_along([(25, 100), (20, 20)], 3)); assert d.objs == []
    for _ in range(5): d.undo()
    assert d.objs[0]["text"] == "hello" and d.objs[0]["points"][0] == (10, 30)


def test_urls_and_ocr_tsv():
    urls = c.find_urls("see https://example.com/a. and www.test.org, mail me@x.com")
    assert "https://example.com/a" in urls and c.normalise_url("www.test.org").startswith("https://")
    hdr = "level\tpage\tblock\tpar\tline\tword\tleft\ttop\twidth\theight\tconf\ttext\n"
    rows = ["5\t1\t1\t1\t1\t1\t20\t20\t60\t20\t95\tVisit", "5\t1\t1\t1\t1\t2\t100\t20\t160\t20\t91\texample.com",
            "5\t1\t1\t1\t2\t1\t20\t60\t60\t20\t10\tjunk"]
    r = c.parse_tesseract_tsv(hdr + "\n".join(rows), scale=2)
    assert r["text"] == "Visit example.com" and r["links"][0]["url"] == "https://example.com"
    assert r["words"][0]["box"] == (10, 10, 30, 10)
    assert c.link_at(r, (60, 15))["label"] == "example.com" and c.link_at(r, (0, 0)) is None


def test_save_naming_and_conf(tmp_path):
    p = tmp_path / "shot.png"
    assert c.default_save_path(str(p)).endswith("shot-marked.png")
    (tmp_path / "shot-marked.png").write_bytes(b"x")
    assert c.default_save_path(str(p)).endswith("shot-marked-2.png")
    cf = tmp_path / "x" / "config.json"; c.save_conf({"bg": "dark"}, str(cf)); assert c.load_conf(str(cf)) == {"bg": "dark"}
    assert c.clamp_zoom(100) == c.ZOOM_MAX and c.clamp_zoom(0) == c.ZOOM_MIN
    assert c.is_new_screenshot("Screenshot 1.png", set()) and not c.is_new_screenshot("a-marked.png", set())
    assert not c.is_new_screenshot("notes.txt", set())
