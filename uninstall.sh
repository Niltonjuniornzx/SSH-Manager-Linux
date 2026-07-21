#!/usr/bin/env bash
# Remove instalação do usuário (launcher, ícones, pasta do app).
set -euo pipefail

APP_ID="ssh-manager-linux"
APP_NAME="SSH-Manager-Linux"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/${APP_ID}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

echo "==> Removendo ${APP_NAME} (${APP_ID})"

rm -f "${BIN_DIR}/${APP_ID}" \
      "${BIN_DIR}/ssh-remote-manager" \
      "${BIN_DIR}/nzxs-remote-manager"

rm -f "${APPS_DIR}/${APP_ID}.desktop" \
      "${APPS_DIR}/nzxs-remote-manager.desktop" \
      "${APPS_DIR}/ssh-remote-manager.desktop"

for size in 16 32 48 64 128 256 512; do
  rm -f "${ICONS_BASE}/${size}x${size}/apps/${APP_ID}.png"
done

if [[ -d "${INSTALL_DIR}" ]]; then
  rm -rf "${INSTALL_DIR}"
  echo "    Removido: ${INSTALL_DIR}"
fi

if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi

echo "OK — desinstalado."
echo "Dados de perfil (opcional) ainda em:"
echo "  ~/.local/share/ssh-manager-linux/"
echo "  ~/.config/ssh-manager-linux/"
echo "Pastas legadas (se existirem):"
echo "  ~/.local/share/nzxs-remote-manager/"
echo "Para apagar também os perfis/credenciais locais:"
echo "  rm -rf ~/.local/share/ssh-manager-linux ~/.config/ssh-manager-linux"
