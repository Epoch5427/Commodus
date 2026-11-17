# -*- mode: python ; coding: utf-8 -*-
import glob
import importlib.util
import os
import sys
from PyInstaller.utils.hooks import collect_data_files

block_cipher = None

# SPECPATH is packaging/windows; repo root is two levels up
ROOT = os.path.abspath(os.path.join(SPECPATH, "..", ".."))
BUILD_DIR = os.path.join(ROOT, "builddir")
INSTALL_ROOT = os.path.join(BUILD_DIR, "_install")

# Resolve active MSYS2 UCRT64 prefix dynamically (works locally and in GitHub Actions)
UCRT_PREFIX = sys.base_prefix
if not os.path.isdir(os.path.join(UCRT_PREFIX, "etc", "fonts")):
    UCRT_PREFIX = os.path.dirname(os.path.dirname(sys.executable))

# Discover Meson-installed Python packages regardless of Python 3.x version
commodus_inits = glob.glob(os.path.join(INSTALL_ROOT, "**", "commodus", "__init__.py"), recursive=True)
if not commodus_inits:
    raise FileNotFoundError(f"Could not find installed commodus package under {INSTALL_ROOT}")

pathex_dirs = sorted({os.path.dirname(os.path.dirname(p)) for p in commodus_inits})
pathex_dirs += glob.glob(os.path.join(INSTALL_ROOT, "**", "site-packages"), recursive=True)

gresources = glob.glob(os.path.join(INSTALL_ROOT, "**", "commodus.gresource"), recursive=True)
if not gresources:
    raise FileNotFoundError(f"Could not find commodus.gresource under {INSTALL_ROOT}")

schema_files = glob.glob(
    os.path.join(INSTALL_ROOT, "**", "share", "glib-2.0", "schemas", "*.gschema.xml"),
    recursive=True,
)
if not schema_files:
    raise FileNotFoundError(f"Could not find *.gschema.xml under {INSTALL_ROOT}")

icons_dirs = glob.glob(os.path.join(INSTALL_ROOT, "**", "share", "icons"), recursive=True)
locale_dirs = glob.glob(os.path.join(INSTALL_ROOT, "**", "share", "locale"), recursive=True)

datas = [
    # Fontconfig configuration (prevents scanning C:\Windows\Fonts from scratch)
    (os.path.join(UCRT_PREFIX, "etc", "fonts"), "etc/fonts"),
    # App GResource bundle
    (gresources[0], "share/commodus"),
]

# Pass raw .gschema.xml files so PyInstaller merges and compiles them with GTK/GLib schemas
for sf in schema_files:
    datas.append((sf, "share/glib-2.0/schemas"))

if icons_dirs:
    datas.append((icons_dirs[0], "share/icons"))

if locale_dirs:
    datas.append((locale_dirs[0], "share/locale"))

hidden_imports = [
    "commodus",
    "commodus.main",
    "commodus.window",
]

if importlib.util.find_spec("certifi") is not None:
    datas += collect_data_files("certifi")
    hidden_imports.append("certifi")

a = Analysis(
    [os.path.join(SPECPATH, "run_commodus.py")],
    pathex=pathex_dirs,
    binaries=[
        (os.path.join(BUILD_DIR, "c++", "scheduler.exe"), "."),
    ],
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={
        "gi": {
            "module-versions": {
                "Gtk": "4.0",
                "Gdk": "4.0",
                "Adw": "1",
            }
        }
    },
    runtime_hooks=[],
    excludes=[],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

exe = EXE(
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="Commodus",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,  # Set to False to eliminate decompression overhead and AV scans
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=os.path.join(SPECPATH, "io.github.Epoch5427.Commodus.ico"),
)

coll = COLLECT(
    exe,
    a.binaries,
    a.zipfiles,
    a.datas,
    strip=False,
    upx=False,  # Set to False so GTK's 80+ DLLs are mapped instantly by the Windows kernel
    upx_exclude=[],
    name="Commodus",
)
