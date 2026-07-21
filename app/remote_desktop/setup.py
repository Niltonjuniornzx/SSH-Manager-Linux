"""Preparação de desktop remoto no servidor via SSH (xrdp)."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from app.utils.sanitize import sanitize_for_log

if TYPE_CHECKING:
    from app.ssh.client import SSHClient

logger = logging.getLogger(__name__)


@dataclass
class SetupResult:
    success: bool
    message: str
    details: str = ""
    rdp_port_open: bool = False


async def check_remote_rdp(client: "SSHClient", port: int = 3389) -> SetupResult:
    """Verifica se algo escuta na porta RDP no servidor (via SSH)."""
    if not client.is_connected:
        return SetupResult(False, "SSH não conectado.")
    # ss ou netstat
    cmd = (
        f"(ss -lnt 2>/dev/null || netstat -lnt 2>/dev/null || true) "
        f"| grep -E '[:.]{port}[[:space:]]' || true"
    )
    try:
        code, out, err = await client.run_command(cmd, timeout=15)
        open_ = bool(out.strip())
        # também testar com bash /dev/tcp se disponível
        if not open_:
            code2, out2, _ = await client.run_command(
                f"timeout 2 bash -c 'echo > /dev/tcp/127.0.0.1/{port}' 2>/dev/null && echo OPEN || echo CLOSED",
                timeout=10,
            )
            open_ = "OPEN" in (out2 or "")
        if open_:
            return SetupResult(True, f"Porta {port} aberta no servidor.", rdp_port_open=True)
        return SetupResult(
            False,
            f"Nenhum serviço RDP na porta {port}.",
            details=out or err,
            rdp_port_open=False,
        )
    except Exception as exc:  # noqa: BLE001
        return SetupResult(False, f"Falha ao verificar porta: {exc}")


async def check_xrdp_installed(client: "SSHClient") -> bool:
    code, out, _ = await client.run_command(
        "command -v xrdp >/dev/null 2>&1 && echo YES || echo NO",
        timeout=10,
    )
    return "YES" in (out or "")


async def install_xrdp_desktop(client: "SSHClient", *, desktop: str = "xfce") -> SetupResult:
    """
    Instala xrdp + desktop leve no servidor Ubuntu/Debian (requer root).

    Usa apenas comandos remotos via SSH — sem shell no cliente.
    """
    if not client.is_connected:
        return SetupResult(False, "SSH não conectado.")

    logger.info(sanitize_for_log("Iniciando instalação xrdp no servidor remoto"))

    # Detectar distro
    code, out, _ = await client.run_command(
        "test -f /etc/os-release && . /etc/os-release && echo $ID || echo unknown",
        timeout=10,
    )
    distro = (out or "unknown").strip().lower()
    if distro not in ("ubuntu", "debian", "linuxmint", "pop"):
        # tentar mesmo assim se apt existir
        code, out, _ = await client.run_command(
            "command -v apt-get >/dev/null && echo apt || echo no",
            timeout=10,
        )
        if "apt" not in (out or ""):
            return SetupResult(
                False,
                f"Distro '{distro}' não suportada automaticamente. "
                "Instale xrdp manualmente no servidor.",
            )

    # Comandos sequenciais (mais robusto que um único bash -c gigante)
    steps: list[tuple[str, str]] = [
        ("update", "export DEBIAN_FRONTEND=noninteractive; apt-get update -qq"),
        (
            "install",
            "export DEBIAN_FRONTEND=noninteractive; "
            "apt-get install -y -qq xrdp xorgxrdp xfce4 xfce4-goodies dbus-x11",
        ),
        (
            "startwm",
            "cp -n /etc/xrdp/startwm.sh /etc/xrdp/startwm.sh.bak 2>/dev/null; "
            "printf '%s\\n' '#!/bin/sh' "
            "'if [ -r /etc/default/locale ]; then . /etc/default/locale; "
            "export LANG LANGUAGE; fi' 'startxfce4' > /etc/xrdp/startwm.sh; "
            "chmod +x /etc/xrdp/startwm.sh",
        ),
        (
            "xsession",
            "echo startxfce4 > /root/.xsession; "
            "echo xfce4-session > /root/.xsessionrc 2>/dev/null; true",
        ),
        ("group", "adduser xrdp ssl-cert 2>/dev/null; true"),
        (
            "service",
            "systemctl enable xrdp 2>/dev/null; "
            "systemctl restart xrdp 2>/dev/null || service xrdp restart 2>/dev/null; "
            "sleep 2; true",
        ),
    ]

    details_parts: list[str] = []
    try:
        for name, cmd in steps:
            logger.info(sanitize_for_log(f"xrdp setup step: {name}"))
            code, out, err = await client.run_command(cmd, timeout=600)
            details_parts.append(f"=== {name} (exit {code}) ===")
            if out:
                details_parts.append(out[-1500:])
            if err:
                details_parts.append(err[-800:])
            # falha crítica só no install
            if name == "install" and code not in (0, None):
                return SetupResult(
                    False,
                    f"Falha ao instalar pacotes (código {code}). "
                    "Verifique se o usuário é root e se o apt funciona.",
                    details="\n".join(details_parts)[-3000:],
                )

        check = await check_remote_rdp(client, 3389)
        details = "\n".join(details_parts)[-3000:]
        if check.rdp_port_open:
            return SetupResult(
                True,
                "Desktop remoto (xrdp + XFCE) instalado e porta 3389 ativa.",
                details=details,
                rdp_port_open=True,
            )
        return SetupResult(
            False,
            "Pacotes instalados, mas a porta 3389 ainda não responde. "
            "Tente: systemctl status xrdp no servidor.",
            details=details,
            rdp_port_open=False,
        )
    except Exception as exc:  # noqa: BLE001
        logger.error(sanitize_for_log("Falha install xrdp", error=str(exc)))
        return SetupResult(False, f"Erro na instalação: {exc}")


async def start_xrdp_service(client: "SSHClient") -> SetupResult:
    if not client.is_connected:
        return SetupResult(False, "SSH não conectado.")
    await client.run_command(
        "systemctl start xrdp 2>/dev/null || service xrdp start 2>/dev/null || true",
        timeout=30,
    )
    check = await check_remote_rdp(client, 3389)
    if check.rdp_port_open:
        return SetupResult(True, "Serviço xrdp em execução.", rdp_port_open=True)
    return SetupResult(False, "Não foi possível iniciar o xrdp na porta 3389.")


def local_freerdp_install_hint() -> str:
    return (
        "Cliente FreeRDP não encontrado neste computador.\n\n"
        "Ubuntu/Debian:\n"
        "  sudo apt install freerdp2-x11\n"
        "  # ou: sudo apt install freerdp3-x11\n\n"
        "Arch/CachyOS:\n"
        "  sudo pacman -S freerdp\n"
    )


async def fix_xfce_dpi(client: "SSHClient", dpi: int = 120) -> SetupResult:
    """
    Aumenta DPI/fonte do XFCE na sessão do usuário (corrige menus minúsculos no xrdp).

    Aplica em /root e em homes existentes. Vale para a *próxima* sessão RDP
    (encerre e reconecte o desktop).
    """
    if not client.is_connected:
        return SetupResult(False, "SSH não conectado.")
    dpi = max(96, min(192, int(dpi)))
    # Escala de cursor e fontes um pouco maiores
    cursor = 32 if dpi >= 120 else 24
    # xfconf + settings.ini + Xft.dpi
    script = f"""
set -e
DPI={dpi}
CURSOR={cursor}
fix_dpi() {{
  H="$1"
  [ -d "$H" ] || return 0
  mkdir -p "$H/.config/xfce4/xfconf/xfce-perchannel-xml" "$H/.config/fontconfig"
  # Xresources
  if grep -q Xft.dpi "$H/.Xresources" 2>/dev/null; then
    sed -i "s/Xft.dpi:.*/Xft.dpi: $DPI/" "$H/.Xresources"
  else
    echo "Xft.dpi: $DPI" >> "$H/.Xresources"
  fi
  # xsettings via xfconf xml (funciona sem sessão gráfica)
  cat > "$H/.config/xfce4/xfconf/xfce-perchannel-xml/xsettings.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xsettings" version="1.0">
  <property name="Xft" type="empty">
    <property name="DPI" type="int" value="$DPI"/>
    <property name="Antialias" type="int" value="1"/>
    <property name="Hinting" type="int" value="1"/>
    <property name="HintStyle" type="string" value="hintslight"/>
    <property name="RGBA" type="string" value="rgb"/>
  </property>
  <property name="Gtk" type="empty">
    <property name="CursorThemeSize" type="int" value="$CURSOR"/>
    <property name="FontName" type="string" value="Sans 12"/>
  </property>
</channel>
EOF
  # painel um pouco mais alto
  cat > "$H/.config/xfce4/xfconf/xfce-perchannel-xml/xfce4-panel.xml" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<channel name="xfce4-panel" version="1.0">
  <property name="panels" type="array">
    <value type="int" value="1"/>
    <property name="panel-1" type="empty">
      <property name="size" type="uint" value="36"/>
      <property name="icon-size" type="uint" value="24"/>
    </property>
  </property>
</channel>
EOF
  echo "OK $H"
}}
fix_dpi /root
for d in /home/*; do fix_dpi "$d"; done
# xrdp: forçar DPI no startwm se possível
if [ -f /etc/xrdp/startwm.sh ]; then
  if ! grep -q Xft.dpi /etc/xrdp/startwm.sh 2>/dev/null; then
    sed -i '1a echo "Xft.dpi: {dpi}" | xrdb -merge 2>/dev/null || true' /etc/xrdp/startwm.sh 2>/dev/null || true
  fi
fi
echo DPI_FIXED
"""
    # Injetar dpi no sed line - already used {dpi} in f-string for startwm - need fix
    script = script.replace("{dpi}", str(dpi))
    try:
        code, out, err = await client.run_command(f"bash -c {repr(script)}", timeout=60)
        details = (out or "") + (err or "")
        if "DPI_FIXED" in details or code == 0:
            return SetupResult(
                True,
                f"DPI do XFCE ajustado para {dpi}. Encerre a sessão RDP e conecte de novo.",
                details=details[-1500:],
                rdp_port_open=True,
            )
        return SetupResult(False, "Não foi possível ajustar o DPI.", details=details[-1500:])
    except Exception as exc:  # noqa: BLE001
        return SetupResult(False, f"Erro ao ajustar DPI: {exc}")


def suggest_rdp_geometry() -> tuple[str, int]:
    """Sugere resolução e escala com base no monitor local."""
    try:
        from PySide6.QtGui import QGuiApplication

        screen = QGuiApplication.primaryScreen()
        if screen is None:
            return "1600x900", 140
        geo = screen.availableGeometry()
        # deixar margem para barra do SO e moldura da janela
        w = max(1280, min(geo.width() - 80, 1920))
        h = max(720, min(geo.height() - 120, 1080))
        # arredondar para múltiplos pares
        w = w - (w % 2)
        h = h - (h % 2)
        dpi = screen.logicalDotsPerInch()
        if dpi >= 140:
            scale = 180
        elif dpi >= 110:
            scale = 140
        else:
            scale = 140  # default um pouco maior — xrdp costuma ficar miúdo
        return f"{w}x{h}", scale
    except Exception:  # noqa: BLE001
        return "1600x900", 140

