"""Testes de importação/exportação e backup criptografado."""

from __future__ import annotations


from app.models.server import ServerProfile
from app.utils.export_import import export_summary, export_to_file, import_from_file


def test_export_import_roundtrip(db, tmp_path):
    db.save_server(ServerProfile(name="ExportMe", host="1.1.1.1", username="u"))
    path = tmp_path / "export.json"
    info = export_to_file(db, path)
    assert info["includes_credentials"] is False
    assert path.is_file()
    text = path.read_text(encoding="utf-8")
    # auth_method pode ser a string "password" (método), mas não valores secretos
    assert "credential_key\": \"\"" in text or '"credential_key": ""' in text
    assert "supersecret" not in text.lower()
    assert "ExportMe" in text

    # new db
    from app.database.db import Database

    db2 = Database(tmp_path / "import.db")
    stats = import_from_file(db2, path)
    assert stats["servers"] >= 1
    names = [s.name for s in db2.list_servers()]
    assert "ExportMe" in names
    db2.close()


def test_encrypted_backup(db, tmp_path):
    db.save_server(ServerProfile(name="Sec", host="2.2.2.2", username="u"))
    path = tmp_path / "backup.sml"
    export_to_file(db, path, encrypt_password="backup-pass-123")
    raw = path.read_bytes()
    assert raw.startswith(b"SML1")
    # Conteúdo em claro não deve aparecer como JSON legível
    assert b'"name": "Sec"' not in raw
    assert b"2.2.2.2" not in raw

    from app.database.db import Database

    db2 = Database(tmp_path / "imp2.db")
    stats = import_from_file(db2, path, encrypt_password="backup-pass-123")
    assert stats["servers"] >= 1
    db2.close()


def test_wrong_password_fails(db, tmp_path):
    path = tmp_path / "backup.nzxs"
    export_to_file(db, path, encrypt_password="right")
    from app.database.db import Database

    db2 = Database(tmp_path / "imp3.db")
    try:
        import pytest

        with pytest.raises(ValueError):
            import_from_file(db2, path, encrypt_password="wrong")
    finally:
        db2.close()


def test_export_summary(db):
    data = db.export_config()
    text = export_summary(data)
    assert "NÃO incluirá" in text or "não" in text.lower()
    assert "Senhas" in text or "senhas" in text.lower()
