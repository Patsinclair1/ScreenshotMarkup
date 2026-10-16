"""Platform-independent checks: run everywhere (Linux, Windows, macOS)."""
import json, os, py_compile, xml.etree.ElementTree as ET
from conftest import ROOT

APP_ID = "io.github.patsinclair1.ScreenshotMarkup"


def test_markup_byte_compiles(tmp_path):
    py_compile.compile(os.path.join(ROOT, "markup.py"), cfile=str(tmp_path / "m.pyc"), doraise=True)


def test_metainfo_well_formed():
    root = ET.parse(os.path.join(ROOT, "packaging/data", APP_ID + ".metainfo.xml")).getroot()
    assert root.findtext("id") == APP_ID
    assert root.find("launchable").text == APP_ID + ".desktop"
    assert root.findtext("project_license") == "MIT"
    assert root.find("screenshots/screenshot/image") is not None


def test_desktop_file_basics():
    txt = open(os.path.join(ROOT, "packaging/data", APP_ID + ".desktop")).read()
    for key in ("[Desktop Entry]", "Exec=screenshot-markup", f"Icon={APP_ID}", "MimeType=image/png"):
        assert key in txt


def test_icons_present():
    d = os.path.join(ROOT, "packaging/data")
    assert os.path.exists(os.path.join(d, APP_ID + ".svg"))
    for s in (128, 256, 512):
        with open(os.path.join(d, f"{APP_ID}-{s}.png"), "rb") as f:
            assert f.read(8) == b"\x89PNG\r\n\x1a\n"


def test_extension_metadata():
    base = os.path.join(ROOT, "packaging/ego")
    ext = [d for d in os.listdir(base) if os.path.isdir(os.path.join(base, d))][0]
    meta = json.load(open(os.path.join(base, ext, "metadata.json")))
    assert meta["uuid"] == ext
    assert "50" in meta["shell-version"]
    assert os.path.exists(os.path.join(base, ext, "extension.js"))
