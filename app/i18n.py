"""Tradução simples pt_BR ↔ en (sem Qt Linguist)."""

from __future__ import annotations

from typing import Callable

_lang: str = "pt_BR"
_listeners: list[Callable[[], None]] = []

# Chave = texto em português (padrão do código)
EN: dict[str, str] = {
    # App / common
    "Configurações": "Settings",
    "Configurações…": "Settings…",
    "Salvar": "Save",
    "Cancelar": "Cancel",
    "Fechar": "Close",
    "Pronto": "Ready",
    "Sobre": "About",
    "Ajuda": "Help",
    "Arquivo": "File",
    "Editar": "Edit",
    "Servidor": "Server",
    "Exibir": "View",
    "Sair": "Quit",
    "Sim": "Yes",
    "Não": "No",
    # Main window
    "Hosts": "Hosts",
    "Organize e conecte com um clique": "Organize and connect in one click",
    "Buscar hosts…": "Search hosts…",
    "Selecione um servidor": "Select a server",
    "Novo servidor": "New server",
    "Gerenciar grupos…": "Manage groups…",
    "Exportar configuração…": "Export configuration…",
    "Importar configuração…": "Import configuration…",
    "Conectar": "Connect",
    "Desconectar": "Disconnect",
    "Terminal": "Terminal",
    "SFTP": "SFTP",
    "Arquivos SFTP": "SFTP Files",
    "Atualizar lista": "Refresh list",
    "Duplicar": "Duplicate",
    "Excluir": "Delete",
    "Início": "Home",
    "Menu (Arquivo, Servidor, …)": "Menu (File, Server, …)",
    "Minimizar": "Minimize",
    "Maximizar": "Maximize",
    "Restaurar": "Restore",
    "Fechar sessão": "Close session",
    "Sem grupo": "No group",
    "offline": "offline",
    "conectado": "connected",
    "conectando…": "connecting…",
    "erro": "error",
    "nunca": "never",
    "Aplicação iniciada": "Application started",
    "Aplicação encerrada": "Application closed",
    # Welcome
    "Gerencie servidores SSH e arquivos SFTP com segurança.\n"
    "Selecione um host na barra lateral ou crie um novo perfil.": (
        "Manage SSH servers and SFTP files securely.\n"
        "Select a host in the sidebar or create a new profile."
    ),
    "＋  Novo servidor": "＋  New server",
    "⚡  Conectar": "⚡  Connect",
    "Dica: clique duplo no servidor para conectar · "
    "Ctrl+T terminal · Ctrl+F SFTP": (
        "Tip: double-click a server to connect · "
        "Ctrl+T terminal · Ctrl+F SFTP"
    ),
    # Settings
    "Geral": "General",
    "Transferências": "Transfers",
    "Clientes externos": "External clients",
    "Segurança": "Security",
    "Tema": "Theme",
    "Idioma": "Language",
    "Escuro": "Dark",
    "Claro": "Light",
    "Sistema": "System",
    "Português (Brasil)": "Portuguese (Brazil)",
    "English": "English",
    "Timeout padrão": "Default timeout",
    "Keep-alive": "Keep-alive",
    "Reconexão automática": "Auto reconnect",
    "Confirmar antes de excluir": "Confirm before delete",
    "Mostrar arquivos ocultos": "Show hidden files",
    "Notificações do sistema": "System notifications",
    "Downloads": "Downloads",
    "Fonte do terminal": "Terminal font",
    "Tamanho da fonte": "Font size",
    "Transferências simultâneas": "Concurrent transfers",
    "Limite de velocidade": "Speed limit",
    "Arquivo existente": "Existing file",
    "Perguntar": "Ask",
    "Sobrescrever": "Overwrite",
    "Ignorar": "Skip",
    "Renomear": "Rename",
    "Verificar hash após transferência": "Verify hash after transfer",
    "Terminal externo": "External terminal",
    "Editor externo": "External editor",
    "Bloqueio automático": "Auto lock",
    "Exigir senha mestra no desbloqueio (camada adicional)": (
        "Require master password on unlock (extra layer)"
    ),
    "Diretório de downloads": "Download directory",
    " min (0=desligado)": " min (0=off)",
    " B/s (0=ilimitado)": " B/s (0=unlimited)",
    " s": " s",
    # Groups
    "Grupos de servidores": "Server groups",
    "Novo grupo": "New group",
    "Editar grupo": "Edit group",
    "Nome *": "Name *",
    "Cor": "Color",
    "Excluir grupo": "Delete group",
    "Organize seus hosts em grupos (Produção, Casa, Clientes…)": (
        "Organize hosts into groups (Production, Home, Clients…)"
    ),
    # Server dialog
    "Editar servidor": "Edit server",
    "Geral": "General",
    "Autenticação": "Authentication",
    "Caminhos e opções": "Paths and options",
    "Nome da conexão *": "Connection name *",
    "Grupo": "Group",
    "Descrição": "Description",
    "IP / Hostname *": "IP / Hostname *",
    "Porta SSH": "SSH port",
    "Usuário *": "Username *",
    "Cor do perfil": "Profile color",
    "Escolher cor": "Pick color",
    "Testar conexão": "Test connection",
    "— Sem grupo —": "— No group —",
    "Senha": "Password",
    "Chave SSH": "SSH key",
    "Chave SSH com passphrase": "SSH key with passphrase",
    "SSH Agent": "SSH Agent",
    # Terminal
    "Desconectado": "Disconnected",
    "Conectado": "Connected",
    "Shell ativo": "Shell active",
    "Shell encerrado": "Shell closed",
    "Reconectar shell": "Reconnect shell",
    "Abrir terminal externo…": "Open external terminal…",
    "Botão direito: reconectar · terminal externo": (
        "Right-click: reconnect · external terminal"
    ),
    # Status / misc
    "Transferências: ocioso": "Transfers: idle",
    "Clique para mostrar/ocultar hosts do grupo": (
        "Click to show/hide hosts in this group"
    ),
    "Exportar configuração": "Export configuration",
    "Importar configuração": "Import configuration",
    "Configurações salvas": "Settings saved",
    "Reinicie o app para aplicar o idioma por completo.": (
        "Restart the app to fully apply the language."
    ),
    "Idioma": "Language",
}


def get_language() -> str:
    return _lang


def set_language(code: str) -> None:
    global _lang
    raw = (code or "pt_BR").strip().strip('"').lower()
    if raw.startswith("en"):
        _lang = "en"
    else:
        _lang = "pt_BR"
    for cb in list(_listeners):
        try:
            cb()
        except Exception:  # noqa: BLE001
            pass


def on_language_change(callback: Callable[[], None]) -> None:
    if callback not in _listeners:
        _listeners.append(callback)


def tr(text: str) -> str:
    """Traduz string pt_BR → idioma atual. Se en e não houver entrada, devolve o original."""
    if not text:
        return text
    if _lang == "en" or _lang.startswith("en"):
        return EN.get(text, text)
    return text
