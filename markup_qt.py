#!/usr/bin/env python3
"""Screenshot Markup - Qt/PySide6 front end (Windows and macOS; also runs on Linux for testing).

Same document model and maths as the GTK app (see markup_core.py).
  ScreenshotMarkup.exe <image>      open the editor
  ScreenshotMarkup.exe              start the tray watcher (Windows) / file picker elsewhere
  ScreenshotMarkup.exe --capture-demo out.png [image]   render a demo window to PNG (CI screenshots)
"""
import asyncio, copy, os, shutil, subprocess, sys, tempfile, threading

if getattr(sys, "frozen", False):
    sys.path.insert(0, getattr(sys, "_MEIPASS", os.path.dirname(sys.executable)))
else:
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import markup_core as core
from markup_core import (HL_ALPHA, HANDLE, BG_PRESETS, ZOOM_MIN, ZOOM_MAX, constrain, shape_points, corners,
                         link_at, default_save_path, load_conf, save_conf, clamp_zoom, checker_cells)

from PySide6.QtCore import Qt, QPointF, QRectF, QTimer, QUrl, Signal, QObject, QSize
from PySide6.QtGui import (QAction, QBrush, QColor, QDesktopServices, QFont, QFontMetricsF, QGuiApplication, QIcon,
                           QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QPolygonF, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QColorDialog, QComboBox, QFileDialog, QHBoxLayout,
                               QInputDialog, QLabel, QMainWindow, QMenu, QMessageBox, QPlainTextEdit, QPushButton,
                               QScrollArea, QSlider, QSplitter, QToolBar, QToolButton, QVBoxLayout, QWidget, QCheckBox)

APP_NAME = "Screenshot Markup"
APP_ID = "io.github.patsinclair1.ScreenshotMarkup"


# ---------------- rendering (QPainter twin of the cairo code) ----------------
def text_font(size):
    f = QFont("Segoe UI" if sys.platform == "win32" else "Sans"); f.setBold(True); f.setPixelSize(max(1, int(round(size))))
    return f


def text_bbox(o):
    fm = QFontMetricsF(text_font(o["size"])); x, y = o["points"][0]
    return (x, y - fm.ascent(), max(fm.horizontalAdvance(o["text"] or " "), 4), fm.ascent() + fm.descent())


def qc(c, a=1.0):
    return QColor.fromRgbF(c[0], c[1], c[2], a)


def _poly_path(pts):
    path = QPainterPath(QPointF(*pts[0]))
    if len(pts) == 1: path.lineTo(pts[0][0] + 0.1, pts[0][1])
    for p in pts[1:]: path.lineTo(*p)
    return path


def draw_stroke(p, s, size):
    pts = s["points"]
    if not pts: return
    p.save(); p.setRenderHint(QPainter.Antialiasing)
    t = s["tool"]
    if t == "text":
        p.setFont(text_font(s["size"])); p.setPen(qc(s["color"])); p.drawText(QPointF(*pts[0]), s["text"])
    elif t == "shape":
        pen = QPen(qc(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin); p.setPen(pen); p.setBrush(Qt.NoBrush)
        if s["kind"] == "ellipse":
            (x0, y0), (x1, y1) = pts[0], pts[-1]; p.drawEllipse(QRectF(QPointF(x0, y0), QPointF(x1, y1)).normalized())
        else:
            for poly in shape_points(s): p.drawPath(_poly_path(poly))
    elif t == "highlighter":
        # opaque stroke on its own layer (no self-overlap darkening), then multiply/screen it on at `alpha`
        layer = QImage(size, QImage.Format_ARGB32_Premultiplied); layer.fill(Qt.transparent)
        lp = QPainter(layer); lp.setRenderHint(QPainter.Antialiasing); lp.setTransform(p.transform())
        lp.setPen(QPen(qc(s["color"]), s["width"] * 4, Qt.SolidLine, Qt.FlatCap, Qt.BevelJoin)); lp.drawPath(_poly_path(pts)); lp.end()
        p.resetTransform()
        p.setCompositionMode(QPainter.CompositionMode_Screen if s.get("blend") == "screen" else QPainter.CompositionMode_Multiply)
        p.setOpacity(s.get("alpha", HL_ALPHA)); p.drawImage(0, 0, layer)
    else:
        p.setPen(QPen(qc(s["color"]), s["width"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)); p.drawPath(_poly_path(pts))
    p.restore()


def render(base, objs):
    """Image + annotations at native size. Never includes OCR overlay, selection or backdrop."""
    out = base.convertToFormat(QImage.Format_ARGB32_Premultiplied)
    p = QPainter(out)
    for s in objs: draw_stroke(p, s, out.size())
    p.end()
    return out


def pick_blend(img, pts):
    def sample(x, y):
        c = img.pixelColor(x, y); return c.red(), c.green(), c.blue()
    return core.pick_blend_from(sample, img.width(), img.height(), pts)


class Doc(core.Doc):
    def __init__(self):
        super().__init__(text_bbox)


# ---------------- OCR: Windows.Media.Ocr (built in) or tesseract ----------------
def find_tesseract():
    cands = [shutil.which("tesseract")]
    if sys.platform == "win32":
        for env in ("ProgramFiles", "ProgramFiles(x86)", "LOCALAPPDATA"):
            if os.environ.get(env): cands.append(os.path.join(os.environ[env], "Tesseract-OCR", "tesseract.exe"))
    else:
        cands += ["/home/linuxbrew/.linuxbrew/bin/tesseract", "/opt/homebrew/bin/tesseract", "/usr/local/bin/tesseract"]
    return next((c for c in cands if c and os.path.isfile(c)), None)


def ocr_winrt(path):
    from winrt.windows.media.ocr import OcrEngine
    from winrt.windows.graphics.imaging import BitmapDecoder
    from winrt.windows.storage import StorageFile, FileAccessMode

    async def go():
        f = await StorageFile.get_file_from_path_async(os.path.abspath(path))
        stream = await f.open_async(FileAccessMode.READ)
        bmp = await (await BitmapDecoder.create_async(stream)).get_software_bitmap_async()
        eng = OcrEngine.try_create_from_user_profile_languages()
        if eng is None: raise RuntimeError("No Windows OCR language installed (Settings > Language > add an OCR pack)")
        res = await eng.recognize_async(bmp)
        words = []
        for li, line in enumerate(res.lines):
            for w in line.words:
                r = w.bounding_rect; words.append({"text": w.text, "box": (r.x, r.y, r.width, r.height), "line": li})
        return core.build_ocr_result(words)
    return asyncio.run(go())


def ocr_tesseract(path, scale=2):
    exe = find_tesseract()
    if not exe: raise RuntimeError("No OCR engine found. Install Tesseract (UB Mannheim build) or a Windows OCR language pack.")
    img = QImage(path); big = QImage(img.width() * scale, img.height() * scale, QImage.Format_RGB32); big.fill(Qt.white)
    p = QPainter(big); p.setRenderHint(QPainter.SmoothPixmapTransform); p.scale(scale, scale); p.drawImage(0, 0, img); p.end()
    fd, tmp = tempfile.mkstemp(suffix=".png", prefix="ssm-ocr-"); os.close(fd)
    try:
        big.save(tmp)
        kw = {"creationflags": 0x08000000} if sys.platform == "win32" else {}   # CREATE_NO_WINDOW
        out = subprocess.run([exe, tmp, "stdout", "--psm", "3", "tsv"], capture_output=True, text=True, timeout=120, **kw)
    finally:
        os.unlink(tmp)
    if out.returncode != 0: raise RuntimeError("tesseract failed: " + out.stderr.strip()[:200])
    return core.parse_tesseract_tsv(out.stdout, scale)


def run_ocr(path):
    if sys.platform == "win32":
        try: return ocr_winrt(path)
        except Exception as e:
            if not find_tesseract(): raise RuntimeError(f"Windows OCR unavailable ({e}); Tesseract not installed either")
    return ocr_tesseract(path)


# ---------------- canvas ----------------
class Canvas(QWidget):
    def __init__(self, win):
        super().__init__(); self.w = win; self.setMouseTracking(True); self.setFocusPolicy(Qt.StrongFocus)

    def sizeHint(self):
        return QSize(int(self.w.base.width() * self.w.zoom), int(self.w.base.height() * self.w.zoom))

    def offset(self):
        z = self.w.zoom; iw, ih = self.w.base.width() * z, self.w.base.height() * z
        return max(0, (self.width() - iw) / 2), max(0, (self.height() - ih) / 2)

    def to_img(self, pos):
        ox, oy = self.offset(); z = self.w.zoom
        return ((pos.x() - ox) / z, (pos.y() - oy) / z)

    def paintEvent(self, _e):
        w = self.w; p = QPainter(self); bg = w.bg
        if bg == "checker" or bg is None:
            p.fillRect(self.rect(), QColor.fromRgbF(0.8, 0.8, 0.8))
            for x, y, a, b in checker_cells(self.width(), self.height()): p.fillRect(int(x), int(y), a, b, QColor.fromRgbF(0.62, 0.62, 0.62))
        else:
            p.fillRect(self.rect(), qc(bg))
        ox, oy = self.offset(); p.translate(ox, oy); p.scale(w.zoom, w.zoom)
        p.setRenderHint(QPainter.SmoothPixmapTransform, w.zoom < 1)
        objs = [o for i, o in enumerate(w.doc.objs) if i not in (w.erasing or ())] + ([w.cur] if w.cur else [])
        # draw annotations into an image-sized buffer so multiply/screen only blend with the screenshot
        img = render(w.base, objs); p.drawImage(0, 0, img)
        if w.ocr and w.ocr_visible and w.btn_ocr.isChecked():
            p.setPen(QPen(QColor(51, 153, 255, 140), 1 / w.zoom)); p.setBrush(QColor(51, 153, 255, 26))
            for wd in w.ocr["words"]:
                x, y, ww, hh = wd["box"]; p.drawRect(QRectF(x - 1, y - 1, ww + 2, hh + 2))
            p.setPen(QPen(QColor(0, 178, 77, 242), 2 / w.zoom)); p.setBrush(QColor(0, 217, 89, 56))
            for l in w.ocr["links"]:
                x, y, ww, hh = l["box"]; p.drawRect(QRectF(x - 2, y - 2, ww + 4, hh + 4))
                p.drawLine(QPointF(x, y + hh + 2), QPointF(x + ww, y + hh + 2))
        if w.doc.sel is not None and w.doc.sel < len(w.doc.objs):
            x, y, bw, bh = text_bbox(w.doc.objs[w.doc.sel]); z = w.zoom; hs = HANDLE / z
            pen = QPen(QColor(51, 128, 255), 1.5 / z, Qt.DashLine); p.setPen(pen); p.setBrush(Qt.NoBrush)
            p.drawRect(QRectF(x - 3 / z, y - 3 / z, bw + 6 / z, bh + 6 / z))
            p.setPen(QPen(QColor(51, 128, 255), 1.5 / z)); p.setBrush(Qt.white)
            for hx, hy in corners((x, y, bw, bh)).values(): p.drawRect(QRectF(hx - hs / 2, hy - hs / 2, hs, hs))
        p.end()

    # ---- input
    def mousePressEvent(self, e):
        w = self.w
        if e.button() == Qt.MiddleButton or (e.button() == Qt.LeftButton and w.space):
            self.pan = (e.globalPosition(), w.scroll.horizontalScrollBar().value(), w.scroll.verticalScrollBar().value()); return
        if e.button() != Qt.LeftButton: return
        self.pan = None; pt = self.to_img(e.position()); w.drag = None; self.start = e.position(); self.moved = False
        if w.ocr and w.ocr_visible and w.btn_ocr.isChecked():
            l = link_at(w.ocr, pt)
            if l: QDesktopServices.openUrl(QUrl(l["url"])); w.say("Opening " + l["label"]); self.ignore_drag = True; return
        self.ignore_drag = False
        if w.tool == "select":
            hnd = w.doc.handle_at(*pt, tol=HANDLE / w.zoom)
            if hnd: w.drag = ["resize", w.doc.sel, hnd, copy.deepcopy(w.doc.objs[w.doc.sel]), False]
            else:
                i = w.doc.hit(*pt); w.doc.sel = i
                if i is not None: w.drag = ["move", i, pt, copy.deepcopy(w.doc.objs[i]), False]
        elif w.tool == "text":
            if w.doc.hit(*pt) is None: w.ask_text(pt)
        elif w.tool == "eraser":
            w.erasing = set(); self._erase(pt)
        elif w.tool == "shape":
            w.cur = {"tool": "shape", "kind": w.shape, "color": w.color, "width": w.pen_w, "points": [pt, pt]}
        else:
            col = w.hl_color if w.tool == "highlighter" else w.color
            w.cur = {"tool": w.tool, "color": col, "width": w.pen_w, "points": [pt]}
            if w.tool == "highlighter": w.cur["alpha"] = w.hl_alpha; w.cur["blend"] = pick_blend(w.base, [pt])
        self.update()

    def _erase(self, pt):
        w = self.w; w.erasing |= w.doc.hits_along([pt], max(6, w.pen_w * 2) / w.zoom)

    def mouseMoveEvent(self, e):
        w = self.w
        if getattr(self, "pan", None):
            g0, hx, vy = self.pan; d = e.globalPosition() - g0
            w.scroll.horizontalScrollBar().setValue(int(hx - d.x())); w.scroll.verticalScrollBar().setValue(int(vy - d.y())); return
        if not (e.buttons() & Qt.LeftButton) or getattr(self, "ignore_drag", False):
            if w.tool == "select": self.setCursor(Qt.SizeFDiagCursor if w.doc.handle_at(*self.to_img(e.position()), tol=HANDLE / w.zoom) else Qt.ArrowCursor)
            return
        pt = self.to_img(e.position())
        if w.drag:
            kind, i, a, orig, pushed = w.drag
            if not pushed:
                if (e.position() - self.start).manhattanLength() < 3: return
                w.doc.push(); w.drag[4] = True
            if kind == "move":
                w.doc.objs[i] = copy.deepcopy(orig); w.doc.move(i, pt[0] - a[0], pt[1] - a[1], push=False)
            else:
                w.doc.resize(i, a, pt[0], pt[1], base=orig, push=False)
        elif w.erasing is not None: self._erase(pt)
        elif w.cur and w.cur["tool"] == "shape":
            p0 = w.cur["points"][0]
            w.cur["points"] = [p0, constrain(w.cur["kind"], p0, pt) if e.modifiers() & Qt.ShiftModifier else pt]
        elif w.cur: w.cur["points"].append(pt)
        self.update()

    def mouseReleaseEvent(self, e):
        w = self.w; self.pan = None; w.drag = None
        if w.erasing is not None:
            w.doc.erase(w.erasing); w.erasing = None
        elif w.cur:
            if w.cur["tool"] == "highlighter": w.cur["alpha"] = w.hl_alpha; w.cur["blend"] = pick_blend(w.base, w.cur["points"])
            w.doc.add(w.cur); w.cur = None
        self.update()

    def mouseDoubleClickEvent(self, e):
        w = self.w; pt = self.to_img(e.position()); i = w.doc.hit(*pt)
        if i is not None: w.doc.sel = i; w.drag = None; self.update(); w.ask_text(pt, i)

    def wheelEvent(self, e):
        if e.modifiers() & Qt.ControlModifier:
            self.w.set_zoom(self.w.zoom * (1.25 if e.angleDelta().y() > 0 else 0.8), anchor=e.position()); e.accept()
        else: e.ignore()


# ---------------- window ----------------
TOOLS = [("select", "⬉", "Select / move text (V)", "V"), ("pen", "✎", "Pen (P)", "P"), ("highlighter", "🖍", "Highlighter (H)", "H"),
         ("text", "T", "Text (T)", "T"), ("shape", "▭", "Shapes (S)", "S"), ("eraser", "⌫", "Eraser (E)", "E")]
SHAPES = {"rect": ("▭", "Rectangle"), "ellipse": ("◯", "Ellipse"), "arrow": ("➚", "Arrow"), "line": ("╱", "Line")}


class Win(QMainWindow):
    def __init__(self, path):
        super().__init__()
        self.path = path; self.base = QImage(path).convertToFormat(QImage.Format_ARGB32_Premultiplied)
        if self.base.isNull(): raise RuntimeError(f"Cannot open image: {path}")
        self.setWindowTitle(f"{os.path.basename(path)} - {APP_NAME}")
        self.doc = Doc(); self.cur = None; self.erasing = None; self.drag = None; self.tool = "pen"; self.shape = "rect"
        self.color = (0.9, 0.1, 0.1); self.hl_color = (1.0, 0.92, 0.0); self.pen_w = 4
        self.conf = load_conf(); self.hl_alpha = float(self.conf.get("hl_strength", HL_ALPHA))
        bg = self.conf.get("bg", "light")
        self.bg = bg if bg == "checker" else tuple(bg) if isinstance(bg, list) else BG_PRESETS.get(bg, BG_PRESETS["light"])
        self.zoom = 1.0; self.fit = True; self.space = False; self.ocr = None; self.ocr_visible = True

        tb = QToolBar(); tb.setMovable(False); self.addToolBar(tb); self.tool_btns = {}; grp = QButtonGroup(self)
        for key, glyph, tip, _ in TOOLS:
            b = QToolButton(text=glyph, toolTip=tip, checkable=True); b.setFocusPolicy(Qt.NoFocus); b.setMinimumWidth(34)
            b.clicked.connect(lambda _=False, k=key: self.set_tool(k)); grp.addButton(b); tb.addWidget(b); self.tool_btns[key] = b
            if key == "shape":
                m = QMenu(self)
                for sk, (g, name) in SHAPES.items(): m.addAction(f"{g}  {name}", lambda sk=sk: self.pick_shape(sk))
                b.setMenu(m); b.setPopupMode(QToolButton.MenuButtonPopup)
        self.tool_btns["pen"].setChecked(True)
        self.btn_ocr = QToolButton(text="≣", toolTip="Transcript / OCR (R)", checkable=True); self.btn_ocr.setFocusPolicy(Qt.NoFocus)
        self.btn_ocr.toggled.connect(self.on_ocr_toggle); tb.addWidget(self.btn_ocr)
        self.cbtn = QToolButton(toolTip="Colour"); self.cbtn.clicked.connect(self.pick_color); tb.addWidget(self.cbtn); self._sync_cbtn()
        tb.addSeparator(); tb.addWidget(QLabel(" Size "))
        self.size_slider = QSlider(Qt.Horizontal, minimum=1, maximum=40, value=self.pen_w); self.size_slider.setFixedWidth(120)
        self.size_slider.setToolTip("Size"); self.size_slider.valueChanged.connect(lambda v: setattr(self, "pen_w", v)); tb.addWidget(self.size_slider)
        tb.addWidget(QLabel(" Strength "))
        self.str_slider = QSlider(Qt.Horizontal, minimum=10, maximum=100, value=round(self.hl_alpha * 100)); self.str_slider.setFixedWidth(90)
        self.str_slider.setSingleStep(5); self.str_slider.valueChanged.connect(self.on_strength); self.on_strength(self.str_slider.value(), save=False)
        tb.addWidget(self.str_slider); tb.addSeparator()
        for glyph, tip, cb in (("↶", "Undo (Ctrl+Z)", self.undo), ("⧉", "Copy (Ctrl+C)", self.copy),
                               ("💾", "Save copy (Ctrl+S)", self.save), ("💾…", "Save as… (Ctrl+Shift+S)", self.save_as)):
            a = QAction(glyph, self, toolTip=tip); a.triggered.connect(cb); tb.addAction(a)

        self.canvas = Canvas(self); self.scroll = QScrollArea(); self.scroll.setWidget(self.canvas); self.scroll.setWidgetResizable(True)
        self.scroll.setAlignment(Qt.AlignCenter)
        left = QWidget(); lv = QVBoxLayout(left); lv.setContentsMargins(0, 0, 0, 0); lv.setSpacing(0)
        lv.addWidget(self.scroll); lv.addWidget(self._zoombar())
        self.side = QWidget(); sv = QVBoxLayout(self.side); hdr = QHBoxLayout()
        hdr.addWidget(QLabel("<b>Transcript</b>")); hdr.addStretch()
        self.chk_overlay = QCheckBox("Overlay", checked=True); self.chk_overlay.toggled.connect(lambda v: (setattr(self, "ocr_visible", v), self.canvas.update()))
        hdr.addWidget(self.chk_overlay); cpy = QPushButton("Copy all"); cpy.clicked.connect(self.copy_transcript); hdr.addWidget(cpy)
        sv.addLayout(hdr); self.ocr_status = QLabel(wordWrap=True); sv.addWidget(self.ocr_status)
        self.links_lbl = QLabel(openExternalLinks=True, wordWrap=True); sv.addWidget(self.links_lbl)
        self.tview = QPlainTextEdit(readOnly=True); sv.addWidget(self.tview, 1)
        self.split = QSplitter(Qt.Horizontal); self.split.addWidget(left); self.split.addWidget(self.side)
        self.split.setCollapsible(0, False); self.split.setCollapsible(1, True); self.split.splitterMoved.connect(self._save_pw)
        self.side.hide(); self.setCentralWidget(self.split)
        self.toast = QLabel(self); self.toast.setStyleSheet("background:rgba(0,0,0,180);color:white;padding:6px 12px;border-radius:8px"); self.toast.hide()

        for seq, cb in (("Ctrl+Z", self.undo), ("Ctrl+C", self.copy), ("Ctrl+S", self.save), ("Ctrl+Shift+S", self.save_as),
                        ("Ctrl+=", lambda: self.set_zoom(self.zoom * 1.25)), ("Ctrl++", lambda: self.set_zoom(self.zoom * 1.25)),
                        ("Ctrl+-", lambda: self.set_zoom(self.zoom / 1.25)), ("Ctrl+0", self.zoom_fit), ("Ctrl+1", lambda: self.set_zoom(1.0)),
                        ("Delete", self.delete_sel), ("Backspace", self.delete_sel), ("Escape", self.deselect),
                        ("R", lambda: self.btn_ocr.toggle())):
            QShortcut(QKeySequence(seq), self, cb)
        for key, _, _, k in TOOLS: QShortcut(QKeySequence(k), self, lambda key=key: self.set_tool(key))
        iw, ih = self.base.width(), self.base.height()
        self.resize(min(iw, 1400) + 40, min(ih, 900) + 110)
        QTimer.singleShot(0, self.zoom_fit)

    # ---- toolbar
    def _sync_cbtn(self):
        c = self.hl_color if self.tool == "highlighter" else self.color; pm = QPixmap(18, 18); pm.fill(qc(c)); self.cbtn.setIcon(QIcon(pm))

    def set_tool(self, t):
        self.tool = t; self.tool_btns[t].setChecked(True); self._sync_cbtn()
        if t != "select": self.doc.sel = None
        self.canvas.update()

    def pick_shape(self, k):
        self.shape = k; self.tool_btns["shape"].setText(SHAPES[k][0]); self.set_tool("shape")

    def pick_color(self):
        cur = self.hl_color if self.tool == "highlighter" else self.color
        c = QColorDialog.getColor(qc(cur), self, "Colour")
        if c.isValid():
            v = (c.redF(), c.greenF(), c.blueF())
            if self.tool == "highlighter": self.hl_color = v
            else: self.color = v
            self._sync_cbtn()

    def on_strength(self, v, save=True):
        self.hl_alpha = v / 100; self.str_slider.setToolTip(f"Highlighter strength {v}%")
        if save: self.conf["hl_strength"] = round(self.hl_alpha, 2); save_conf(self.conf)

    # ---- zoom + background
    def _zoombar(self):
        bar = QWidget(); h = QHBoxLayout(bar); h.setContentsMargins(6, 2, 6, 2)
        minus = QToolButton(text="−"); minus.clicked.connect(lambda: self.set_zoom(self.zoom / 1.25)); h.addWidget(minus)
        self.zslider = QSlider(Qt.Horizontal, minimum=int(ZOOM_MIN * 100), maximum=int(ZOOM_MAX * 100), value=100)
        self.zslider.setFixedWidth(220); self.zslider.valueChanged.connect(self._on_zslider); h.addWidget(self.zslider)
        plus = QToolButton(text="+"); plus.clicked.connect(lambda: self.set_zoom(self.zoom * 1.25)); h.addWidget(plus)
        self.zlabel = QLabel("100%"); self.zlabel.setMinimumWidth(48); h.addWidget(self.zlabel)
        fit = QPushButton("Fit"); fit.clicked.connect(self.zoom_fit); h.addWidget(fit)
        one = QPushButton("100%"); one.clicked.connect(lambda: self.set_zoom(1.0)); h.addWidget(one)
        h.addStretch(); h.addWidget(QLabel("Background"))
        self.bgcombo = QComboBox(); self.bgcombo.addItems(["Light", "Dark", "Checkerboard", "Custom…"])
        self.bgcombo.setCurrentIndex({"checker": 2}.get(self.bg if isinstance(self.bg, str) else "", 1 if self.bg == BG_PRESETS["dark"] else 0))
        self.bgcombo.activated.connect(self._on_bg); h.addWidget(self.bgcombo)
        return bar

    def _on_bg(self, i):
        if i == 3:
            c = QColorDialog.getColor(parent=self)
            if not c.isValid(): return
            self.set_bg([c.redF(), c.greenF(), c.blueF()])
        else: self.set_bg(["light", "dark", "checker"][i])

    def set_bg(self, key):
        self.conf["bg"] = key; save_conf(self.conf)
        self.bg = "checker" if key == "checker" else tuple(key) if isinstance(key, list) else BG_PRESETS[key]; self.canvas.update()

    def _on_zslider(self, v):
        if abs(v - self.zoom * 100) >= 1: self.set_zoom(v / 100)

    def set_zoom(self, z, anchor=None, fit=False):
        sb_h, sb_v = self.scroll.horizontalScrollBar(), self.scroll.verticalScrollBar()
        old = self.zoom; self.zoom = clamp_zoom(z); self.fit = fit
        if anchor is None: anchor = QPointF(self.scroll.viewport().width() / 2, self.scroll.viewport().height() / 2) + QPointF(sb_h.value(), sb_v.value())
        img_pt = self.canvas.to_img(anchor)
        self.canvas.setMinimumSize(self.canvas.sizeHint()); self.canvas.adjustSize()
        self.zslider.blockSignals(True); self.zslider.setValue(round(self.zoom * 100)); self.zslider.blockSignals(False)
        self.zlabel.setText(f"{round(self.zoom * 100)}%")
        if not fit and old != self.zoom:
            ox, oy = self.canvas.offset(); vx = anchor.x() - sb_h.value(); vy = anchor.y() - sb_v.value()
            QTimer.singleShot(0, lambda: (sb_h.setValue(int(ox + img_pt[0] * self.zoom - vx)), sb_v.setValue(int(oy + img_pt[1] * self.zoom - vy))))
        self.canvas.update()

    def zoom_fit(self):
        vp = self.scroll.viewport()
        z = min((vp.width() - 8) / self.base.width(), (vp.height() - 8) / self.base.height(), 1.0)
        self.set_zoom(z, fit=True)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        if self.fit: QTimer.singleShot(0, self.zoom_fit)

    def keyPressEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat(): self.space = True
        super().keyPressEvent(e)

    def keyReleaseEvent(self, e):
        if e.key() == Qt.Key_Space and not e.isAutoRepeat(): self.space = False
        super().keyReleaseEvent(e)

    # ---- text
    def ask_text(self, pt, idx=None):
        old = self.doc.objs[idx]["text"] if idx is not None else ""
        t, ok = QInputDialog.getText(self, "Text", "Text:", text=old)
        if not ok: return
        if idx is None and t: self.doc.add_text(pt, t, self.color, self.pen_w * 4)
        elif idx is not None and t != old:
            if t: self.doc.edit(idx, t)
            else: self.doc.delete(idx)
        self.canvas.update()

    def delete_sel(self):
        if self.doc.sel is not None: self.doc.delete(self.doc.sel); self.canvas.update()

    def deselect(self):
        self.doc.sel = None; self.canvas.update()

    # ---- transcript
    def on_ocr_toggle(self, on):
        self.side.setVisible(on)
        if on:
            w = int(self.conf.get("panel_width", 320)); self.split.setSizes([max(200, self.width_px() - w), w])
            if self.ocr is None: self.start_ocr()
        self.canvas.update()

    def width_px(self): return self.split.width() or self.width()

    def _save_pw(self, *_):
        s = self.split.sizes()
        if len(s) == 2 and s[1] > 40: self.conf["panel_width"] = s[1]; save_conf(self.conf)

    def start_ocr(self):
        self.ocr_status.setText("Reading text…")
        sig = _Relay(self); sig.done.connect(self.ocr_done)
        def work():
            try: sig.done.emit(run_ocr(self.path), "")
            except Exception as e: sig.done.emit(None, str(e))
        threading.Thread(target=work, daemon=True).start()

    def ocr_done(self, res, err):
        if err: self.ocr_status.setText("OCR failed: " + err); return
        self.set_ocr(res)

    def set_ocr(self, res):
        self.ocr = res; n = len(res["words"])
        self.ocr_status.setText(f"{n} words, {len(res['links'])} links" if n else "No text found")
        self.links_lbl.setText("<br>".join(f'<a href="{l["url"]}">{l["label"]}</a>' for l in res["links"]))
        self.tview.setPlainText(res["text"]); self.canvas.update()

    def copy_transcript(self):
        if self.ocr: QGuiApplication.clipboard().setText(self.ocr["text"]); self.say("Transcript copied")

    # ---- output
    def say(self, msg):
        self.toast.setText(msg); self.toast.adjustSize()
        self.toast.move((self.width() - self.toast.width()) // 2, self.height() - self.toast.height() - 50); self.toast.show(); self.toast.raise_()
        QTimer.singleShot(1800, self.toast.hide)

    def undo(self):
        self.doc.undo(); self.canvas.update()

    def export_image(self):
        return render(self.base, self.doc.objs)

    def save(self, path=None):
        path = path or default_save_path(self.path)
        if not self.export_image().save(path, "PNG"):
            QMessageBox.warning(self, APP_NAME, f"Could not save {path}"); return None
        self.say("Saved " + os.path.basename(path)); return path

    def save_as(self):
        p, _ = QFileDialog.getSaveFileName(self, "Save as", default_save_path(self.path), "PNG image (*.png)")
        if p: self.save(p if p.lower().endswith(".png") else p + ".png")

    def copy(self):
        img = self.export_image()
        QGuiApplication.clipboard().setImage(img)
        self.say("Copied to clipboard"); return img


class _Relay(QObject):
    done = Signal(object, str)


# ---------------- demo / CI screenshot ----------------
DEMO_TEXT = ["Screenshot Markup for Windows", "Docs: https://github.com/Patsinclair1/ScreenshotMarkup", "Highlight text, draw, erase, undo."]


def make_demo_image(path, dark=False):
    img = QImage(1000, 560, QImage.Format_RGB32); img.fill(QColor(30, 30, 34) if dark else QColor(250, 250, 250))
    p = QPainter(img); p.setRenderHint(QPainter.Antialiasing); f = QFont("Segoe UI" if sys.platform == "win32" else "Sans"); f.setPixelSize(30)
    p.setFont(f); p.setPen(QColor(230, 230, 230) if dark else QColor(20, 20, 20))
    for i, t in enumerate(DEMO_TEXT): p.drawText(40, 90 + i * 70, t)
    p.fillRect(40, 330, 300, 160, QColor(70, 130, 220)); p.end(); img.save(path); return path


def demo_annotations(win):
    d = win.doc
    d.add({"tool": "highlighter", "color": (1, 0.92, 0), "width": 9, "alpha": 0.55, "blend": pick_blend(win.base, [(40, 150), (900, 150)]),
           "points": [(40, 150), (620, 150)]})
    d.add({"tool": "pen", "color": (0.9, 0.1, 0.1), "width": 5, "points": [(400, 360), (440, 400), (480, 380), (540, 440), (600, 420)]})
    d.add({"tool": "shape", "kind": "rect", "color": (0.1, 0.6, 0.2), "width": 4, "points": [(30, 320), (350, 500)]})
    d.add({"tool": "shape", "kind": "arrow", "color": (0.9, 0.1, 0.1), "width": 5, "points": [(700, 470), (360, 410)]})
    i = d.add_text((660, 330), "Edit me!", (0.2, 0.3, 0.9), 34); d.sel = i


def capture_demo(out, image=None, transcript=True):
    """Build a window with demo marks (+ mock transcript), grab it to PNG. Works offscreen or on a real desktop."""
    app = QApplication.instance() or QApplication(sys.argv)
    tmpdir = tempfile.mkdtemp(prefix="ssm-demo-")
    image = image or make_demo_image(os.path.join(tmpdir, "demo.png"))
    w = Win(image); w.resize(1280, 760); w.show(); demo_annotations(w)
    if transcript:
        words = []
        for li, t in enumerate(DEMO_TEXT):
            x = 40
            for wd in t.split():
                words.append({"text": wd, "box": (x, 62 + li * 70, len(wd) * 15, 36), "line": li}); x += len(wd) * 15 + 10
        w.btn_ocr.blockSignals(True); w.btn_ocr.setChecked(True); w.btn_ocr.blockSignals(False)
        w.side.show(); w.split.setSizes([960, 320]); w.set_ocr(core.build_ocr_result(words))
    for _ in range(5): app.processEvents()
    w.zoom_fit()
    for _ in range(5): app.processEvents()
    ok = w.grab().save(out, "PNG")
    w.export_image().save(os.path.splitext(out)[0] + "-export.png", "PNG")
    w.close(); return ok


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv[:1] == ["--capture-demo"]:
        out = argv[1] if len(argv) > 1 else "markup-demo.png"
        sys.exit(0 if capture_demo(out, argv[2] if len(argv) > 2 else None) else 1)
    app = QApplication(sys.argv); app.setApplicationName(APP_NAME); app.setDesktopFileName(APP_ID)
    files = [a for a in argv if not a.startswith("-")]
    if not files and "--editor" not in argv:
        if sys.platform == "win32" or "--tray" in argv:
            import markup_tray
            return markup_tray.run(app)
        f, _ = QFileDialog.getOpenFileName(None, "Open screenshot", os.path.expanduser("~"), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        files = [f] if f else []
    wins = []
    for f in files:
        w = Win(f); w.show(); wins.append(w)
    return app.exec() if wins else 0


if __name__ == "__main__":
    sys.exit(main())
