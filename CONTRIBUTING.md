# Contribuindo

Obrigado por contribuir com o **SSH-Manager-Linux**.

## Ambiente de desenvolvimento

```bash
git clone https://github.com/Niltonjuniornzx/SSH-Manager-Linux.git
cd SSH-Manager-Linux
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pip install -e ".[dev]"
```

## Antes do PR

1. Rode os testes:

   ```bash
   pytest -q
   ```

2. Rode o linter nos módulos alterados:

   ```bash
   ruff check app tests main.py
   ```

3. Não inclua:
   - Credenciais, hosts reais ou senhas
   - Arquivos de `~/.local/share/ssh-manager-linux/`
   - `.venv/`, caches ou builds

## Estilo de código

- Python 3.12+
- Preferir type hints
- UI em português (pt_BR) por padrão
- Separar UI / domínio / I/O (como na pasta `app/`)

## Commits

Mensagens claras em português ou inglês, por exemplo:

- `fix(ssh): validar host key antes da autenticação`
- `sec: migrar senha mestra para Argon2id`

## Segurança

Se encontrar uma falha de segurança, veja [SECURITY.md](SECURITY.md) — preferível não abrir issue pública detalhada de exploit.
