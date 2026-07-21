"""Integração com clientes de desktop remoto (RDP/VNC/RustDesk/custom)."""

from app.remote_desktop.launcher import RemoteDesktopLauncher, RemoteSession
from app.remote_desktop.setup import (
    check_remote_rdp,
    install_xrdp_desktop,
    local_freerdp_install_hint,
)

__all__ = [
    "RemoteDesktopLauncher",
    "RemoteSession",
    "check_remote_rdp",
    "install_xrdp_desktop",
    "local_freerdp_install_hint",
]
