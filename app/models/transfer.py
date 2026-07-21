"""Modelos de transferência SFTP."""

from __future__ import annotations

import time
import uuid
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any, Optional


class TransferDirection(str, Enum):
    UPLOAD = "upload"
    DOWNLOAD = "download"

    @property
    def label_pt(self) -> str:
        return {
            TransferDirection.UPLOAD: "Upload",
            TransferDirection.DOWNLOAD: "Download",
        }[self]


class TransferStatus(str, Enum):
    QUEUED = "queued"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"
    SKIPPED = "skipped"

    @property
    def label_pt(self) -> str:
        return {
            TransferStatus.QUEUED: "Na fila",
            TransferStatus.RUNNING: "Em andamento",
            TransferStatus.PAUSED: "Pausado",
            TransferStatus.COMPLETED: "Concluído",
            TransferStatus.FAILED: "Falhou",
            TransferStatus.CANCELLED: "Cancelado",
            TransferStatus.SKIPPED: "Ignorado",
        }[self]


class ConflictPolicy(str, Enum):
    OVERWRITE = "overwrite"
    SKIP = "skip"
    RENAME = "rename"
    ASK = "ask"

    @property
    def label_pt(self) -> str:
        return {
            ConflictPolicy.OVERWRITE: "Sobrescrever",
            ConflictPolicy.SKIP: "Ignorar",
            ConflictPolicy.RENAME: "Renomear automaticamente",
            ConflictPolicy.ASK: "Perguntar",
        }[self]


@dataclass
class TransferItem:
    id: str = field(default_factory=lambda: str(uuid.uuid4()))
    server_id: Optional[int] = None
    direction: TransferDirection = TransferDirection.DOWNLOAD
    local_path: str = ""
    remote_path: str = ""
    status: TransferStatus = TransferStatus.QUEUED
    total_bytes: int = 0
    transferred_bytes: int = 0
    speed_bps: float = 0.0
    started_at: Optional[float] = None
    finished_at: Optional[float] = None
    error_message: str = ""
    conflict_policy: ConflictPolicy = ConflictPolicy.ASK
    verify_hash: bool = False
    is_directory: bool = False

    @property
    def progress(self) -> float:
        if self.total_bytes <= 0:
            return 0.0
        return min(100.0, (self.transferred_bytes / self.total_bytes) * 100.0)

    @property
    def elapsed_seconds(self) -> float:
        if self.started_at is None:
            return 0.0
        end = self.finished_at if self.finished_at else time.time()
        return max(0.0, end - self.started_at)

    @property
    def eta_seconds(self) -> Optional[float]:
        if self.speed_bps <= 0 or self.total_bytes <= 0:
            return None
        remaining = self.total_bytes - self.transferred_bytes
        if remaining <= 0:
            return 0.0
        return remaining / self.speed_bps

    @property
    def display_name(self) -> str:
        if self.direction == TransferDirection.DOWNLOAD:
            return Path(self.remote_path).name or self.remote_path
        return Path(self.local_path).name or self.local_path

    def to_history_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "server_id": self.server_id,
            "direction": self.direction.value,
            "local_path": self.local_path,
            "remote_path": self.remote_path,
            "status": self.status.value,
            "total_bytes": self.total_bytes,
            "transferred_bytes": self.transferred_bytes,
            "error_message": self.error_message,
            "is_directory": self.is_directory,
        }
