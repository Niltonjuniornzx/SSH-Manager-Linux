"""Navegador e operações SFTP via AsyncSSH."""

from __future__ import annotations

import logging
import stat
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional

import asyncssh

from app.sftp.paths import SFTPPathError, is_safe_remote_path, normalize_remote_path
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)


class SFTPError(Exception):
    def __init__(self, message: str, *, code: str = "sftp_error") -> None:
        super().__init__(message)
        self.code = code


@dataclass
class RemoteFileInfo:
    name: str
    path: str
    size: int
    is_dir: bool
    is_link: bool
    permissions: str
    mode: int
    owner: str
    group: str
    mtime: Optional[float]
    extension: str = ""

    @property
    def type_label(self) -> str:
        if self.is_link:
            return "Link simbólico"
        if self.is_dir:
            return "Pasta"
        if self.extension:
            return self.extension.upper()
        return "Arquivo"

    @property
    def mtime_str(self) -> str:
        if self.mtime is None:
            return ""
        try:
            return datetime.fromtimestamp(self.mtime).strftime("%Y-%m-%d %H:%M")
        except (OSError, ValueError, OverflowError):
            return ""

    @property
    def size_str(self) -> str:
        if self.is_dir:
            return "—"
        return format_size(self.size)


def format_size(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    for unit in ("KB", "MB", "GB", "TB"):
        n_f = n / 1024.0
        if n_f < 1024.0:
            return f"{n_f:.1f} {unit}"
        n = int(n_f)
    return f"{n} PB"


def mode_to_str(mode: int) -> str:
    """Converte modo Unix para string estilo ls (ex: drwxr-xr-x)."""
    if stat.S_ISDIR(mode):
        s = "d"
    elif stat.S_ISLNK(mode):
        s = "l"
    else:
        s = "-"
    perms = [
        (stat.S_IRUSR, "r"),
        (stat.S_IWUSR, "w"),
        (stat.S_IXUSR, "x"),
        (stat.S_IRGRP, "r"),
        (stat.S_IWGRP, "w"),
        (stat.S_IXGRP, "x"),
        (stat.S_IROTH, "r"),
        (stat.S_IWOTH, "w"),
        (stat.S_IXOTH, "x"),
    ]
    for bit, ch in perms:
        s += ch if mode & bit else "-"
    return s


class SFTPBrowser:
    """Operações SFTP de alto nível sobre um SFTPClient asyncssh."""

    def __init__(
        self,
        sftp: asyncssh.SFTPClient,
        *,
        username: str = "",
    ) -> None:
        self.sftp = sftp
        self.username = username
        self.cwd: str = "."
        self.home: str = ""
        self._history: list[str] = []
        self._history_index: int = -1

    async def pwd(self) -> str:
        try:
            self.cwd = await self.sftp.getcwd()
        except Exception:  # noqa: BLE001
            pass
        return self.cwd

    @staticmethod
    def _is_valid_home_path(path: str) -> bool:
        """Rejeita expansões quebradas como /root/~ (comum em alguns OpenSSH)."""
        if not path or path in (".", ""):
            return False
        p = path.replace("\\", "/").rstrip("/")
        # realpath("~") em alguns servidores devolve "/home/user/~" ou "/root/~"
        if p.endswith("/~") or p.endswith("~") and "/" in p[:-1]:
            return False
        if "/~/" in p or p == "~":
            return False
        return True

    async def _path_exists_dir(self, path: str) -> bool:
        try:
            attrs = await self.sftp.stat(path)
            mode = int(attrs.permissions or 0)
            return bool(stat.S_ISDIR(mode)) if mode else True
        except Exception:  # noqa: BLE001
            return False

    async def resolve_home(self) -> str:
        """
        Resolve o diretório home real do usuário remoto.

        Ordem:
        1. Valor já em cache
        2. getcwd() inicial da sessão SFTP (no OpenSSH costuma ser o home)
        3. /root ou /home/<user> conforme username
        4. realpath("~") só se não terminar em /~
        5. /
        """
        if self.home and self._is_valid_home_path(self.home):
            return self.home

        # 1) cwd da sessão — mais confiável logo após open_sftp
        try:
            cur = await self.sftp.getcwd()
            cur_s = str(cur) if cur else ""
            if self._is_valid_home_path(cur_s) and await self._path_exists_dir(cur_s):
                self.home = cur_s
                return self.home
        except Exception:  # noqa: BLE001
            pass

        # 2) caminhos típicos por usuário
        user = (self.username or "").strip()
        guesses: list[str] = []
        if user == "root" or not user:
            guesses.append("/root")
        if user and user != "root":
            guesses.append(f"/home/{user}")
            guesses.append(f"/Users/{user}")  # macOS remoto raro
        guesses.append("/root")

        for g in guesses:
            if await self._path_exists_dir(g):
                self.home = g
                return self.home

        # 3) realpath("~") — alguns OpenSSH NÃO expandem e devolvem ".../~"
        try:
            resolved = str(await self.sftp.realpath("~"))
            if self._is_valid_home_path(resolved) and await self._path_exists_dir(resolved):
                self.home = resolved
                return self.home
        except Exception:  # noqa: BLE001
            pass

        self.home = "/"
        return self.home

    async def chdir(self, path: str, *, track_history: bool = True) -> str:
        try:
            target = (path or "").strip()
            if target in ("~", "$HOME", ""):
                target = await self.resolve_home()
            # se alguém passar literalmente /root/~ por bug antigo, corrigir
            if target.endswith("/~") or target.endswith("~") and "/" in target[:-1]:
                target = await self.resolve_home()
            await self.sftp.chdir(target)
            self.cwd = await self.sftp.getcwd()
            if track_history:
                self._history = self._history[: self._history_index + 1]
                self._history.append(self.cwd)
                self._history_index = len(self._history) - 1
            return self.cwd
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="chdir") from exc
        except OSError as exc:
            raise SFTPError(f"Erro ao acessar diretório: {exc}", code="chdir") from exc

    async def go_home(self) -> str:
        # limpar cache inválido
        if self.home and not self._is_valid_home_path(self.home):
            self.home = ""
        home = await self.resolve_home()
        return await self.chdir(home)

    async def go_up(self) -> str:
        parent = str(Path(self.cwd).parent) if self.cwd not in ("/", "") else "/"
        return await self.chdir(parent)

    async def go_back(self) -> Optional[str]:
        if self._history_index <= 0:
            return None
        self._history_index -= 1
        path = self._history[self._history_index]
        return await self.chdir(path, track_history=False)

    async def go_forward(self) -> Optional[str]:
        if self._history_index >= len(self._history) - 1:
            return None
        self._history_index += 1
        path = self._history[self._history_index]
        return await self.chdir(path, track_history=False)

    async def listdir(
        self, path: Optional[str] = None, *, show_hidden: bool = False
    ) -> list[RemoteFileInfo]:
        target = path or self.cwd or "."
        # Nunca listar caminhos lixo tipo /root/~
        if not self._is_valid_home_path(target) and target not in (".", "/"):
            if target.endswith("/~") or target.endswith("~"):
                target = await self.resolve_home()
        try:
            entries = await self.sftp.readdir(target)
        except asyncssh.SFTPError as exc:
            # retry no cwd se path relativo falhar
            if target not in (".", self.cwd):
                try:
                    entries = await self.sftp.readdir(".")
                    target = self.cwd or "."
                except asyncssh.SFTPError:
                    raise SFTPError(self._map_error(exc), code="list") from exc
            else:
                raise SFTPError(self._map_error(exc), code="list") from exc

        result: list[RemoteFileInfo] = []
        for entry in entries:
            name = entry.filename
            if name in (".", ".."):
                continue
            if not show_hidden and name.startswith("."):
                continue
            attrs = entry.attrs
            mode = int(attrs.permissions or 0)
            is_dir = stat.S_ISDIR(mode) if mode else False
            is_link = stat.S_ISLNK(mode) if mode else False
            if not mode and entry.longname:
                is_dir = entry.longname.startswith("d")
                is_link = entry.longname.startswith("l")
            if target in (".", ""):
                full = name
            elif target.endswith("/"):
                full = target + name
            else:
                full = f"{target}/{name}"
            ext = Path(name).suffix.lstrip(".") if not is_dir else ""
            owner = str(attrs.uid) if attrs.uid is not None else ""
            group = str(attrs.gid) if attrs.gid is not None else ""
            result.append(
                RemoteFileInfo(
                    name=name,
                    path=full,
                    size=int(attrs.size or 0),
                    is_dir=is_dir,
                    is_link=is_link,
                    permissions=mode_to_str(mode) if mode else "----------",
                    mode=mode,
                    owner=owner,
                    group=group,
                    mtime=float(attrs.mtime) if attrs.mtime is not None else None,
                    extension=ext,
                )
            )
        # pastas primeiro, depois nome
        result.sort(key=lambda f: (not f.is_dir, f.name.lower()))
        return result

    async def mkdir(self, path: str) -> None:
        path = self._safe_path(path)
        try:
            await self.sftp.mkdir(path)
            logger.info(sanitize_for_log("Pasta remota criada", path=path))
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="mkdir") from exc

    async def remove(self, path: str, *, is_dir: bool = False) -> None:
        path = self._safe_path(path)
        try:
            if is_dir:
                await self._rmtree(path)
            else:
                await self.sftp.remove(path)
            logger.info(sanitize_for_log("Removido remoto", path=path))
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="remove") from exc

    async def _rmtree(self, path: str) -> None:
        entries = await self.sftp.readdir(path)
        for entry in entries:
            if entry.filename in (".", ".."):
                continue
            child = str(Path(path) / entry.filename)
            mode = int(entry.attrs.permissions or 0)
            if stat.S_ISDIR(mode):
                await self._rmtree(child)
            else:
                await self.sftp.remove(child)
        await self.sftp.rmdir(path)

    async def rename(self, old: str, new: str) -> None:
        old = self._safe_path(old)
        new = self._safe_path(new)
        try:
            await self.sftp.rename(old, new)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="rename") from exc

    async def chmod(self, path: str, mode: int) -> None:
        path = self._safe_path(path)
        try:
            await self.sftp.chmod(path, mode)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="chmod") from exc

    async def symlink(self, target: str, path: str) -> None:
        path = self._safe_path(path)
        # target é o destino do link — normaliza sem forçar base
        if not is_safe_remote_path(target) and not target.startswith("/"):
            raise SFTPError("Destino de symlink inválido", code="symlink")
        try:
            await self.sftp.symlink(target, path)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="symlink") from exc

    async def readlink(self, path: str) -> str:
        try:
            return await self.sftp.readlink(path)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="readlink") from exc

    async def stat(self, path: str) -> Any:
        try:
            return await self.sftp.stat(path)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="stat") from exc

    async def exists(self, path: str) -> bool:
        try:
            await self.sftp.stat(path)
            return True
        except asyncssh.SFTPError:
            return False

    async def write_file(self, path: str, data: bytes) -> None:
        path = self._safe_path(path)
        try:
            async with self.sftp.open(path, "wb") as f:
                await f.write(data)
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="write") from exc

    async def read_file(self, path: str, max_size: int = 10 * 1024 * 1024) -> bytes:
        path = self._safe_path(path)
        try:
            attrs = await self.sftp.stat(path)
            size = int(attrs.size or 0)
            if size > max_size:
                raise SFTPError(
                    f"Arquivo muito grande para edição ({size} bytes).",
                    code="too_large",
                )
            async with self.sftp.open(path, "rb") as f:
                return await f.read()
        except asyncssh.SFTPError as exc:
            raise SFTPError(self._map_error(exc), code="read") from exc

    async def create_empty_file(self, path: str) -> None:
        await self.write_file(path, b"")

    def _safe_path(self, path: str) -> str:
        try:
            return normalize_remote_path(path, base=self.cwd if path and not str(path).startswith("/") else None)
        except SFTPPathError as exc:
            raise SFTPError(str(exc), code="bad_path") from exc

    @staticmethod
    def _map_error(exc: asyncssh.SFTPError) -> str:
        code = getattr(exc, "code", None)
        reason = str(exc)
        # AsyncSSH SFTP error codes
        mapping = {
            2: "Arquivo ou diretório não encontrado.",
            3: "Permissão negada no servidor remoto.",
            4: "Falha na operação SFTP.",
            11: "Arquivo ou diretório já existe.",
        }
        if code in mapping:
            return mapping[code]
        lower = reason.lower()
        if "permission" in lower:
            return "Permissão negada no servidor remoto."
        if "no such file" in lower or "not found" in lower:
            return "Arquivo ou diretório não encontrado."
        return f"Erro SFTP: {reason}"
