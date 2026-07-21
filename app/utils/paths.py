"""Caminhos de dados e configuração — SSH-Manager-Linux + migração legada."""

from __future__ import annotations

import logging
import os
import shutil
import stat
from pathlib import Path

logger = logging.getLogger(__name__)

APP_DIR_NAME = "ssh-manager-linux"
# pastas legadas a migrar (não apaga as antigas — backup do usuário)
_LEGACY_DATA_NAMES = (
    "nzxs-remote-manager",
    "ssh-remote-manager",
    "SSH Remote Manager",
    "NZXS Remote Manager",
)
_LEGACY_CONFIG_NAMES = (
    "nzxs-remote-manager",
    "ssh-remote-manager",
    "SSH Remote Manager",
    "NZXS Remote Manager",
)
_LEGACY_CACHE_NAMES = (
    "nzxs-remote-manager",
    "ssh-remote-manager",
)

_migrated = False


def _xdg(env: str, default_parts: tuple[str, ...]) -> Path:
    base = os.environ.get(env)
    if base:
        return Path(base)
    return Path.home().joinpath(*default_parts)


def _safe_migrate_dir(src: Path, dst: Path) -> bool:
    """Copia src → dst se dst vazio/inexistente. Não apaga src (backup do usuário)."""
    if not src.exists() or not src.is_dir():
        return False
    if dst.exists():
        try:
            # se já tem dados, não sobrescreve
            if any(dst.iterdir()):
                return False
        except OSError:
            return False
    try:
        ensure_secure_dir(dst.parent, 0o700)
        shutil.copytree(src, dst, dirs_exist_ok=True, symlinks=False)
        ensure_secure_dir(dst, 0o700)
        logger.info("Migração de dados: %s → %s", src, dst)
        return True
    except OSError as exc:
        logger.warning("Falha ao migrar %s → %s: %s", src, dst, exc)
        return False


def migrate_legacy_paths() -> None:
    """Migra dados/config/cache de nomes antigos para ssh-manager-linux (uma vez)."""
    global _migrated
    if _migrated:
        return
    _migrated = True

    data_root = _xdg("XDG_DATA_HOME", (".local", "share"))
    cfg_root = _xdg("XDG_CONFIG_HOME", (".config",))
    cache_root = _xdg("XDG_CACHE_HOME", (".cache",))

    new_data = data_root / APP_DIR_NAME
    new_cfg = cfg_root / APP_DIR_NAME
    new_cache = cache_root / APP_DIR_NAME

    for name in _LEGACY_DATA_NAMES:
        _safe_migrate_dir(data_root / name, new_data)
    for name in _LEGACY_CONFIG_NAMES:
        _safe_migrate_dir(cfg_root / name, new_cfg)
    for name in _LEGACY_CACHE_NAMES:
        _safe_migrate_dir(cache_root / name, new_cache)

    # também migrar install legada se só existir a antiga
    # (não move install; apenas dados de usuário)


def app_data_dir() -> Path:
    """~/.local/share/ssh-manager-linux (0700)."""
    migrate_legacy_paths()
    base = _xdg("XDG_DATA_HOME", (".local", "share"))
    path = base / APP_DIR_NAME
    return ensure_secure_dir(path, 0o700)


def app_config_dir() -> Path:
    """~/.config/ssh-manager-linux (0700)."""
    migrate_legacy_paths()
    base = _xdg("XDG_CONFIG_HOME", (".config",))
    path = base / APP_DIR_NAME
    return ensure_secure_dir(path, 0o700)


def app_cache_dir() -> Path:
    """~/.cache/ssh-manager-linux (0700)."""
    migrate_legacy_paths()
    base = _xdg("XDG_CACHE_HOME", (".cache",))
    path = base / APP_DIR_NAME
    return ensure_secure_dir(path, 0o700)


def database_path() -> Path:
    path = app_data_dir() / "manager.db"
    # não cria ainda se não existir — Database cuida
    if path.exists():
        ensure_secure_file(path)
    return path


def known_hosts_path() -> Path:
    path = app_data_dir() / "known_hosts"
    ensure_secure_file(path)
    return path


def logs_dir() -> Path:
    return ensure_secure_dir(app_data_dir() / "logs", 0o700)


def ensure_secure_file(path: Path, mode: int = 0o600) -> Path:
    """Cria o arquivo se não existir e força permissão 0600. Recusa symlinks."""
    parent = path.parent
    ensure_secure_dir(parent, 0o700)
    if path.is_symlink():
        raise OSError(f"Recusado: {path} é symlink")
    if not path.exists():
        # criação atômica
        tmp = parent / f".{path.name}.tmp"
        flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
        fd = os.open(str(tmp), flags, mode)
        os.close(fd)
        os.replace(str(tmp), str(path))
    try:
        if not path.is_symlink():
            path.chmod(mode)
    except OSError:
        pass
    return path


def ensure_secure_dir(path: Path, mode: int = 0o700) -> Path:
    if path.is_symlink():
        raise OSError(f"Recusado: {path} é symlink")
    path.mkdir(parents=True, exist_ok=True)
    try:
        path.chmod(mode)
    except OSError:
        pass
    return path


def atomic_write(path: Path, data: bytes | str, mode: int = 0o600) -> None:
    """Gravação atômica com permissão segura."""
    ensure_secure_dir(path.parent, 0o700)
    if path.is_symlink():
        raise OSError(f"Recusado: {path} é symlink")
    tmp = path.parent / f".{path.name}.{os.getpid()}.tmp"
    try:
        if isinstance(data, str):
            tmp.write_text(data, encoding="utf-8")
        else:
            tmp.write_bytes(data)
        tmp.chmod(mode)
        os.replace(str(tmp), str(path))
        path.chmod(mode)
    finally:
        if tmp.exists():
            try:
                tmp.unlink()
            except OSError:
                pass


def is_secure_permissions(path: Path) -> bool:
    """Retorna True se o arquivo não for legível por grupo/outros."""
    if not path.exists():
        return True
    if path.is_symlink():
        return False
    mode = path.stat().st_mode
    return not (mode & (stat.S_IRGRP | stat.S_IROTH | stat.S_IWGRP | stat.S_IWOTH))
