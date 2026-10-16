# Build dist\ScreenshotMarkup.exe with PyInstaller (run from the repo root, in a venv with requirements-windows.txt + pyinstaller + pillow).
$ErrorActionPreference = "Stop"
pyinstaller --noconfirm --clean --onefile --windowed --name ScreenshotMarkup `
  --icon packaging/data/io.github.patsinclair1.ScreenshotMarkup-256.png `
  --hidden-import markup_tray --hidden-import markup_core `
  --collect-submodules winrt --collect-submodules windows_toasts `
  markup_qt.py
Get-Item dist\ScreenshotMarkup.exe | Format-List Name, Length
