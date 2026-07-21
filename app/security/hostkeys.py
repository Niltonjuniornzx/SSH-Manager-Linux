"""Gerenciamento de host keys — validação antes da autenticação."""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from app.utils.paths import atomic_write, ensure_secure_file, known_hosts_path
from app.utils.sanitize import sanitize_for_log

if TYPE_CHECKING:
    from app.database.db import Database

logger = logging.getLogger(__name__)


class HostKeyDecision(str, Enum):
    ACCEPT = "accept"
    REJECT = "reject"
    CHANGED_BLOCK = "changed_block"


@dataclass
class HostKeyResult:
    decision: HostKeyDecision
    fingerprint_sha256: str
    key_type: str
    hostname: str
    port: int
    is_new: bool = False
    is_changed: bool = False
    previous_fingerprint: str = ""
    public_key_b64: str = ""
    message: str = ""


def fingerprint_sha256(public_data: bytes) -> str:
    """Fingerprint SHA-256 no formato OpenSSH (SHA256:base64)."""
    digest = hashlib.sha256(public_data).digest()
    b64 = base64.b64encode(digest).decode("ascii").rstrip("=")
    return f"SHA256:{b64}"


def _fp_equal(a: str, b: str) -> bool:
    """Comparação em tempo constante de fingerprints."""
    return hmac.compare_digest(a.encode("ascii"), b.encode("ascii"))


def canonical_host_marker(hostname: str, port: int) -> str:
    """Formato OpenSSH: host ou [host]:port."""
    host = (hostname or "").strip().lower()
    if port and port != 22:
        return f"[{host}]:{port}"
    return host


class HostKeyManager:
    """
    Verifica e armazena host keys.

    Política:
    - Primeira conexão: is_new=True; UI deve pedir confirmação EXPLÍCITA
    - Host key conhecida e igual: ACCEPT
    - Host key mudou: CHANGED_BLOCK (nunca aceitar silenciosamente)
    """

    def __init__(self, db: "Database", known_hosts: Optional[Path] = None) -> None:
        self.db = db
        self.known_hosts = known_hosts or known_hosts_path()
        ensure_secure_file(self.known_hosts)

    def check(
        self,
        hostname: str,
        port: int,
        key_type: str,
        public_key_data: bytes,
    ) -> HostKeyResult:
        hostname = (hostname or "").strip()
        key_type = (key_type or "").strip()
        fp = fingerprint_sha256(public_key_data)
        pub_b64 = base64.b64encode(public_key_data).decode("ascii")
        existing = self.db.get_trusted_host(hostname, port, key_type)

        if existing is None:
            # também tenta sem key_type estrito (algumas migrações)
            logger.info(
                sanitize_for_log(
                    "Host key desconhecida — requer confirmação",
                    host=hostname,
                    port=port,
                    key_type=key_type,
                    fingerprint=fp,
                )
            )
            return HostKeyResult(
                decision=HostKeyDecision.REJECT,
                fingerprint_sha256=fp,
                key_type=key_type,
                hostname=hostname,
                port=port,
                is_new=True,
                public_key_b64=pub_b64,
                message=(
                    "Servidor desconhecido — confirme a host key antes de autenticar.\n\n"
                    f"Host: {hostname}\n"
                    f"Porta: {port}\n"
                    f"Algoritmo: {key_type}\n"
                    f"Fingerprint SHA-256:\n{fp}\n\n"
                    "Deseja confiar neste servidor e continuar?"
                ),
            )

        old_fp = existing["fingerprint_sha256"] or ""
        if not _fp_equal(old_fp, fp):
            logger.warning(
                sanitize_for_log(
                    "ALERTA: host key ALTERADA — bloqueado antes da autenticação",
                    host=hostname,
                    port=port,
                    key_type=key_type,
                )
            )
            return HostKeyResult(
                decision=HostKeyDecision.CHANGED_BLOCK,
                fingerprint_sha256=fp,
                key_type=key_type,
                hostname=hostname,
                port=port,
                is_changed=True,
                previous_fingerprint=old_fp,
                public_key_b64=pub_b64,
                message=(
                    "⚠ HOST KEY ALTERADA — conexão bloqueada\n\n"
                    f"O servidor {hostname}:{port} apresentou uma chave diferente "
                    "da que foi confiada anteriormente.\n\n"
                    f"Anterior:\n{old_fp}\n\n"
                    f"Atual:\n{fp}\n\n"
                    "Isso pode indicar um ataque man-in-the-middle.\n"
                    "Nenhuma credencial foi enviada.\n\n"
                    "Se você reinstalou o servidor intencionalmente, remova a chave "
                    "confiável em Configurações e conecte novamente."
                ),
            )

        return HostKeyResult(
            decision=HostKeyDecision.ACCEPT,
            fingerprint_sha256=fp,
            key_type=key_type,
            hostname=hostname,
            port=port,
            public_key_b64=pub_b64,
            message="Host key verificada.",
        )

    def accept(
        self,
        hostname: str,
        port: int,
        key_type: str,
        fingerprint_sha256: str,
        public_key_b64: str,
    ) -> None:
        self.db.trust_host(
            hostname, port, key_type, fingerprint_sha256, public_key_b64
        )
        self._append_known_hosts(hostname, port, key_type, public_key_b64)
        logger.info(
            sanitize_for_log(
                "Host key aceita e salva",
                host=hostname,
                port=port,
                fingerprint=fingerprint_sha256,
            )
        )

    def _append_known_hosts(
        self, hostname: str, port: int, key_type: str, public_key_b64: str
    ) -> None:
        """Arquivo known_hosts estilo OpenSSH (0600)."""
        ensure_secure_file(self.known_hosts)
        marker = canonical_host_marker(hostname, port)
        line = f"{marker} {key_type} {public_key_b64}\n"
        try:
            existing_lines = self.known_hosts.read_text(encoding="utf-8").splitlines(
                keepends=True
            )
        except OSError:
            existing_lines = []
        host_plain = hostname.strip().lower()
        filtered: list[str] = []
        for ln in existing_lines:
            s = ln.strip()
            if not s or s.startswith("#"):
                filtered.append(ln)
                continue
            # remove entradas antigas do mesmo host:port
            if s.startswith(marker + " ") or s.startswith(host_plain + " "):
                continue
            if port != 22 and s.startswith(f"[{host_plain}]:{port} "):
                continue
            filtered.append(ln if ln.endswith("\n") else ln + "\n")
        filtered.append(line)
        atomic_write(self.known_hosts, "".join(filtered), mode=0o600)

    def remove(self, hostname: str, port: int, key_type: Optional[str] = None) -> None:
        hosts = self.db.list_trusted_hosts()
        for h in hosts:
            if h["hostname"] == hostname and int(h["port"]) == int(port):
                if key_type is None or h["key_type"] == key_type:
                    self.db.delete_trusted_host(h["id"])
        # limpar known_hosts
        try:
            marker = canonical_host_marker(hostname, port)
            host_plain = hostname.strip().lower()
            lines = self.known_hosts.read_text(encoding="utf-8").splitlines(keepends=True)
            kept = []
            for ln in lines:
                s = ln.strip()
                if s.startswith(marker + " ") or s.startswith(host_plain + " "):
                    continue
                kept.append(ln)
            atomic_write(self.known_hosts, "".join(kept), mode=0o600)
        except OSError:
            pass

    def list_trusted(self) -> list[dict]:
        return self.db.list_trusted_hosts()
