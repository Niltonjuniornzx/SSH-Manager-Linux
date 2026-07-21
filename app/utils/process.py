"""Execução segura de processos externos — nunca shell=True."""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Optional, Sequence

from app.utils.sanitize import sanitize_args


class ProcessError(Exception):
    """Falha ao iniciar ou executar processo externo."""


def find_executable(candidates: Sequence[str]) -> Optional[str]:
    """Retorna o primeiro executável encontrado no PATH."""
    for name in candidates:
        path = shutil.which(name)
        if path:
            return path
    return None


def validate_executable(path: str | Path) -> Path:
    """Valida que o caminho aponta para um executável existente."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        raise ProcessError(f"Executável não encontrado: {p}")
    if not p.is_file():
        raise ProcessError(f"Caminho não é um arquivo: {p}")
    # Verifica bit de execução ou presença no PATH
    if not (p.stat().st_mode & 0o111) and shutil.which(str(p)) is None:
        # Ainda pode ser um script interpretado; aceitamos se for arquivo
        pass
    return p


def run_external(
    args: Sequence[str],
    *,
    cwd: Optional[str | Path] = None,
    env: Optional[dict[str, str]] = None,
    timeout: Optional[float] = None,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    """
    Executa processo com lista de argumentos (sem shell).

    NUNCA use shell=True. NUNCA coloque senhas em args se puder evitar.
    """
    if not args:
        raise ProcessError("Lista de argumentos vazia")
    cmd = list(args)
    # Validar primeiro argumento se for caminho absoluto
    first = cmd[0]
    if "/" in first:
        validate_executable(first)
    else:
        found = shutil.which(first)
        if not found:
            raise ProcessError(f"Programa não encontrado no PATH: {first}")
        cmd[0] = found

    try:
        return subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            timeout=timeout,
            capture_output=capture,
            text=True,
            check=check,
            shell=False,  # explícito e obrigatório
        )
    except subprocess.TimeoutExpired as exc:
        raise ProcessError(f"Timeout ao executar: {sanitize_args(cmd)}") from exc
    except FileNotFoundError as exc:
        raise ProcessError(f"Programa não encontrado: {cmd[0]}") from exc
    except OSError as exc:
        raise ProcessError(f"Erro ao executar processo: {exc}") from exc


def start_process(
    args: Sequence[str],
    *,
    cwd: Optional[str | Path] = None,
    env: Optional[dict[str, str]] = None,
) -> subprocess.Popen[bytes]:
    """Inicia processo em background (sem shell)."""
    if not args:
        raise ProcessError("Lista de argumentos vazia")
    cmd = list(args)
    first = cmd[0]
    if "/" in first:
        validate_executable(first)
    else:
        found = shutil.which(first)
        if not found:
            raise ProcessError(f"Programa não encontrado no PATH: {first}")
        cmd[0] = found

    try:
        return subprocess.Popen(
            cmd,
            cwd=str(cwd) if cwd else None,
            env=env,
            shell=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except FileNotFoundError as exc:
        raise ProcessError(f"Programa não encontrado: {cmd[0]}") from exc
    except OSError as exc:
        raise ProcessError(f"Erro ao iniciar processo: {exc}") from exc


def build_safe_preview(args: Sequence[str]) -> str:
    """Prévia segura dos argumentos (segredos redigidos) para UI."""
    return " ".join(sanitize_args(list(args)))
