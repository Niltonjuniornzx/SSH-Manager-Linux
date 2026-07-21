"""Acesso SQLite com migrations e repositórios."""

from __future__ import annotations

import json
import sqlite3
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Generator, Optional

from app.database.migrations import MIGRATIONS
from app.models.remote import RemoteProfile
from app.models.server import ServerGroup, ServerProfile
from app.models.settings import AppSettings
from app.models.transfer import TransferItem
from app.models.tunnel import TunnelProfile
from app.utils.enums import enum_value
from app.utils.paths import database_path, ensure_secure_file


def _utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")


def _row_to_dict(row: sqlite3.Row) -> dict[str, Any]:
    return {k: row[k] for k in row.keys()}


class Database:
    """Gerenciador SQLite thread-safe (uma conexão por thread)."""

    def __init__(self, path: Optional[Path] = None) -> None:
        self.path = Path(path) if path else database_path()
        ensure_secure_file(self.path)
        self._local = threading.local()
        self._lock = threading.RLock()
        self._init_db()

    def _connect(self) -> sqlite3.Connection:
        conn = getattr(self._local, "conn", None)
        if conn is None:
            conn = sqlite3.connect(str(self.path), check_same_thread=False)
            conn.row_factory = sqlite3.Row
            conn.execute("PRAGMA foreign_keys = ON")
            conn.execute("PRAGMA journal_mode = WAL")
            self._local.conn = conn
        return conn

    @contextmanager
    def cursor(self) -> Generator[sqlite3.Cursor, None, None]:
        with self._lock:
            conn = self._connect()
            cur = conn.cursor()
            try:
                yield cur
                conn.commit()
            except Exception:
                conn.rollback()
                raise

    def _init_db(self) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                CREATE TABLE IF NOT EXISTS schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL DEFAULT (datetime('now'))
                )
                """
            )
            cur.execute("SELECT COALESCE(MAX(version), 0) FROM schema_version")
            current = int(cur.fetchone()[0])
            for version, _desc, sql in MIGRATIONS:
                if version > current:
                    cur.executescript(sql)
                    cur.execute(
                        "INSERT INTO schema_version (version) VALUES (?)",
                        (version,),
                    )

    def close(self) -> None:
        conn = getattr(self._local, "conn", None)
        if conn is not None:
            conn.close()
            self._local.conn = None

    # ── Groups ──────────────────────────────────────────────

    def list_groups(self) -> list[ServerGroup]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM server_groups ORDER BY sort_order, name")
            return [ServerGroup.from_row(_row_to_dict(r)) for r in cur.fetchall()]

    def get_group(self, group_id: int) -> Optional[ServerGroup]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM server_groups WHERE id = ?", (group_id,))
            row = cur.fetchone()
            return ServerGroup.from_row(_row_to_dict(row)) if row else None

    def save_group(self, group: ServerGroup) -> ServerGroup:
        with self.cursor() as cur:
            if group.id is None:
                cur.execute(
                    "INSERT INTO server_groups (name, color, sort_order) VALUES (?, ?, ?)",
                    (group.name, group.color, group.sort_order),
                )
                group.id = cur.lastrowid
            else:
                cur.execute(
                    "UPDATE server_groups SET name=?, color=?, sort_order=? WHERE id=?",
                    (group.name, group.color, group.sort_order, group.id),
                )
        return group

    def delete_group(self, group_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE servers SET group_id = NULL WHERE group_id = ?", (group_id,)
            )
            cur.execute("DELETE FROM server_groups WHERE id = ?", (group_id,))

    # ── Servers ─────────────────────────────────────────────

    def list_servers(self, search: str = "") -> list[ServerProfile]:
        with self.cursor() as cur:
            if search:
                like = f"%{search}%"
                cur.execute(
                    """
                    SELECT s.*, g.name AS group_name
                    FROM servers s
                    LEFT JOIN server_groups g ON g.id = s.group_id
                    WHERE s.name LIKE ? OR s.host LIKE ? OR s.username LIKE ?
                          OR s.description LIKE ? OR g.name LIKE ?
                    ORDER BY g.sort_order, s.name
                    """,
                    (like, like, like, like, like),
                )
            else:
                cur.execute(
                    """
                    SELECT s.*, g.name AS group_name
                    FROM servers s
                    LEFT JOIN server_groups g ON g.id = s.group_id
                    ORDER BY g.sort_order, s.name
                    """
                )
            return [ServerProfile.from_row(_row_to_dict(r)) for r in cur.fetchall()]

    def get_server(self, server_id: int) -> Optional[ServerProfile]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT s.*, g.name AS group_name
                FROM servers s
                LEFT JOIN server_groups g ON g.id = s.group_id
                WHERE s.id = ?
                """,
                (server_id,),
            )
            row = cur.fetchone()
            return ServerProfile.from_row(_row_to_dict(row)) if row else None

    def save_server(self, server: ServerProfile) -> ServerProfile:
        now = _utc_now()
        with self.cursor() as cur:
            if server.id is None:
                server.created_at = now
                server.updated_at = now
                if not server.credential_key:
                    # Será atualizado após insert com o id
                    pass
                cur.execute(
                    """
                    INSERT INTO servers (
                        name, group_id, description, host, port, username,
                        auth_method, private_key_path, credential_key,
                        remote_path, local_path, timeout, keepalive,
                        terminal_encoding, color, auto_reconnect, jump_host_id,
                        remember_credential, last_connected_at, last_latency_ms,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        server.name,
                        server.group_id,
                        server.description,
                        server.host,
                        server.port,
                        server.username,
                        enum_value(server.auth_method),
                        server.private_key_path,
                        server.credential_key,
                        server.remote_path,
                        server.local_path,
                        server.timeout,
                        server.keepalive,
                        server.terminal_encoding,
                        server.color,
                        int(server.auto_reconnect),
                        server.jump_host_id,
                        int(server.remember_credential),
                        server.last_connected_at,
                        server.last_latency_ms,
                        server.created_at,
                        server.updated_at,
                    ),
                )
                server.id = cur.lastrowid
                if not server.credential_key:
                    server.credential_key = f"server-{server.id}"
                    cur.execute(
                        "UPDATE servers SET credential_key = ? WHERE id = ?",
                        (server.credential_key, server.id),
                    )
            else:
                server.updated_at = now
                if not server.credential_key:
                    server.credential_key = f"server-{server.id}"
                cur.execute(
                    """
                    UPDATE servers SET
                        name=?, group_id=?, description=?, host=?, port=?, username=?,
                        auth_method=?, private_key_path=?, credential_key=?,
                        remote_path=?, local_path=?, timeout=?, keepalive=?,
                        terminal_encoding=?, color=?, auto_reconnect=?, jump_host_id=?,
                        remember_credential=?, last_connected_at=?, last_latency_ms=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        server.name,
                        server.group_id,
                        server.description,
                        server.host,
                        server.port,
                        server.username,
                        enum_value(server.auth_method),
                        server.private_key_path,
                        server.credential_key,
                        server.remote_path,
                        server.local_path,
                        server.timeout,
                        server.keepalive,
                        server.terminal_encoding,
                        server.color,
                        int(server.auto_reconnect),
                        server.jump_host_id,
                        int(server.remember_credential),
                        server.last_connected_at,
                        server.last_latency_ms,
                        server.updated_at,
                        server.id,
                    ),
                )
        return server

    def delete_server(self, server_id: int) -> None:
        with self.cursor() as cur:
            cur.execute(
                "UPDATE servers SET jump_host_id = NULL WHERE jump_host_id = ?",
                (server_id,),
            )
            cur.execute("DELETE FROM servers WHERE id = ?", (server_id,))

    def update_server_connection_meta(
        self,
        server_id: int,
        *,
        last_connected_at: Optional[str] = None,
        last_latency_ms: Optional[float] = None,
    ) -> None:
        with self.cursor() as cur:
            if last_connected_at is not None and last_latency_ms is not None:
                cur.execute(
                    "UPDATE servers SET last_connected_at=?, last_latency_ms=? WHERE id=?",
                    (last_connected_at, last_latency_ms, server_id),
                )
            elif last_connected_at is not None:
                cur.execute(
                    "UPDATE servers SET last_connected_at=? WHERE id=?",
                    (last_connected_at, server_id),
                )
            elif last_latency_ms is not None:
                cur.execute(
                    "UPDATE servers SET last_latency_ms=? WHERE id=?",
                    (last_latency_ms, server_id),
                )

    def detect_jump_loop(self, server_id: int, jump_host_id: Optional[int]) -> bool:
        """Detecta ciclo em cadeia de jump hosts."""
        if jump_host_id is None:
            return False
        if jump_host_id == server_id:
            return True
        visited: set[int] = {server_id}
        current: Optional[int] = jump_host_id
        while current is not None:
            if current in visited:
                return True
            visited.add(current)
            srv = self.get_server(current)
            if srv is None:
                break
            current = srv.jump_host_id
        return False

    # ── Tunnels ─────────────────────────────────────────────

    def list_tunnels(self, server_id: Optional[int] = None) -> list[TunnelProfile]:
        with self.cursor() as cur:
            if server_id is not None:
                cur.execute(
                    "SELECT * FROM tunnels WHERE server_id = ? ORDER BY name",
                    (server_id,),
                )
            else:
                cur.execute("SELECT * FROM tunnels ORDER BY name")
            return [TunnelProfile.from_row(_row_to_dict(r)) for r in cur.fetchall()]

    def get_tunnel(self, tunnel_id: int) -> Optional[TunnelProfile]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM tunnels WHERE id = ?", (tunnel_id,))
            row = cur.fetchone()
            return TunnelProfile.from_row(_row_to_dict(row)) if row else None

    def save_tunnel(self, tunnel: TunnelProfile) -> TunnelProfile:
        now = _utc_now()
        with self.cursor() as cur:
            if tunnel.id is None:
                tunnel.created_at = now
                tunnel.updated_at = now
                cur.execute(
                    """
                    INSERT INTO tunnels (
                        server_id, name, tunnel_type, listen_address, listen_port,
                        dest_host, dest_port, auto_start, auto_reconnect, local_only,
                        created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        tunnel.server_id,
                        tunnel.name,
                        enum_value(tunnel.tunnel_type),
                        tunnel.listen_address,
                        tunnel.listen_port,
                        tunnel.dest_host,
                        tunnel.dest_port,
                        int(tunnel.auto_start),
                        int(tunnel.auto_reconnect),
                        int(tunnel.local_only),
                        tunnel.created_at,
                        tunnel.updated_at,
                    ),
                )
                tunnel.id = cur.lastrowid
            else:
                tunnel.updated_at = now
                cur.execute(
                    """
                    UPDATE tunnels SET
                        server_id=?, name=?, tunnel_type=?, listen_address=?,
                        listen_port=?, dest_host=?, dest_port=?, auto_start=?,
                        auto_reconnect=?, local_only=?, updated_at=?
                    WHERE id=?
                    """,
                    (
                        tunnel.server_id,
                        tunnel.name,
                        enum_value(tunnel.tunnel_type),
                        tunnel.listen_address,
                        tunnel.listen_port,
                        tunnel.dest_host,
                        tunnel.dest_port,
                        int(tunnel.auto_start),
                        int(tunnel.auto_reconnect),
                        int(tunnel.local_only),
                        tunnel.updated_at,
                        tunnel.id,
                    ),
                )
        return tunnel

    def delete_tunnel(self, tunnel_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM tunnels WHERE id = ?", (tunnel_id,))

    def find_tunnels_by_listen_port(
        self, port: int, exclude_id: Optional[int] = None
    ) -> list[TunnelProfile]:
        with self.cursor() as cur:
            if exclude_id is not None:
                cur.execute(
                    "SELECT * FROM tunnels WHERE listen_port = ? AND id != ?",
                    (port, exclude_id),
                )
            else:
                cur.execute("SELECT * FROM tunnels WHERE listen_port = ?", (port,))
            return [TunnelProfile.from_row(_row_to_dict(r)) for r in cur.fetchall()]

    # ── Remote profiles ─────────────────────────────────────

    def get_remote_profile(self, server_id: int) -> Optional[RemoteProfile]:
        with self.cursor() as cur:
            cur.execute(
                "SELECT * FROM remote_profiles WHERE server_id = ?", (server_id,)
            )
            row = cur.fetchone()
            return RemoteProfile.from_row(_row_to_dict(row)) if row else None

    def save_remote_profile(self, profile: RemoteProfile) -> RemoteProfile:
        now = _utc_now()
        existing = (
            self.get_remote_profile(profile.server_id)
            if profile.server_id
            else None
        )
        with self.cursor() as cur:
            if existing is None or profile.id is None:
                profile.created_at = now
                profile.updated_at = now
                if not profile.credential_key and profile.server_id:
                    profile.credential_key = f"remote-{profile.server_id}"
                cur.execute(
                    """
                    INSERT INTO remote_profiles (
                        server_id, enabled, protocol, host, use_ssh_host, port,
                        username, domain, rustdesk_id, resolution, fullscreen,
                        auto_scale, quality, color_depth, audio, microphone,
                        clipboard, share_folder, view_only, auto_reconnect,
                        protect_with_tunnel, custom_executable, custom_args,
                        credential_key, created_at, updated_at
                    ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    ON CONFLICT(server_id) DO UPDATE SET
                        enabled=excluded.enabled, protocol=excluded.protocol,
                        host=excluded.host, use_ssh_host=excluded.use_ssh_host,
                        port=excluded.port, username=excluded.username,
                        domain=excluded.domain, rustdesk_id=excluded.rustdesk_id,
                        resolution=excluded.resolution, fullscreen=excluded.fullscreen,
                        auto_scale=excluded.auto_scale, quality=excluded.quality,
                        color_depth=excluded.color_depth, audio=excluded.audio,
                        microphone=excluded.microphone, clipboard=excluded.clipboard,
                        share_folder=excluded.share_folder, view_only=excluded.view_only,
                        auto_reconnect=excluded.auto_reconnect,
                        protect_with_tunnel=excluded.protect_with_tunnel,
                        custom_executable=excluded.custom_executable,
                        custom_args=excluded.custom_args,
                        credential_key=excluded.credential_key,
                        updated_at=excluded.updated_at
                    """,
                    (
                        profile.server_id,
                        int(profile.enabled),
                        enum_value(profile.protocol),
                        profile.host,
                        int(profile.use_ssh_host),
                        profile.port,
                        profile.username,
                        profile.domain,
                        profile.rustdesk_id,
                        profile.resolution,
                        int(profile.fullscreen),
                        int(profile.auto_scale),
                        profile.quality,
                        profile.color_depth,
                        int(profile.audio),
                        int(profile.microphone),
                        int(profile.clipboard),
                        profile.share_folder,
                        int(profile.view_only),
                        int(profile.auto_reconnect),
                        int(profile.protect_with_tunnel),
                        profile.custom_executable,
                        profile.custom_args,
                        profile.credential_key,
                        profile.created_at,
                        profile.updated_at,
                    ),
                )
                if profile.id is None:
                    # recarregar id
                    if profile.server_id:
                        saved = self.get_remote_profile(profile.server_id)
                        if saved:
                            profile.id = saved.id
            else:
                profile.updated_at = now
                cur.execute(
                    """
                    UPDATE remote_profiles SET
                        enabled=?, protocol=?, host=?, use_ssh_host=?, port=?,
                        username=?, domain=?, rustdesk_id=?, resolution=?,
                        fullscreen=?, auto_scale=?, quality=?, color_depth=?,
                        audio=?, microphone=?, clipboard=?, share_folder=?,
                        view_only=?, auto_reconnect=?, protect_with_tunnel=?,
                        custom_executable=?, custom_args=?, credential_key=?,
                        updated_at=?
                    WHERE id=?
                    """,
                    (
                        int(profile.enabled),
                        enum_value(profile.protocol),
                        profile.host,
                        int(profile.use_ssh_host),
                        profile.port,
                        profile.username,
                        profile.domain,
                        profile.rustdesk_id,
                        profile.resolution,
                        int(profile.fullscreen),
                        int(profile.auto_scale),
                        profile.quality,
                        profile.color_depth,
                        int(profile.audio),
                        int(profile.microphone),
                        int(profile.clipboard),
                        profile.share_folder,
                        int(profile.view_only),
                        int(profile.auto_reconnect),
                        int(profile.protect_with_tunnel),
                        profile.custom_executable,
                        profile.custom_args,
                        profile.credential_key,
                        profile.updated_at,
                        profile.id,
                    ),
                )
        return profile

    # ── Settings ────────────────────────────────────────────

    def get_settings(self) -> AppSettings:
        with self.cursor() as cur:
            cur.execute("SELECT key, value FROM settings")
            raw: dict[str, Any] = {}
            for row in cur.fetchall():
                key, value = row["key"], row["value"]
                try:
                    raw[key] = json.loads(value)
                except (json.JSONDecodeError, TypeError):
                    raw[key] = value
        return AppSettings.from_dict(raw)

    def save_settings(self, settings: AppSettings) -> None:
        data = settings.to_dict()
        with self.cursor() as cur:
            for key, value in data.items():
                cur.execute(
                    """
                    INSERT INTO settings (key, value) VALUES (?, ?)
                    ON CONFLICT(key) DO UPDATE SET value = excluded.value
                    """,
                    (key, json.dumps(value)),
                )

    def get_setting(self, key: str, default: Any = None) -> Any:
        with self.cursor() as cur:
            cur.execute("SELECT value FROM settings WHERE key = ?", (key,))
            row = cur.fetchone()
            if row is None:
                return default
            try:
                return json.loads(row["value"])
            except (json.JSONDecodeError, TypeError):
                return row["value"]

    def set_setting(self, key: str, value: Any) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO settings (key, value) VALUES (?, ?)
                ON CONFLICT(key) DO UPDATE SET value = excluded.value
                """,
                (key, json.dumps(value)),
            )

    # ── Trusted hosts ───────────────────────────────────────

    def get_trusted_host(
        self, hostname: str, port: int, key_type: str
    ) -> Optional[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM trusted_hosts
                WHERE hostname = ? AND port = ? AND key_type = ?
                """,
                (hostname, port, key_type),
            )
            row = cur.fetchone()
            return _row_to_dict(row) if row else None

    def trust_host(
        self,
        hostname: str,
        port: int,
        key_type: str,
        fingerprint_sha256: str,
        public_key: str,
    ) -> None:
        now = _utc_now()
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO trusted_hosts
                    (hostname, port, key_type, fingerprint_sha256, public_key,
                     first_seen, last_seen)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(hostname, port, key_type) DO UPDATE SET
                    fingerprint_sha256 = excluded.fingerprint_sha256,
                    public_key = excluded.public_key,
                    last_seen = excluded.last_seen
                """,
                (hostname, port, key_type, fingerprint_sha256, public_key, now, now),
            )

    def list_trusted_hosts(self) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute("SELECT * FROM trusted_hosts ORDER BY hostname")
            return [_row_to_dict(r) for r in cur.fetchall()]

    def delete_trusted_host(self, host_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM trusted_hosts WHERE id = ?", (host_id,))

    # ── Transfer history ────────────────────────────────────

    def add_transfer_history(self, item: TransferItem) -> None:
        d = item.to_history_dict()
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT OR REPLACE INTO transfer_history
                    (id, server_id, direction, local_path, remote_path, status,
                     total_bytes, transferred_bytes, error_message, is_directory)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    d["id"],
                    d["server_id"],
                    d["direction"],
                    d["local_path"],
                    d["remote_path"],
                    d["status"],
                    d["total_bytes"],
                    d["transferred_bytes"],
                    d["error_message"],
                    int(d["is_directory"]),
                ),
            )

    def list_transfer_history(self, limit: int = 100) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            cur.execute(
                """
                SELECT * FROM transfer_history
                ORDER BY created_at DESC LIMIT ?
                """,
                (limit,),
            )
            return [_row_to_dict(r) for r in cur.fetchall()]

    # ── Favorites ───────────────────────────────────────────

    def list_favorites(self, server_id: Optional[int] = None) -> list[dict[str, Any]]:
        with self.cursor() as cur:
            if server_id is not None:
                cur.execute(
                    "SELECT * FROM favorites WHERE server_id = ? OR server_id IS NULL ORDER BY label",
                    (server_id,),
                )
            else:
                cur.execute("SELECT * FROM favorites ORDER BY label")
            return [_row_to_dict(r) for r in cur.fetchall()]

    def add_favorite(
        self,
        path: str,
        *,
        server_id: Optional[int] = None,
        is_remote: bool = True,
        label: str = "",
    ) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO favorites (server_id, path, is_remote, label)
                VALUES (?, ?, ?, ?)
                """,
                (server_id, path, int(is_remote), label or path),
            )

    def delete_favorite(self, fav_id: int) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM favorites WHERE id = ?", (fav_id,))

    # ── Logs ────────────────────────────────────────────────

    def add_log(
        self,
        level: str,
        message: str,
        *,
        category: str = "app",
        server_id: Optional[int] = None,
        details: str = "",
    ) -> None:
        with self.cursor() as cur:
            cur.execute(
                """
                INSERT INTO app_logs (level, category, message, server_id, details)
                VALUES (?, ?, ?, ?, ?)
                """,
                (level, category, message, server_id, details),
            )

    def list_logs(
        self,
        *,
        search: str = "",
        level: str = "",
        category: str = "",
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        clauses: list[str] = []
        params: list[Any] = []
        if search:
            clauses.append("(message LIKE ? OR details LIKE ?)")
            like = f"%{search}%"
            params.extend([like, like])
        if level:
            clauses.append("level = ?")
            params.append(level)
        if category:
            clauses.append("category = ?")
            params.append(category)
        where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
        params.append(limit)
        with self.cursor() as cur:
            cur.execute(
                f"SELECT * FROM app_logs {where} ORDER BY id DESC LIMIT ?",
                params,
            )
            return [_row_to_dict(r) for r in cur.fetchall()]

    def clear_logs(self) -> None:
        with self.cursor() as cur:
            cur.execute("DELETE FROM app_logs")

    # ── Export / Import ─────────────────────────────────────

    def export_config(self, *, include_key_paths: bool = False) -> dict[str, Any]:
        """Exporta configuração sem credenciais."""
        servers = []
        for s in self.list_servers():
            d = s.to_dict(for_export=True)
            if not include_key_paths:
                d["private_key_path"] = ""
            servers.append(d)
        return {
            "version": 1,
            "exported_at": _utc_now(),
            "includes_credentials": False,
            "includes_private_keys": False,
            "groups": [g.to_dict() for g in self.list_groups()],
            "servers": servers,
            "tunnels": [t.to_dict() for t in self.list_tunnels()],
            "remote_profiles": [
                (self.get_remote_profile(s.id).to_dict(for_export=True)
                 if s.id and self.get_remote_profile(s.id)
                 else None)
                for s in self.list_servers()
                if s.id
            ],
            "settings": self.get_settings().to_dict(),
            "favorites": self.list_favorites(),
        }

    def import_config(
        self, data: dict[str, Any], *, skip_duplicates: bool = True
    ) -> dict[str, int]:
        """Importa configuração. Retorna contadores."""
        stats = {"groups": 0, "servers": 0, "tunnels": 0, "skipped": 0}
        group_map: dict[int, int] = {}  # old_id -> new_id
        server_map: dict[int, int] = {}

        existing_names = {s.name for s in self.list_servers()}

        for gdata in data.get("groups") or []:
            old_id = gdata.get("id")
            existing = next(
                (g for g in self.list_groups() if g.name == gdata.get("name")),
                None,
            )
            if existing:
                if old_id is not None:
                    group_map[old_id] = existing.id  # type: ignore[assignment]
                continue
            group = ServerGroup(
                name=gdata.get("name") or "Importado",
                color=gdata.get("color") or "#4a9eff",
                sort_order=int(gdata.get("sort_order") or 0),
            )
            self.save_group(group)
            if old_id is not None and group.id is not None:
                group_map[old_id] = group.id
            stats["groups"] += 1

        for sdata in data.get("servers") or []:
            name = sdata.get("name") or ""
            if skip_duplicates and name in existing_names:
                stats["skipped"] += 1
                continue
            old_id = sdata.get("id")
            old_gid = sdata.get("group_id")
            new_gid = group_map.get(old_gid) if old_gid else None
            from app.models.server import AuthMethod

            try:
                auth = AuthMethod(sdata.get("auth_method") or "password")
            except ValueError:
                auth = AuthMethod.PASSWORD
            server = ServerProfile(
                name=name,
                group_id=new_gid,
                description=sdata.get("description") or "",
                host=sdata.get("host") or "",
                port=int(sdata.get("port") or 22),
                username=sdata.get("username") or "",
                auth_method=auth,
                private_key_path=sdata.get("private_key_path") or "",
                remote_path=sdata.get("remote_path") or "~",
                local_path=sdata.get("local_path") or "",
                timeout=int(sdata.get("timeout") or 30),
                keepalive=int(sdata.get("keepalive") or 30),
                terminal_encoding=sdata.get("terminal_encoding") or "utf-8",
                color=sdata.get("color") or "#4a9eff",
                auto_reconnect=bool(sdata.get("auto_reconnect")),
                remember_credential=bool(sdata.get("remember_credential", True)),
            )
            self.save_server(server)
            if old_id is not None and server.id is not None:
                server_map[old_id] = server.id
            existing_names.add(name)
            stats["servers"] += 1

        for tdata in data.get("tunnels") or []:
            old_sid = tdata.get("server_id")
            new_sid = server_map.get(old_sid) if old_sid else None
            if new_sid is None:
                continue
            from app.models.tunnel import TunnelType

            try:
                ttype = TunnelType(tdata.get("tunnel_type") or "local")
            except ValueError:
                ttype = TunnelType.LOCAL
            tunnel = TunnelProfile(
                server_id=new_sid,
                name=tdata.get("name") or "Túnel",
                tunnel_type=ttype,
                listen_address=tdata.get("listen_address") or "127.0.0.1",
                listen_port=int(tdata.get("listen_port") or 0),
                dest_host=tdata.get("dest_host") or "127.0.0.1",
                dest_port=int(tdata.get("dest_port") or 0),
                auto_start=bool(tdata.get("auto_start")),
                auto_reconnect=bool(tdata.get("auto_reconnect", True)),
                local_only=bool(tdata.get("local_only", True)),
            )
            self.save_tunnel(tunnel)
            stats["tunnels"] += 1

        if "settings" in data and isinstance(data["settings"], dict):
            settings = AppSettings.from_dict(data["settings"])
            self.save_settings(settings)

        return stats


_db_instance: Optional[Database] = None
_db_lock = threading.Lock()


def get_database(path: Optional[Path] = None) -> Database:
    global _db_instance
    with _db_lock:
        if _db_instance is None or path is not None:
            _db_instance = Database(path)
        return _db_instance


def reset_database_singleton() -> None:
    """Usado em testes."""
    global _db_instance
    with _db_lock:
        if _db_instance is not None:
            _db_instance.close()
        _db_instance = None
