"""Toolkit-independent logic shared by the GTK (Linux) and Qt (Windows/macOS) front ends.

Nothing in here may import GTK, Qt or cairo. Text measurement is injected as
`bbox_fn(obj) -> (x, y, w, h)` so each toolkit can use its own font metrics.
"""
import copy, json, math, os, re, sys

HL_ALPHA = 0.55
HANDLE = 8
ZOOM_MIN, ZOOM_MAX = 0.10, 8.0
BG_PRESETS = {"light": (0.92, 0.92, 0.92), "dark": (0.16, 0.16, 0.18), "checker": None}
DARK_LUMA = 110          # mean 0-255 luminance below which the highlighter switches to 'screen'
OCR_MIN_CONF = 30


# ---------------- geometry ----------------
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


def seg_dist(p, a, b):
    ax, ay = a; bx, by = b; px, py = p; vx, vy = bx - ax, by - ay
    L = vx * vx + vy * vy
    t = 0 if L == 0 else max(0, min(1, ((px - ax) * vx + (py - ay) * vy) / L))
    return math.hypot(px - ax - t * vx, py - ay - t * vy)


def touches(s, p, r, bbox_fn):
    """Does an eraser of radius r at point p touch annotation s?"""
    if s["tool"] == "text":
        x, y, w, h = bbox_fn(s)
        return x - r <= p[0] <= x + w + r and y - r <= p[1] <= y + h + r
    half = s["width"] * (2 if s["tool"] == "highlighter" else 0.5)
    for poly in shape_points(s):
        if len(poly) == 1 and math.hypot(p[0] - poly[0][0], p[1] - poly[0][1]) <= r + half: return True
        for a, b in zip(poly, poly[1:]):
            if seg_dist(p, a, b) <= r + half: return True
    return False


OPP = {"nw": "se", "se": "nw", "ne": "sw", "sw": "ne"}


def corners(b):
    x, y, w, h = b
    return {"nw": (x, y), "ne": (x + w, y), "sw": (x, y + h), "se": (x + w, y + h)}


# ---------------- highlighter blend maths ----------------
def luma(r, g, b):
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def pick_blend_from(sample, w, h, pts):
    """sample(x, y) -> (r, g, b) 0-255. Mean luminance under the stroke picks
    'multiply' (light background) or 'screen' (dark background)."""
    try:
        step = max(1, len(pts) // 200); tot = n = 0
        for x, y in pts[::step]:
            for ox in (-3, 0, 3):
                for oy in (-3, 0, 3):
                    xi, yi = int(x) + ox, int(y) + oy
                    if 0 <= xi < w and 0 <= yi < h:
                        tot += luma(*sample(xi, yi)); n += 1
        return "screen" if n and tot / n < DARK_LUMA else "multiply"
    except Exception:
        return "multiply"


def blend_pixel(base, colour, alpha, mode):
    """Reference maths for one channel set (0-1 floats) - what both renderers must produce."""
    out = []
    for b, c in zip(base, colour):
        top = b * c if mode == "multiply" else 1 - (1 - b) * (1 - c)
        out.append(b + (top - b) * alpha)
    return tuple(out)


# ---------------- document model (objects + snapshot undo) ----------------
class Doc:
    """Objects + snapshot undo. Every user action = one push()."""
    def __init__(self, bbox_fn):
        self.bbox = bbox_fn; self.objs = []; self.hist = []; self.sel = None
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
                bx, by, bw, bh = self.bbox(o)
                if bx - 4 <= x <= bx + bw + 4 and by - 4 <= y <= by + bh + 4: return i
        return None
    def handle_at(self, x, y, tol=HANDLE):
        if self.sel is None: return None
        for name, (hx, hy) in corners(self.bbox(self.objs[self.sel])).items():
            if abs(x - hx) <= tol and abs(y - hy) <= tol: return name
        return None
    def move(self, i, dx, dy, push=True):
        if push: self.push()
        x, y = self.objs[i]["points"][0]; self.objs[i]["points"][0] = (x + dx, y + dy)
    def resize(self, i, handle, nx, ny, base=None, push=True):
        """Drag corner `handle` to (nx,ny); opposite corner stays fixed; font scales."""
        if push: self.push()
        o = self.objs[i]; b = base or copy.deepcopy(o)
        c = corners(self.bbox(b)); opp = c[OPP[handle]]; old = c[handle]
        od = math.hypot(old[0] - opp[0], old[1] - opp[1]) or 1
        nd = math.hypot(nx - opp[0], ny - opp[1])
        o["size"] = max(4.0, b["size"] * nd / od); o["points"][0] = b["points"][0]
        nb = corners(self.bbox(o))[OPP[handle]]
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
        return {i for i, o in enumerate(self.objs) if any(touches(o, p, r, self.bbox) for p in pts)}
    def delete(self, i):
        self.push(); del self.objs[i]; self.sel = None


# ---------------- links + OCR parsing ----------------
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


def build_ocr_result(words):
    """words: [{'text', 'box':(x,y,w,h), 'line': hashable}] -> {'words','lines','text','links'}."""
    lines = {}
    for w in words: lines.setdefault(w.get("line", 0), []).append(w)
    line_objs = []
    for k in sorted(lines):
        ws = lines[k]; x0 = min(w["box"][0] for w in ws); y0 = min(w["box"][1] for w in ws)
        x1 = max(w["box"][0] + w["box"][2] for w in ws); y1 = max(w["box"][1] + w["box"][3] for w in ws)
        line_objs.append({"text": " ".join(w["text"] for w in ws), "box": (x0, y0, x1 - x0, y1 - y0)})
    links = [{"url": normalise_url(u), "label": u, "box": w["box"]} for w in words for u in find_urls(w["text"])]
    words = [{"text": w["text"], "box": w["box"]} for w in words]
    return {"words": words, "lines": line_objs, "text": "\n".join(l["text"] for l in line_objs), "links": links}


def parse_tesseract_tsv(tsv, scale=1):
    words = []
    for row in tsv.splitlines()[1:]:
        f = row.split("\t")
        if len(f) < 12 or f[0] != "5" or not f[11].strip(): continue
        try: conf = float(f[10])
        except ValueError: continue
        if conf < OCR_MIN_CONF: continue
        words.append({"text": f[11].strip(), "box": tuple(int(v) / scale for v in f[6:10]),
                      "line": (int(f[2]), int(f[3]), int(f[4]))})
    return build_ocr_result(words)


def link_at(ocr, pt, pad=3):
    for l in (ocr or {}).get("links", []):
        x, y, w, h = l["box"]
        if x - pad <= pt[0] <= x + w + pad and y - pad <= pt[1] <= y + h + pad: return l
    return None


# ---------------- files + config ----------------
def default_save_path(path):
    root, _ = os.path.splitext(path)
    cand = root + "-marked.png"; n = 2
    while os.path.exists(cand):
        cand = f"{root}-marked-{n}.png"; n += 1
    return cand


def config_dir():
    if sys.platform == "win32":
        return os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "ScreenshotMarkup")
    if sys.platform == "darwin":
        return os.path.expanduser("~/Library/Application Support/ScreenshotMarkup")
    return os.path.join(os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config"), "screenshot-markup")


CONF_PATH = os.path.join(config_dir(), "config.json")


def load_conf(path=None):
    try:
        with open(path or CONF_PATH) as f: return json.load(f)
    except Exception: return {}


def save_conf(c, path=None):
    path = path or CONF_PATH
    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        tmp = path + ".tmp"
        with open(tmp, "w") as f: json.dump(c, f, indent=1)
        os.replace(tmp, path)
    except Exception as e: print("config save failed:", e, file=sys.stderr)


def clamp_zoom(z):
    return max(ZOOM_MIN, min(ZOOM_MAX, z))


def checker_cells(w, h, t=12):
    """Dark squares of the checkerboard backdrop: [(x, y, t, t)]."""
    return [(xx, yy, t, t) for yy in range(0, int(h) + t, t) for xx in range((yy // t % 2) * t, int(w) + t, 2 * t)]


IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp")


def is_new_screenshot(name, seen):
    n = name.lower()
    return n.endswith(IMAGE_EXTS) and "-marked" not in n and name not in seen
