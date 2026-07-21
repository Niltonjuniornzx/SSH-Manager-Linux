"""Fixtures de teste — sem servidores ou credenciais reais."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

# Keyring de teste em memória
os.environ.setdefault("PYTHON_KEYRING_BACKEND", "keyring.backends.null.Keyring")


@pytest.fixture
def tmp_db_path(tmp_path: Path) -> Path:
    return tmp_path / "test.db"


@pytest.fixture
def db(tmp_db_path: Path):
    from app.database.db import Database, reset_database_singleton

    reset_database_singleton()
    database = Database(tmp_db_path)
    yield database
    database.close()
    reset_database_singleton()


@pytest.fixture
def credentials():
    """CredentialStore com backend que funciona em memória se possível."""
    import keyring
    from keyring.backend import KeyringBackend

    class MemoryKeyring(KeyringBackend):
        priority = 100
        _store: dict[tuple[str, str], str] = {}

        def get_password(self, service, username):
            return self._store.get((service, username))

        def set_password(self, service, username, password):
            self._store[(service, username)] = password

        def delete_password(self, service, username):
            self._store.pop((service, username), None)

    MemoryKeyring._store = {}
    keyring.set_keyring(MemoryKeyring())
    from app.security.credentials import CredentialStore

    return CredentialStore(service="ssh-manager-linux-test")


@pytest.fixture
def sample_server(db):
    from app.models.server import AuthMethod, ServerProfile

    s = ServerProfile(
        name="Lab",
        host="127.0.0.1",
        port=22,
        username="testuser",
        auth_method=AuthMethod.PASSWORD,
        remember_credential=True,
    )
    return db.save_server(s)
