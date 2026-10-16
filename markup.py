#!/usr/bin/env python3
"""Screenshot Markup - tiny GTK4 annotator (pen, multiply highlighter, colour, undo, save, copy)."""
import os, sys, math
import gi
gi.require_version("Gtk", "4.0"); gi.require_version("Gdk", "4.0"); gi.require_version("GdkPixbuf", "2.0")
from gi.repository import Gtk, Gdk, GdkPixbuf, Gio, GLib
import cairo, warnings
warnings.filterwarnings("ignore", category=DeprecationWarning)

APP_ID = "dev.paddy.ScreenshotMarkup"
HL_ALPHA = 0.55


def load_surface(path):
    pb = GdkPixbuf.Pixbuf.new_from_file(path)
    surf = cairo.ImageSurface(cairo.FORMAT_ARGB32, pb.get_width(), pb.get_height())
    cr = cairo.Context(surf)
    Gdk.cairo_set_source_pixbuf(cr, pb, 0, 0)
    cr.paint()
    return surf


def constrain(kind, p0, p1):
    """Shift: square / circle for rect+ellipse, 45-degree snaps for line+arrow."""
    dx, dy = p1[0] - p0[0], p1[1] - p0[1]
    if kind in ("rect", "ellipse"):
        m = max(abs(dx), abs(dy))
        return (p0[0] + math.copysign(m, dx or 1), p0[1] + math.copysign(m, dy or 1))
    ang = round(math.atan2(dy, dx) / (math.pi / 4)) * (math.pi / 4); d = math.hypot(dx, dy)
    return (p0[0] + d * math.cos(ang), p0[1] + d * math.sin(ang))


def arrow_head(p0, p1, w):
    L = max(10, w * 4); a = math.atan2(p1[1] - p0[1], p1[0] - p0[0])
    return [(p1[0] - L * math.cos(a - 0.45), p1[1] - L * math.sin(a - 0.45)), p1,
            (p1[0] - L * math.cos(a + 0.45), p1[1] - L * math.sin(a + 0.45))]


def shape_points(s):
    """Outline polylines of an annotation in image coords (used for eraser hit tests)."""
    t = s["tool"]; pts = s["points"]
    if t == "shape":
        (x0, y0), (x1, y1) = pts[0], pts[-1]; k = s["kind"]
        if k == "rect": return [[(x0, y0), (x1, y0), (x1, y1), (x0, y1), (x0, y0)]]
        if k == "ellipse":
            cx, cy, rx, ry = (x0 + x1) / 2, (y0 + y1) / 2, abs(x1 - x0) / 2, abs(y1 - y0) / 2
            return [[(cx + rx * math.cos(i * math.pi / 24), cy + ry * math.sin(i * math.pi / 24)) for i in range(49)]]
        if k == "arrow": return [[pts[0], pts[-1]], arrow_head(pts[0], pts[-1], s["width"])]
        return [[pts[0], pts[-1]]]
    return [pts]


def _seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p; vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - ax - t * vx, py - ay - t * vy)


def touches(s, p, r):
    """Does an eraser of radius r at point p touch annotation s?"""
    if s["tool"] == "text":
        x, y, w, h = text_bbox(s)
        return x - r <= p[0] <= x + w + r and y - r <= p[1] <= y + h + r
    half = s["width"] * (2 if s["tool"] == "highlighter" else 0.5)
    for poly in shape_points(s):
        if len(poly) == 1 and math.hypot(p[0] - poly[0][0], p[1] - poly[0][1]) <= r + half: return True
        for a, b in zip(poly, poly[1:]):
            if _seg_dist(p, a, b) <= r + half: return True
    return False


def pick_blend(base, pts):
    """Mean luminance of the image under the stroke -> 'multiply' (light) or 'screen' (dark)."""
    try:
        base.flush(); d = base.get_data(); st = base.get_stride(); W, H = base.get_width(), base.get_height()
        step = max(1, len(pts) // 200); tot = n = 0
        for x, y in pts[::step]:
            for ox in (-3, 0, 3):
                for oy in (-3, 0, 3):
                    xi, yi = int(x) + ox, int(y) + oy
                    if 0 <= xi < W and 0 <= yi < H:
                        i = yi * st + xi * 4
                        tot += 0.0722 * d[i] + 0.7152 * d[i + 1] + 0.2126 * d[i + 2]; n += 1
        return "screen" if n and tot / n < 110 else "multiply"
    except Exception:
        return "multiply"


def draw_stroke(cr, s):
    pts = s["points"]
    if not pts:
        return
    r, g, b = s["color"]
    if s["tool"] == "text":
        cr.save(); cr.set_source_rgb(r, g, b)
        cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
        cr.set_font_size(s.get("size", s.get("width", 4) * 4))
        cr.move_to(*pts[0]); cr.show_text(s["text"]); cr.restore()
        return
    if s["tool"] == "shape":
        cr.save(); cr.set_source_rgb(r, g, b); cr.set_line_width(s["width"])
        cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
        if s["kind"] == "ellipse":
            (x0, y0), (x1, y1) = pts[0], pts[-1]
            rx, ry = abs(x1 - x0) / 2, abs(y1 - y0) / 2
            if rx > 0.5 and ry > 0.5:
                cr.save(); cr.translate((x0 + x1) / 2, (y0 + y1) / 2); cr.scale(rx, ry)
                cr.arc(0, 0, 1, 0, 2 * math.pi); cr.restore(); cr.stroke()
        else:
            for poly in shape_points(s):
                cr.move_to(*poly[0])
                for q in poly[1:]: cr.line_to(*q)
                cr.stroke()
        cr.restore(); return
    def path():
        cr.move_to(*pts[0])
        if len(pts) == 1:
            cr.line_to(pts[0][0] + 0.1, pts[0][1])
        for p in pts[1:]:
            cr.line_to(*p)
    cr.save()
    if s["tool"] == "highlighter":
        # Draw the whole stroke opaque into a group (no self-overlap darkening),
        # then multiply it onto the image so the text underneath shows through.
        cr.push_group()
        cr.set_source_rgb(r, g, b)
        cr.set_line_width(s["width"] * 4)
        cr.set_line_cap(cairo.LINE_CAP_BUTT)      # flat chisel ends
        cr.set_line_join(cairo.LINE_JOIN_BEVEL)
        path(); cr.stroke()
        cr.pop_group_to_source()
        # multiply on light backgrounds; screen (lighten) on dark ones, where
        # multiply would vanish into the dark pixels. Chosen per stroke.
        cr.set_operator(cairo.OPERATOR_SCREEN if s.get("blend") == "screen" else cairo.OPERATOR_MULTIPLY)
        cr.paint_with_alpha(s.get("alpha", HL_ALPHA))
    else:
        cr.set_source_rgb(r, g, b)
        cr.set_line_width(s["width"])
        cr.set_line_cap(cairo.LINE_CAP_ROUND); cr.set_line_join(cairo.LINE_JOIN_ROUND)
        path(); cr.stroke()
    cr.restore()


def render(base, strokes):
    out = cairo.ImageSurface(cairo.FORMAT_ARGB32, base.get_width(), base.get_height())
    cr = cairo.Context(out)
    cr.set_source_surface(base, 0, 0); cr.paint()
    for s in strokes:
        draw_stroke(cr, s)
    out.flush()
    return out


def default_save_path(path):
    root, _ = os.path.splitext(path)
    cand = root + "-marked.png"; n = 2
    while os.path.exists(cand):
        cand = f"{root}-marked-{n}.png"; n += 1
    return cand


def surface_to_texture(surf):
    import tempfile
    fd, tmp = tempfile.mkstemp(suffix=".png"); os.close(fd)
    surf.write_to_png(tmp)
    tex = Gdk.Texture.new_from_filename(tmp); os.unlink(tmp)
    return tex


import copy
_scratch = cairo.Context(cairo.ImageSurface(cairo.FORMAT_ARGB32, 1, 1))
HANDLE = 8


def text_bbox(o):
    cr = _scratch; cr.select_font_face("Sans", cairo.FONT_SLANT_NORMAL, cairo.FONT_WEIGHT_BOLD)
    cr.set_font_size(o["size"]); fe = cr.font_extents(); te = cr.text_extents(o["text"] or " ")
    x, y = o["points"][0]
    return (x, y - fe[0], max(te.x_advance, 4), fe[0] + fe[1])


class Doc:
    """Objects + snapshot undo. Every user action = one push()."""
    def __init__(self):
        self.objs = []; self.hist = []; self.sel = None
    def push(self):
        self.hist.append((copy.deepcopy(self.objs), self.sel))
    def undo(self):
        if self.hist:
            self.objs, self.sel = self.hist.pop()
            if self.sel is not None and self.sel >= len(self.objs): self.sel = None
    def add(self, o):
        self.push(); self.objs.append(o); return len(self.objs) - 1
    def add_text(self, pt, text, color, size):
        return self.add({"tool": "text", "color": color, "size": size, "points": [pt], "text": text})
    def hit(self, x, y):
        for i in range(len(self.objs) - 1, -1, -1):
            o = self.objs[i]
            if o["tool"] == "text":
                bx, by, bw, bh = text_bbox(o)
                if bx - 4 <= x <= bx + bw + 4 and by - 4 <= y <= by + bh + 4: return i
        return None
    def handle_at(self, x, y, tol=HANDLE):
        if self.sel is None: return None
        for name, (hx, hy) in corners(text_bbox(self.objs[self.sel])).items():
            if abs(x - hx) <= tol and abs(y - hy) <= tol: return name
        return None
    def move(self, i, dx, dy, push=True):
        if push: self.push()
        x, y = self.objs[i]["points"][0]; self.objs[i]["points"][0] = (x + dx, y + dy)
    def resize(self, i, handle, nx, ny, base=None, push=True):
        """Drag corner `handle` to (nx,ny); opposite corner stays fixed; font scales."""
        if push: self.push()
        o = self.objs[i]; b = base or copy.deepcopy(o)
        c = corners(text_bbox(b)); opp = c[OPP[handle]]; old = c[handle]
        od = math.hypot(old[0] - opp[0], old[1] - opp[1]) or 1
        nd = math.hypot(nx - opp[0], ny - opp[1])
        o["size"] = max(4.0, b["size"] * nd / od); o["points"][0] = b["points"][0]
        nb = corners(text_bbox(o))[OPP[handle]]
        x, y = o["points"][0]; o["points"][0] = (x + opp[0] - nb[0], y + opp[1] - nb[1])
    def edit(self, i, text):
        self.push(); self.objs[i]["text"] = text
    def erase(self, idxs):
        """Remove several annotations as ONE undo step. Never touches the image."""
        idxs = sorted(set(idxs), reverse=True)
        if not idxs: return
        self.push()
        for i in idxs: del self.objs[i]
        self.sel = None
    def hits_along(self, pts, r):
        return {i for i, o in enumerate(self.objs) if any(touches(o, p, r) for p in pts)}
    def delete(self, i):
        self.push(); del self.objs[i]; self.sel = None


OPP = {"nw": "se", "se": "nw", "ne": "sw", "sw": "ne"}
def corners(b):
    x, y, w, h = b
    return {"nw": (x, y), "ne": (x + w, y), "sw": (x, y + h), "se": (x + w, y + h)}


def draw_selection(cr, o, scale=1.0):
    x, y, w, h = text_bbox(o); lw = 1.5 / scale; hs = HANDLE / scale
    cr.save(); cr.set_line_width(lw); cr.set_dash([4 / scale, 3 / scale])
    cr.set_source_rgb(0.2, 0.5, 1); cr.rectangle(x - 3 / scale, y - 3 / scale, w + 6 / scale, h + 6 / scale); cr.stroke()
    cr.set_dash([])
    for hx, hy in corners((x, y, w, h)).values():
        cr.rectangle(hx - hs / 2, hy - hs / 2, hs, hs); cr.set_source_rgb(1, 1, 1); cr.fill_preserve()
        cr.set_source_rgb(0.2, 0.5, 1); cr.stroke()
    cr.restore()


# ---------------- OCR (tesseract, per-user via Homebrew) ----------------
import re, shutil, subprocess, tempfile, threading

def find_tesseract():
    for c in (shutil.which("tesseract"), "/home/linuxbrew/.linuxbrew/bin/tesseract",
              os.path.expanduser("~/.linuxbrew/bin/tesseract")):
        if c and os.access(c, os.X_OK): return c
    return None

URL_RE = re.compile(r"""(?ix)\b(
    (?:https?://|www\.)[^\s<>"'()]+ |
    (?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+
    (?:com|org|net|io|dev|co|uk|ai|app|gov|edu|me|sh|xyz|tv|gg|info|biz|us|eu|de|fr|so|ly|to)
    (?::\d+)?(?:/[^\s<>"'()]*)?
)""")

def find_urls(text):
    out = []
    for m in URL_RE.finditer(text):
        u = m.group(1).rstrip(".,;:!?)]}")
        if "@" in text[max(0, m.start() - 1):m.start()]: continue   # skip emails
        out.append(u)
    return out

def normalise_url(u):
    return u if re.match(r"(?i)https?://", u) else "https://" + u

def launch_uri(uri, parent=None):
    """Open in default browser. Module-level so tests can mock it."""
    Gtk.UriLauncher(uri=uri).launch(parent, None, None)

def run_ocr(path, scale=2):
    """Returns {'words','lines','text','links'}; boxes are (x,y,w,h) in image px."""
    exe = find_tesseract()
    if not exe: raise RuntimeError("OCR engine not found. Install it with:  brew install tesseract")
    src = load_surface(path); W, H = src.get_width() * scale, src.get_height() * scale
    big = cairo.ImageSurface(cairo.FORMAT_ARGB32, W, H); cr = cairo.Context(big)
    cr.set_source_rgb(1, 1, 1); cr.paint(); cr.scale(scale, scale); cr.set_source_surface(src, 0, 0)
    cr.get_source().set_filter(cairo.FILTER_BEST); cr.paint()
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ssm-ocr-"); os.close(fd)
    try:
        big.write_to_png(tmp)
        out = subprocess.run([exe, tmp, "stdout", "--psm", "3", "tsv"], capture_output=True, text=True, timeout=120)
    finally:
        os.unlink(tmp)
    if out.returncode != 0: raise RuntimeError("tesseract failed: " + out.stderr.strip()[:200])
    words, lines = [], {}
    for row in out.stdout.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip(): continue
        try: conf = float(f[10])
        except ValueError: continue
        if conf < 30: continue
        box = tuple(int(v) / scale for v in f[6:10])
        w = {"text": f[11].strip(), "box": box}; words.append(w)
        lines.setdefault((int(f[2]), int(f[3]), int(f[4])), []).append(w)
    line_objs = []
    for k in sorted(lines):
        ws = lines[k]; x0 = min(w["box"][0] for w in ws); y0 = min(w["box"][1] for w in ws)
        x1 = max(w["box"][0] + w["box"][2] for w in ws); y1 = max(w["box"][1] + w["box"][3] for w in ws)
        line_objs.append({"text": " ".join(w["text"] for w in ws), "box": (x0, y0, x1 - x0, y1 - y0)})
    links = []
    for w in words:
        for u in find_urls(w["text"]):
            links.append({"url": normalise_url(u), "label": u, "box": w["box"]})
    return {"words": words, "lines": line_objs, "text": "\n".join(l["text"] for l in line_objs), "links": links}

def link_at(ocr, pt, pad=3):
    for l in (ocr or {}).get("links", []):
        x, y, w, h = l["box"]
        if x - pad <= pt[0] <= x + w + pad and y - pad <= pt[1] <= y + h + pad: return l
    return None

def draw_ocr_overlay(cr, ocr, scale=1.0):
    """Display-only. Never called by render()."""
    cr.save(); cr.set_line_width(1 / scale)
    for w in ocr["words"]:
        x, y, ww, hh = w["box"]; cr.rectangle(x - 1, y - 1, ww + 2, hh + 2)
    cr.set_source_rgba(0.2, 0.6, 1.0, 0.10); cr.fill_preserve()
    cr.set_source_rgba(0.2, 0.6, 1.0, 0.55); cr.stroke()
    for l in ocr["links"]:
        x, y, ww, hh = l["box"]; cr.rectangle(x - 2, y - 2, ww + 4, hh + 4)
        cr.set_source_rgba(0.0, 0.85, 0.35, 0.22); cr.fill_preserve()
        cr.set_source_rgba(0.0, 0.7, 0.3, 0.95); cr.set_line_width(2 / scale); cr.stroke()
        cr.move_to(x, y + hh + 2); cr.line_to(x + ww, y + hh + 2); cr.stroke()
    cr.restore()


# ---------------- config + zoom ----------------
import json
CONF_PATH = os.path.expanduser("~/.config/screenshot-markup/config.json")
ZOOM_MIN, ZOOM_MAX = 0.10, 8.0
BG_PRESETS = {"light": (0.92, 0.92, 0.92), "dark": (0.16, 0.16, 0.18), "checker": None}

def load_conf():
    try:
        with open(CONF_PATH) as f: return json.load(f)
    except Exception: return {}

def save_conf(c):
    try:
        os.makedirs(os.path.dirname(CONF_PATH), exist_ok=True)
        tmp = CONF_PATH + ".tmp"
        with open(tmp, "w") as f: json.dump(c, f, indent=1)
        os.replace(tmp, CONF_PATH)
    except Exception as e: print("config save failed:", e, file=sys.stderr)

def paint_background(cr, w, h, bg):
    """Canvas backdrop outside the image. Display only; render() never calls it."""
    if bg == "checker" or bg is None:
        cr.set_source_rgb(0.80, 0.80, 0.80); cr.paint(); cr.set_source_rgb(0.62, 0.62, 0.62)
        t = 12
        for yy in range(0, int(h) + t, t):
            for xx in range((yy // t % 2) * t, int(w) + t, 2 * t): cr.rectangle(xx, yy, t, t)
        cr.fill()
    else:
        cr.set_source_rgb(*bg); cr.paint()


class Win(Gtk.ApplicationWindow):
    def __init__(self, app, path):
        super().__init__(application=app, title=os.path.basename(path))
        self.path = path; self.base = load_surface(path)
        self.doc = Doc(); self.cur = None; self.erasing = None; self.tool = "pen"; self.drag = None
        self.color = (0.9, 0.1, 0.1); self.hl_color = (1.0, 0.92, 0.0)
        self.width = 4
        w, h = self.base.get_width(), self.base.get_height()
        self.set_default_size(min(w, 1400) + 20, min(h, 900) + 80)

        hb = Gtk.HeaderBar(); self.set_titlebar(hb)
        box = Gtk.Box(spacing=6); hb.set_title_widget(box)
        self.btn_sel = Gtk.ToggleButton(icon_name="edit-select-symbolic", tooltip_text="Select / move text (V)")
        self.btn_sel.set_child(Gtk.Label(label="⬉"))
        self.btn_pen = Gtk.ToggleButton(icon_name="document-edit-symbolic", tooltip_text="Pen (P)", active=True, group=self.btn_sel)
        self.btn_hl = Gtk.ToggleButton(tooltip_text="Highlighter (H)", group=self.btn_sel)
        self.btn_hl.set_child(Gtk.Label(label="🖍"))
        self.btn_txt = Gtk.ToggleButton(icon_name="insert-text-symbolic", tooltip_text="Text (T)", group=self.btn_sel)
        self.shape = "rect"; self.shape_lbl = {"rect": "▭", "ellipse": "◯", "arrow": "➚", "line": "╱"}
        self.btn_shape = Gtk.ToggleButton(tooltip_text="Shapes (S)", group=self.btn_sel)
        self.btn_shape.set_child(Gtk.Label(label=self.shape_lbl["rect"]))
        self.btn_eraser = Gtk.ToggleButton(icon_name="edit-clear-symbolic", tooltip_text="Eraser (E)", group=self.btn_sel)
        for b, t in ((self.btn_sel, "select"), (self.btn_pen, "pen"), (self.btn_hl, "highlighter"),
                     (self.btn_txt, "text"), (self.btn_shape, "shape"), (self.btn_eraser, "eraser")):
            b.connect("toggled", self.on_tool, t); b.set_focusable(False)
        menu = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        self.shape_pop = Gtk.Popover(child=menu)
        for k, name in (("rect", "Rectangle"), ("ellipse", "Ellipse"), ("arrow", "Arrow"), ("line", "Line")):
            mb = Gtk.Button(label=f"{self.shape_lbl[k]}  {name}", css_classes=["flat"], focusable=False)
            mb.connect("clicked", lambda _b, k=k: self.pick_shape(k)); menu.append(mb)
        self.shape_menu = Gtk.MenuButton(popover=self.shape_pop, tooltip_text="Choose shape", focusable=False,
                                         icon_name="pan-down-symbolic", css_classes=["flat"])
        shape_box = Gtk.Box(css_classes=["linked"]); shape_box.append(self.btn_shape); shape_box.append(self.shape_menu)
        for b in (self.btn_sel, self.btn_pen, self.btn_hl, self.btn_txt): box.append(b)
        box.append(shape_box); box.append(self.btn_eraser)
        self.btn_ocr = Gtk.ToggleButton(icon_name="format-justify-left-symbolic", tooltip_text="Transcript / OCR (R)", focusable=False)
        self.btn_ocr.connect("toggled", self.on_ocr_toggle); box.append(self.btn_ocr)
        self.ocr = None; self.ocr_busy = False; self.ocr_visible = True
        self.cbtn = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), tooltip_text="Colour")
        self._set_cbtn(self.color); self.cbtn.connect("notify::rgba", self.on_color); box.append(self.cbtn)
        self.scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 1, 40, 1)
        self.scale.set_value(self.width); self.scale.set_draw_value(False); self.scale.set_size_request(120, -1)
        self.scale.set_tooltip_text("Size"); self.scale.set_focusable(False)
        self.scale.connect("value-changed", lambda s: setattr(self, "width", int(s.get_value()))); box.append(self.scale)
        self.hl_alpha = float(load_conf().get("hl_strength", HL_ALPHA))
        box.append(Gtk.Label(label="Strength", css_classes=["dim-label"]))
        self.str_scale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, 10, 100, 5)
        self.str_scale.set_value(round(self.hl_alpha * 100)); self.str_scale.set_draw_value(False)
        self.str_scale.set_size_request(90, -1); self.str_scale.set_focusable(False)
        self.str_scale.set_tooltip_text(f"Highlighter strength {round(self.hl_alpha * 100)}%")
        self.str_scale.connect("value-changed", self.on_strength); box.append(self.str_scale)
        for icon, tip, cb in (("edit-undo-symbolic", "Undo (Ctrl+Z)", self.undo),
                              ("edit-copy-symbolic", "Copy (Ctrl+C)", self.copy),
                              ("document-save-symbolic", "Save copy (Ctrl+S)", self.save),
                              ("document-save-as-symbolic", "Save as… (Ctrl+Shift+S)", self.save_as)):
            b = Gtk.Button(icon_name=icon, tooltip_text=tip, focusable=False); b.connect("clicked", lambda _b, c=cb: c()); box.append(b)

        self.conf = load_conf()
        bg = self.conf.get("bg", "light")
        self.bg = bg if bg == "checker" else tuple(bg) if isinstance(bg, list) else BG_PRESETS.get(bg, BG_PRESETS["light"])
        self.fit = True; self.zoom = 1.0; self._anchor = None; self.space = False; self.pan = None
        self.area = Gtk.DrawingArea(hexpand=True, vexpand=True, focusable=True)
        self.area.set_draw_func(self.on_draw)
        self.scroller = Gtk.ScrolledWindow(child=self.area, hexpand=True, vexpand=True)
        self.area.connect("resize", lambda *_: self._after_layout())
        canvas_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL)
        canvas_box.append(self.scroller); canvas_box.append(self._build_zoombar())
        ov = Gtk.Overlay(); ov.set_child(canvas_box)
        self.toast = Gtk.Label(css_classes=["osd"], halign=Gtk.Align.CENTER, valign=Gtk.Align.END, margin_bottom=12, visible=False)
        ov.add_overlay(self.toast)
        # Transcript side panel
        side = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=6, margin_top=6, margin_bottom=6,
                       margin_start=6, margin_end=6, width_request=300)
        hdr = Gtk.Box(spacing=6); hdr.append(Gtk.Label(label="<b>Transcript</b>", use_markup=True, hexpand=True, xalign=0))
        self.chk_overlay = Gtk.CheckButton(label="Overlay", active=True, focusable=False)
        self.chk_overlay.connect("toggled", lambda c: (setattr(self, "ocr_visible", c.get_active()), self.area.queue_draw()))
        hdr.append(self.chk_overlay)
        cpy = Gtk.Button(label="Copy all", focusable=False); cpy.connect("clicked", lambda _b: self.copy_transcript()); hdr.append(cpy)
        side.append(hdr)
        self.ocr_status = Gtk.Label(xalign=0, wrap=True, css_classes=["dim-label"]); side.append(self.ocr_status)
        self.links_box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL); side.append(self.links_box)
        self.tview = Gtk.TextView(editable=False, cursor_visible=False, wrap_mode=Gtk.WrapMode.WORD_CHAR, monospace=False)
        sc = Gtk.ScrolledWindow(vexpand=True, child=self.tview); side.append(sc)
        side.set_size_request(0, -1); side.set_visible(False); self.side = side
        self.paned = Gtk.Paned(orientation=Gtk.Orientation.HORIZONTAL, start_child=ov, end_child=side,
                               resize_start_child=True, shrink_start_child=True,
                               resize_end_child=False, shrink_end_child=True, wide_handle=True)
        self.paned.connect("notify::position", self._on_paned_pos)
        self.set_child(self.paned)
        scroll = Gtk.EventControllerScroll(flags=Gtk.EventControllerScrollFlags.VERTICAL)
        scroll.connect("scroll", self.on_scroll); self.area.add_controller(scroll)
        self._ptr = (0, 0); mot = Gtk.EventControllerMotion()
        mot.connect("motion", lambda c, x, y: setattr(self, "_ptr", (x, y))); self.area.add_controller(mot)
        mid = Gtk.GestureDrag(button=Gdk.BUTTON_MIDDLE)
        mid.connect("drag-begin", lambda g, x, y: self._pan_begin())
        mid.connect("drag-update", lambda g, dx, dy: self._pan_update(dx, dy)); self.area.add_controller(mid)
        krel = Gtk.EventControllerKey(); krel.connect("key-released", self.on_key_release); self.add_controller(krel)
        drag = Gtk.GestureDrag(); drag.connect("drag-begin", self.d_begin); drag.connect("drag-update", self.d_update)
        drag.connect("drag-end", self.d_end); self.area.add_controller(drag)
        click = Gtk.GestureClick(); click.connect("pressed", self.on_click); self.area.add_controller(click)
        keys = Gtk.EventControllerKey(); keys.connect("key-pressed", self.on_key); self.add_controller(keys)

    def _set_cbtn(self, c):
        rgba = Gdk.RGBA(); rgba.red, rgba.green, rgba.blue, rgba.alpha = c[0], c[1], c[2], 1; self.cbtn.set_rgba(rgba)

    def on_strength(self, sc):
        self.hl_alpha = sc.get_value() / 100; sc.set_tooltip_text(f"Highlighter strength {round(sc.get_value())}%")
        if hasattr(self, "conf"):
            self.conf["hl_strength"] = round(self.hl_alpha, 2)
            if getattr(self, "_st_timer", None): GLib.source_remove(self._st_timer)
            self._st_timer = GLib.timeout_add(400, lambda: (setattr(self, "_st_timer", None), save_conf(self.conf), False)[2])

    def pick_shape(self, k):
        self.shape = k; self.btn_shape.get_child().set_label(self.shape_lbl[k])
        self.btn_shape.set_active(True); self.shape_pop.popdown()

    def on_tool(self, b, t):
        if b.get_active():
            self.tool = t
            self._set_cbtn(self.hl_color if t == "highlighter" else self.color)
            if t != "select": self.doc.sel = None; self.area.queue_draw()

    def on_color(self, *_):
        c = self.cbtn.get_rgba(); c = (c.red, c.green, c.blue)
        if self.tool == "highlighter": self.hl_color = c
        else: self.color = c

    def _xf(self):
        """(scale, offset_x, offset_y) mapping image px -> area px."""
        w, h = max(1, self.area.get_width()), max(1, self.area.get_height())
        bw, bh = self.base.get_width(), self.base.get_height()
        if self.fit:
            vw = max(1, self.scroller.get_width()); vh = max(1, self.scroller.get_height())
            self.zoom = max(ZOOM_MIN, min(ZOOM_MAX, vw / bw, vh / bh))
        s = self.zoom
        return s, max(0.0, (w - bw * s) / 2), max(0.0, (h - bh * s) / 2)

    # ---- zoom
    def _build_zoombar(self):
        bar = Gtk.Box(spacing=6, margin_start=6, margin_end=6, margin_top=3, margin_bottom=3)
        def btn(label, tip, cb):
            b = Gtk.Button(label=label, tooltip_text=tip, focusable=False, css_classes=["flat"]); b.connect("clicked", lambda _b: cb()); bar.append(b); return b
        btn("−", "Zoom out (Ctrl+-)", lambda: self.zoom_step(1 / 1.25))
        self.zscale = Gtk.Scale.new_with_range(Gtk.Orientation.HORIZONTAL, math.log(ZOOM_MIN), math.log(ZOOM_MAX), 0.01)
        self.zscale.set_draw_value(False); self.zscale.set_size_request(180, -1); self.zscale.set_focusable(False)
        self._zs_guard = False
        self.zscale.connect("value-changed", lambda sc: None if self._zs_guard else self.set_zoom(math.exp(sc.get_value())))
        bar.append(self.zscale)
        btn("+", "Zoom in (Ctrl+=)", lambda: self.zoom_step(1.25))
        self.zlabel = Gtk.Label(label="100%", width_chars=5); bar.append(self.zlabel)
        btn("Fit", "Fit to window (Ctrl+0)", self.zoom_fit)
        btn("100%", "Actual size (Ctrl+1)", lambda: self.set_zoom(1.0))
        bar.append(Gtk.Box(hexpand=True))
        bgbox = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=2)
        for k, name in (("light", "Light"), ("dark", "Dark"), ("checker", "Checkerboard")):
            b = Gtk.Button(label=name, css_classes=["flat"], focusable=False)
            b.connect("clicked", lambda _b, k=k: self.set_bg(k)); bgbox.append(b)
        self.bg_color = Gtk.ColorDialogButton(dialog=Gtk.ColorDialog(with_alpha=False), tooltip_text="Custom colour")
        self.bg_color.connect("notify::rgba", lambda b, _p: self.set_bg(None, b.get_rgba()) if not self._bg_guard else None)
        self._bg_guard = False
        row = Gtk.Box(spacing=6); row.append(Gtk.Label(label="Custom")); row.append(self.bg_color); bgbox.append(row)
        bar.append(Gtk.MenuButton(label="Background", popover=Gtk.Popover(child=bgbox), focusable=False,
                                  tooltip_text="Canvas background (not saved in the image)", css_classes=["flat"]))
        return bar

    def set_bg(self, key, rgba=None):
        if rgba is not None:
            self.bg = (rgba.red, rgba.green, rgba.blue); self.conf["bg"] = list(self.bg)
        else:
            self.bg = "checker" if key == "checker" else BG_PRESETS[key]; self.conf["bg"] = key
        save_conf(self.conf); self.area.queue_draw()

    def _sync_zoom_ui(self):
        self._zs_guard = True; self.zscale.set_value(math.log(self.zoom)); self._zs_guard = False
        self.zlabel.set_label(f"{round(self.zoom * 100)}%")

    def set_zoom(self, z, anchor=None):
        """anchor = (area_x, area_y) to keep fixed under the cursor; default view centre."""
        z = max(ZOOM_MIN, min(ZOOM_MAX, z))
        s, ox, oy = self._xf()
        if anchor is None:
            ha, va = self.scroller.get_hadjustment(), self.scroller.get_vadjustment()
            anchor = (ha.get_value() + ha.get_page_size() / 2, va.get_value() + va.get_page_size() / 2)
        ha, va = self.scroller.get_hadjustment(), self.scroller.get_vadjustment()
        img_pt = ((anchor[0] - ox) / s, (anchor[1] - oy) / s)
        view_off = (anchor[0] - ha.get_value(), anchor[1] - va.get_value())
        self.fit = False; self.zoom = z
        bw, bh = self.base.get_width(), self.base.get_height()
        self.area.set_content_width(int(math.ceil(bw * z))); self.area.set_content_height(int(math.ceil(bh * z)))
        self._anchor = (img_pt, view_off)
        self._sync_zoom_ui(); self.area.queue_resize(); self.area.queue_draw()

    def _apply_anchor(self):
        # Runs from on_draw, i.e. after layout, when adjustments know the new size.
        if self._anchor:
            (ix, iy), (vx, vy) = self._anchor
            s, ox, oy = self._xf()
            ha, va = self.scroller.get_hadjustment(), self.scroller.get_vadjustment()
            ha.set_value(ix * s + ox - vx); va.set_value(iy * s + oy - vy)
            self._anchor = None

    def _after_layout(self):
        if self.fit: self._sync_zoom_ui()

    def zoom_step(self, f, anchor=None): self.set_zoom(self.zoom * f, anchor)

    def zoom_fit(self):
        self.fit = True; self.area.set_content_width(0); self.area.set_content_height(0)
        self.area.queue_resize(); self.area.queue_draw()
        GLib.idle_add(lambda: (self._sync_zoom_ui(), False)[1])

    def on_scroll(self, c, dx, dy):
        if not (c.get_current_event_state() & Gdk.ModifierType.CONTROL_MASK): return False
        self.zoom_step(1.15 if dy < 0 else 1 / 1.15, anchor=self._ptr); return True

    def _pan_begin(self):
        self.pan = (self.scroller.get_hadjustment().get_value(), self.scroller.get_vadjustment().get_value())

    def _pan_update(self, dx, dy):
        if self.pan:
            self.scroller.get_hadjustment().set_value(self.pan[0] - dx)
            self.scroller.get_vadjustment().set_value(self.pan[1] - dy)

    def on_key_release(self, c, kv, code, mod):
        if Gdk.keyval_name(kv) == "space": self.space = False

    def _on_paned_pos(self, *_):
        if self.side.get_visible() and self.paned.get_width() > 0:
            wdt = self.paned.get_width() - self.paned.get_position()
            if wdt < 40: return          # collapsed: keep the last real width
            if self.conf.get("panel_width") != wdt:
                self.conf["panel_width"] = wdt
                if getattr(self, "_pw_timer", None): GLib.source_remove(self._pw_timer)
                self._pw_timer = GLib.timeout_add(400, self._save_pw)

    def _save_pw(self):
        self._pw_timer = None; save_conf(self.conf); return False

    def to_img(self, x, y):
        s, ox, oy = self._xf(); return ((x - ox) / s, (y - oy) / s)

    def on_draw(self, area, cr, w, h):
        paint_background(cr, w, h, self.bg)
        if self._anchor: GLib.idle_add(lambda: (self._apply_anchor(), False)[1])
        s, ox, oy = self._xf()
        if self.fit and self.zlabel.get_label() != f"{round(s * 100)}%":
            GLib.idle_add(lambda: (self._sync_zoom_ui(), False)[1])
        cr.translate(ox, oy); cr.scale(s, s)
        cr.set_source_surface(self.base, 0, 0); cr.paint()
        doomed = self.erasing or set()
        for i, st in enumerate(self.doc.objs):
            if i not in doomed: draw_stroke(cr, st)
        if self.cur: draw_stroke(cr, self.cur)
        if self.ocr and self.ocr_visible and self.btn_ocr.get_active():   # display only
            draw_ocr_overlay(cr, self.ocr, s)
        if self.doc.sel is not None:      # on-screen only, never in render()
            draw_selection(cr, self.doc.objs[self.doc.sel], s)

    def on_click(self, g, n, x, y):
        if n == 2:
            i = self.doc.hit(*self.to_img(x, y))
            if i is not None:
                self.drag = None; self.doc.sel = i; self.area.queue_draw(); self.ask_text(x, y, i)

    def d_begin(self, g, x, y):
        if self.space:
            self._pan_begin(); self._space_pan = True; return
        self._space_pan = False
        self.start = (x, y); self.area.grab_focus(); p = self.to_img(x, y); self.drag = None
        if self.handle_link(p): g.set_state(Gtk.EventSequenceState.DENIED); return
        if self.tool == "select":
            s = self._xf()[0]
            hnd = self.doc.handle_at(*p, tol=HANDLE / s)
            if hnd:
                self.drag = ("resize", self.doc.sel, hnd, copy.deepcopy(self.doc.objs[self.doc.sel]), False)
            else:
                i = self.doc.hit(*p); self.doc.sel = i
                if i is not None: self.drag = ("move", i, p, copy.deepcopy(self.doc.objs[i]), False)
            self.area.queue_draw(); return
        if self.tool == "text":
            if self.doc.hit(*p) is None: self.ask_text(x, y)
            return
        if self.tool == "eraser":
            self.erasing = set(); self._erase_at(p); return
        col = self.hl_color if self.tool == "highlighter" else self.color
        if self.tool == "shape":
            self.cur = {"tool": "shape", "kind": self.shape, "color": self.color, "width": self.width, "points": [p, p]}
            return
        self.cur = {"tool": self.tool, "color": col, "width": self.width, "points": [p]}
        if self.tool == "highlighter":   # preview uses strength + blend from the start point
            self.cur["alpha"] = self.hl_alpha; self.cur["blend"] = pick_blend(self.base, [p])

    def _erase_at(self, p):
        r = max(6, self.width * 2) / self._xf()[0]
        self.erasing |= self.doc.hits_along([p], r); self.area.queue_draw()

    def d_update(self, g, dx, dy):
        if getattr(self, "_space_pan", False): self._pan_update(dx, dy); return
        p = self.to_img(self.start[0] + dx, self.start[1] + dy)
        if self.drag:
            kind, i, a, orig, pushed = self.drag
            if not pushed:
                if abs(dx) + abs(dy) < 3: return
                self.doc.push(); self.drag = (kind, i, a, orig, True)
            if kind == "move":
                self.doc.objs[i] = copy.deepcopy(orig); self.doc.move(i, p[0] - a[0], p[1] - a[1], push=False)
            else:
                self.doc.resize(i, a, p[0], p[1], base=orig, push=False)
            self.area.queue_draw()
        elif self.erasing is not None:
            self._erase_at(p)
        elif self.cur and self.cur["tool"] == "shape":
            shift = g.get_current_event_state() & Gdk.ModifierType.SHIFT_MASK
            p0 = self.cur["points"][0]
            self.cur["points"] = [p0, constrain(self.cur["kind"], p0, p) if shift else p]; self.area.queue_draw()
        elif self.cur:
            self.cur["points"].append(p); self.area.queue_draw()

    def d_end(self, *_):
        if getattr(self, "_space_pan", False): self._space_pan = False; self.pan = None; return
        self.drag = None
        if self.erasing is not None:
            self.doc.erase(self.erasing); self.erasing = None; self.area.queue_draw(); return
        if self.cur:
            if self.cur["tool"] == "highlighter":
                self.cur["alpha"] = self.hl_alpha; self.cur["blend"] = pick_blend(self.base, self.cur["points"])
            self.doc.add(self.cur); self.cur = None; self.area.queue_draw()

    def ask_text(self, wx, wy, idx=None):
        pop = Gtk.Popover(); e = Gtk.Entry(placeholder_text="Text, Enter to place"); pop.set_child(e)
        if idx is not None: e.set_text(self.doc.objs[idx]["text"])
        pt = self.to_img(wx, wy)
        pop.set_parent(self.area); r = Gdk.Rectangle(); r.x, r.y = int(wx), int(wy); r.width = r.height = 1
        pop.set_pointing_to(r)
        def done(_e):
            t = e.get_text()
            if idx is None and t:
                self.doc.add_text(pt, t, self.color, self.width * 4)
            elif idx is not None and t != self.doc.objs[idx]["text"]:
                if t: self.doc.edit(idx, t)
                else: self.doc.delete(idx)
            self.area.queue_draw(); pop.popdown()
        e.connect("activate", done); pop.connect("closed", lambda p: GLib.idle_add(p.unparent)); pop.popup(); e.grab_focus()

    def on_key(self, c, kv, code, mod):
        ctrl = mod & Gdk.ModifierType.CONTROL_MASK; shift = mod & Gdk.ModifierType.SHIFT_MASK
        if isinstance(self.get_focus(), Gtk.Text): return False
        k = Gdk.keyval_name(kv).lower()
        if k == "space" and not ctrl: self.space = True; return True
        if ctrl and k in ("equal", "plus", "kp_add"): self.zoom_step(1.25); return True
        if ctrl and k in ("minus", "kp_subtract", "underscore"): self.zoom_step(1 / 1.25); return True
        if ctrl and k in ("0", "kp_0"): self.zoom_fit(); return True
        if ctrl and k in ("1", "kp_1"): self.set_zoom(1.0); return True
        if ctrl and k == "z": self.undo()
        elif ctrl and k == "s": self.save_as() if shift else self.save()
        elif ctrl and k == "c": self.copy()
        elif k in ("delete", "backspace") and self.doc.sel is not None:
            self.doc.delete(self.doc.sel); self.area.queue_draw()
        elif not ctrl and k == "v": self.btn_sel.set_active(True)
        elif not ctrl and k == "p": self.btn_pen.set_active(True)
        elif not ctrl and k == "h": self.btn_hl.set_active(True)
        elif not ctrl and k == "t": self.btn_txt.set_active(True)
        elif not ctrl and k == "s": self.btn_shape.set_active(True)
        elif not ctrl and k == "e": self.btn_eraser.set_active(True)
        elif not ctrl and k == "r": self.btn_ocr.set_active(not self.btn_ocr.get_active())
        elif k == "escape": self.doc.sel = None; self.area.queue_draw()
        else: return False
        return True

    # ---- transcript
    def handle_link(self, img_pt):
        if not (self.ocr and self.ocr_visible and self.btn_ocr.get_active()): return False
        l = link_at(self.ocr, img_pt)
        if not l: return False
        launch_uri(l["url"], self); self.say("Opening " + l["label"]); return True

    def on_ocr_toggle(self, b):
        self.side.set_visible(b.get_active())
        if b.get_active():
            wdt = int(self.conf.get("panel_width", 320))
            GLib.idle_add(lambda: (self.paned.set_position(max(0, self.paned.get_width() - wdt)), False)[1])
        self.area.queue_draw()
        if b.get_active() and self.ocr is None and not self.ocr_busy: self.start_ocr()

    def start_ocr(self):
        self.ocr_busy = True; self.ocr_status.set_label("Reading text…")
        def work():
            try: res, err = run_ocr(self.path), None
            except Exception as e: res, err = None, str(e)
            GLib.idle_add(self.ocr_done, res, err)
        threading.Thread(target=work, daemon=True).start()

    def ocr_done(self, res, err):
        self.ocr_busy = False
        if err:
            self.ocr_status.set_label("OCR unavailable: " + err); self.say("OCR unavailable"); return False
        self.ocr = res
        self.ocr_status.set_label(f"{len(res['words'])} words, {len(res['links'])} link(s). Click a green box to open it.")
        self.tview.get_buffer().set_text(res["text"])
        c = self.links_box.get_first_child()
        while c: n = c.get_next_sibling(); self.links_box.remove(c); c = n
        seen = set()
        for l in res["links"]:
            if l["url"] in seen: continue
            seen.add(l["url"]); lb = Gtk.LinkButton(uri=l["url"], label=l["label"], halign=Gtk.Align.START)
            self.links_box.append(lb)
        self.area.queue_draw(); return False

    def copy_transcript(self):
        if self.ocr:
            self.get_display().get_clipboard().set(self.ocr["text"]); self.say("Transcript copied")

    def say(self, msg):
        self.toast.set_label(msg); self.toast.set_visible(True)
        GLib.timeout_add(2000, lambda: self.toast.set_visible(False))

    def undo(self):
        self.doc.undo(); self.area.queue_draw()

    def export_surface(self):
        """Image + all annotations, at original size. No overlay/selection/background."""
        return render(self.base, self.doc.objs)

    def export_png_bytes(self):
        import io
        buf = io.BytesIO(); self.export_surface().write_to_png(buf); return buf.getvalue()

    def save(self, path=None):
        path = path or default_save_path(self.path)
        try:
            self.export_surface().write_to_png(path)
        except Exception as e:
            self.say(f"Save failed: {e}"); print("save failed:", e, file=sys.stderr); return None
        self.say(f"Saved {os.path.basename(path)}"); return path

    def save_to_gfile(self, f):
        """Save As target. Works for local paths and portal/GVfs URIs (no local path)."""
        try:
            path = f.get_path()
            if path:
                if not path.lower().endswith(".png"): path += ".png"
                return self.save(path)
            f.replace_contents(self.export_png_bytes(), None, False, Gio.FileCreateFlags.REPLACE_DESTINATION, None)
            self.say(f"Saved {f.get_basename()}"); return f.get_uri()
        except Exception as e:
            self.say(f"Save failed: {e}"); print("save-as failed:", e, file=sys.stderr); return None

    def save_as(self):
        d = Gtk.FileDialog(title="Save annotated copy", modal=True,
                           initial_name=os.path.basename(default_save_path(self.path)),
                           initial_folder=Gio.File.new_for_path(os.path.dirname(os.path.abspath(self.path))))
        def cb(dlg, res):
            try: f = dlg.save_finish(res)
            except GLib.Error: return      # cancelled
            if f is not None: self.save_to_gfile(f)
        d.save(self, None, cb)

    def copy(self):
        """Copy the SAME flattened image Save writes (export_png_bytes) to the clipboard.

        GTK's Gdk.Clipboard.set_content() was silently not taking ownership on
        GNOME/Wayland, so pasting returned GNOME's own screenshot clipboard entry
        (the original, without annotations). Prefer wl-copy, which owns the
        selection in its own process (also survives closing the editor), and fall
        back to a Gdk.Texture built from the flattened PNG bytes.
        """
        try:
            png = self.export_png_bytes()
        except Exception as e:
            self.say(f"Copy failed: {e}"); print("copy failed:", e, file=sys.stderr); return False
        if copy_png_wl(png):
            self.say("Copied to clipboard"); return True
        try:
            tex = Gdk.Texture.new_from_bytes(GLib.Bytes.new(png))
            prov = Gdk.ContentProvider.new_union([
                Gdk.ContentProvider.new_for_bytes("image/png", GLib.Bytes.new(png)),
                Gdk.ContentProvider.new_for_value(tex)])
            self.get_display().get_clipboard().set_content(prov)
            self._clip_provider = prov
            self.say("Copied to clipboard"); return True
        except Exception as e:
            self.say(f"Copy failed: {e}"); print("copy failed:", e, file=sys.stderr); return False


def copy_png_wl(png):
    """Put PNG bytes on the Wayland clipboard with wl-copy. True on success."""
    import shutil, subprocess, tempfile
    exe = shutil.which("wl-copy")
    if not exe or not os.environ.get("WAYLAND_DISPLAY"):
        return False
    try:
        with tempfile.TemporaryFile() as f:
            f.write(png); f.seek(0)
            r = subprocess.run([exe, "--type", "image/png"], stdin=f, timeout=10,
                               stdout=subprocess.DEVNULL, stderr=subprocess.PIPE)
        if r.returncode != 0:
            print("wl-copy failed:", r.stderr.decode(errors="replace"), file=sys.stderr)
        return r.returncode == 0
    except Exception as e:
        print("wl-copy failed:", e, file=sys.stderr); return False


class App(Gtk.Application):
    def __init__(self):
        super().__init__(application_id=APP_ID, flags=Gio.ApplicationFlags.HANDLES_OPEN | Gio.ApplicationFlags.NON_UNIQUE)
    def do_open(self, files, n, hint):
        for f in files: Win(self, f.get_path()).present()
    def do_activate(self):
        d = os.path.expanduser("~/Pictures/Screenshots")
        pngs = sorted((os.path.join(d, f) for f in os.listdir(d) if f.lower().endswith(".png")), key=os.path.getmtime) if os.path.isdir(d) else []
        if pngs: Win(self, pngs[-1]).present()
        else: print("No screenshot to open", file=sys.stderr)


if __name__ == "__main__":
    sys.exit(App().run(sys.argv))
