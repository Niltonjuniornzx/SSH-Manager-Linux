#!/usr/bin/env python3
"""Ponto de entrada do SSH-Manager-Linux."""

from __future__ import annotations

import sys
from pathlib import Path

# Garante que o pacote app seja importável quando executado diretamente
_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))


def main() -> int:
    """Inicia a UI Qt integrada ao loop asyncio (qasync)."""
    import asyncio

    import qasync
    from PySide6.QtCore import Qt
    from PySide6.QtGui import QIcon
    from PySide6.QtWidgets import QApplication

    from app import __app_id__, __app_name__, __version__
    from app.database.db import get_database
    from app.security.credentials import CredentialStore
    from app.ui.main_window import MainWindow
    from app.ui.styles import apply_theme
    from app.utils.logging_setup import setup_logging

    QApplication.setHighDpiScaleFactorRoundingPolicy(
        Qt.HighDpiScaleFactorRoundingPolicy.PassThrough
    )

    app = QApplication(sys.argv)
    app.setApplicationName(__app_name__)
    app.setOrganizationName(__app_name__)
    app.setOrganizationDomain("ssh-manager-linux.local")
    app.setApplicationVersion(__version__)
    app.setDesktopFileName(__app_id__)

    icon_candidates = [
        _ROOT / "assets" / "icons" / "ssh-manager-linux-256.png",
        _ROOT / "assets" / "icon.png",
        _ROOT / "assets" / "icons" / "ssh-manager-linux-128.png",
    ]
    icon_path = next((p for p in icon_candidates if p.is_file()), None)
    if icon_path is not None:
        app.setWindowIcon(QIcon(str(icon_path)))

    db = get_database()
    settings = db.get_settings()
    setup_logging(settings.log_level)

    from app.i18n import set_language

    # Normaliza idioma (evita aspas/valores estranhos no SQLite)
    lang = (settings.language or "pt_BR").strip().strip('"')
    if lang.lower().startswith("en"):
        lang = "en"
    else:
        lang = "pt_BR"
    settings.language = lang
    settings.theme = "dark"
    set_language(lang)
    apply_theme(app, "dark")

    loop = qasync.QEventLoop(app)
    asyncio.set_event_loop(loop)

    window = MainWindow(db, CredentialStore(), settings)
    if icon_path is not None:
        window.setWindowIcon(QIcon(str(icon_path)))
    window.show()

    with loop:
        return loop.run_forever()


if __name__ == "__main__":
    raise SystemExit(main())
