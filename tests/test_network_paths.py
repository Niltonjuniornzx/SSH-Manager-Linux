"""Testes de utilitários de rede e caminhos."""

from __future__ import annotations

import stat

from app.utils.paths import ensure_secure_file, is_secure_permissions


def test_ensure_secure_file(tmp_path):
    p = tmp_path / "secret.db"
    ensure_secure_file(p)
    assert p.exists()
    mode = p.stat().st_mode
    assert not (mode & (stat.S_IRGRP | stat.S_IROTH))
    assert is_secure_permissions(p)


def test_check_tcp_localhost_closed():
    from app.utils.network import check_tcp_port

    # porta improvável
    ok, err = check_tcp_port("127.0.0.1", 1, timeout=0.5)
    assert ok is False
    assert err is not None
