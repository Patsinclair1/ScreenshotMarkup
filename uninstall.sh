#!/usr/bin/env bash
systemctl --user disable --now screenshot-markup-watcher.service 2>/dev/null
rm -f ~/.config/systemd/user/screenshot-markup-watcher.service ~/.local/bin/screenshot-markup \
      ~/.local/share/applications/dev.paddy.ScreenshotMarkup.desktop
gnome-extensions disable screenshot-markup@paddy.dev 2>/dev/null
rm -rf ~/.local/share/gnome-shell/extensions/screenshot-markup@paddy.dev
rm -rf ~/.local/share/screenshot-markup
systemctl --user daemon-reload; update-desktop-database ~/.local/share/applications 2>/dev/null || true
echo "Uninstalled."
# OCR engine (installed per-user with Homebrew). Remove it with:
#   brew uninstall tesseract leptonica   (kept by default in case other tools use it)
if [ "${1:-}" = "--with-ocr" ] && command -v brew >/dev/null; then brew uninstall tesseract && brew autoremove; fi
