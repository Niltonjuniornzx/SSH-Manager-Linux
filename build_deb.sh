#!/usr/bin/env bash
# Gera pacote .deb do SSH-Manager-Linux
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
VERSION="1.0.0"
PKG_NAME="ssh-manager-linux"
BUILD="$ROOT/packaging/deb/build"
DIST="$ROOT/packaging/deb"

echo "==> Limpando build anterior"
rm -rf "$BUILD"
mkdir -p "$BUILD/DEBIAN"
mkdir -p "$BUILD/usr/lib/$PKG_NAME"
mkdir -p "$BUILD/usr/bin"
mkdir -p "$BUILD/usr/share/applications"
mkdir -p "$BUILD/usr/share/icons/hicolor/256x256/apps"
mkdir -p "$BUILD/usr/share/doc/$PKG_NAME"

echo "==> Copiando arquivos"
cp -a "$ROOT/app" "$BUILD/usr/lib/$PKG_NAME/"
cp -a "$ROOT/main.py" "$BUILD/usr/lib/$PKG_NAME/"
cp -a "$ROOT/pyproject.toml" "$BUILD/usr/lib/$PKG_NAME/" 2>/dev/null || true
cp -a "$ROOT/requirements.txt" "$BUILD/usr/lib/$PKG_NAME/"
cp -a "$ROOT/README.md" "$BUILD/usr/share/doc/$PKG_NAME/"
cp -a "$ROOT/LICENSE" "$BUILD/usr/share/doc/$PKG_NAME/" 2>/dev/null || true
cp -a "$ROOT/packaging/ssh-manager-linux.desktop" \
  "$BUILD/usr/share/applications/"

ICON_SRC=""
if [[ -f "$ROOT/assets/icons/ssh-manager-linux-256.png" ]]; then
  ICON_SRC="$ROOT/assets/icons/ssh-manager-linux-256.png"
elif [[ -f "$ROOT/assets/icon.png" ]]; then
  ICON_SRC="$ROOT/assets/icon.png"
fi
if [[ -n "$ICON_SRC" ]]; then
  cp -a "$ICON_SRC" \
    "$BUILD/usr/share/icons/hicolor/256x256/apps/ssh-manager-linux.png"
fi

echo "==> Wrapper em /usr/bin"
cat > "$BUILD/usr/bin/ssh-manager-linux" << 'EOF'
#!/usr/bin/env bash
ROOT="/usr/lib/ssh-manager-linux"
export PYTHONPATH="$ROOT${PYTHONPATH:+:$PYTHONPATH}"
if [[ -x "$ROOT/.venv/bin/python" ]]; then
  exec "$ROOT/.venv/bin/python" "$ROOT/main.py" "$@"
fi
exec python3 "$ROOT/main.py" "$@"
EOF
chmod 755 "$BUILD/usr/bin/ssh-manager-linux"

echo "==> Control"
if [[ -f "$ROOT/packaging/deb/control" ]]; then
  # atualizar Package name no control se necessário
  sed "s/^Package:.*/Package: ${PKG_NAME}/" "$ROOT/packaging/deb/control" \
    > "$BUILD/DEBIAN/control"
else
  cat > "$BUILD/DEBIAN/control" << EOF
Package: ${PKG_NAME}
Version: ${VERSION}
Section: net
Priority: optional
Architecture: all
Depends: python3 (>= 3.12), python3-venv
Maintainer: SSH-Manager-Linux
Description: SSH-Manager-Linux — cliente desktop SSH/SFTP para Linux
EOF
fi

cat > "$BUILD/DEBIAN/postinst" << 'EOF'
#!/bin/sh
set -e
ROOT=/usr/lib/ssh-manager-linux
if command -v python3 >/dev/null; then
  if [ ! -d "$ROOT/.venv" ]; then
    python3 -m venv "$ROOT/.venv" 2>/dev/null || true
  fi
  if [ -x "$ROOT/.venv/bin/pip" ]; then
    "$ROOT/.venv/bin/pip" install --upgrade pip -q || true
    "$ROOT/.venv/bin/pip" install -r "$ROOT/requirements.txt" -q || true
  fi
fi
update-desktop-database /usr/share/applications 2>/dev/null || true
exit 0
EOF
chmod 755 "$BUILD/DEBIAN/postinst"

echo "==> Construindo .deb"
if command -v dpkg-deb >/dev/null 2>&1; then
  dpkg-deb --build "$BUILD" "$DIST/${PKG_NAME}_${VERSION}_all.deb"
  echo "OK: $DIST/${PKG_NAME}_${VERSION}_all.deb"
else
  echo "dpkg-deb não encontrado. Estrutura pronta em $BUILD"
  echo "Instale dpkg-dev e rode novamente para gerar o .deb"
fi
