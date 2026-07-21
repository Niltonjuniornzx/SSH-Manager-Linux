"""Utilitários de rede: portas livres, resolução DNS, etc."""

from __future__ import annotations

import socket
from typing import Optional


def find_free_port(host: str = "127.0.0.1", start: int = 10000, end: int = 60000) -> int:
    """Encontra uma porta TCP livre no host indicado."""
    for port in range(start, end):
        if not is_port_in_use(port, host):
            return port
    raise RuntimeError(f"Nenhuma porta livre entre {start} e {end}")


def is_port_in_use(port: int, host: str = "127.0.0.1") -> bool:
    """Verifica se a porta está em uso (bind de teste)."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind((host, port))
            return False
        except OSError:
            return True


def resolve_host(hostname: str, timeout: float = 5.0) -> list[str]:
    """Resolve hostname para lista de IPs. Levanta socket.gaierror se falhar."""
    old = socket.getdefaulttimeout()
    try:
        socket.setdefaulttimeout(timeout)
        infos = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
        ips: list[str] = []
        seen: set[str] = set()
        for info in infos:
            ip = info[4][0]
            if ip not in seen:
                seen.add(ip)
                ips.append(ip)
        return ips
    finally:
        socket.setdefaulttimeout(old)


def check_tcp_port(host: str, port: int, timeout: float = 5.0) -> tuple[bool, Optional[str]]:
    """Testa conectividade TCP. Retorna (ok, mensagem_erro)."""
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True, None
    except socket.gaierror as exc:
        return False, f"Host não encontrado: {exc}"
    except TimeoutError:
        return False, f"Timeout ao conectar em {host}:{port}"
    except ConnectionRefusedError:
        return False, f"Conexão recusada em {host}:{port}"
    except OSError as exc:
        return False, f"Erro de rede: {exc}"


def measure_latency_ms(host: str, port: int, timeout: float = 5.0) -> Optional[float]:
    """Mede latência RTT aproximada em ms (handshake TCP)."""
    import time

    start = time.perf_counter()
    ok, _ = check_tcp_port(host, port, timeout)
    if not ok:
        return None
    elapsed = (time.perf_counter() - start) * 1000.0
    return round(elapsed, 1)
