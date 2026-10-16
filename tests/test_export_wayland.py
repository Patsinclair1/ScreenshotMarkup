"""Wraps the save/copy regression script; it needs a real GNOME Wayland session."""
import os, shutil, subprocess, sys
import pytest
from conftest import ROOT, HAS_GTK4

pytestmark = [pytest.mark.gtk, pytest.mark.wayland]


@pytest.mark.skipif(not HAS_GTK4, reason="requires GTK/Wayland: PyGObject with GTK 4 missing")
@pytest.mark.skipif(not os.environ.get("WAYLAND_DISPLAY") or not shutil.which("wl-paste"),
                    reason="requires GTK/Wayland: needs a Wayland session + wl-paste for the clipboard check (not available under xvfb)")
def test_save_and_copy_include_annotations():
    r = subprocess.run([sys.executable, os.path.join(ROOT, "tests/test_export.py")],
                       capture_output=True, text=True, timeout=120)
    assert r.returncode == 0, r.stdout[-2000:] + r.stderr[-2000:]
