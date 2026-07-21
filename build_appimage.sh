#!/usr/bin/env bash
# Gera AppImage (estrutura AppDir). Requer appimagetool se disponível.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.0.0"
APP="SSH-Manager-Linux"
APPDIR="$ROOT/packaging/appimage/${APP}.AppDir"
OUT="$ROOT/packaging/appimage/${APP}-${VERSION}-x86_64.AppImage"
PKG="ssh-manager-linux"

echo "==> Preparando AppDir"
rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin"
mkdir -p "$APPDIR/usr/lib/$PKG"
mkdir -p "$APPDIR/usr/share/applications"
mkdir -p "$APPDIR/usr/share/icons/hicolor/256x256/apps"

cp -a "$ROOT/app" "$APPDIR/usr/lib/$PKG/"
cp -a "$ROOT/main.py" "$APPDIR/usr/lib/$PKG/"
cp -a "$ROOT/requirements.txt" "$APPDIR/usr/lib/$PKG/"
cp -a "$ROOT/packaging/ssh-manager-linux.desktop" "$APPDIR/"
cp -a "$ROOT/packaging/ssh-manager-linux.desktop" \
  "$APPDIR/usr/share/applications/"

if [[ -f "$ROOT/assets/icons/ssh-manager-linux-256.png" ]]; then
  cp -a "$ROOT/assets/icons/ssh-manager-linux-256.png" "$APPDIR/${PKG}.png"
  cp -a "$ROOT/assets/icons/ssh-manager-linux-256.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/${PKG}.png"
elif [[ -f "$ROOT/assets/icon.png" ]]; then
  cp -a "$ROOT/assets/icon.png" "$APPDIR/${PKG}.png"
  cp -a "$ROOT/assets/icon.png" \
    "$APPDIR/usr/share/icons/hicolor/256x256/apps/${PKG}.png"
fi

cat > "$APPDIR/AppRun" << EOF
#!/usr/bin/env bash
HERE="\$(dirname "\$(readlink -f "\$0")")"
export PYTHONPATH="\$HERE/usr/lib/${PKG}\${PYTHONPATH:+:\$PYTHONPATH}"
VENV="\$HERE/usr/lib/${PKG}/.venv"
if [[ ! -x "\$VENV/bin/python" ]]; then
  python3 -m venv "\$VENV"
  "\$VENV/bin/pip" install -q -r "\$HERE/usr/lib/${PKG}/requirements.txt"
fi
exec "\$VENV/bin/python" "\$HERE/usr/lib/${PKG}/main.py" "\$@"
EOF
chmod 755 "$APPDIR/AppRun"

sed -i 's|^Exec=.*|Exec=AppRun|' "$APPDIR/ssh-manager-linux.desktop"
sed -i "s|^Icon=.*|Icon=${PKG}|" "$APPDIR/ssh-manager-linux.desktop"

echo "==> AppDir pronto em $APPDIR"

if command -v appimagetool >/dev/null 2>&1; then
  ARCH=x86_64 appimagetool "$APPDIR" "$OUT"
  echo "OK: $OUT"
else
  echo "appimagetool não encontrado. AppDir criado; instale appimagetool para gerar .AppImage:"
  echo "  https://github.com/AppImage/AppImageKit/releases"
  echo "  appimagetool $APPDIR $OUT"
fi
