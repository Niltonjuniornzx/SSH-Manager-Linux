"""Tema visual inspirado em clientes modernos (estilo anySCP / Termius).

Paleta:
  bg base    #0b0d12
  painéis    #11141b / #151922
  borda      #1e2430
  texto      #e8eaed
  muted      #8b93a7
  accent     #2dd4bf (teal) / #38bdf8 (sky)
  success    #34d399
  danger     #f87171
  warning    #fbbf24
"""

DARK_QSS = """
* {
    font-family: "Inter", "Segoe UI", "Ubuntu", "Noto Sans", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog {
    background-color: #0b0d12;
    color: #e8eaed;
}
/* Borda própria do app (substitui a moldura do desktop) */
QMainWindow#mainWindow {
    background-color: #0b0d12;
    border: 1px solid #3a465c;
    border-radius: 14px;
}
QDialog {
    background-color: #0b0d12;
    color: #e8eaed;
    border: 1px solid #2a3344;
    border-radius: 14px;
}
QDialog#appDialog {
    background-color: #0b0d12;
    border: 1px solid #3a465c;
    border-radius: 14px;
}
QWidget {
    background-color: transparent;
    color: #e8eaed;
}
QToolTip {
    background-color: #1a1f2b;
    color: #e8eaed;
    border: 1px solid #2a3344;
    border-radius: 10px;
    padding: 8px 10px;
}

/* ── Janela custom (sem borda do DE) ────────────────────── */
QWidget#windowChrome {
    background-color: #0b0d12;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QWidget#titleBar {
    background-color: #0f1218;
    border: none;
    border-bottom: 1px solid #1a1f2b;
    border-top: 2px solid #2dd4bf;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QLabel#titleBarLabel {
    color: #c5cad6;
    font-size: 12px;
    font-weight: 600;
    letter-spacing: 0.01em;
    background: transparent;
}
QLabel#titleBarIcon {
    background: transparent;
}
QPushButton#titleBtnMin, QPushButton#titleBtnMax, QPushButton#titleBtnClose,
QPushButton#titleBtnMenu {
    background-color: transparent;
    color: #8b93a7;
    border: 1px solid transparent;
    border-radius: 8px;
    font-size: 13px;
    font-weight: 600;
    padding: 0;
    min-height: 0;
}
QPushButton#titleBtnMenu {
    font-size: 15px;
}
QPushButton#titleBtnMin:hover, QPushButton#titleBtnMax:hover,
QPushButton#titleBtnMenu:hover {
    background-color: #1a1f2b;
    border-color: #2a3344;
    color: #e8eaed;
}
QPushButton#titleBtnClose:hover {
    background-color: #f87171;
    border-color: #f87171;
    color: #0b0d12;
}

/* Botão só com ícone (ex.: grupos na sidebar) */
QPushButton#iconBtn {
    background-color: #151922;
    border: 1px solid #252b3a;
    border-radius: 10px;
    padding: 0;
    min-height: 28px;
}
QPushButton#iconBtn:hover {
    background-color: #1c2330;
    border-color: #2dd4bf;
}
QPushButton#iconBtn:pressed {
    background-color: #12161f;
}

/* ── Menu / toolbar ─────────────────────────────────────── */
QMenuBar {
    background-color: #0b0d12;
    color: #c5cad6;
    border-bottom: 1px solid #1a1f2b;
    padding: 2px 4px;
    spacing: 4px;
}
QMenuBar::item {
    padding: 6px 12px;
    border-radius: 6px;
    background: transparent;
}
QMenuBar::item:selected {
    background-color: #1a1f2b;
    color: #ffffff;
}
QMenu {
    background-color: #151922;
    color: #e8eaed;
    border: 1px solid #2a3344;
    border-radius: 10px;
    padding: 6px;
}
QMenu::item {
    padding: 8px 28px 8px 14px;
    border-radius: 6px;
}
QMenu::item:selected {
    background-color: rgba(45, 212, 191, 0.15);
    color: #5eead4;
}
QMenu::separator {
    height: 1px;
    background: #1e2430;
    margin: 4px 8px;
}
QToolBar {
    background-color: #0f1218;
    border: none;
    border-bottom: 1px solid #1a1f2b;
    spacing: 6px;
    padding: 8px 12px;
}
QToolBar QToolButton {
    background-color: #151922;
    color: #e8eaed;
    border: 1px solid #252b3a;
    border-radius: 8px;
    padding: 7px 14px;
    margin: 0 2px;
}
QToolBar QToolButton:hover {
    background-color: #1c2330;
    border-color: #2dd4bf;
    color: #ffffff;
}
QToolBar QToolButton:pressed {
    background-color: #12161f;
}
QStatusBar {
    background-color: #0b0d12;
    color: #8b93a7;
    border-top: 1px solid #1a1f2b;
    border-bottom-left-radius: 14px;
    border-bottom-right-radius: 14px;
    min-height: 26px;
}

/* ── Inputs ─────────────────────────────────────────────── */
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background-color: #0f131a;
    color: #e8eaed;
    border: 1px solid #252b3a;
    border-radius: 10px;
    padding: 8px 12px;
    min-height: 20px;
    selection-background-color: rgba(45, 212, 191, 0.35);
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus, QTextEdit:focus, QPlainTextEdit:focus {
    border: 1px solid #2dd4bf;
    background-color: #11161f;
}
QLineEdit:hover, QSpinBox:hover, QComboBox:hover {
    border-color: #3a4558;
}
QComboBox {
    padding-right: 28px;
}
QComboBox::drop-down {
    border: none;
    width: 28px;
}
QComboBox::down-arrow {
    width: 0; height: 0;
    border-left: 5px solid transparent;
    border-right: 5px solid transparent;
    border-top: 6px solid #8b93a7;
    margin-right: 10px;
}
QComboBox QAbstractItemView {
    background-color: #151922;
    color: #e8eaed;
    selection-background-color: rgba(45, 212, 191, 0.2);
    border: 1px solid #2a3344;
    border-radius: 8px;
    outline: none;
    padding: 4px;
}

/* ── Buttons ────────────────────────────────────────────── */
QPushButton {
    background-color: #151922;
    color: #e8eaed;
    border: 1px solid #252b3a;
    border-radius: 10px;
    padding: 8px 16px;
    min-height: 20px;
    font-weight: 500;
}
QPushButton:hover {
    background-color: #1c2330;
    border-color: #2dd4bf;
    color: #ffffff;
}
QPushButton:pressed {
    background-color: #10141c;
}
QPushButton:disabled {
    color: #4a5160;
    background-color: #12151c;
    border-color: #1a1f2b;
}
QPushButton#primaryBtn {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #14b8a6, stop:1 #0ea5e9);
    border: none;
    color: #041016;
    font-weight: 700;
    padding: 9px 18px;
}
QPushButton#primaryBtn:hover {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #2dd4bf, stop:1 #38bdf8);
}
QPushButton#primaryBtn:pressed {
    background-color: #0d9488;
}
QPushButton#dangerBtn {
    background-color: rgba(248, 113, 113, 0.12);
    border: 1px solid rgba(248, 113, 113, 0.35);
    color: #fca5a5;
}
QPushButton#dangerBtn:hover {
    background-color: rgba(248, 113, 113, 0.22);
    border-color: #f87171;
    color: #fecaca;
}
QToolButton {
    background-color: transparent;
    color: #c5cad6;
    border: 1px solid transparent;
    border-radius: 8px;
    padding: 4px;
}
QToolButton:hover {
    background-color: #1a1f2b;
    border-color: #252b3a;
    color: #2dd4bf;
}
QToolButton:pressed {
    background-color: #12161f;
}

/* ── Lists / tables ─────────────────────────────────────── */
QTreeWidget, QListWidget, QTableWidget, QTreeView, QListView, QTableView {
    background-color: #0f131a;
    color: #e8eaed;
    border: 1px solid #1a1f2b;
    border-radius: 12px;
    outline: none;
    alternate-background-color: #12171f;
    gridline-color: #1a1f2b;
    padding: 4px;
}
QTreeWidget::item, QListWidget::item, QTableWidget::item, QTreeView::item {
    padding: 5px 6px;
    border-radius: 6px;
    margin: 0px 1px;
    min-height: 22px;
}
QTreeWidget#sftpTree {
    font-size: 11px;
}
QTreeWidget#sftpTree::item {
    padding: 4px 6px;
    min-height: 22px;
}
QTreeWidget::item:hover, QListWidget::item:hover, QTableWidget::item:hover {
    background-color: #1a2030;
}
QTreeWidget::item:selected, QListWidget::item:selected,
QTableWidget::item:selected, QTreeView::item:selected {
    background-color: rgba(45, 212, 191, 0.16);
    color: #f0fdfa;
}
QHeaderView::section {
    background-color: #11151d;
    color: #8b93a7;
    border: none;
    border-bottom: 1px solid #1a1f2b;
    border-right: 1px solid #1a1f2b;
    padding: 10px 12px;
    font-weight: 600;
    font-size: 11px;
    text-transform: uppercase;
    letter-spacing: 0.04em;
}
QHeaderView::section:first {
    border-top-left-radius: 10px;
}

/* ── Tabs (pílulas arredondadas em todos os cantos) ─────── */
QTabWidget {
    background: transparent;
}
QTabWidget::pane {
    border: 1px solid #1e2430;
    border-radius: 14px;
    background-color: #0f131a;
    top: 0px;
    margin-top: 4px;
    padding: 4px;
}
QTabBar {
    background: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: #151922;
    color: #8b93a7;
    border: 1px solid #252b3a;
    /* 4 cantos arredondados — inclusive a base */
    border-radius: 12px;
    padding: 7px 10px 7px 14px;
    margin: 3px 3px 6px 3px;
    font-weight: 500;
    min-width: 64px;
}
QTabBar::tab:selected {
    background-color: #10241f;
    color: #5eead4;
    border: 1px solid #2dd4bf;
    border-radius: 12px;
}
QTabBar::tab:hover:!selected {
    background-color: #1a2030;
    color: #e8eaed;
    border-color: #3a4558;
    border-radius: 12px;
}
QTabBar::close-button {
    subcontrol-position: right;
    margin: 0;
}
QToolButton#tabCloseBtn {
    background: transparent;
    border: none;
    border-radius: 10px;
    padding: 0;
    margin: 0 2px 0 4px;
    min-width: 20px;
    min-height: 20px;
}
QToolButton#tabCloseBtn:hover {
    background-color: transparent; /* hover vem do ícone */
}
QToolButton#tabCloseBtn:pressed {
    background-color: rgba(248, 113, 113, 0.12);
}

/* Lista de hosts — plana, zero decoração à esquerda */
QTreeWidget#hostTree {
    padding: 4px;
    outline: none;
    show-decoration-selected: 0;
    border: 1px solid #1a1f2b;
    border-radius: 12px;
}
QTreeWidget#hostTree::item {
    padding: 6px 10px;
    border-radius: 8px;
    min-height: 26px;
    margin: 1px 0;
}
QTreeWidget#hostTree::item:selected {
    background-color: rgba(45, 212, 191, 0.16);
    color: #f0fdfa;
}
QTreeWidget#hostTree::branch {
    background: transparent;
    border: none;
    border-image: none;
    image: none;
    width: 0px;
    height: 0px;
}

/* ── Scrollbars ─────────────────────────────────────────── */
QScrollBar:vertical {
    background: transparent;
    width: 10px;
    margin: 4px 2px;
}
QScrollBar::handle:vertical {
    background: #2a3344;
    border-radius: 5px;
    min-height: 28px;
}
QScrollBar::handle:vertical:hover {
    background: #2dd4bf;
}
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
    height: 0;
}
QScrollBar:horizontal {
    background: transparent;
    height: 10px;
    margin: 2px 4px;
}
QScrollBar::handle:horizontal {
    background: #2a3344;
    border-radius: 5px;
    min-width: 28px;
}
QScrollBar::handle:horizontal:hover {
    background: #2dd4bf;
}
QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
    width: 0;
}

/* ── Splitter / groups ──────────────────────────────────── */
QSplitter::handle {
    background-color: #1a1f2b;
    width: 2px;
    height: 2px;
    margin: 0 2px;
}
QSplitter::handle:hover {
    background-color: #2dd4bf;
}
QGroupBox {
    border: 1px solid #1e2430;
    border-radius: 12px;
    margin-top: 14px;
    padding: 16px 12px 12px 12px;
    font-weight: 600;
    background-color: #11151d;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 14px;
    padding: 0 8px;
    color: #8b93a7;
    font-size: 11px;
    font-weight: 700;
    letter-spacing: 0.06em;
}

/* ── Checkbox ───────────────────────────────────────────── */
QCheckBox, QRadioButton {
    spacing: 10px;
    color: #e8eaed;
}
QCheckBox::indicator, QRadioButton::indicator {
    width: 18px;
    height: 18px;
    border: 1.5px solid #3a4558;
    border-radius: 5px;
    background: #0f131a;
}
QCheckBox::indicator:checked {
    background-color: #14b8a6;
    border-color: #14b8a6;
}
QCheckBox::indicator:hover {
    border-color: #2dd4bf;
}

/* ── Progress ───────────────────────────────────────────── */
QProgressBar {
    background-color: #12171f;
    border: 1px solid #1e2430;
    border-radius: 6px;
    text-align: center;
    color: #c5cad6;
    height: 14px;
    font-size: 11px;
}
QProgressBar::chunk {
    background-color: qlineargradient(x1:0, y1:0, x2:1, y2:0,
        stop:0 #14b8a6, stop:1 #0ea5e9);
    border-radius: 5px;
}

/* ── Labels ─────────────────────────────────────────────── */
QLabel#titleLabel {
    font-size: 18px;
    font-weight: 700;
    color: #f0f4f8;
    letter-spacing: -0.02em;
}
QLabel#subtitleLabel {
    font-size: 13px;
    color: #8b93a7;
    font-weight: 400;
}
QLabel#mutedLabel {
    color: #8b93a7;
    font-size: 12px;
}
QLabel#statusConnected {
    color: #34d399;
    font-weight: 600;
}
QLabel#statusDisconnected {
    color: #8b93a7;
}
QLabel#statusError {
    color: #f87171;
    font-weight: 600;
}
QLabel#brandLabel {
    font-size: 22px;
    font-weight: 800;
    color: #f0f4f8;
    letter-spacing: -0.03em;
}
QLabel#accentDot {
    color: #2dd4bf;
    font-size: 10px;
}

/* ── Frames ─────────────────────────────────────────────── */
QFrame#sidebar {
    background-color: #0f1218;
    border-right: 1px solid #1a1f2b;
    border-bottom-left-radius: 12px;
}
QFrame#bottomBar {
    background-color: #0b0d12;
    border-top: 1px solid #1a1f2b;
    border-radius: 10px;
}
QFrame#card {
    background-color: #151922;
    border: 1px solid #1e2430;
    border-radius: 14px;
}
QFrame#card:hover {
    border-color: #2dd4bf;
}
QFrame#welcomeHero {
    background-color: #11151d;
    border: 1px solid #1e2430;
    border-radius: 18px;
}
"""

LIGHT_QSS = """
* {
    font-family: "Inter", "Segoe UI", "Ubuntu", "Noto Sans", sans-serif;
    font-size: 13px;
}
QMainWindow, QDialog, QWidget {
    background-color: #f4f6f9;
    color: #0f1419;
}
QMainWindow#mainWindow {
    background-color: #ffffff;
    border: 1px solid #cbd5e1;
    border-radius: 14px;
}
QDialog {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}
QWidget#windowChrome {
    background-color: #ffffff;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QWidget#titleBar {
    background-color: #ffffff;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    border-top-left-radius: 14px;
    border-top-right-radius: 14px;
}
QLabel#titleBarLabel {
    color: #334155;
    font-size: 12px;
    font-weight: 600;
    background: transparent;
}
QPushButton#titleBtnMin, QPushButton#titleBtnMax, QPushButton#titleBtnClose,
QPushButton#titleBtnMenu {
    background-color: transparent;
    color: #64748b;
    border: 1px solid transparent;
    border-radius: 8px;
    font-size: 12px;
    font-weight: 600;
    padding: 0;
    min-height: 0;
}
QPushButton#titleBtnMenu { font-size: 15px; }
QPushButton#titleBtnMin:hover, QPushButton#titleBtnMax:hover,
QPushButton#titleBtnMenu:hover {
    background-color: #f1f5f9;
    border-color: #e2e8f0;
    color: #0f1419;
}
QPushButton#titleBtnClose:hover {
    background-color: #f87171;
    color: #ffffff;
}
QPushButton#iconBtn {
    background-color: #f8fafc;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QPushButton#iconBtn:hover {
    background-color: #f0fdfa;
    border-color: #14b8a6;
}
QMenuBar {
    background-color: #ffffff;
    color: #0f1419;
    border-bottom: 1px solid #e2e8f0;
}
QMenu {
    background-color: #ffffff;
    color: #0f1419;
    border: 1px solid #e2e8f0;
    border-radius: 10px;
}
QMenu::item:selected {
    background-color: #ccfbf1;
    color: #0f766e;
}
QToolBar {
    background-color: #ffffff;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    spacing: 6px;
    padding: 8px 12px;
}
QStatusBar {
    background-color: #ffffff;
    color: #64748b;
    border-top: 1px solid #e2e8f0;
}
QLineEdit, QSpinBox, QComboBox, QTextEdit, QPlainTextEdit {
    background-color: #ffffff;
    color: #0f1419;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 12px;
    selection-background-color: #99f6e4;
}
QLineEdit:focus, QSpinBox:focus, QComboBox:focus {
    border: 1px solid #14b8a6;
}
QPushButton {
    background-color: #ffffff;
    color: #0f1419;
    border: 1px solid #cbd5e1;
    border-radius: 10px;
    padding: 8px 16px;
}
QPushButton:hover {
    background-color: #f0fdfa;
    border-color: #14b8a6;
}
QPushButton#primaryBtn {
    background-color: #14b8a6;
    border: none;
    color: #ffffff;
    font-weight: 700;
}
QPushButton#primaryBtn:hover {
    background-color: #0d9488;
}
QPushButton#dangerBtn {
    background-color: #fef2f2;
    border-color: #fecaca;
    color: #b91c1c;
}
QTreeWidget, QListWidget, QTableWidget, QTreeView, QListView, QTableView {
    background-color: #ffffff;
    color: #0f1419;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    alternate-background-color: #f8fafc;
    gridline-color: #e2e8f0;
}
QTreeWidget::item:selected, QListWidget::item:selected, QTableWidget::item:selected {
    background-color: #ccfbf1;
    color: #134e4a;
}
QHeaderView::section {
    background-color: #f1f5f9;
    color: #64748b;
    border: none;
    border-bottom: 1px solid #e2e8f0;
    border-right: 1px solid #e2e8f0;
    padding: 10px 12px;
    font-weight: 600;
}
QTabWidget::pane {
    border: 1px solid #e2e8f0;
    border-radius: 14px;
    margin-top: 4px;
    top: 0px;
    background-color: #ffffff;
}
QTabBar {
    background: transparent;
    qproperty-drawBase: 0;
}
QTabBar::tab {
    background-color: #f1f5f9;
    color: #64748b;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    padding: 8px 16px;
    margin: 3px 3px 6px 3px;
}
QTabBar::tab:selected {
    background-color: #ccfbf1;
    color: #0f766e;
    border: 1px solid #14b8a6;
    border-radius: 12px;
}
QGroupBox {
    border: 1px solid #e2e8f0;
    border-radius: 12px;
    margin-top: 14px;
    padding-top: 16px;
    background-color: #ffffff;
}
QProgressBar {
    background-color: #f1f5f9;
    border: 1px solid #e2e8f0;
    border-radius: 6px;
    text-align: center;
}
QProgressBar::chunk {
    background-color: #14b8a6;
    border-radius: 5px;
}
QFrame#sidebar {
    background-color: #f8fafc;
    border-right: 1px solid #e2e8f0;
    border-bottom-left-radius: 12px;
}
QFrame#bottomBar {
    background-color: #ffffff;
    border-top: 1px solid #e2e8f0;
    border-radius: 10px;
}
QFrame#card {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 14px;
}
QFrame#card:hover {
    border-color: #14b8a6;
}
QFrame#welcomeHero {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 18px;
}
QLabel#titleLabel {
    font-size: 18px;
    font-weight: 700;
    color: #0f1419;
}
QLabel#subtitleLabel {
    font-size: 13px;
    color: #64748b;
}
QLabel#mutedLabel {
    color: #64748b;
}
QLabel#statusConnected {
    color: #059669;
    font-weight: 600;
}
QLabel#statusDisconnected {
    color: #64748b;
}
QLabel#statusError {
    color: #dc2626;
    font-weight: 600;
}
QLabel#brandLabel {
    font-size: 22px;
    font-weight: 800;
    color: #0f1419;
}
QTreeWidget#hostTree {
    background-color: #ffffff;
    border: 1px solid #e2e8f0;
    border-radius: 12px;
}
QTreeWidget#hostTree::item:selected {
    background-color: #ccfbf1;
    color: #134e4a;
}
QToolButton#tabCloseBtn {
    background: transparent;
    border: none;
    border-radius: 10px;
}
"""


def _system_prefers_dark() -> bool:
    try:
        from PySide6.QtGui import QGuiApplication
        from PySide6.QtCore import Qt

        app = QGuiApplication.instance()
        if app is None:
            return True
        hints = app.styleHints()
        # Qt 6.5+: colorScheme()
        scheme = getattr(hints, "colorScheme", None)
        if callable(scheme):
            cs = scheme()
            dark = getattr(Qt, "ColorScheme", None)
            if dark is not None and hasattr(dark, "Dark"):
                return cs == dark.Dark
        # Fallback: luminosidade da cor de janela
        pal = app.palette()
        window = pal.color(pal.ColorRole.Window)
        return window.lightness() < 128
    except Exception:  # noqa: BLE001
        return True


def resolve_theme(theme: str) -> str:
    """Retorna 'dark' ou 'light' efetivo."""
    if theme == "light":
        return "light"
    if theme == "system":
        return "dark" if _system_prefers_dark() else "light"
    return "dark"


def apply_theme(app_or_widget, theme: str = "dark") -> None:
    # Tema claro descontinuado — sempre dark
    app_or_widget.setStyleSheet(DARK_QSS)
