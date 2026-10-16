# Porting plan: Windows and macOS
Covers both apps: **Screenshot Markup** (GTK4/Python) and **Edgetune** (GTK3/Python hotbar).

## What is Linux-only today
| Piece | App | Why |
|---|---|---|
| GNOME Shell extension (Edit button) | Markup | GNOME Shell only |
| `~/Pictures/Screenshots` convention, Wayland clipboard/portals | Markup | Linux desktop |
| MPRIS over D-Bus (`dbus-python`) | Edgetune | Linux only |
| EWMH via python-xlib (find/raise/minimise Spotify, screen-edge docking, fullscreen detection) | Edgetune | X11/XWayland only |
| `GDK_BACKEND=x11`, `/proc` scanning, `flatpak run`, `xdg-open`, `playerctl` | Edgetune | Linux only |
| Spicetify/CDP extras (`hotbar_cdp.py`) | Edgetune | Portable in principle, but needs Spicetify; drop for stores |
| Cairo drawing, tesseract OCR, LRCLIB lyrics, URL detection | both | **portable** |

## Windows (MSIX / Microsoft Store)
**Toolkit options**
1. *Keep PyGObject/GTK via MSYS2* (`mingw-w64-ucrt-x86_64-gtk4`, `-python-gobject`). Works, but you have
   to bundle the whole MSYS2 runtime (~150–250 MB), fonts/theming look non-native, and MSIX packaging of
   MSYS2 trees is fiddly (no PyInstaller hooks for GTK4 out of the box). OK for Markup, poor for Edgetune.
2. *Rewrite the UI in Qt/PySide6* (recommended): one codebase for Windows and macOS, PyInstaller or
   Nuitka → MSIX via `MakeAppx`/MSIX Packaging Tool. QPainter covers the cairo drawing
   (CompositionMode_Multiply/Screen for the highlighter).

**Markup on Windows**: no GNOME extension. Entry points: (a) "Open with" for PNG via MSIX file-type
association; (b) a tray app that registers a global Print Screen hook (`RegisterHotKey`/low-level keyboard
hook), captures with the Windows.Graphics.Capture API or `mss`, then opens the editor; or (c) watch the
Snipping Tool's `%USERPROFILE%\Pictures\Screenshots` folder and show a toast with an **Edit** action
(Windows App SDK notifications). Clipboard via `QClipboard.setImage`. OCR: bundle tesseract.exe or use
`Windows.Media.Ocr` (built in, via `winrt` Python projections). Note: in an MSIX the PrtScn key is
claimed by Snipping Tool unless the user turns that setting off.

**Edgetune on Windows**: replace MPRIS with **SMTC** (`Windows.Media.Control.GlobalSystemMediaTransportControlsSessionManager`,
via `winrt-Windows.Media.Control`), which gives Spotify's title/artist/art/playback state and play/pause/next/prev/seek.
Volume is not exposed by SMTC, so use per-app audio session volume (pycaw/`ISimpleAudioVolume`).
Window raising: `SetForegroundWindow` with restrictions, or `spotify:` URI. Edge docking: a frameless
always-on-top Qt window (or AppBar `SHAppBarMessage`). Lyrics stay as LRCLIB.

## macOS (Mac App Store or notarised direct download)
- **Sandbox:** App Store apps must be sandboxed. Markup: user-selected file access + Pictures entitlement;
  screen capture needs the Screen Recording permission (ScreenCaptureKit). Edgetune: network client entitlement,
  and controlling Spotify needs the Apple Events entitlement with `com.apple.security.temporary-exception.apple-events`
  for `com.spotify.client` (or `NSAppleEventsUsageDescription` outside the store). App Review may reject temporary exceptions,
  so a notarised direct download is the safer first route for Edgetune.
- **Now-playing data:** the **MediaRemote** framework is private and **not allowed** on the App Store (and has been
  locked down since macOS 15.4). Use **Spotify's AppleScript dictionary** (`tell application "Spotify"` → current track,
  player state, playpause, next track, sound volume, player position) or the **Spotify Web API** (OAuth, needs a
  registered Spotify developer app and their Developer Terms).
- **Toolkit:** Qt/PySide6 (shared with Windows) bundled with PyInstaller/briefcase, then codesign + notarise; or native
  Swift/SwiftUI (best fit for a menu-bar/edge widget, ScreenCaptureKit, Vision OCR `VNRecognizeTextRequest`).
- **Markup entry:** Services/Share menu extension, "Open With", or a menu-bar app with a global hotkey; macOS
  ⇧⌘5 screenshots land on the Desktop by default.
- **Signing:** Developer ID Application cert + `notarytool` for outside-store; Mac App Distribution cert for the store.

## Effort estimate (one experienced dev; Markup ≈1,000 lines, Edgetune ≈3,200 lines)
| Work | Estimate |
|---|---|
| Markup → PySide6 (canvas, tools, undo, text objects, zoom, transcript panel) | 6–9 days |
| Markup Windows integration (MSIX, file assoc, tray/hotkey or toast, OCR) | 3–5 days |
| Markup macOS integration (sandbox, capture permission, Vision or tesseract, notarise) | 3–5 days |
| Edgetune → PySide6 (custom-painted panel, springs, lyrics) | 6–10 days |
| Edgetune media backend abstraction + SMTC (Win) + AppleScript (mac) | 4–6 days |
| Edgetune window/edge docking per OS | 2–4 days |
| Packaging/CI (PyInstaller, MSIX, codesign/notarise, GitHub Actions) | 3–5 days |
| **Total** | **≈ 27–44 dev-days** (Swift-native macOS instead of PySide6: add ~2 weeks) |

Low-cost interim option for Markup on Windows: MSYS2 GTK4 build in ~3–5 days, with no rewrite and a large, less native package.
