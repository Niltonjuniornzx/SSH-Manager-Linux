# Política de segurança — SSH-Manager-Linux

## Relatar vulnerabilidades

Se encontrar um problema de segurança (vazamento de credenciais, bypass de host key,
execução insegura de processos, etc.):

1. **Não** abra uma issue pública com PoC explorável.
2. Abra uma issue genérica pedindo contato privado, ou envie detalhes por canal
   privado do mantenedor no GitHub.

## Garantias do projeto

### Host keys (prioridade crítica)

- Validação no handshake SSH via `validate_host_public_key` do AsyncSSH.
- **Nunca** usa `known_hosts=None` (que desabilita a verificação).
- Host key é conferida **antes** de enviar senha, desbloquear chave privada,
  usar agente, abrir terminal/SFTP/túneis ou executar comandos.
- Primeiro acesso: hostname, porta, algoritmo e fingerprint SHA-256 + confirmação explícita.
- Host key alterada: bloqueio imediato (sem botão genérico para ignorar).
- Remoção manual de chaves confiáveis em **Configurações → Segurança**.
- Arquivo `known_hosts` com permissão `0600`.

### Credenciais

- Apenas no keyring do sistema (KDE Wallet / GNOME Keyring / Secret Service).
- Serviço: `SSH-Manager-Linux`.
- **Nunca** no SQLite, JSON, configurações ou logs.
- Sem fallback em texto simples: se o keyring falhar, a senha não é salva.
- Exportações **não** incluem credenciais por padrão.
- Backup opcional: Argon2id + AES-256-GCM (nonce/salt aleatórios).

### Senha mestra

- Hash **Argon2id** com salt aleatório e parâmetros de custo configuráveis.
- Formato versionado (`argon2id$v=1$…`).
- Comparação em tempo constante (via biblioteca Argon2).
- Migração automática de SHA-256 legado **somente** após senha correta.
- Bloqueio por inatividade + atraso progressivo entre tentativas.

### Processos externos

- Nunca `shell=True`.
- Argumentos em listas.
- FreeRDP: senha via `/from-stdin` (não em `/proc`).
- VNC: arquivo de senha no formato DES do cliente (não texto simples), `0600`.
- RustDesk: **não** usa `--password` (exposição em `/proc`).
- Temporários com criação atômica, `0600`, limpeza em sucesso/erro/cancelamento.
- Logs sanitizados (sem senhas, chaves privadas ou tokens).

### Arquivos e banco

- Diretórios de dados: `0700`.
- SQLite, known_hosts, logs privados, configs sensíveis: `0600`.
- Gravação atômica (`os.replace`) e recusa de symlinks em caminhos sensíveis.
- Importação com limites de tamanho e validação anti path-traversal.

### SFTP

- Confirmação antes de exclusões/sobrescritas (quando habilitado).
- Proteção contra path traversal.
- Downloads via arquivo parcial + rename atômico.
- Cancelamento real de transferências.

## Caminhos XDG

| Uso | Caminho |
|-----|---------|
| Dados | `~/.local/share/ssh-manager-linux` |
| Config | `~/.config/ssh-manager-linux` |
| Cache | `~/.cache/ssh-manager-linux` |

Pastas legadas (`nzxs-remote-manager`, etc.) são **migradas por cópia** (não apagadas).

## Versões suportadas

A branch principal (`main`) recebe correções de segurança.

## Escopo fora

- Comprometimento do keyring do sistema operacional
- Servidores SSH mal configurados pelo usuário
- Clientes externos (terminal, FreeRDP, VNC, editores) instalados no SO
- Comandos remotos interpretados pelo shell do servidor (sempre explicitados na UI)
