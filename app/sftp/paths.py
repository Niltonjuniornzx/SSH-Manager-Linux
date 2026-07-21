"""Validação segura de caminhos SFTP (path traversal, links, limites)."""

from __future__ import annotations

from pathlib import PurePosixPath
from typing import Optional


class SFTPPathError(ValueError):
    """Caminho SFTP inválido ou inseguro."""


MAX_PATH_LEN = 4096
MAX_NAME_LEN = 255


def normalize_remote_path(path: str, *, base: Optional[str] = None) -> str:
    """
    Normaliza caminho remoto estilo POSIX.
    Rejeita path traversal (../), nulos e caminhos absurdamente longos.
    """
    if path is None:
        raise SFTPPathError("Caminho vazio")
    raw = str(path).replace("\x00", "")
    if not raw or raw.strip() == "":
        raise SFTPPathError("Caminho vazio")
    if len(raw) > MAX_PATH_LEN:
        raise SFTPPathError("Caminho excede o tamanho máximo")
    # Unificar separadores
    raw = raw.replace("\\", "/")
    if base and not raw.startswith("/"):
        base_n = str(base).replace("\\", "/").rstrip("/")
        raw = f"{base_n}/{raw}" if base_n else raw

    # PurePosixPath resolve ".." semanticamente sem FS
    parts: list[str] = []
    is_abs = raw.startswith("/")
    for part in PurePosixPath(raw).parts:
        if part in ("", "."):
            continue
        if part == "/":
            continue
        if part == "..":
            if parts:
                parts.pop()
            elif not is_abs:
                raise SFTPPathError("Path traversal não permitido (..)")
            # em absoluto, ".." na raiz é no-op
            continue
        if len(part) > MAX_NAME_LEN:
            raise SFTPPathError(f"Nome de arquivo muito longo: {part[:40]}…")
        if "\x00" in part:
            raise SFTPPathError("Caractere nulo no caminho")
        parts.append(part)

    if is_abs:
        return "/" + "/".join(parts) if parts else "/"
    return "/".join(parts) if parts else "."


def is_safe_remote_path(path: str, *, allow_absolute: bool = True) -> bool:
    try:
        n = normalize_remote_path(path)
    except SFTPPathError:
        return False
    if not allow_absolute and n.startswith("/"):
        return False
    # bloquear sequências suspeitas após normalização
    if ".." in PurePosixPath(n).parts:
        return False
    return True


def safe_join_remote(base: str, name: str) -> str:
    """Junta base + nome rejeitando traversal no name."""
    name = (name or "").replace("\\", "/").strip()
    if not name or name in (".", ".."):
        raise SFTPPathError("Nome inválido")
    if "/" in name or name.startswith("~"):
        # se name for caminho, normalizar contra base
        if name.startswith("/"):
            return normalize_remote_path(name)
        return normalize_remote_path(name, base=base)
    base_n = normalize_remote_path(base or "/")
    if base_n == "/":
        return f"/{name}"
    return f"{base_n.rstrip('/')}/{name}"


def is_within_base(path: str, base: str) -> bool:
    """True se path normalizado está sob base (prefixo de componentes)."""
    p = normalize_remote_path(path)
    b = normalize_remote_path(base)
    if b == "/":
        return p.startswith("/")
    return p == b or p.startswith(b.rstrip("/") + "/")
