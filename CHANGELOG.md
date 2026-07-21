# Changelog

Todas as mudanças notáveis neste projeto serão documentadas aqui.

O formato é baseado em [Keep a Changelog](https://keepachangelog.com/pt-BR/1.0.0/),
e este projeto adere a [Semantic Versioning](https://semver.org/lang/pt-BR/).

## [1.0.0] — 2026-07-20

### Segurança

- **Host key pré-autenticação**: validação no handshake AsyncSSH (`validate_host_public_key`)
  com `known_hosts=b''` — **nunca** `known_hosts=None`
- Fase de probe sem senha/chave/agente; credenciais só após host key aceita
- Host key nova: confirmação explícita (hostname, porta, algoritmo, fingerprint SHA-256)
- Host key alterada: bloqueio imediato (sem ignorar silenciosamente)
- Remoção manual de chaves confiáveis em Configurações
- **Senha mestra Argon2id** (salt aleatório, formato versionado, migração do SHA-256 legado)
- Bloqueio por inatividade + atraso progressivo entre tentativas
- Keyring: serviço `SSH-Manager-Linux`; migração de serviços legados; sem fallback em texto
- Export sem credenciais; backup opcional Argon2id + AES-256-GCM
- FreeRDP: senha via `/from-stdin` (não em argv/`/proc`)
- VNC: arquivo de senha no formato DES do cliente (`0600`)
- RustDesk: não usa `--password`
- SFTP: path traversal bloqueado; downloads atômicos; cancelamento real
- Permissões: diretórios `0700`, arquivos sensíveis `0600`
- Logs sanitizados; nunca `shell=True`

### Adicionado

- Nome padronizado: **SSH-Manager-Linux** (`ssh-manager-linux`)
- Migração automática de pastas legadas (`nzxs-remote-manager`, etc.)
- Interface em português (Brasil): Servidores, Salvar, Cancelar, Configurações…
- Suite ampliada de testes de segurança

### Interface

- Tema escuro
- Perfis de servidor, grupos e jump host
- Terminal PTY embutido e terminal externo opcional
- SFTP dual-pane com drag-and-drop
- Fila de transferências
- Import/export de configuração
- Scripts de empacotamento `.deb` e AppImage

### Removido da UI (foco do produto)

- Controle remoto RDP/VNC/RustDesk na interface principal  
  (código em `app/remote_desktop/` endurecido, sem exposição na UI principal)
