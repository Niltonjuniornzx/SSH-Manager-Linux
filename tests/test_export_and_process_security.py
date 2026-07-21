"""Testes de export sem credenciais, processos e SFTP paths."""

from __future__ import annotations

import json
import stat

import pytest

from app.models.server import AuthMethod, ServerProfile
from app.sftp.paths import SFTPPathError, is_safe_remote_path, normalize_remote_path, safe_join_remote
from app.utils.export_import import export_to_file, import_from_file
from app.utils.process import build_safe_preview
from app.utils.vnc_passwd import vnc_encrypt_password, write_vnc_passwd_file


def test_export_without_credentials(db, tmp_path, credentials):
    s = ServerProfile(
        name="Lab",
        host="10.0.0.1",
        port=22,
        username="admin",
        auth_method=AuthMethod.PASSWORD,
        remember_credential=True,
    )
    db.save_server(s)
    # credencial só no keyring
    credentials.store_server_password("1", "should-not-export")
    out = tmp_path / "export.json"
    info = export_to_file(db, out)
    assert info["includes_credentials"] is False
    data = json.loads(out.read_text(encoding="utf-8"))
    blob = json.dumps(data)
    assert "should-not-export" not in blob
    # auth_method pode ser a string "password" (método), mas sem valor secreto
    for server in data.get("servers") or []:
        assert "password" not in server or server.get("password") in (None, "")
        assert not server.get("passphrase")
    assert "master_password_hash" not in (data.get("settings") or {})
    # permissões
    mode = out.stat().st_mode
    assert not (mode & (stat.S_IRGRP | stat.S_IROTH))


def test_export_encrypted_roundtrip(db, tmp_path):
    s = ServerProfile(
        name="A",
        host="h",
        port=22,
        username="u",
        auth_method=AuthMethod.KEY,
    )
    db.save_server(s)
    out = tmp_path / "backup.sml"
    export_to_file(db, out, encrypt_password="backup-secret-phrase")
    raw = out.read_bytes()
    assert raw.startswith(b"SML1")
    # import em outro db
    from app.database.db import Database, reset_database_singleton

    reset_database_singleton()
    db2 = Database(tmp_path / "other.db")
    stats = import_from_file(db2, out, encrypt_password="backup-secret-phrase")
    assert stats["servers"] >= 1
    db2.close()
    reset_database_singleton()


def test_import_wrong_password(db, tmp_path):
    out = tmp_path / "b.sml"
    export_to_file(db, out, encrypt_password="right")
    with pytest.raises(ValueError, match="incorreta|corrompido"):
        import_from_file(db, out, encrypt_password="wrong")


def test_import_malicious_path(db, tmp_path):
    payload = {
        "servers": [
            {
                "name": "x",
                "host": "h",
                "port": 22,
                "username": "u",
                "auth_method": "password",
                "private_key_path": "file://evil",
            }
        ],
        "groups": [],
        "tunnels": [],
        "settings": {},
    }
    p = tmp_path / "bad.json"
    p.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        import_from_file(db, p)


def test_import_too_large(db, tmp_path):
    p = tmp_path / "huge.json"
    # não criar 20MB de verdade — mock via patch do limite
    import app.utils.export_import as ei

    old = ei.MAX_IMPORT_BYTES
    ei.MAX_IMPORT_BYTES = 100
    try:
        p.write_bytes(b"{" + b"x" * 200 + b"}")
        with pytest.raises(ValueError, match="grande"):
            import_from_file(db, p)
    finally:
        ei.MAX_IMPORT_BYTES = old


def test_sftp_path_traversal():
    with pytest.raises(SFTPPathError):
        normalize_remote_path("../../etc/passwd")
    assert is_safe_remote_path("/home/user/file") is True
    assert is_safe_remote_path("ok/file.txt") is True
    n = normalize_remote_path("/home/user/../user/docs")
    assert n == "/home/user/docs"
    joined = safe_join_remote("/home/u", "file.txt")
    assert joined.endswith("file.txt")
    with pytest.raises(SFTPPathError):
        safe_join_remote("/home/u", "..")


def test_vnc_passwd_not_plaintext(tmp_path):
    data = vnc_encrypt_password("secret12")
    assert data != b"secret12"
    assert len(data) == 8
    path = write_vnc_passwd_file("mypass", directory=tmp_path)
    assert path.exists()
    raw = path.read_bytes()
    assert b"mypass" not in raw
    mode = path.stat().st_mode
    assert not (mode & (stat.S_IRGRP | stat.S_IROTH))
    path.unlink()


def test_rdp_args_no_password_in_argv():
    """FreeRDP deve usar /from-stdin, não /p:senha."""
    from app.models.remote import RemoteProfile, RemoteProtocol
    from app.models.server import ServerProfile
    from app.remote_desktop.launcher import RemoteDesktopLauncher

    launcher = RemoteDesktopLauncher()
    # força exe fake para build_args não falhar por detecção
    launcher.detect_rdp = lambda: "/usr/bin/xfreerdp"  # type: ignore
    profile = RemoteProfile(
        protocol=RemoteProtocol.RDP,
        host="10.0.0.5",
        port=3389,
        username="user",
    )
    server = ServerProfile(name="s", host="10.0.0.5", username="user")
    args, temps = launcher.build_args(profile, server, password="SuperSecret!")
    joined = " ".join(args)
    assert "SuperSecret!" not in joined
    assert "/from-stdin" in args
    assert not any(a.startswith("/p:") for a in args)
    safe = build_safe_preview(args)
    assert "SuperSecret" not in safe


def test_rustdesk_no_password_flag():
    from app.models.remote import RemoteProfile, RemoteProtocol
    from app.models.server import ServerProfile
    from app.remote_desktop.launcher import RemoteDesktopLauncher

    launcher = RemoteDesktopLauncher()
    launcher.detect_rustdesk = lambda: "/usr/bin/rustdesk"  # type: ignore
    profile = RemoteProfile(
        protocol=RemoteProtocol.RUSTDESK,
        rustdesk_id="123456789",
    )
    server = ServerProfile(name="s", host="h", username="u")
    args, _ = launcher.build_args(profile, server, password="hidden-pw")
    assert "--password" not in args
    assert "hidden-pw" not in " ".join(args)


def test_process_never_shell_true():
    import ast
    import inspect

    from app.utils import process as proc

    src = inspect.getsource(proc)
    assert "shell=False" in src
    tree = ast.parse(src)
    for node in ast.walk(tree):
        if isinstance(node, ast.keyword) and node.arg == "shell":
            # shell= deve ser False literal
            assert isinstance(node.value, ast.Constant) and node.value.value is False
