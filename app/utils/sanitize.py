"""Sanitização de logs e mensagens — nunca expor segredos."""

from __future__ import annotations

import re
from typing import Any

# Padrões que indicam conteúdo sensível
_SECRET_PATTERNS: list[re.Pattern[str]] = [
    re.compile(r"(?i)(password|passwd|pwd|passphrase|secret|token|api[_-]?key)\s*[=:]\s*\S+"),
    re.compile(r"(?i)(password|passwd|pwd|passphrase|secret|token)\s+\S+"),
    re.compile(r"-----BEGIN[^-]+PRIVATE KEY-----[\s\S]*?-----END[^-]+PRIVATE KEY-----"),
    re.compile(r"(?i)bearer\s+[A-Za-z0-9\-._~+/]+=*"),
    re.compile(r"(?i)authorization:\s*\S+"),
]

_SENSITIVE_KEYS = frozenset(
    {
        "password",
        "passwd",
        "pwd",
        "passphrase",
        "secret",
        "token",
        "private_key",
        "privatekey",
        "api_key",
        "apikey",
        "credential",
        "credentials",
    }
)

REDACTED = "***REDACTED***"


def redact_secrets(text: str) -> str:
    """Remove padrões sensíveis de uma string."""
    if not text:
        return text
    result = text
    for pattern in _SECRET_PATTERNS:
        result = pattern.sub(REDACTED, result)
    return result


def sanitize_for_log(message: Any, **extra: Any) -> str:
    """Prepara mensagem de log sem dados sensíveis."""
    if message is None:
        base = ""
    else:
        base = redact_secrets(str(message))

    if not extra:
        return base

    safe_parts: list[str] = []
    for key, value in extra.items():
        key_lower = key.lower().replace("-", "_")
        if key_lower in _SENSITIVE_KEYS or any(s in key_lower for s in _SENSITIVE_KEYS):
            safe_parts.append(f"{key}={REDACTED}")
        else:
            safe_parts.append(f"{key}={redact_secrets(str(value))}")
    if safe_parts:
        return f"{base} | " + " ".join(safe_parts) if base else " ".join(safe_parts)
    return base


def sanitize_args(args: list[str]) -> list[str]:
    """Sanitiza lista de argumentos de processo para exibição/log."""
    sensitive_flags = {
        "-p",
        "--password",
        "--passwd",
        "-pw",
        "/p",
        "--pass",
        "--token",
        "--secret",
    }
    result: list[str] = []
    skip_next = False
    for arg in args:
        if skip_next:
            result.append(REDACTED)
            skip_next = False
            continue
        if arg in sensitive_flags:
            result.append(arg)
            skip_next = True
            continue
        # flag=value
        for flag in sensitive_flags:
            if arg.startswith(f"{flag}=") or arg.startswith(f"{flag}:"):
                result.append(f"{flag}={REDACTED}")
                break
        else:
            result.append(redact_secrets(arg))
    return result


def is_sensitive_key(key: str) -> bool:
    key_lower = key.lower().replace("-", "_")
    return key_lower in _SENSITIVE_KEYS or any(s in key_lower for s in _SENSITIVE_KEYS)
