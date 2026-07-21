"""Migrations SQL versionadas."""

from __future__ import annotations

# Cada migration: (version, description, sql)
MIGRATIONS: list[tuple[int, str, str]] = [
    (
        1,
        "schema inicial",
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS server_groups (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL UNIQUE,
            color TEXT NOT NULL DEFAULT '#4a9eff',
            sort_order INTEGER NOT NULL DEFAULT 0
        );

        CREATE TABLE IF NOT EXISTS servers (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL,
            group_id INTEGER REFERENCES server_groups(id) ON DELETE SET NULL,
            description TEXT DEFAULT '',
            host TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 22,
            username TEXT NOT NULL,
            auth_method TEXT NOT NULL DEFAULT 'password',
            private_key_path TEXT DEFAULT '',
            credential_key TEXT DEFAULT '',
            remote_path TEXT DEFAULT '~',
            local_path TEXT DEFAULT '',
            timeout INTEGER NOT NULL DEFAULT 30,
            keepalive INTEGER NOT NULL DEFAULT 30,
            terminal_encoding TEXT DEFAULT 'utf-8',
            color TEXT DEFAULT '#4a9eff',
            auto_reconnect INTEGER NOT NULL DEFAULT 0,
            jump_host_id INTEGER REFERENCES servers(id) ON DELETE SET NULL,
            remember_credential INTEGER NOT NULL DEFAULT 1,
            last_connected_at TEXT,
            last_latency_ms REAL,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS tunnels (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            name TEXT NOT NULL,
            tunnel_type TEXT NOT NULL DEFAULT 'local',
            listen_address TEXT NOT NULL DEFAULT '127.0.0.1',
            listen_port INTEGER NOT NULL DEFAULT 0,
            dest_host TEXT DEFAULT '127.0.0.1',
            dest_port INTEGER DEFAULT 0,
            auto_start INTEGER NOT NULL DEFAULT 0,
            auto_reconnect INTEGER NOT NULL DEFAULT 1,
            local_only INTEGER NOT NULL DEFAULT 1,
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS remote_profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER NOT NULL REFERENCES servers(id) ON DELETE CASCADE,
            enabled INTEGER NOT NULL DEFAULT 0,
            protocol TEXT NOT NULL DEFAULT 'rdp',
            host TEXT DEFAULT '',
            use_ssh_host INTEGER NOT NULL DEFAULT 1,
            port INTEGER DEFAULT 3389,
            username TEXT DEFAULT '',
            domain TEXT DEFAULT '',
            rustdesk_id TEXT DEFAULT '',
            resolution TEXT DEFAULT '1920x1080',
            fullscreen INTEGER NOT NULL DEFAULT 0,
            auto_scale INTEGER NOT NULL DEFAULT 1,
            quality TEXT DEFAULT 'auto',
            color_depth INTEGER DEFAULT 32,
            audio INTEGER NOT NULL DEFAULT 1,
            microphone INTEGER NOT NULL DEFAULT 0,
            clipboard INTEGER NOT NULL DEFAULT 1,
            share_folder TEXT DEFAULT '',
            view_only INTEGER NOT NULL DEFAULT 0,
            auto_reconnect INTEGER NOT NULL DEFAULT 0,
            protect_with_tunnel INTEGER NOT NULL DEFAULT 1,
            custom_executable TEXT DEFAULT '',
            custom_args TEXT DEFAULT '',
            credential_key TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now')),
            updated_at TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(server_id)
        );

        CREATE TABLE IF NOT EXISTS favorites (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            server_id INTEGER REFERENCES servers(id) ON DELETE CASCADE,
            path TEXT NOT NULL,
            is_remote INTEGER NOT NULL DEFAULT 1,
            label TEXT DEFAULT '',
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS settings (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS transfer_history (
            id TEXT PRIMARY KEY,
            server_id INTEGER REFERENCES servers(id) ON DELETE SET NULL,
            direction TEXT NOT NULL,
            local_path TEXT NOT NULL,
            remote_path TEXT NOT NULL,
            status TEXT NOT NULL,
            total_bytes INTEGER DEFAULT 0,
            transferred_bytes INTEGER DEFAULT 0,
            error_message TEXT DEFAULT '',
            is_directory INTEGER DEFAULT 0,
            created_at TEXT NOT NULL DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS trusted_hosts (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            hostname TEXT NOT NULL,
            port INTEGER NOT NULL DEFAULT 22,
            key_type TEXT NOT NULL,
            fingerprint_sha256 TEXT NOT NULL,
            public_key TEXT NOT NULL,
            first_seen TEXT NOT NULL DEFAULT (datetime('now')),
            last_seen TEXT NOT NULL DEFAULT (datetime('now')),
            UNIQUE(hostname, port, key_type)
        );

        CREATE TABLE IF NOT EXISTS app_logs (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            timestamp TEXT NOT NULL DEFAULT (datetime('now')),
            level TEXT NOT NULL DEFAULT 'INFO',
            category TEXT DEFAULT 'app',
            message TEXT NOT NULL,
            server_id INTEGER,
            details TEXT DEFAULT ''
        );

        CREATE INDEX IF NOT EXISTS idx_servers_group ON servers(group_id);
        CREATE INDEX IF NOT EXISTS idx_tunnels_server ON tunnels(server_id);
        CREATE INDEX IF NOT EXISTS idx_trusted_hosts_host ON trusted_hosts(hostname, port);
        CREATE INDEX IF NOT EXISTS idx_logs_ts ON app_logs(timestamp);
        CREATE INDEX IF NOT EXISTS idx_transfer_history_server ON transfer_history(server_id);

        INSERT OR IGNORE INTO server_groups (id, name, color, sort_order)
        VALUES (1, 'Padrão', '#4a9eff', 0);
        """,
    ),
]
