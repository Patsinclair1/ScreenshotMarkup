#!/usr/bin/env bash
set -euo pipefail
cd "$(dirname "$0")"
B=~/.local/bin; A=~/.local/share/applications; U=~/.config/systemd/user; L=~/.local/share/screenshot-markup
mkdir -p "$B" "$A" "$U" "$L"
install -m755 markup.py "$L/markup.py"
install -m644 markup_core.py "$L/markup_core.py"
printf '#!/bin/sh\nexec python3 %s/markup.py "$@"\n' "$L" > "$B/screenshot-markup"; chmod 755 "$B/screenshot-markup"
cat > "$A/dev.paddy.ScreenshotMarkup.desktop" <<D
[Desktop Entry]
Type=Application
Name=Screenshot Markup
Comment=Draw and highlight on screenshots
Exec=$B/screenshot-markup %F
Icon=applications-graphics
MimeType=image/png;image/jpeg;image/webp;
Categories=Graphics;
Terminal=false
D
# Old watcher service is superseded by the GNOME Shell extension
systemctl --user disable --now screenshot-markup-watcher.service 2>/dev/null || true
rm -f "$U/screenshot-markup-watcher.service"
E=~/.local/share/gnome-shell/extensions/screenshot-markup@paddy.dev
mkdir -p "$E"; cp extension/screenshot-markup@paddy.dev/* "$E/"
gnome-extensions enable screenshot-markup@paddy.dev 2>/dev/null || \
  gsettings set org.gnome.shell enabled-extensions "$(python3 -c "import ast,subprocess;l=ast.literal_eval(subprocess.check_output(['gsettings','get','org.gnome.shell','enabled-extensions'],text=True).replace('@as ',''));u='screenshot-markup@paddy.dev';print(l if u in l else l+[u])")"
update-desktop-database "$A" 2>/dev/null || true
systemctl --user daemon-reload
echo "Installed. Right-click a PNG > Open With > Screenshot Markup, or click Edit on the screenshot notification (log out/in once after first install on Wayland)."
