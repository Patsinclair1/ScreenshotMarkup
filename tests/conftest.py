import importlib.util, os, sys
import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, ROOT)


def _has_gtk4():
    if importlib.util.find_spec("gi") is None:
        return False
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import Gtk  # noqa: F401
        return True
    except Exception:
        return False


HAS_GTK4 = _has_gtk4()


@pytest.fixture(scope="session")
def m():
    if not HAS_GTK4:
        pytest.skip("requires GTK/Wayland: PyGObject with GTK 4 is not available on this platform")
    import markup
    return markup
