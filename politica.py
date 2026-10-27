"""Politica P1: diagnosticos fixos ou aprovacao LOCAL para PowerShell arbitrario.

Isto nao e sandbox: apenas exige consentimento local por comando exato.
O arquivo de aprovacao contem exclusivamente assinatura SHA-256 e expiracao.
"""

import hashlib
import json
import os
from pathlib import Path
import secrets
import time

VALIDADE_SEGUNDOS = 120
MAX_COMANDO = 8000

CONSULTAS = {
    "sistema": (
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object Caption,Version,BuildNumber | ConvertTo-Json -Compress"
    ),
    "memoria": (
        "Get-CimInstance Win32_OperatingSystem | "
        "Select-Object TotalVisibleMemorySize,FreePhysicalMemory | ConvertTo-Json -Compress"
    ),
    "processos": (
        "Get-Process | Sort-Object CPU -Descending | Select-Object -First 15 "
        "Name,Id,CPU,WorkingSet64 | ConvertTo-Json -Compress"
    ),
    "discos": (
        "Get-CimInstance Win32_LogicalDisk | "
        "Select-Object DeviceID,Size,FreeSpace | ConvertTo-Json -Compress"
    ),
}


def _pasta_aprovacoes() -> Path:
    raiz = os.environ.get("LOCALAPPDATA")
    base = Path(raiz) if raiz else Path.home() / ".controlador-de-pc"
    return base / "ControladorDePC" / "aprovacoes"


def assinatura(comando: str, diretorio: str) -> str:
    """Vincula autorizacao ao texto exato e diretorio de trabalho normalizado."""
    payload = json.dumps([comando, os.path.normcase(os.path.normpath(diretorio))],
                         ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def comando_consulta(tipo: str) -> str | None:
    return CONSULTAS.get(tipo) if isinstance(tipo, str) else None


def _consulta_aprovada(comando: str, diretorio: str) -> bool:
    return (comando in CONSULTAS.values()
            and os.path.normcase(os.path.normpath(diretorio))
            == os.path.normcase(os.path.normpath(str(Path.home().resolve()))))


def conceder(comando: str, diretorio: str) -> str:
    """API destinada APENAS ao processo local de autorizacao, nao ao MCP."""
    if (not isinstance(comando, str) or not comando.strip()
            or len(comando) > MAX_COMANDO or "\x00" in comando):
        raise ValueError("Comando invalido.")
    if not isinstance(diretorio, str) or not Path(diretorio).is_dir():
        raise ValueError("Diretorio invalido.")
    pasta = _pasta_aprovacoes()
    pasta.mkdir(parents=True, exist_ok=True, mode=0o700)
    digest = assinatura(comando, diretorio)
    destino = pasta / (digest + ".permit")
    temporario = pasta / (secrets.token_hex(16) + ".tmp")
    try:
        fd = os.open(str(temporario), os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        with os.fdopen(fd, "w", encoding="ascii") as f:
            f.write(str(time.time() + VALIDADE_SEGUNDOS))
        os.replace(temporario, destino)
    finally:
        temporario.unlink(missing_ok=True)
    return digest


def _consumir(comando: str, diretorio: str) -> bool:
    """Renomeacao atomica remove permissao da fila antes de conferir validade."""
    pasta = _pasta_aprovacoes()
    caminho = pasta / (assinatura(comando, diretorio) + ".permit")
    reivindicado = pasta / (secrets.token_hex(16) + ".claimed")
    try:
        os.rename(caminho, reivindicado)
    except OSError:
        return False
    try:
        expira = float(reivindicado.read_text(encoding="ascii").strip())
        return 0 < expira - time.time() <= VALIDADE_SEGUNDOS
    except (OSError, ValueError, OverflowError):
        return False
    finally:
        reivindicado.unlink(missing_ok=True)


def permitir(comando: str, diretorio: str) -> bool:
    """Nega por padrao. Nunca faz parse 'seguro' de texto PowerShell."""
    if _consulta_aprovada(comando, diretorio):
        return True
    return _consumir(comando, diretorio)
