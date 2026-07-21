#!/usr/bin/env bash
# Instala o SSH-Manager-Linux para o usuário atual (sem root).
# - Copia/usa o código em ~/.local/share/ssh-manager-linux
# - Cria venv e instala dependências Python
# - Instala ícones e launcher no menu de aplicativos
set -euo pipefail

APP_ID="ssh-manager-linux"
APP_NAME="SSH-Manager-Linux"
INSTALL_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/${APP_ID}"
BIN_DIR="${XDG_BIN_HOME:-$HOME/.local/bin}"
APPS_DIR="${XDG_DATA_HOME:-$HOME/.local/share}/applications"
ICONS_BASE="${XDG_DATA_HOME:-$HOME/.local/share}/icons/hicolor"

# Diretório deste script (= raiz do repositório ao clonar)
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "==> ${APP_NAME} — instalação local"
echo "    Destino: ${INSTALL_DIR}"

# Python
if ! command -v python3 >/dev/null 2>&1; then
  echo "Erro: python3 não encontrado. Instale com:"
  echo "  sudo apt install python3 python3-venv python3-pip"
  exit 1
fi

PY_VER="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
# shellcheck disable=SC2072
if [[ "$(printf '%s\n' "3.12" "$PY_VER" | sort -V | head -n1)" != "3.12" ]]; then
  echo "Aviso: recomendado Python 3.12+ (encontrado ${PY_VER}). Continuando…"
fi

# Dependências de sistema (opcional, se apt existir e sudo funcionar)
if command -v apt-get >/dev/null 2>&1; then
  if sudo -n true 2>/dev/null; then
    echo "==> Dependências de sistema (apt)"
    sudo apt-get install -y -qq python3-venv python3-pip libsecret-1-0 openssh-client || true
  else
    echo "==> Dica: se faltar keyring/SSH, rode:"
    echo "    sudo apt install python3-venv python3-pip libsecret-1-0 openssh-client"
  fi
fi

echo "==> Copiando arquivos"
mkdir -p "${INSTALL_DIR}"
# rsync se existir; senão cp
if command -v rsync >/dev/null 2>&1; then
  rsync -a --delete \
    --exclude '.venv' \
    --exclude '.git' \
    --exclude '.pytest_cache' \
    --exclude '.ruff_cache' \
    --exclude '__pycache__' \
    --exclude '*.pyc' \
    --exclude 'packaging/deb/build' \
    --exclude 'packaging/appimage' \
    --exclude 'manager.db' \
    --exclude 'manager.db-wal' \
    --exclude 'manager.db-shm' \
    --exclude 'known_hosts' \
    --exclude 'logs' \
    "${ROOT}/" "${INSTALL_DIR}/"
else
  # cópia simples (preserva .venv e dados do usuário)
  find "${INSTALL_DIR}" -mindepth 1 -maxdepth 1 \
    ! -name '.venv' \
    ! -name 'manager.db' \
    ! -name 'manager.db-wal' \
    ! -name 'manager.db-shm' \
    ! -name 'known_hosts' \
    ! -name 'logs' \
    -exec rm -rf {} + 2>/dev/null || true
  cp -a "${ROOT}/app" "${ROOT}/main.py" "${ROOT}/requirements.txt" \
    "${ROOT}/pyproject.toml" "${ROOT}/assets" "${ROOT}/LICENSE" \
    "${ROOT}/README.md" "${INSTALL_DIR}/" 2>/dev/null || true
  # garantir assets
  mkdir -p "${INSTALL_DIR}/assets"
  cp -a "${ROOT}/assets/." "${INSTALL_DIR}/assets/" 2>/dev/null || true
fi

echo "==> Ambiente virtual Python"
if [[ ! -x "${INSTALL_DIR}/.venv/bin/python" ]]; then
  python3 -m venv "${INSTALL_DIR}/.venv"
fi
# shellcheck disable=SC1091
source "${INSTALL_DIR}/.venv/bin/activate"
pip install -q --upgrade pip
pip install -q -r "${INSTALL_DIR}/requirements.txt"

echo "==> Launcher em ${BIN_DIR}"
mkdir -p "${BIN_DIR}"
cat > "${BIN_DIR}/${APP_ID}" << EOF
#!/usr/bin/env bash
exec "${INSTALL_DIR}/.venv/bin/python" "${INSTALL_DIR}/main.py" "\$@"
EOF
chmod 755 "${BIN_DIR}/${APP_ID}"
# alias amigável
ln -sfn "${BIN_DIR}/${APP_ID}" "${BIN_DIR}/ssh-remote-manager"
ln -sfn "${BIN_DIR}/${APP_ID}" "${BIN_DIR}/nzxs-remote-manager"

echo "==> Ícones"
install_icon() {
  local size="$1"
  local src="$2"
  local dir="${ICONS_BASE}/${size}x${size}/apps"
  mkdir -p "${dir}"
  if [[ -f "${src}" ]]; then
    cp -f "${src}" "${dir}/${APP_ID}.png"
  fi
}
ICON_SRC="${INSTALL_DIR}/assets/icons"
install_icon 16  "${ICON_SRC}/ssh-manager-linux-16.png"
install_icon 32  "${ICON_SRC}/ssh-manager-linux-32.png"
install_icon 48  "${ICON_SRC}/ssh-manager-linux-48.png"
install_icon 64  "${ICON_SRC}/ssh-manager-linux-64.png"
install_icon 128 "${ICON_SRC}/ssh-manager-linux-128.png"
install_icon 256 "${ICON_SRC}/ssh-manager-linux-256.png"
install_icon 512 "${ICON_SRC}/ssh-manager-linux-512.png"
# fallback
if [[ ! -f "${ICONS_BASE}/256x256/apps/${APP_ID}.png" ]] && [[ -f "${INSTALL_DIR}/assets/icon.png" ]]; then
  install_icon 256 "${INSTALL_DIR}/assets/icon.png"
fi

echo "==> Atalho no menu de aplicativos"
mkdir -p "${APPS_DIR}"
cat > "${APPS_DIR}/${APP_ID}.desktop" << EOF
[Desktop Entry]
Version=1.0
Type=Application
Name=${APP_NAME}
Name[pt_BR]=SSH-Manager-Linux
GenericName=SSH Client
GenericName[pt_BR]=Cliente SSH
Comment=SSH/SFTP tunnel manager for Linux
Comment[pt_BR]=Gerenciador SSH e SFTP para Linux
Exec=${BIN_DIR}/${APP_ID}
Icon=${APP_ID}
Terminal=false
Categories=Network;RemoteAccess;System;
Keywords=SSH;SFTP;Tunnel;Server;Remote;
StartupNotify=true
StartupWMClass=SSH-Manager-Linux
EOF
chmod 644 "${APPS_DIR}/${APP_ID}.desktop"

# Atualizar caches do desktop (se existirem)
if command -v update-desktop-database >/dev/null 2>&1; then
  update-desktop-database "${APPS_DIR}" 2>/dev/null || true
fi
if command -v gtk-update-icon-cache >/dev/null 2>&1; then
  gtk-update-icon-cache -f -t "${ICONS_BASE}" 2>/dev/null || true
fi

# PATH
if ! echo ":$PATH:" | grep -q ":${BIN_DIR}:"; then
  echo ""
  echo "Aviso: ${BIN_DIR} não está no PATH."
  echo "Adicione ao ~/.bashrc:"
  echo "  export PATH=\"${BIN_DIR}:\$PATH\""
fi

echo ""
echo "OK — instalação concluída."
echo ""
echo "  Abrir pelo menu:  procure \"SSH-Manager-Linux\""
echo "  Pelo terminal:    ${APP_ID}"
echo "  (aliases legados ssh-remote-manager / nzxs-remote-manager também instalados)"
echo ""
echo "  Desinstalar:      ${INSTALL_DIR}/uninstall.sh"
echo "                    (ou: bash ${ROOT}/uninstall.sh)"
echo ""

# copiar uninstall para install dir
cp -f "${ROOT}/uninstall.sh" "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
chmod 755 "${INSTALL_DIR}/uninstall.sh" 2>/dev/null || true
