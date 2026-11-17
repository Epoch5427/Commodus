#!/usr/bin/env bash
set -euo pipefail

if [[ "${MSYSTEM:-}" != "UCRT64" ]]; then
    echo "Error: Run this script inside an MSYS2 UCRT64 shell on Windows (or via GitHub Actions)." >&2
    exit 1
fi

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "$SCRIPT_DIR/../.." && pwd)"
cd "$ROOT_DIR"

export LC_ALL=C.UTF-8
export LANG=C.UTF-8
export PYTHONUTF8=1

BUILD_DIR="$ROOT_DIR/builddir"
INSTALL_DIR="$BUILD_DIR/_install"

rm -rf "$BUILD_DIR" "$ROOT_DIR/dist" "$ROOT_DIR/build"

# MSYS2_ARG_CONV_EXCL keeps --prefix=/ucrt64 from turning into a Windows host path
MSYS2_ARG_CONV_EXCL="--prefix" meson setup "$BUILD_DIR" "$ROOT_DIR" --prefix=/ucrt64 -Dbuildtype=release
meson compile -C "$BUILD_DIR"
DESTDIR="$INSTALL_DIR" meson install -C "$BUILD_DIR"

# Ensure hicolor index.theme is present before caching app icons
while IFS= read -r -d '' hicolor_dir; do
    if [ ! -f "$hicolor_dir/index.theme" ] && [ -f "$MINGW_PREFIX/share/icons/hicolor/index.theme" ]; then
        cp "$MINGW_PREFIX/share/icons/hicolor/index.theme" "$hicolor_dir/"
    fi
    gtk4-update-icon-cache -f "$hicolor_dir" || true
done < <(find "$INSTALL_DIR" -type d -name "hicolor" -print0)

pyinstaller --noconfirm --clean "$SCRIPT_DIR/Commodus.spec"

# Verify the bundled gschemas.compiled actually contains Commodus's schema (isolated from system schemas)
python -c "
import gi
gi.require_version('Gio', '2.0')
from gi.repository import Gio
src = Gio.SettingsSchemaSource.new_from_directory('dist/Commodus/_internal/share/glib-2.0/schemas', None, False)
assert src.lookup('io.github.Epoch5427.Commodus', True) is not None, 'Missing Commodus GSettings schema in dist!'
print('Verified Commodus GSettings schema in bundle.')
"
