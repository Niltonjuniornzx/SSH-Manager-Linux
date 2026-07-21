"""Fila de uploads/downloads com progresso, pause/cancel e limites."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from pathlib import Path
from typing import Awaitable, Callable, Optional

import asyncssh

from app.models.transfer import (
    ConflictPolicy,
    TransferDirection,
    TransferItem,
    TransferStatus,
)
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

ProgressCallback = Callable[[TransferItem], None]
StatusCallback = Callable[[TransferItem], None]


class TransferQueue:
    """
    Gerencia fila de transferências SFTP com concorrência configurável.

    A interface deve fornecer um factory de SFTP client por server_id.
    """

    def __init__(
        self,
        *,
        max_concurrent: int = 3,
        speed_limit_bps: int = 0,
        get_sftp: Optional[
            Callable[[int], Awaitable[Optional[asyncssh.SFTPClient]]]
        ] = None,
        on_progress: Optional[ProgressCallback] = None,
        on_status: Optional[StatusCallback] = None,
    ) -> None:
        self.max_concurrent = max_concurrent
        self.speed_limit_bps = speed_limit_bps
        self.get_sftp = get_sftp
        self.on_progress = on_progress
        self.on_status = on_status
        self._items: dict[str, TransferItem] = {}
        self._order: list[str] = []
        self._running: set[str] = set()
        self._pause_flags: dict[str, asyncio.Event] = {}
        self._cancel_flags: set[str] = set()
        self._lock = asyncio.Lock()
        self._workers: list[asyncio.Task[None]] = []
        self._queue: asyncio.Queue[str] = asyncio.Queue()
        self._started = False

    def start(self) -> None:
        if self._started:
            return
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            # Sem loop ainda (ex.: construção da UI antes do qasync) —
            # enqueue() tentará de novo quando o loop estiver ativo.
            return
        self._started = True
        for _ in range(max(1, self.max_concurrent)):
            self._workers.append(loop.create_task(self._worker()))

    async def stop(self) -> None:
        self._started = False
        for item_id in list(self._items):
            self._cancel_flags.add(item_id)
        for w in self._workers:
            w.cancel()
        await asyncio.gather(*self._workers, return_exceptions=True)
        self._workers.clear()

    def list_items(self) -> list[TransferItem]:
        return [self._items[i] for i in self._order if i in self._items]

    def get(self, item_id: str) -> Optional[TransferItem]:
        return self._items.get(item_id)

    async def enqueue(self, item: TransferItem) -> TransferItem:
        self._items[item.id] = item
        self._order.append(item.id)
        self._pause_flags[item.id] = asyncio.Event()
        self._pause_flags[item.id].set()  # not paused
        item.status = TransferStatus.QUEUED
        self._emit_status(item)
        await self._queue.put(item.id)
        if not self._started:
            self.start()
        logger.info(
            sanitize_for_log(
                "Transferência enfileirada",
                direction=item.direction.value,
                name=item.display_name,
            )
        )
        return item

    def pause(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item or item.status != TransferStatus.RUNNING:
            return
        flag = self._pause_flags.get(item_id)
        if flag:
            flag.clear()
        item.status = TransferStatus.PAUSED
        self._emit_status(item)

    def resume(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item or item.status != TransferStatus.PAUSED:
            return
        flag = self._pause_flags.get(item_id)
        if flag:
            flag.set()
        item.status = TransferStatus.RUNNING
        self._emit_status(item)

    def cancel(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        self._cancel_flags.add(item_id)
        flag = self._pause_flags.get(item_id)
        if flag:
            flag.set()  # desbloquear se pausado
        if item.status in (TransferStatus.QUEUED, TransferStatus.PAUSED):
            item.status = TransferStatus.CANCELLED
            item.finished_at = time.time()
            self._emit_status(item)

    async def retry(self, item_id: str) -> None:
        item = self._items.get(item_id)
        if not item:
            return
        if item.status not in (
            TransferStatus.FAILED,
            TransferStatus.CANCELLED,
            TransferStatus.SKIPPED,
        ):
            return
        self._cancel_flags.discard(item_id)
        item.status = TransferStatus.QUEUED
        item.transferred_bytes = 0
        item.speed_bps = 0
        item.error_message = ""
        item.started_at = None
        item.finished_at = None
        self._pause_flags[item_id] = asyncio.Event()
        self._pause_flags[item_id].set()
        self._emit_status(item)
        await self._queue.put(item_id)

    async def _worker(self) -> None:
        while True:
            try:
                item_id = await self._queue.get()
            except asyncio.CancelledError:
                break
            item = self._items.get(item_id)
            if not item or item.status == TransferStatus.CANCELLED:
                self._queue.task_done()
                continue
            if item_id in self._cancel_flags:
                item.status = TransferStatus.CANCELLED
                item.finished_at = time.time()
                self._emit_status(item)
                self._queue.task_done()
                continue
            self._running.add(item_id)
            try:
                await self._process(item)
            except Exception as exc:  # noqa: BLE001
                item.status = TransferStatus.FAILED
                item.error_message = str(exc)
                item.finished_at = time.time()
                self._emit_status(item)
                logger.error(
                    sanitize_for_log("Transferência falhou", error=str(exc), name=item.display_name)
                )
            finally:
                self._running.discard(item_id)
                self._queue.task_done()

    async def _process(self, item: TransferItem) -> None:
        if self.get_sftp is None or item.server_id is None:
            raise RuntimeError("SFTP não disponível para esta transferência.")
        sftp = await self.get_sftp(item.server_id)
        if sftp is None:
            raise RuntimeError("Sem conexão SFTP. Conecte-se ao servidor primeiro.")

        item.status = TransferStatus.RUNNING
        item.started_at = time.time()
        self._emit_status(item)

        if item.direction == TransferDirection.DOWNLOAD:
            await self._download(sftp, item)
        else:
            await self._upload(sftp, item)

        if item_id_cancelled(item.id, self._cancel_flags):
            item.status = TransferStatus.CANCELLED
            item.finished_at = time.time()
            self._emit_status(item)
            return

        if item.status == TransferStatus.RUNNING:
            if item.verify_hash and not item.is_directory:
                ok = await self._verify(sftp, item)
                if not ok:
                    item.status = TransferStatus.FAILED
                    item.error_message = "Verificação de hash falhou."
                    item.finished_at = time.time()
                    self._emit_status(item)
                    return
            item.status = TransferStatus.COMPLETED
            item.finished_at = time.time()
            item.transferred_bytes = item.total_bytes or item.transferred_bytes
            self._emit_status(item)
            logger.info(
                sanitize_for_log(
                    "Transferência concluída",
                    direction=item.direction.value,
                    name=item.display_name,
                    bytes=item.total_bytes,
                )
            )

    async def _download(self, sftp: asyncssh.SFTPClient, item: TransferItem) -> None:
        local = Path(item.local_path)
        if item.is_directory:
            local.mkdir(parents=True, exist_ok=True)
            await self._download_dir(sftp, item.remote_path, local, item)
            return

        # conflito
        if local.exists():
            action = await self._resolve_conflict(item, local)
            if action == "skip":
                item.status = TransferStatus.SKIPPED
                item.finished_at = time.time()
                self._emit_status(item)
                return
            if action == "rename":
                local = unique_path(local)
                item.local_path = str(local)

        local.parent.mkdir(parents=True, exist_ok=True)
        try:
            attrs = await sftp.stat(item.remote_path)
            item.total_bytes = int(attrs.size or 0)
        except Exception:  # noqa: BLE001
            item.total_bytes = 0

        # Download via arquivo temporário + rename atômico (evita parcial corrompido)
        tmp = local.parent / f".{local.name}.partial.{os.getpid()}"
        if tmp.is_symlink() or local.is_symlink():
            raise RuntimeError("Recusado: caminho local é symlink")

        offset = 0
        mode = "wb"
        # retomar parcial se existir e for menor que o remoto
        if tmp.exists():
            offset = tmp.stat().st_size
            if 0 < offset < (item.total_bytes or 0):
                mode = "ab"
                item.transferred_bytes = offset
            else:
                offset = 0
                mode = "wb"
                try:
                    tmp.unlink()
                except OSError:
                    pass

        last_t = time.perf_counter()
        last_bytes = item.transferred_bytes
        chunk_size = 64 * 1024
        cancelled = False

        try:
            async with sftp.open(item.remote_path, "rb") as rf:
                if offset:
                    await rf.seek(offset)
                with open(tmp, mode) as lf:
                    try:
                        os.chmod(tmp, 0o600)
                    except OSError:
                        pass
                    while True:
                        await self._wait_if_paused(item.id)
                        if item_id_cancelled(item.id, self._cancel_flags):
                            cancelled = True
                            break
                        data = await rf.read(chunk_size)
                        if not data:
                            break
                        lf.write(data)
                        item.transferred_bytes += len(data)
                        now = time.perf_counter()
                        dt = now - last_t
                        if dt >= 0.25:
                            item.speed_bps = (item.transferred_bytes - last_bytes) / dt
                            last_t = now
                            last_bytes = item.transferred_bytes
                            self._emit_progress(item)
                        if self.speed_limit_bps > 0:
                            await self._throttle(len(data))
            if cancelled:
                # manter .partial para possível retentativa; status cancelado no _process
                return
            # rename atômico para o destino final
            os.replace(str(tmp), str(local))
            try:
                local.chmod(0o600)
            except OSError:
                pass
        except Exception:
            # em erro, manter parcial se houver dados; não sobrescrever destino bom
            raise
        finally:
            if cancelled:
                pass  # deixa partial
            elif tmp.exists() and not local.exists():
                # falha sem rename — limpar partial vazio
                try:
                    if tmp.stat().st_size == 0:
                        tmp.unlink()
                except OSError:
                    pass

        self._emit_progress(item)

    async def _upload(self, sftp: asyncssh.SFTPClient, item: TransferItem) -> None:
        local = Path(item.local_path)
        if not local.exists():
            raise FileNotFoundError(f"Arquivo local não encontrado: {local}")

        if local.is_dir() or item.is_directory:
            item.is_directory = True
            await self._upload_dir(sftp, local, item.remote_path, item)
            return

        item.total_bytes = local.stat().st_size
        # conflito remoto
        try:
            await sftp.stat(item.remote_path)
            exists = True
        except Exception:  # noqa: BLE001
            exists = False

        if exists:
            action = await self._resolve_conflict(item, Path(item.remote_path))
            if action == "skip":
                item.status = TransferStatus.SKIPPED
                item.finished_at = time.time()
                self._emit_status(item)
                return
            if action == "rename":
                item.remote_path = unique_remote_path(item.remote_path)

        # garantir diretório pai
        parent = str(Path(item.remote_path).parent)
        try:
            await sftp.makedirs(parent, exist_ok=True)
        except Exception:  # noqa: BLE001
            pass

        last_t = time.perf_counter()
        last_bytes = 0
        chunk_size = 64 * 1024

        async with sftp.open(item.remote_path, "wb") as rf:
            with open(local, "rb") as lf:
                while True:
                    await self._wait_if_paused(item.id)
                    if item_id_cancelled(item.id, self._cancel_flags):
                        return
                    data = lf.read(chunk_size)
                    if not data:
                        break
                    await rf.write(data)
                    item.transferred_bytes += len(data)
                    now = time.perf_counter()
                    dt = now - last_t
                    if dt >= 0.25:
                        item.speed_bps = (item.transferred_bytes - last_bytes) / dt
                        last_t = now
                        last_bytes = item.transferred_bytes
                        self._emit_progress(item)
                    if self.speed_limit_bps > 0:
                        await self._throttle(len(data))

        self._emit_progress(item)

    async def _download_dir(
        self,
        sftp: asyncssh.SFTPClient,
        remote: str,
        local: Path,
        item: TransferItem,
    ) -> None:
        entries = await sftp.readdir(remote)
        for entry in entries:
            if entry.filename in (".", ".."):
                continue
            if item_id_cancelled(item.id, self._cancel_flags):
                return
            rpath = str(Path(remote) / entry.filename)
            lpath = local / entry.filename
            mode = int(entry.attrs.permissions or 0)
            import stat as statmod

            if statmod.S_ISDIR(mode):
                lpath.mkdir(parents=True, exist_ok=True)
                await self._download_dir(sftp, rpath, lpath, item)
            else:
                sub = TransferItem(
                    server_id=item.server_id,
                    direction=TransferDirection.DOWNLOAD,
                    local_path=str(lpath),
                    remote_path=rpath,
                    conflict_policy=item.conflict_policy,
                    verify_hash=item.verify_hash,
                )
                # reutilizar flags do item pai
                self._pause_flags[sub.id] = self._pause_flags[item.id]
                sub.status = TransferStatus.RUNNING
                sub.started_at = time.time()
                await self._download(sftp, sub)
                item.transferred_bytes += sub.transferred_bytes
                item.total_bytes += sub.total_bytes
                self._emit_progress(item)

    async def _upload_dir(
        self,
        sftp: asyncssh.SFTPClient,
        local: Path,
        remote: str,
        item: TransferItem,
    ) -> None:
        try:
            await sftp.makedirs(remote, exist_ok=True)
        except Exception:  # noqa: BLE001
            try:
                await sftp.mkdir(remote)
            except Exception:  # noqa: BLE001
                pass
        for child in local.iterdir():
            if item_id_cancelled(item.id, self._cancel_flags):
                return
            rpath = str(Path(remote) / child.name)
            if child.is_dir():
                await self._upload_dir(sftp, child, rpath, item)
            else:
                sub = TransferItem(
                    server_id=item.server_id,
                    direction=TransferDirection.UPLOAD,
                    local_path=str(child),
                    remote_path=rpath,
                    conflict_policy=item.conflict_policy,
                    verify_hash=item.verify_hash,
                )
                self._pause_flags[sub.id] = self._pause_flags[item.id]
                sub.status = TransferStatus.RUNNING
                sub.started_at = time.time()
                await self._upload(sftp, sub)
                item.transferred_bytes += sub.transferred_bytes
                item.total_bytes += sub.total_bytes
                self._emit_progress(item)

    async def _resolve_conflict(self, item: TransferItem, path: Path) -> str:
        policy = item.conflict_policy
        if policy == ConflictPolicy.OVERWRITE:
            return "overwrite"
        if policy == ConflictPolicy.SKIP:
            return "skip"
        if policy == ConflictPolicy.RENAME:
            return "rename"
        # ASK — por padrão sobrescrever se não houver UI; UI deve definir policy antes
        return "overwrite"

    async def _verify(self, sftp: asyncssh.SFTPClient, item: TransferItem) -> bool:
        """Compara SHA-256 local vs remoto."""
        local_hash = sha256_file(Path(item.local_path))
        h = hashlib.sha256()
        async with sftp.open(item.remote_path, "rb") as rf:
            while True:
                data = await rf.read(1024 * 1024)
                if not data:
                    break
                h.update(data)
        return local_hash == h.hexdigest()

    async def _wait_if_paused(self, item_id: str) -> None:
        flag = self._pause_flags.get(item_id)
        if flag:
            await flag.wait()

    async def _throttle(self, nbytes: int) -> None:
        if self.speed_limit_bps <= 0:
            return
        # delay proporcional
        delay = nbytes / float(self.speed_limit_bps)
        if delay > 0:
            await asyncio.sleep(delay)

    def _emit_progress(self, item: TransferItem) -> None:
        if self.on_progress:
            try:
                self.on_progress(item)
            except Exception:  # noqa: BLE001
                pass

    def _emit_status(self, item: TransferItem) -> None:
        if self.on_status:
            try:
                self.on_status(item)
            except Exception:  # noqa: BLE001
                pass

    @property
    def total_progress(self) -> tuple[int, int]:
        """(transferred, total) de todos os itens ativos/completos."""
        transferred = sum(i.transferred_bytes for i in self._items.values())
        total = sum(i.total_bytes for i in self._items.values())
        return transferred, total


def item_id_cancelled(item_id: str, flags: set[str]) -> bool:
    return item_id in flags


def unique_path(path: Path) -> Path:
    if not path.exists():
        return path
    stem, suffix = path.stem, path.suffix
    parent = path.parent
    n = 1
    while True:
        candidate = parent / f"{stem} ({n}){suffix}"
        if not candidate.exists():
            return candidate
        n += 1


def unique_remote_path(path: str) -> str:
    p = Path(path)
    stem, suffix = p.stem, p.suffix
    parent = p.parent
    n = 1
    return str(parent / f"{stem} ({n}){suffix}")


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()
