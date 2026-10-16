"""Windows entry point: tray icon that watches for new screenshots and offers an Edit toast.

Sources of new screenshots:
  * %USERPROFILE%\\Pictures\\Screenshots   (Win+PrtScn, Snipping Tool auto-save)
  * the clipboard after Win+Shift+S        (saved to %LOCALAPPDATA%\\ScreenshotMarkup\\clips)
Toast: windows-toasts (real toast with an Edit button) when available, else the tray balloon (click = Edit).
"""
import os, sys, time
import markup_core as core
from PySide6.QtCore import QObject, QTimer, Signal, QFileSystemWatcher
from PySide6.QtGui import QAction, QGuiApplication, QIcon, QPixmap, QColor, QPainter, QPen
from PySide6.QtWidgets import QMenu, QSystemTrayIcon, QApplication, QFileDialog


def screenshots_dir():
    if sys.platform == "win32":
        try:   # honour a relocated Pictures folder
            import ctypes, uuid
            from ctypes import wintypes
            fid = uuid.UUID("{b7bede81-df94-4682-a7d8-57a52620b86f}")   # FOLDERID_Screenshots
            buf = ctypes.c_wchar_p(); g = (ctypes.c_byte * 16).from_buffer_copy(fid.bytes_le)
            if ctypes.windll.shell32.SHGetKnownFolderPath(g, 0, None, ctypes.byref(buf)) == 0:
                p = buf.value; ctypes.windll.ole32.CoTaskMemFree(buf); return p
        except Exception: pass
    return os.path.join(os.path.expanduser("~"), "Pictures", "Screenshots")


def clips_dir():
    base = os.environ.get("LOCALAPPDATA") or core.config_dir()
    return os.path.join(base, "ScreenshotMarkup", "clips")


def tray_icon():
    pm = QPixmap(64, 64); pm.fill(QColor(0, 0, 0, 0)); p = QPainter(pm); p.setRenderHint(QPainter.Antialiasing)
    p.setBrush(QColor(40, 120, 220)); p.setPen(QPen(QColor(255, 255, 255), 3)); p.drawRoundedRect(6, 10, 52, 44, 8, 8)
    p.setPen(QPen(QColor(255, 220, 0), 7)); p.drawLine(16, 44, 46, 22); p.end()
    return QIcon(pm)


class Watcher(QObject):
    new_image = Signal(str)

    def __init__(self, folder):
        super().__init__(); self.folder = folder; os.makedirs(folder, exist_ok=True)
        self.seen = set(os.listdir(folder)); self.fsw = QFileSystemWatcher([folder]); self.fsw.directoryChanged.connect(self.scan)
        self.poll = QTimer(interval=3000, timeout=self.scan); self.poll.start()   # backup for missed notifications
        self.cb = QGuiApplication.clipboard(); self.cb.dataChanged.connect(self.on_clip); self.ignore_clip_until = 0

    def scan(self, *_):
        try: names = os.listdir(self.folder)
        except OSError: return
        for n in sorted(names):
            if core.is_new_screenshot(n, self.seen):
                self.seen.add(n); path = os.path.join(self.folder, n)
                QTimer.singleShot(400, lambda p=path: self.new_image.emit(p))   # let the writer finish
        self.seen |= set(names)

    def on_clip(self):
        if time.time() < self.ignore_clip_until: return
        md = self.cb.mimeData()
        if not md or not md.hasImage() or md.hasUrls(): return
        img = self.cb.image()
        if img.isNull(): return
        d = clips_dir(); os.makedirs(d, exist_ok=True)
        path = os.path.join(d, time.strftime("clip-%Y%m%d-%H%M%S.png"))
        if img.save(path, "PNG"): self.new_image.emit(path)


class Tray(QObject):
    def __init__(self, app):
        super().__init__(); self.app = app; self.wins = []; self.last = None
        self.icon = QSystemTrayIcon(tray_icon()); self.icon.setToolTip("Screenshot Markup")
        m = QMenu(); m.addAction("Open image…", self.open_dialog); self.edit_last = m.addAction("Edit last screenshot", lambda: self.edit(self.last))
        self.edit_last.setEnabled(False); m.addSeparator(); m.addAction("Quit", app.quit); self.menu = m
        self.icon.setContextMenu(m); self.icon.messageClicked.connect(lambda: self.edit(self.last))
        self.icon.activated.connect(lambda r: self.edit(self.last) if r == QSystemTrayIcon.DoubleClick and self.last else None)
        self.icon.show(); self.watcher = Watcher(screenshots_dir()); self.watcher.new_image.connect(self.notify)
        self.toaster = None
        try:
            from windows_toasts import InteractableWindowsToaster, Toast, ToastButton   # optional dependency
            self._wt = (Toast, ToastButton); self.toaster = InteractableWindowsToaster("Screenshot Markup")
        except Exception: pass

    def notify(self, path):
        self.last = path; self.edit_last.setEnabled(True)
        if self.toaster:
            try:
                Toast, ToastButton = self._wt
                t = Toast(["Screenshot captured", os.path.basename(path)]); t.AddAction(ToastButton("Edit", "edit"))
                t.on_activated = lambda ev, p=path: QTimer.singleShot(0, lambda: self.edit(p))
                self.toaster.show_toast(t); return
            except Exception: pass
        self.icon.showMessage("Screenshot captured", "Click to edit " + os.path.basename(path), QSystemTrayIcon.Information, 15000)

    def edit(self, path):
        if not path or not os.path.exists(path): return
        from markup_qt import Win
        w = Win(path); w.show(); w.raise_(); w.activateWindow(); self.wins = [x for x in self.wins if x.isVisible()] + [w]

    def open_dialog(self):
        f, _ = QFileDialog.getOpenFileName(None, "Open screenshot", screenshots_dir(), "Images (*.png *.jpg *.jpeg *.webp *.bmp)")
        if f: self.edit(f)


def run(app):
    app.setQuitOnLastWindowClosed(False)
    if not QSystemTrayIcon.isSystemTrayAvailable():
        print("No system tray available", file=sys.stderr)
    tray = Tray(app); app._tray = tray
    return app.exec()
