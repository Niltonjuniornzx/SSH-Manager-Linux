"""Testes: host key validada ANTES de qualquer credencial."""

from __future__ import annotations

import pytest

from app.models.server import AuthMethod, ServerProfile
from app.security.hostkeys import HostKeyDecision, HostKeyManager, HostKeyResult
from app.ssh.client import (
    HostKeyChangedError,
    HostKeyUnknownError,
    SSHClient,
    _HostKeyVerifyingClient,
)


class _FakeKey:
    def __init__(self, data: bytes, algorithm: str = "ssh-ed25519") -> None:
        self.public_data = data
        self._alg = algorithm

    def get_algorithm(self) -> str:
        return self._alg


def test_verifier_rejects_new_before_auth(db):
    mgr = HostKeyManager(db)
    client = _HostKeyVerifyingClient(mgr, hostname="h.example", port=22)
    key = _FakeKey(b"new-server-key")
    ok = client.validate_host_public_key("h.example", "1.2.3.4", 22, key)  # type: ignore[arg-type]
    assert ok is False
    assert client.host_key_result is not None
    assert client.host_key_result.is_new
    assert client.credentials_sent is False
    assert client.auth_phase_reached is False


def test_verifier_accepts_trusted(db):
    mgr = HostKeyManager(db)
    data = b"known-server-key"
    r = mgr.check("h.example", 22, "ssh-ed25519", data)
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)
    client = _HostKeyVerifyingClient(mgr, hostname="h.example", port=22)
    ok = client.validate_host_public_key("h.example", "1.2.3.4", 22, _FakeKey(data))  # type: ignore[arg-type]
    assert ok is True
    assert client.host_key_result is not None
    assert client.host_key_result.decision == HostKeyDecision.ACCEPT


def test_verifier_blocks_changed(db):
    mgr = HostKeyManager(db)
    r = mgr.check("h.example", 22, "ssh-ed25519", b"original")
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)
    client = _HostKeyVerifyingClient(mgr, hostname="h.example", port=22)
    ok = client.validate_host_public_key(
        "h.example", "1.2.3.4", 22, _FakeKey(b"ATTACKER")
    )  # type: ignore[arg-type]
    assert ok is False
    assert client.host_key_result is not None
    assert client.host_key_result.is_changed
    assert client.credentials_sent is False


@pytest.mark.asyncio
async def test_no_secrets_before_hostkey_unknown(db, credentials):
    profile = ServerProfile(
        name="t",
        host="example.invalid",
        port=22,
        username="u",
        auth_method=AuthMethod.PASSWORD,
    )
    mgr = HostKeyManager(db)
    client = SSHClient(
        profile=profile,
        credentials=credentials,
        host_keys=mgr,
        password="super-secret-password",
    )
    secrets_calls = []

    def tracked_resolve(profile, *, is_target):
        secrets_calls.append(True)
        return ("super-secret-password", None)

    client._resolve_secrets = tracked_resolve  # type: ignore[method-assign]

    async def fake_probe(profile, verifier, jump_tunnel):
        verifier.host_key_result = HostKeyResult(
            decision=HostKeyDecision.REJECT,
            fingerprint_sha256="SHA256:newfp",
            key_type="ssh-ed25519",
            hostname=profile.host,
            port=profile.port,
            is_new=True,
            public_key_b64="YQ==",
            message="unknown",
        )
        raise HostKeyUnknownError(verifier.host_key_result)

    client._probe_host_key = fake_probe  # type: ignore[method-assign]

    with pytest.raises(HostKeyUnknownError):
        await client._connect_profile(profile, is_target=True)
    assert secrets_calls == [], "Credenciais não devem ser resolvidas antes da host key"


@pytest.mark.asyncio
async def test_no_secrets_before_hostkey_changed(db, credentials):
    profile = ServerProfile(
        name="t",
        host="example.invalid",
        port=22,
        username="u",
        auth_method=AuthMethod.PASSWORD,
    )
    mgr = HostKeyManager(db)
    # confiar em uma key
    r = mgr.check(profile.host, profile.port, "ssh-ed25519", b"old")
    mgr.accept(r.hostname, r.port, r.key_type, r.fingerprint_sha256, r.public_key_b64)

    client = SSHClient(
        profile=profile,
        credentials=credentials,
        host_keys=mgr,
        password="super-secret-password",
    )
    secrets_calls = []

    def tracked_resolve(profile, *, is_target):
        secrets_calls.append(True)
        return ("super-secret-password", None)

    client._resolve_secrets = tracked_resolve  # type: ignore[method-assign]

    async def fake_probe(profile, verifier, jump_tunnel):
        verifier.host_key_result = HostKeyResult(
            decision=HostKeyDecision.CHANGED_BLOCK,
            fingerprint_sha256="SHA256:new",
            key_type="ssh-ed25519",
            hostname=profile.host,
            port=profile.port,
            is_changed=True,
            previous_fingerprint=r.fingerprint_sha256,
            public_key_b64="Yg==",
            message="changed",
        )
        raise HostKeyChangedError(verifier.host_key_result)

    client._probe_host_key = fake_probe  # type: ignore[method-assign]

    with pytest.raises(HostKeyChangedError):
        await client._connect_profile(profile, is_target=True)
    assert secrets_calls == []


@pytest.mark.asyncio
async def test_jump_host_changed_blocks(db, credentials):
    jump = ServerProfile(
        id=1,
        name="jump",
        host="jump.example",
        port=22,
        username="j",
        auth_method=AuthMethod.PASSWORD,
    )
    target = ServerProfile(
        id=2,
        name="target",
        host="target.example",
        port=22,
        username="t",
        auth_method=AuthMethod.PASSWORD,
        jump_host_id=1,
    )
    mgr = HostKeyManager(db)
    client = SSHClient(
        profile=target,
        credentials=credentials,
        host_keys=mgr,
        password="x",
        resolve_server=lambda sid: jump if sid == 1 else None,
    )
    secrets_calls = []
    client._resolve_secrets = lambda *a, **k: secrets_calls.append(1) or ("x", None)  # type: ignore

    async def fake_probe(profile, verifier, jump_tunnel):
        verifier.host_key_result = HostKeyResult(
            decision=HostKeyDecision.CHANGED_BLOCK,
            fingerprint_sha256="SHA256:x",
            key_type="ssh-ed25519",
            hostname=profile.host,
            port=profile.port,
            is_changed=True,
            previous_fingerprint="SHA256:old",
            public_key_b64="YQ==",
            message="changed jump",
        )
        raise HostKeyChangedError(verifier.host_key_result)

    client._probe_host_key = fake_probe  # type: ignore[method-assign]

    with pytest.raises(HostKeyChangedError):
        await client._connect_profile(target, is_target=True)
    assert secrets_calls == []


def test_never_known_hosts_none():
    """Garantia estática: o código-fonte não usa known_hosts=None nem b''."""
    import inspect

    from app.ssh import client as client_mod

    src = inspect.getsource(client_mod)
    assert "known_hosts=None" not in src
    assert 'known_hosts": None' not in src
    assert "known_hosts: None" not in src
    # b'' faz o AsyncSSH cair no ~/.ssh/known_hosts do sistema
    assert 'known_hosts"] = b""' not in src
    assert "known_hosts'] = b''" not in src
    assert client_mod._EMPTY_KNOWN_HOSTS  # truthy — não dispara fallback
    assert client_mod._EMPTY_KNOWN_HOSTS.startswith(b"#")
