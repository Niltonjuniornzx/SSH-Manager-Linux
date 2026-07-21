"""Testes do banco de dados SQLite."""

from __future__ import annotations

from app.models.server import AuthMethod, ServerGroup, ServerProfile
from app.models.tunnel import TunnelProfile, TunnelType


def test_save_and_get_server(db):
    s = ServerProfile(
        name="DB Test",
        host="10.0.0.1",
        port=2222,
        username="root",
        auth_method=AuthMethod.KEY,
        private_key_path="/tmp/fake_key",
    )
    saved = db.save_server(s)
    assert saved.id is not None
    assert saved.credential_key == f"server-{saved.id}"
    loaded = db.get_server(saved.id)
    assert loaded is not None
    assert loaded.name == "DB Test"
    assert loaded.port == 2222
    assert loaded.private_key_path == "/tmp/fake_key"


def test_list_servers_search(db):
    db.save_server(ServerProfile(name="Alpha", host="a.example", username="u"))
    db.save_server(ServerProfile(name="Beta", host="b.example", username="u"))
    results = db.list_servers("Alpha")
    assert len(results) == 1
    assert results[0].name == "Alpha"


def test_groups(db):
    g = db.save_group(ServerGroup(name="Produção", color="#ff0000"))
    assert g.id is not None
    groups = db.list_groups()
    names = [x.name for x in groups]
    assert "Produção" in names
    assert "Padrão" in names


def test_delete_server_clears_jump(db):
    jump = db.save_server(ServerProfile(name="Bastion", host="j", username="u"))
    target = db.save_server(
        ServerProfile(name="Target", host="t", username="u", jump_host_id=jump.id)
    )
    db.delete_server(jump.id)
    loaded = db.get_server(target.id)
    assert loaded is not None
    assert loaded.jump_host_id is None


def test_jump_loop_detection(db):
    a = db.save_server(ServerProfile(name="A", host="a", username="u"))
    b = db.save_server(
        ServerProfile(name="B", host="b", username="u", jump_host_id=a.id)
    )
    # A -> B -> A
    a.jump_host_id = b.id
    db.save_server(a)
    assert db.detect_jump_loop(a.id, b.id) is True
    assert db.detect_jump_loop(a.id, None) is False


def test_tunnels_crud(db, sample_server):
    t = TunnelProfile(
        server_id=sample_server.id,
        name="HTTP",
        tunnel_type=TunnelType.LOCAL,
        listen_port=8080,
        dest_host="127.0.0.1",
        dest_port=80,
    )
    saved = db.save_tunnel(t)
    assert saved.id is not None
    listed = db.list_tunnels(sample_server.id)
    assert len(listed) == 1
    conflicts = db.find_tunnels_by_listen_port(8080)
    assert len(conflicts) == 1
    db.delete_tunnel(saved.id)
    assert db.list_tunnels(sample_server.id) == []


def test_settings_roundtrip(db):
    settings = db.get_settings()
    settings.theme = "light"
    settings.max_concurrent_transfers = 5
    db.save_settings(settings)
    loaded = db.get_settings()
    assert loaded.theme == "light"
    assert loaded.max_concurrent_transfers == 5


def test_trusted_hosts(db):
    db.trust_host("example.com", 22, "ssh-ed25519", "SHA256:abc", "AAAA")
    row = db.get_trusted_host("example.com", 22, "ssh-ed25519")
    assert row is not None
    assert row["fingerprint_sha256"] == "SHA256:abc"


def test_no_secrets_in_export(db, sample_server):
    data = db.export_config()
    assert data["includes_credentials"] is False
    for s in data["servers"]:
        assert s.get("credential_key") == ""


def test_import_export(db, sample_server):
    data = db.export_config()
    # import into same db with skip duplicates
    stats = db.import_config(data, skip_duplicates=True)
    assert stats["skipped"] >= 1
