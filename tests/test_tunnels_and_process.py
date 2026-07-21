"""Testes de túneis (portas) e construção segura de argumentos."""

from __future__ import annotations

import json

import pytest

from app.models.remote import RemoteProfile, RemoteProtocol
from app.models.server import ServerProfile
from app.models.tunnel import TunnelProfile
from app.remote_desktop.launcher import RemoteDesktopLauncher
from app.tunnels.manager import TunnelManager
from app.utils.network import find_free_port, is_port_in_use
from app.utils.process import build_safe_preview, find_executable


def test_find_free_port():
    port = find_free_port("127.0.0.1", 20000, 30000)
    assert 20000 <= port < 30000
    assert is_port_in_use(port, "127.0.0.1") is False


def test_tunnel_port_conflict_validation():
    mgr = TunnelManager(get_connection=lambda sid: None)
    running = TunnelProfile(
        id=1,
        server_id=1,
        name="A",
        listen_port=19999,
        listen_address="127.0.0.1",
    )
    from app.models.tunnel import TunnelStatus

    running.status = TunnelStatus.RUNNING
    mgr._profiles[1] = running
    errors = mgr.validate_port(19999, "127.0.0.1")
    assert any("uso" in e.lower() for e in errors)


def test_tunnel_default_local_only():
    t = TunnelProfile(name="t", server_id=1, listen_address="0.0.0.0", local_only=True)
    assert t.effective_listen_address() == "127.0.0.1"


def test_rdp_args_no_shell_and_redacts_password():
    launcher = RemoteDesktopLauncher()
    # force detect path if freerdp missing — skip build
    exe = find_executable(RemoteDesktopLauncher.RDP_CANDIDATES)
    if not exe:
        pytest.skip("FreeRDP não instalado")
    profile = RemoteProfile(
        enabled=True,
        protocol=RemoteProtocol.RDP,
        use_ssh_host=True,
        port=3389,
        username="admin",
    )
    server = ServerProfile(name="S", host="10.0.0.5", username="admin")
    args, _ = launcher.build_args(profile, server, password="SuperSecret123")
    assert args[0] == exe
    assert all(isinstance(a, str) for a in args)
    preview = build_safe_preview(args)
    assert "SuperSecret123" not in preview
    # password may be in raw args but never in preview/logs
    assert any(a.startswith("/v:") for a in args)


def test_custom_command_json_args():
    launcher = RemoteDesktopLauncher()
    # use /bin/true or /bin/echo as executable
    import shutil

    exe = shutil.which("true") or shutil.which("echo")
    if not exe:
        pytest.skip("true/echo não encontrado")
    profile = RemoteProfile(
        enabled=True,
        protocol=RemoteProtocol.CUSTOM,
        custom_executable=exe,
        custom_args=json.dumps(["{host}", "{port}"]),
        use_ssh_host=True,
        port=5900,
    )
    server = ServerProfile(name="S", host="192.168.1.10", username="u")
    args, _ = launcher.build_args(profile, server)
    assert args[0] == exe or args[0].endswith("true") or args[0].endswith("echo")
    assert "192.168.1.10" in args
    assert "5900" in args


def test_custom_command_rejects_invalid_json():
    launcher = RemoteDesktopLauncher()
    import shutil

    exe = shutil.which("true")
    if not exe:
        pytest.skip("true não encontrado")
    profile = RemoteProfile(
        enabled=True,
        protocol=RemoteProtocol.CUSTOM,
        custom_executable=exe,
        custom_args="not-json",
    )
    server = ServerProfile(name="S", host="h", username="u")
    from app.utils.process import ProcessError

    with pytest.raises(ProcessError):
        launcher.build_args(profile, server)


def test_vnc_tunnel_target_localhost():
    launcher = RemoteDesktopLauncher()
    exe = find_executable(RemoteDesktopLauncher.VNC_CANDIDATES)
    if not exe:
        pytest.skip("TigerVNC não instalado")
    profile = RemoteProfile(
        enabled=True, protocol=RemoteProtocol.VNC, port=5901, use_ssh_host=True
    )
    server = ServerProfile(name="S", host="remote.example", username="u")
    args, _ = launcher.build_args(profile, server, tunnel_local_port=15901)
    joined = " ".join(args)
    assert "127.0.0.1" in joined
