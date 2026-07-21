"""Testes de validação de perfis."""

from __future__ import annotations

from app.models.server import AuthMethod, ServerProfile
from app.models.tunnel import TunnelProfile, TunnelType
from app.models.remote import RemoteProfile, RemoteProtocol


def test_server_validation_ok():
    s = ServerProfile(
        name="Prod",
        host="example.com",
        port=22,
        username="admin",
        auth_method=AuthMethod.PASSWORD,
    )
    assert s.validate() == []


def test_server_validation_missing_fields():
    s = ServerProfile()
    errors = s.validate()
    assert any("Nome" in e for e in errors)
    assert any("hostname" in e.lower() or "IP" in e for e in errors)
    assert any("usuário" in e.lower() or "usuario" in e.lower() for e in errors)


def test_server_key_requires_path():
    s = ServerProfile(
        name="X",
        host="h",
        username="u",
        auth_method=AuthMethod.KEY,
        private_key_path="",
    )
    errors = s.validate()
    assert any("chave" in e.lower() for e in errors)


def test_server_self_jump():
    s = ServerProfile(id=1, name="A", host="h", username="u", jump_host_id=1)
    errors = s.validate()
    assert any("jump" in e.lower() for e in errors)


def test_server_export_strips_credentials():
    s = ServerProfile(
        name="A",
        host="h",
        username="u",
        credential_key="server-1",
        private_key_path="/home/u/.ssh/id_rsa",
    )
    d = s.to_dict(for_export=True)
    assert d["credential_key"] == ""
    assert d["private_key_path"] == ""


def test_tunnel_validation():
    t = TunnelProfile(name="", server_id=None)
    errors = t.validate()
    assert len(errors) >= 2


def test_tunnel_local_only_forces_localhost():
    t = TunnelProfile(
        name="web",
        server_id=1,
        tunnel_type=TunnelType.LOCAL,
        listen_address="0.0.0.0",
        listen_port=8080,
        dest_host="127.0.0.1",
        dest_port=80,
        local_only=True,
    )
    errors = t.validate()
    assert any("local" in e.lower() or "0.0.0.0" in e for e in errors)
    assert t.effective_listen_address() == "127.0.0.1"


def test_tunnel_dynamic_no_dest_required():
    t = TunnelProfile(
        name="socks",
        server_id=1,
        tunnel_type=TunnelType.DYNAMIC,
        listen_port=1080,
    )
    assert t.validate() == []


def test_remote_validation_rustdesk():
    r = RemoteProfile(enabled=True, protocol=RemoteProtocol.RUSTDESK, rustdesk_id="")
    errors = r.validate()
    assert any("RustDesk" in e or "ID" in e for e in errors)


def test_remote_disabled_skips_validation():
    r = RemoteProfile(enabled=False, protocol=RemoteProtocol.CUSTOM)
    assert r.validate() == []
