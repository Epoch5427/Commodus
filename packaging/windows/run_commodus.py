import gettext
import locale
import os
import sys

if os.name == "nt":
    os.environ.setdefault("DBUS_SESSION_BUS_ADDRESS", "none")
    os.environ.setdefault("GTK_A11Y", "none")

base_dir = (
    sys._MEIPASS
    if getattr(sys, "frozen", False)
    else os.path.dirname(os.path.abspath(__file__))
)

# Make sure shutil.which("scheduler") finds _internal/scheduler.exe
os.environ["PATH"] = base_dir + os.pathsep + os.environ.get("PATH", "")

share_dir = os.path.join(base_dir, "share")
os.environ["GSETTINGS_SCHEMA_DIR"] = os.path.join(share_dir, "glib-2.0", "schemas")
os.environ["XDG_DATA_DIRS"] = share_dir + os.pathsep + os.environ.get("XDG_DATA_DIRS", "")
os.environ["FONTCONFIG_PATH"] = os.path.join(base_dir, "etc", "fonts")
os.environ["FONTCONFIG_FILE"] = os.path.join(base_dir, "etc", "fonts", "fonts.conf")
os.environ["XDG_CACHE_HOME"] = os.environ.get("LOCALAPPDATA", os.path.expanduser("~"))

try:
    import certifi
    os.environ.setdefault("SSL_CERT_FILE", certifi.where())
except ImportError:
    pass

localedir = os.path.join(share_dir, "locale")
if hasattr(locale, "bindtextdomain"):
    locale.bindtextdomain("commodus", localedir)
    locale.textdomain("commodus")
gettext.bindtextdomain("commodus", localedir)
gettext.textdomain("commodus")
gettext.install("commodus", localedir)

import gi
gi.require_version("Gtk", "4.0")
gi.require_version("Adw", "1")
from gi.repository import Gio

gresource_path = os.path.join(share_dir, "commodus", "commodus.gresource")
if os.path.exists(gresource_path):
    resource = Gio.Resource.load(gresource_path)
    Gio.resources_register(resource)

try:
    from commodus.version import APP_VERSION
except ImportError:
    APP_VERSION = "1.3.0"

from commodus.main import main

if __name__ == "__main__":
    sys.exit(main(APP_VERSION))
