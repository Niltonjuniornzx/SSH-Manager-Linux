"""Armazenamento seguro de credenciais via keyring do sistema."""

from __future__ import annotations

import logging
from typing import Optional

import keyring
from keyring.errors import KeyringError, PasswordDeleteError

from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# Nome do serviço no keyring (KDE Wallet / GNOME Keyring / Secret Service)
SERVICE_NAME = "SSH-Manager-Linux"
# Serviços legados — lidos e migrados sob demanda
_LEGACY_SERVICE_NAMES = (
    "nzxs-remote-manager",
    "ssh-remote-manager",
    "SSH Remote Manager",
    "NZXS Remote Manager",
)


class CredentialStore:
    """
    Wrapper do keyring (KDE Wallet / GNOME Keyring / Secret Service).

    Nunca armazena senhas no SQLite, JSON, configurações ou logs.
    Sem fallback inseguro em texto simples.
    """

    def __init__(self, service: str = SERVICE_NAME) -> None:
        self.service = service

    def set_password(self, key: str, password: str) -> None:
        if not key:
            raise ValueError("Chave de credencial vazia")
        try:
            keyring.set_password(self.service, key, password)
            logger.info(sanitize_for_log("Credencial salva no keyring", key=key))
        except KeyringError as exc:
            logger.error(sanitize_for_log("Falha ao salvar no keyring", error=str(exc)))
            raise RuntimeError(
                "Não foi possível salvar a credencial no cofre do sistema "
                "(KDE Wallet / GNOME Keyring / Secret Service). "
                "Verifique se o serviço está ativo. A senha NÃO foi salva em disco."
            ) from exc

    def get_password(self, key: str) -> Optional[str]:
        if not key:
            return None
        try:
            value = keyring.get_password(self.service, key)
            if value is not None:
                return value
            # migrar de serviços legados
            return self._migrate_from_legacy(key)
        except KeyringError as exc:
            logger.error(sanitize_for_log("Falha ao ler keyring", error=str(exc)))
            return None

    def _migrate_from_legacy(self, key: str) -> Optional[str]:
        for legacy in _LEGACY_SERVICE_NAMES:
            if legacy == self.service:
                continue
            try:
                value = keyring.get_password(legacy, key)
            except KeyringError:
                continue
            if value is None:
                continue
            try:
                keyring.set_password(self.service, key, value)
                try:
                    keyring.delete_password(legacy, key)
                except (KeyringError, PasswordDeleteError):
                    pass
                logger.info(
                    sanitize_for_log(
                        "Credencial migrada de serviço legado do keyring",
                        key=key,
                    )
                )
            except KeyringError:
                # ainda retorna o valor lido do legado
                pass
            return value
        return None

    def delete_password(self, key: str) -> None:
        if not key:
            return
        for service in (self.service, *_LEGACY_SERVICE_NAMES):
            try:
                keyring.delete_password(service, key)
            except (KeyringError, PasswordDeleteError):
                pass
        logger.info(sanitize_for_log("Credencial removida do keyring", key=key))

    def test_keyring(self) -> tuple[bool, str]:
        """Testa se o keyring funciona. Retorna (ok, mensagem)."""
        test_key = "__ssh_manager_linux_keyring_test__"
        test_value = "ok"
        try:
            keyring.set_password(self.service, test_key, test_value)
            got = keyring.get_password(self.service, test_key)
            try:
                keyring.delete_password(self.service, test_key)
            except (KeyringError, PasswordDeleteError):
                pass
            if got == test_value:
                backend = type(keyring.get_keyring()).__name__
                return True, f"Keyring operacional ({backend})"
            return False, "Keyring retornou valor inesperado"
        except Exception as exc:  # noqa: BLE001
            return False, f"Keyring indisponível: {exc}"

    def store_server_password(self, credential_key: str, password: str) -> None:
        self.set_password(f"{credential_key}:password", password)

    def get_server_password(self, credential_key: str) -> Optional[str]:
        return self.get_password(f"{credential_key}:password")

    def store_passphrase(self, credential_key: str, passphrase: str) -> None:
        self.set_password(f"{credential_key}:passphrase", passphrase)

    def get_passphrase(self, credential_key: str) -> Optional[str]:
        return self.get_password(f"{credential_key}:passphrase")

    def store_remote_password(self, credential_key: str, password: str) -> None:
        self.set_password(f"{credential_key}:remote", password)

    def get_remote_password(self, credential_key: str) -> Optional[str]:
        return self.get_password(f"{credential_key}:remote")

    def store_rustdesk_password(self, credential_key: str, password: str) -> None:
        self.set_password(f"{credential_key}:rustdesk", password)

    def get_rustdesk_password(self, credential_key: str) -> Optional[str]:
        return self.get_password(f"{credential_key}:rustdesk")

    def delete_server_credentials(self, credential_key: str) -> None:
        for suffix in (":password", ":passphrase", ":remote", ":rustdesk"):
            self.delete_password(f"{credential_key}{suffix}")
