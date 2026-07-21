"""Testes de keyring, host keys, Argon2id, sanitização e permissões."""

from __future__ import annotations

import hashlib
import stat

import pytest

from app.security.credentials import SERVICE_NAME, CredentialStore
from app.security.hostkeys import HostKeyDecision, HostKeyManager, fingerprint_sha256
from app.security.lock import (
    HASH_PREFIX,
    AppLock,
    hash_master_password,
    verify_master_password,
)
from app.utils.sanitize import redact_secrets, sanitize_args, sanitize_for_log


def test_credential_store(credentials):
    credentials.set_password("test-key", "s3cret")
    assert credentials.get_password("test-key") == "s3cret"
    credentials.delete_password("test-key")
    assert credentials.get_password("test-key") is None


def test_server_password_helpers(credentials):
    credentials.store_server_password("server-1", "pass")
    assert credentials.get_server_password("server-1") == "pass"
    credentials.store_passphrase("server-1", "pp")
    assert credentials.get_passphrase("server-1") == "pp"
    credentials.delete_server_credentials("server-1")
    assert credentials.get_server_password("server-1") is None


def test_keyring_test(credentials):
    ok, msg = credentials.test_keyring()
    assert ok is True
    assert msg


def test_keyring_service_name():
    assert SERVICE_NAME == "SSH-Manager-Linux"


def test_keyring_unavailable_raises(monkeypatch):
    import keyring
    from keyring.errors import KeyringError

    class Broken(keyring.backend.KeyringBackend):
        priority = 100

        def get_password(self, service, username):
            raise KeyringError("down")

        def set_password(self, service, username, password):
            raise KeyringError("down")

        def delete_password(self, service, username):
            raise KeyringError("down")

    keyring.set_keyring(Broken())
    store = CredentialStore(service="test-broken")
    with pytest.raises(RuntimeError, match="Não foi possível salvar"):
        store.set_password("k", "v")


def test_fingerprint_stable():
    data = b"test-public-key-bytes"
    fp1 = fingerprint_sha256(data)
    fp2 = fingerprint_sha256(data)
    assert fp1 == fp2
    assert fp1.startswith("SHA256:")


def test_host_key_new(db):
    mgr = HostKeyManager(db)
    result = mgr.check("host.example", 22, "ssh-ed25519", b"pubkeydata1")
    assert result.is_new is True
    assert result.decision == HostKeyDecision.REJECT
    mgr.accept(
        result.hostname,
        result.port,
        result.key_type,
        result.fingerprint_sha256,
        result.public_key_b64,
    )
    result2 = mgr.check("host.example", 22, "ssh-ed25519", b"pubkeydata1")
    assert result2.decision == HostKeyDecision.ACCEPT
    assert result2.is_new is False


def test_host_key_trusted(db):
    mgr = HostKeyManager(db)
    r1 = mgr.check("srv.local", 2222, "ssh-ed25519", b"trusted-key")
    mgr.accept(r1.hostname, r1.port, r1.key_type, r1.fingerprint_sha256, r1.public_key_b64)
    r2 = mgr.check("srv.local", 2222, "ssh-ed25519", b"trusted-key")
    assert r2.decision == HostKeyDecision.ACCEPT
    assert not r2.is_changed


def test_host_key_changed_blocks(db):
    mgr = HostKeyManager(db)
    r1 = mgr.check("host.example", 22, "ssh-ed25519", b"original-key")
    mgr.accept(
        r1.hostname, r1.port, r1.key_type, r1.fingerprint_sha256, r1.public_key_b64
    )
    r2 = mgr.check("host.example", 22, "ssh-ed25519", b"ATTACKER-KEY")
    assert r2.decision == HostKeyDecision.CHANGED_BLOCK
    assert r2.is_changed is True
    assert r2.previous_fingerprint
    assert r2.fingerprint_sha256 != r2.previous_fingerprint


def test_host_key_nonstandard_port(db):
    mgr = HostKeyManager(db)
    r = mgr.check("jump.example", 2200, "ssh-rsa", b"jump-key")
    assert r.is_new
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)
    ok = mgr.check("jump.example", 2200, "ssh-rsa", b"jump-key")
    assert ok.decision == HostKeyDecision.ACCEPT
    # porta diferente = host diferente
    other = mgr.check("jump.example", 22, "ssh-rsa", b"jump-key")
    assert other.is_new


def test_host_key_remove(db):
    mgr = HostKeyManager(db)
    r = mgr.check("x", 22, "ssh-ed25519", b"k")
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)
    mgr.remove("x", 22)
    again = mgr.check("x", 22, "ssh-ed25519", b"k")
    assert again.is_new


def test_known_hosts_permissions(db, tmp_path, monkeypatch):
    kh = tmp_path / "known_hosts"
    mgr = HostKeyManager(db, known_hosts=kh)
    r = mgr.check("h", 22, "ssh-ed25519", b"data")
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)
    mode = kh.stat().st_mode
    assert not (mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH))


def test_argon2_master_password():
    h = hash_master_password("correct horse battery")
    assert h.startswith(HASH_PREFIX)
    ok, migrated = verify_master_password(h, "correct horse battery")
    assert ok is True
    assert migrated is None
    ok2, _ = verify_master_password(h, "wrong")
    assert ok2 is False
    # nunca deve conter a senha em claro
    assert "correct" not in h
    assert "horse" not in h


def test_legacy_sha256_migration():
    password = "old-password"
    legacy = hashlib.sha256(password.encode()).hexdigest()
    ok, new_hash = verify_master_password(legacy, password)
    assert ok is True
    assert new_hash is not None
    assert new_hash.startswith(HASH_PREFIX)
    ok2, _ = verify_master_password(new_hash, password)
    assert ok2 is True
    # senha errada no legado
    ok3, m3 = verify_master_password(legacy, "nope")
    assert ok3 is False
    assert m3 is None


def test_app_lock_backoff():
    h = hash_master_password("secret")
    lock = AppLock(timeout_minutes=1, master_password_hash=h)
    lock.lock()
    assert lock.unlock("wrong") is False
    assert lock.unlock("wrong") is False
    # ainda pode desbloquear com senha certa após backoff se lockout passou
    # forçar lockout_until no passado
    lock._lockout_until = 0
    assert lock.unlock("secret") is True
    assert lock.is_locked is False


def test_sanitize_password():
    text = "login password=supersecret token=abc123"
    red = redact_secrets(text)
    assert "supersecret" not in red
    assert "REDACTED" in red


def test_sanitize_private_key():
    key = "-----BEGIN OPENSSH PRIVATE KEY-----\nAAAA\n-----END OPENSSH PRIVATE KEY-----"
    assert "AAAA" not in redact_secrets(key)


def test_sanitize_args():
    args = ["xfreerdp", "/v:host", "/p:SecretPass", "/u:user", "--password", "x"]
    safe = sanitize_args(args)
    joined = " ".join(safe)
    assert "SecretPass" not in joined
    assert "REDACTED" in joined


def test_sanitize_for_log_extra():
    msg = sanitize_for_log("connecting", password="hidden", host="1.2.3.4")
    assert "hidden" not in msg
    assert "1.2.3.4" in msg


def test_secure_dir_permissions(tmp_path, monkeypatch):
    from app.utils import paths as paths_mod

    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path / "data"))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    monkeypatch.setenv("XDG_CACHE_HOME", str(tmp_path / "cache"))
    paths_mod._migrated = False
    d = paths_mod.app_data_dir()
    assert d.name == "ssh-manager-linux"
    mode = d.stat().st_mode
    assert mode & 0o777 == 0o700 or not (mode & (stat.S_IRGRP | stat.S_IROTH))


def test_legacy_path_migration(tmp_path, monkeypatch):
    from app.utils import paths as paths_mod

    data = tmp_path / "data"
    cfg = tmp_path / "cfg"
    cache = tmp_path / "cache"
    legacy = data / "nzxs-remote-manager"
    legacy.mkdir(parents=True)
    (legacy / "manager.db").write_text("legacy-db")
    monkeypatch.setenv("XDG_DATA_HOME", str(data))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(cfg))
    monkeypatch.setenv("XDG_CACHE_HOME", str(cache))
    paths_mod._migrated = False
    new_dir = paths_mod.app_data_dir()
    assert new_dir.name == "ssh-manager-linux"
    assert (new_dir / "manager.db").read_text() == "legacy-db"
    # legado preservado
    assert (legacy / "manager.db").exists()
