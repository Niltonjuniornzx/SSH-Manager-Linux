"""Bloqueio por inatividade e senha mestra (Argon2id)."""

from __future__ import annotations

import hashlib
import hmac
import logging
import secrets
import time
from typing import Callable, Optional

from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# Formato versionado: argon2id$v=1$<encoded_argon2>
# Legado: 64 hex chars (SHA-256)
HASH_PREFIX = "argon2id$v=1$"

# Parâmetros seguros e configuráveis
DEFAULT_TIME_COST = 3
DEFAULT_MEMORY_COST = 65536  # KiB (= 64 MiB)
DEFAULT_PARALLELISM = 4

# Limite de tentativas com atraso progressivo
MAX_ATTEMPTS_WINDOW = 10
BASE_DELAY_SEC = 0.5
MAX_DELAY_SEC = 30.0


def _argon2_hash(
    password: str,
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_cost: int = DEFAULT_MEMORY_COST,
    parallelism: int = DEFAULT_PARALLELISM,
) -> str:
    from argon2 import PasswordHasher
    from argon2.low_level import Type

    ph = PasswordHasher(
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
        hash_len=32,
        salt_len=16,
        type=Type.ID,
    )
    encoded = ph.hash(password)
    return f"{HASH_PREFIX}{encoded}"


def _argon2_verify(stored: str, password: str) -> bool:
    from argon2 import PasswordHasher
    from argon2.exceptions import InvalidHashError, VerifyMismatchError

    if not stored.startswith(HASH_PREFIX):
        return False
    encoded = stored[len(HASH_PREFIX) :]
    ph = PasswordHasher()
    try:
        return bool(ph.verify(encoded, password))
    except VerifyMismatchError:
        return False
    except (InvalidHashError, Exception):  # noqa: BLE001
        logger.warning(sanitize_for_log("Hash de senha mestra inválido ou corrompido"))
        return False


def _is_legacy_sha256(stored: str) -> bool:
    if not stored or len(stored) != 64:
        return False
    try:
        int(stored, 16)
        return True
    except ValueError:
        return False


def _verify_legacy_sha256(stored: str, password: str) -> bool:
    digest = hashlib.sha256(password.encode("utf-8")).hexdigest()
    return hmac.compare_digest(digest, stored)


def hash_master_password(
    password: str,
    *,
    time_cost: int = DEFAULT_TIME_COST,
    memory_cost: int = DEFAULT_MEMORY_COST,
    parallelism: int = DEFAULT_PARALLELISM,
) -> str:
    """Gera hash Argon2id versionado. Nunca logar o retorno."""
    if not password:
        raise ValueError("Senha mestra vazia")
    return _argon2_hash(
        password,
        time_cost=time_cost,
        memory_cost=memory_cost,
        parallelism=parallelism,
    )


def verify_master_password(stored: str, password: str) -> tuple[bool, Optional[str]]:
    """
    Verifica senha mestra.

    Retorna (ok, new_hash_if_migrated).
    Migra SHA-256 legado → Argon2id somente após senha correta.
    """
    if not stored or not password:
        return False, None

    if stored.startswith(HASH_PREFIX):
        return _argon2_verify(stored, password), None

    if _is_legacy_sha256(stored):
        if _verify_legacy_sha256(stored, password):
            # migrar só depois de senha correta
            new_hash = hash_master_password(password)
            logger.info(
                sanitize_for_log(
                    "Senha mestra migrada de SHA-256 para Argon2id"
                )
            )
            return True, new_hash
        return False, None

    # Formato desconhecido
    logger.warning(sanitize_for_log("Formato de hash de senha mestra desconhecido"))
    return False, None


def needs_rehash(stored: str) -> bool:
    """True se o hash deve ser atualizado (legado ou parâmetros antigos)."""
    if not stored:
        return False
    if _is_legacy_sha256(stored):
        return True
    if not stored.startswith(HASH_PREFIX):
        return True
    try:
        from argon2 import PasswordHasher

        encoded = stored[len(HASH_PREFIX) :]
        ph = PasswordHasher(
            time_cost=DEFAULT_TIME_COST,
            memory_cost=DEFAULT_MEMORY_COST,
            parallelism=DEFAULT_PARALLELISM,
            hash_len=32,
            salt_len=16,
        )
        return bool(ph.check_needs_rehash(encoded))
    except Exception:  # noqa: BLE001
        return False


class AppLock:
    """Controla bloqueio por timeout de inatividade e senha mestra opcional."""

    def __init__(
        self,
        timeout_minutes: int = 0,
        master_password_hash: Optional[str] = None,
        on_lock: Optional[Callable[[], None]] = None,
        on_unlock: Optional[Callable[[], None]] = None,
        on_hash_upgraded: Optional[Callable[[str], None]] = None,
    ) -> None:
        self.timeout_minutes = timeout_minutes
        self._master_hash = master_password_hash
        self._on_lock = on_lock
        self._on_unlock = on_unlock
        self._on_hash_upgraded = on_hash_upgraded
        self._last_activity = time.monotonic()
        self._locked = False
        self._failed_attempts = 0
        self._lockout_until = 0.0

    @property
    def is_locked(self) -> bool:
        return self._locked

    @property
    def is_enabled(self) -> bool:
        return self.timeout_minutes > 0

    @property
    def has_master_password(self) -> bool:
        return bool(self._master_hash)

    def touch(self) -> None:
        """Registra atividade do usuário."""
        self._last_activity = time.monotonic()

    def check(self) -> bool:
        """Verifica se deve bloquear. Retorna True se bloqueou agora."""
        if not self.is_enabled or self._locked:
            return False
        elapsed_min = (time.monotonic() - self._last_activity) / 60.0
        if elapsed_min >= self.timeout_minutes:
            self.lock()
            return True
        return False

    def lock(self) -> None:
        self._locked = True
        if self._on_lock:
            self._on_lock()

    def _apply_backoff(self) -> None:
        """Atraso progressivo após falhas consecutivas."""
        self._failed_attempts += 1
        delay = min(
            MAX_DELAY_SEC,
            BASE_DELAY_SEC * (2 ** min(self._failed_attempts - 1, 6)),
        )
        # jitter leve
        delay += secrets.SystemRandom().uniform(0, 0.25)
        self._lockout_until = time.monotonic() + delay
        logger.info(
            sanitize_for_log(
                "Tentativa de desbloqueio falhou",
                attempts=self._failed_attempts,
                delay_sec=round(delay, 2),
            )
        )

    def unlock(self, password: Optional[str] = None) -> bool:
        """
        Desbloqueia. Se master password estiver configurada, exige-a.
        Nota: a senha mestra é camada ADICIONAL, não substitui o keyring.
        """
        now = time.monotonic()
        if now < self._lockout_until:
            # ainda em cooldown — falha sem revelar se a senha estaria correta
            remaining = self._lockout_until - now
            logger.info(
                sanitize_for_log(
                    "Desbloqueio em espera por tentativas",
                    wait_sec=round(remaining, 1),
                )
            )
            return False

        if self._master_hash:
            if not password:
                self._apply_backoff()
                return False
            ok, new_hash = verify_master_password(self._master_hash, password)
            # limpar referência o quanto antes
            password = None
            if not ok:
                self._apply_backoff()
                return False
            if new_hash:
                self._master_hash = new_hash
                if self._on_hash_upgraded:
                    self._on_hash_upgraded(new_hash)
            elif needs_rehash(self._master_hash or ""):
                # rehash com parâmetros atuais se possível — precisa da senha
                # (já consumida); só migração legada cobre o caso principal
                pass

        self._failed_attempts = 0
        self._lockout_until = 0.0
        self._locked = False
        self.touch()
        if self._on_unlock:
            self._on_unlock()
        return True

    def set_master_password(self, password: str) -> str:
        """Define senha mestra (Argon2id) e retorna o hash para persistir."""
        h = hash_master_password(password)
        self._master_hash = h
        password = None  # noqa: F841
        return h

    def clear_master_password(self) -> None:
        self._master_hash = None

    def set_timeout(self, minutes: int) -> None:
        self.timeout_minutes = max(0, minutes)

    def set_master_hash(self, hash_value: Optional[str]) -> None:
        self._master_hash = hash_value
