# Screenshot Markup

A lightweight GTK4/Python annotator for screenshots: pen, multiply-blend highlighter with strength slider,
shapes, editable text, mark-only eraser, OCR transcript (tesseract) with clickable links, zoom, undo,
save a copy and copy to clipboard.

## Run from source
    python3 markup.py path/to/image.png
Needs PyGObject with GTK 4, pycairo, and optionally `tesseract` on PATH for the Transcript tool.

`./install.sh` / `./uninstall.sh` do a per-user install (launcher, desktop file, GNOME extension).

## Packaging (see `packaging/`)
| Target | File | Status |
|---|---|---|
| Flathub | `packaging/flatpak/io.github.OWNER.ScreenshotMarkup.yml` | builds locally (see below) |
| GNOME Extensions | `packaging/ego/screenshot-markup@OWNER.github.io.shell-extension.zip` | packed, upload by hand |
| Snap (optional) | `packaging/snap/snapcraft.yaml` | written, not built |
| Metainfo / desktop / icons | `packaging/data/` | validated with appstreamcli + desktop-file-validate |

Build the Flatpak locally:

    cd packaging/flatpak
    flatpak run org.flatpak.Builder --user --force-clean --install-deps-from=flathub \
        --install build io.github.OWNER.ScreenshotMarkup.yml
    flatpak run io.github.OWNER.ScreenshotMarkup

### Sandbox notes
- **GNOME Shell extension** can't ship in a Flatpak; it goes to extensions.gnome.org separately. The EGO
  version launches the app through its desktop file (Flatpak or native), falling back to `~/.local/bin`.
- **Saving:** "Save copy" writes next to the original, which needs `--filesystem=xdg-pictures`. Save As
  uses the FileChooser portal and works anywhere.
- **Clipboard:** works under Wayland in the sandbox (GDK ContentProvider, no wl-copy).
- **Opening links** from the Transcript uses `Gtk.UriLauncher` → OpenURI portal.
- **No Screenshots-folder watcher** in the Flatpak (the old systemd watcher was removed); the Edit
  button comes from the extension, or use "Open With" in Files.
- **OCR:** tesseract 5.5.1 + leptonica 1.85.0 + English `tessdata_fast` are bundled; `TESSDATA_PREFIX` is set by the launcher.
