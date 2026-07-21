"""Importação/exportação e backup criptografado (Argon2id + AES-256-GCM)."""

from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from typing import Any, Optional

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives.ciphers.aead import AESGCM

from app.database.db import Database
from app.utils.paths import atomic_write, ensure_secure_file
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# Formato versionado: SML1 | salt(16) | nonce(12) | ciphertext+tag
MAGIC = b"SML1"
# Legado Fernet+PBKDF2
LEGACY_MAGIC = b"NZXS1"

MAX_IMPORT_BYTES = 20 * 1024 * 1024  # 20 MiB
MAX_SERVERS = 5000
MAX_FIELD_LEN = 8192

ARGON2_TIME = 3
ARGON2_MEMORY = 65536  # KiB
ARGON2_PARALLELISM = 4
SALT_LEN = 16
NONCE_LEN = 12
KEY_LEN = 32


def export_to_file(
    db: Database,
    path: Path,
    *,
    include_key_paths: bool = False,
    encrypt_password: Optional[str] = None,
) -> dict[str, Any]:
    """
    Exporta configuração SEM credenciais.
    Se encrypt_password for fornecida, grava backup com Argon2id + AES-256-GCM.
    """
    data = db.export_config(include_key_paths=include_key_paths)
    # Garantir que nenhuma credencial vazou
    _assert_no_credentials(data)
    payload = json.dumps(data, ensure_ascii=False, indent=2).encode("utf-8")

    if encrypt_password:
        token = _encrypt(payload, encrypt_password)
        atomic_write(path, token, mode=0o600)
        info = {
            "encrypted": True,
            "path": str(path),
            "servers": len(data.get("servers") or []),
            "includes_credentials": False,
            "includes_private_keys": False,
            "cipher": "argon2id+aes-256-gcm",
        }
    else:
        atomic_write(path, payload, mode=0o600)
        info = {
            "encrypted": False,
            "path": str(path),
            "servers": len(data.get("servers") or []),
            "includes_credentials": False,
            "includes_private_keys": bool(include_key_paths),
        }
    ensure_secure_file(path)
    logger.info(sanitize_for_log("Configuração exportada", path=str(path)))
    return info


def import_from_file(
    db: Database,
    path: Path,
    *,
    encrypt_password: Optional[str] = None,
    skip_duplicates: bool = True,
) -> dict[str, int]:
    if path.is_symlink():
        raise ValueError("Importação recusada: o caminho é um symlink.")
    raw = path.read_bytes()
    if len(raw) > MAX_IMPORT_BYTES:
        raise ValueError(
            f"Arquivo de importação muito grande ({len(raw)} bytes; "
            f"máximo {MAX_IMPORT_BYTES})."
        )

    data = _parse_import_payload(raw, encrypt_password)
    _validate_import_data(data)
    _assert_no_credentials(data)

    stats = db.import_config(data, skip_duplicates=skip_duplicates)
    logger.info(sanitize_for_log("Configuração importada", **stats))
    return stats


def export_summary(data: dict[str, Any]) -> str:
    """Texto claro do que será exportado."""
    n_servers = len(data.get("servers") or [])
    n_groups = len(data.get("groups") or [])
    n_tunnels = len(data.get("tunnels") or [])
    return (
        "O export incluirá:\n"
        f"  • {n_groups} grupo(s)\n"
        f"  • {n_servers} servidor(es) (sem senhas/passphrases)\n"
        f"  • {n_tunnels} túnel(is)\n"
        f"  • Configurações da aplicação\n"
        f"  • Favoritos\n\n"
        "NÃO incluirá:\n"
        "  • Senhas ou passphrases\n"
        "  • Conteúdo de chaves privadas\n"
        "  • Tokens\n"
        "  • Credenciais do keyring\n"
    )


def _assert_no_credentials(data: dict[str, Any]) -> None:
    """Remove e recusa campos sensíveis em export/import."""
    # Nunca exportar hash de senha mestra
    settings = data.get("settings")
    if isinstance(settings, dict):
        settings.pop("master_password_hash", None)
        for bad in ("password", "passphrase", "secret", "token"):
            settings.pop(bad, None)

    sensitive_keys = {
        "password",
        "passwd",
        "passphrase",
        "secret",
        "private_key_data",
        "private_key_pem",
        "token",
        "credential_value",
        "api_key",
    }

    def _walk(obj: Any, path: str = "") -> None:
        if isinstance(obj, dict):
            for k, v in list(obj.items()):
                kl = str(k).lower()
                if kl in sensitive_keys:
                    # permitir apenas null/vazio/false
                    if v in (None, "", False, 0):
                        obj.pop(k, None)
                        continue
                    raise ValueError(
                        f"Export/import recusado: campo sensível '{k}'."
                    )
                _walk(v, f"{path}.{k}")
        elif isinstance(obj, list):
            for i, item in enumerate(obj):
                _walk(item, f"{path}[{i}]")

    _walk(data)


def _validate_import_data(data: dict[str, Any]) -> None:
    if not isinstance(data, dict) or "servers" not in data:
        raise ValueError("Arquivo de importação inválido.")
    servers = data.get("servers")
    if not isinstance(servers, list):
        raise ValueError("Lista de servidores inválida.")
    if len(servers) > MAX_SERVERS:
        raise ValueError(f"Muitos servidores no import (máx. {MAX_SERVERS}).")
    for s in servers:
        if not isinstance(s, dict):
            raise ValueError("Entrada de servidor inválida.")
        host = str(s.get("host") or "")
        name = str(s.get("name") or "")
        if ".." in host or "\x00" in host or "\x00" in name:
            raise ValueError("Dados de servidor maliciosos ou corrompidos.")
        for k, v in s.items():
            if isinstance(v, str) and len(v) > MAX_FIELD_LEN:
                raise ValueError(f"Campo '{k}' excede o tamanho máximo.")
        # path traversal em private_key_path
        pk = str(s.get("private_key_path") or "")
        if pk and ("\x00" in pk or pk.startswith("\\\\") or "://" in pk):
            raise ValueError("Caminho de chave privada inválido no import.")


def _parse_import_payload(
    raw: bytes, encrypt_password: Optional[str]
) -> dict[str, Any]:
    if raw.startswith(MAGIC):
        if not encrypt_password:
            raise ValueError(
                "Arquivo criptografado. Informe a senha de backup."
            )
        try:
            plain = _decrypt(raw, encrypt_password)
            return json.loads(plain.decode("utf-8"))
        except (InvalidTag, ValueError, json.JSONDecodeError) as exc:
            raise ValueError(
                "Senha de backup incorreta ou arquivo corrompido."
            ) from exc

    if raw.startswith(LEGACY_MAGIC):
        if not encrypt_password:
            raise ValueError(
                "Arquivo criptografado (formato legado). Informe a senha de backup."
            )
        try:
            plain = _decrypt_legacy_fernet(raw, encrypt_password)
            return json.loads(plain.decode("utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise ValueError(
                "Senha de backup incorreta ou arquivo corrompido (legado)."
            ) from exc

    try:
        return json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError("Arquivo de importação inválido ou corrompido.") from exc


def _derive_key_argon2(password: str, salt: bytes) -> bytes:
    from argon2.low_level import Type, hash_secret_raw

    return hash_secret_raw(
        secret=password.encode("utf-8"),
        salt=salt,
        time_cost=ARGON2_TIME,
        memory_cost=ARGON2_MEMORY,
        parallelism=ARGON2_PARALLELISM,
        hash_len=KEY_LEN,
        type=Type.ID,
    )


def _encrypt(data: bytes, password: str) -> bytes:
    salt = os.urandom(SALT_LEN)
    nonce = os.urandom(NONCE_LEN)  # nunca reutilizar
    key = _derive_key_argon2(password, salt)
    aesgcm = AESGCM(key)
    # AAD: magic + versão implícita
    ct = aesgcm.encrypt(nonce, data, MAGIC)
    # limpar key da memória o quanto possível (best-effort)
    key = b"\x00" * len(key)
    return MAGIC + salt + nonce + ct


def _decrypt(blob: bytes, password: str) -> bytes:
    if not blob.startswith(MAGIC):
        raise ValueError("Formato de backup desconhecido")
    if len(blob) < 4 + SALT_LEN + NONCE_LEN + 16:
        raise ValueError("Arquivo de backup truncado")
    salt = blob[4 : 4 + SALT_LEN]
    nonce = blob[4 + SALT_LEN : 4 + SALT_LEN + NONCE_LEN]
    ct = blob[4 + SALT_LEN + NONCE_LEN :]
    key = _derive_key_argon2(password, salt)
    aesgcm = AESGCM(key)
    try:
        return aesgcm.decrypt(nonce, ct, MAGIC)
    finally:
        key = b"\x00" * KEY_LEN


def _decrypt_legacy_fernet(blob: bytes, password: str) -> bytes:
    """Compatibilidade com backups NZXS1 (PBKDF2 + Fernet)."""
    import base64

    from cryptography.fernet import Fernet, InvalidToken
    from cryptography.hazmat.primitives import hashes
    from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC

    if not blob.startswith(LEGACY_MAGIC):
        raise InvalidToken("Formato legado desconhecido")
    salt = blob[5:21]
    token = blob[21:]
    kdf = PBKDF2HMAC(
        algorithm=hashes.SHA256(),
        length=32,
        salt=salt,
        iterations=480_000,
    )
    key = base64.urlsafe_b64encode(kdf.derive(password.encode("utf-8")))
    return Fernet(key).decrypt(token)
