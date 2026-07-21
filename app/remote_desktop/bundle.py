"""Baixa e usa FreeRDP embutido no app (sem sudo), se o sistema não tiver xfreerdp."""

from __future__ import annotations

import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path
from typing import Optional
from urllib.request import urlretrieve

from app.utils.paths import app_data_dir, ensure_secure_dir
from app.utils.process import find_executable
from app.utils.sanitize import sanitize_for_log

logger = logging.getLogger(__name__)

# Pacotes Ubuntu noble (amd64) — extraídos localmente com dpkg-deb
_PACKAGES = (
    "freerdp2-x11",
    "libfreerdp-client2-2t64",
)

_MARKER = "bundle_ready_v1"


def runtime_dir() -> Path:
    return ensure_secure_dir(app_data_dir() / "runtime" / "freerdp")


def system_xfreerdp() -> Optional[str]:
    return find_executable(("xfreerdp3", "xfreerdp", "wlfreerdp", "wlfreerdp3"))


def bundled_xfreerdp() -> Optional[str]:
    root = runtime_dir()
    candidate = root / "usr" / "bin" / "xfreerdp"
    if candidate.is_file() and os.access(candidate, os.X_OK):
        if (root / _MARKER).is_file():
            return str(candidate)
    return None


def resolve_xfreerdp() -> Optional[str]:
    """Retorna caminho do xfreerdp: sistema ou bundle local."""
    return system_xfreerdp() or bundled_xfreerdp()


def freerdp_env(exe: str) -> dict[str, str]:
    """LD_LIBRARY_PATH quando usa binário embutido."""
    env = os.environ.copy()
    root = runtime_dir()
    lib = root / "usr" / "lib" / "x86_64-linux-gnu"
    if lib.is_dir() and str(root) in exe:
        prev = env.get("LD_LIBRARY_PATH", "")
        env["LD_LIBRARY_PATH"] = f"{lib}:{prev}" if prev else str(lib)
    return env


def is_ready() -> bool:
    return resolve_xfreerdp() is not None


def ensure_freerdp(progress_cb=None) -> tuple[bool, str]:
    """
    Garante FreeRDP disponível.
    1) Sistema PATH
    2) Bundle já baixado
    3) Baixa debs com apt-get download (sem root) e extrai
    """
    sys_exe = system_xfreerdp()
    if sys_exe:
        return True, f"Usando FreeRDP do sistema: {sys_exe}"

    bundled = bundled_xfreerdp()
    if bundled:
        return True, f"Usando FreeRDP embutido: {bundled}"

    if progress_cb:
        progress_cb("Baixando FreeRDP para o app (sem sudo)…")

    try:
        _download_and_extract(progress_cb)
    except Exception as exc:  # noqa: BLE001
        logger.error(sanitize_for_log("Falha ao embutir FreeRDP", error=str(exc)))
        return (
            False,
            f"Não foi possível obter FreeRDP automaticamente: {exc}\n\n"
            "Instale manualmente:\n  sudo apt install freerdp2-x11",
        )

    bundled = bundled_xfreerdp()
    if not bundled:
        return False, "Download concluído, mas xfreerdp não foi encontrado no bundle."

    # test run
    env = freerdp_env(bundled)
    try:
        r = subprocess.run(
            [bundled, "/version"],
            capture_output=True,
            text=True,
            timeout=10,
            env=env,
            shell=False,
        )
        if r.returncode != 0 and not (r.stdout or r.stderr):
            return False, "xfreerdp embutido não executou corretamente."
    except Exception as exc:  # noqa: BLE001
        return False, f"Falha ao testar xfreerdp embutido: {exc}"

    if progress_cb:
        progress_cb("FreeRDP pronto (embutido no app).")
    return True, f"FreeRDP embutido pronto: {bundled}"


def _download_and_extract(progress_cb=None) -> None:
    root = runtime_dir()
    # limpar parcial
    for child in root.iterdir():
        if child.name == _MARKER:
            continue
        if child.is_dir():
            shutil.rmtree(child, ignore_errors=True)
        else:
            try:
                child.unlink()
            except OSError:
                pass

    with tempfile.TemporaryDirectory(prefix="nzxs-frdp-") as tmp:
        tmp_path = Path(tmp)
        # apt-get download
        cmd = ["apt-get", "download", *_PACKAGES]
        if progress_cb:
            progress_cb("apt-get download " + " ".join(_PACKAGES))
        r = subprocess.run(
            cmd,
            cwd=str(tmp_path),
            capture_output=True,
            text=True,
            timeout=120,
            shell=False,
        )
        if r.returncode != 0:
            # fallback: URLs diretas Ubuntu noble
            if progress_cb:
                progress_cb("apt-get falhou; tentando download HTTP…")
            _http_download_debs(tmp_path)
        debs = list(tmp_path.glob("*.deb"))
        if not debs:
            raise RuntimeError(
                "Nenhum .deb baixado. Verifique rede/apt.\n" + (r.stderr or "")
            )
        for deb in debs:
            if progress_cb:
                progress_cb(f"Extraindo {deb.name}…")
            subprocess.run(
                ["dpkg-deb", "-x", str(deb), str(root)],
                check=True,
                capture_output=True,
                shell=False,
            )

    exe = root / "usr" / "bin" / "xfreerdp"
    if not exe.is_file():
        raise RuntimeError("xfreerdp não encontrado após extração")
    exe.chmod(0o755)
    (root / _MARKER).write_text("ok\n", encoding="utf-8")
    logger.info(sanitize_for_log("FreeRDP embutido instalado", path=str(exe)))


def _http_download_debs(dest: Path) -> None:
    """Fallback HTTP para Ubuntu 24.04 amd64."""
    base = "http://archive.ubuntu.com/ubuntu/pool/universe/f/freerdp2"
    files = [
        "freerdp2-x11_2.11.5+dfsg1-1build2_amd64.deb",
        "libfreerdp-client2-2t64_2.11.5+dfsg1-1build2_amd64.deb",
    ]
    for name in files:
        url = f"{base}/{name}"
        target = dest / name
        urlretrieve(url, str(target))  # noqa: S310 — URL fixa conhecida
