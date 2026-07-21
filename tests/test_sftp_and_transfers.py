"""Testes SFTP (mocks) e fila de transferências."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock

import pytest

from app.models.transfer import (
    ConflictPolicy,
    TransferDirection,
    TransferItem,
    TransferStatus,
)
from app.sftp.client import RemoteFileInfo, format_size, mode_to_str
from app.transfers.queue import TransferQueue, unique_path, sha256_file
import stat as statmod


def test_format_size():
    assert format_size(500) == "500 B"
    assert "KB" in format_size(2048)


def test_mode_to_str():
    mode = statmod.S_IFREG | 0o644
    s = mode_to_str(mode)
    assert s.startswith("-")
    assert "rw" in s


def test_unique_path(tmp_path):
    f = tmp_path / "file.txt"
    f.write_text("a")
    u = unique_path(f)
    assert u != f
    assert "file" in u.name


def test_sha256_file(tmp_path):
    f = tmp_path / "x.bin"
    f.write_bytes(b"hello")
    h = sha256_file(f)
    assert len(h) == 64


@pytest.mark.asyncio
async def test_transfer_queue_download(tmp_path):
    remote_data = b"hello world transfer"
    local_file = tmp_path / "out.bin"

    # mock SFTP
    mock_file = AsyncMock()
    mock_file.read = AsyncMock(side_effect=[remote_data, b""])
    mock_file.seek = AsyncMock()
    mock_file.__aenter__ = AsyncMock(return_value=mock_file)
    mock_file.__aexit__ = AsyncMock(return_value=None)

    sftp = AsyncMock()
    attrs = MagicMock()
    attrs.size = len(remote_data)
    sftp.stat = AsyncMock(return_value=attrs)
    sftp.open = MagicMock(return_value=mock_file)

    async def get_sftp(sid):
        return sftp

    statuses: list[TransferStatus] = []
    queue = TransferQueue(
        max_concurrent=1,
        get_sftp=get_sftp,
        on_status=lambda i: statuses.append(i.status),
    )
    queue.start()
    item = TransferItem(
        server_id=1,
        direction=TransferDirection.DOWNLOAD,
        local_path=str(local_file),
        remote_path="/remote/file.bin",
        conflict_policy=ConflictPolicy.OVERWRITE,
    )
    await queue.enqueue(item)
    # wait for completion
    for _ in range(50):
        if item.status in (
            TransferStatus.COMPLETED,
            TransferStatus.FAILED,
            TransferStatus.CANCELLED,
        ):
            break
        await asyncio.sleep(0.05)
    await queue.stop()
    assert item.status == TransferStatus.COMPLETED
    assert local_file.read_bytes() == remote_data


@pytest.mark.asyncio
async def test_transfer_cancel(tmp_path):
    queue = TransferQueue(max_concurrent=1, get_sftp=AsyncMock(return_value=None))
    queue.start()
    item = TransferItem(
        server_id=1,
        direction=TransferDirection.DOWNLOAD,
        local_path=str(tmp_path / "x"),
        remote_path="/r",
    )
    await queue.enqueue(item)
    queue.cancel(item.id)
    await asyncio.sleep(0.1)
    await queue.stop()
    assert item.status in (TransferStatus.CANCELLED, TransferStatus.FAILED)


def test_remote_file_info():
    info = RemoteFileInfo(
        name="test.py",
        path="/tmp/test.py",
        size=100,
        is_dir=False,
        is_link=False,
        permissions="-rw-r--r--",
        mode=0o100644,
        owner="1000",
        group="1000",
        mtime=None,
        extension="py",
    )
    assert info.type_label == "PY"
    assert "B" in info.size_str or info.size_str
