"""Execucao de PowerShell no Windows via servidor MCP privado.

Os comandos continuam sendo arbitrarios: nao ha sandbox.
O usuario habilita o terminal no processo local com MEU_PC_HABILITADO=1.
"""

import base64
import os
import subprocess
import tempfile
import time
from pathlib import Path

import politica

LIMITE_COMANDO = 8000
LIMITE_SAIDA_BYTES = 12000
TIMEOUT_MAXIMO = 90
TIMEOUT_TAREFA_MAXIMO = 600


def sistema_windows() -> bool:
    return os.name == "nt"


def estado() -> dict:
    """Diagnostico minimo, sem usuarios, caminhos ou credenciais."""
    return {
        "sistema": "Windows" if os.name == "nt" else "Nao Windows",
        "terminal_habilitado": os.environ.get("MEU_PC_HABILITADO") == "1",
        "transporte": "stdio (por Secure MCP Tunnel)",
        "politica": "comando_exato_uma_execucao",
    }


def _erro(tipo: str, mensagem: str) -> dict:
    return {"ok": False, "erro": tipo, "mensagem": mensagem}


def _ler_saida(arquivo) -> tuple[str, bool]:
    arquivo.seek(0, os.SEEK_END)
    tamanho = arquivo.tell()
    arquivo.seek(0)
    conteudo = arquivo.read(LIMITE_SAIDA_BYTES)
    return conteudo.decode("utf-8", errors="replace"), tamanho > LIMITE_SAIDA_BYTES


def preparar(comando: str, diretorio: str = "", timeout_segundos: int = 30,
             limite_timeout: int = TIMEOUT_MAXIMO) -> dict:
    """Valida e prepara a execucao sem iniciar nenhum processo.

    Retorno interno: contem ambiente e argumentos, nunca deve ser exposto pelo MCP.
    """
    if not sistema_windows():
        return _erro("sistema_nao_suportado", "Este agente foi criado para Windows.")
    if os.environ.get("MEU_PC_HABILITADO") != "1":
        return _erro("terminal_desabilitado", "Habilite MEU_PC_HABILITADO=1 no processo local.")
    if not isinstance(comando, str) or not comando.strip() or len(comando) > LIMITE_COMANDO or "\x00" in comando:
        return _erro("comando_invalido", f"Informe um comando PowerShell de ate {LIMITE_COMANDO} caracteres.")
    if isinstance(timeout_segundos, bool) or not isinstance(timeout_segundos, int) or not 1 <= timeout_segundos <= limite_timeout:
        return _erro("timeout_invalido", f"O tempo deve ficar entre 1 e {limite_timeout} segundos.")
    if not isinstance(diretorio, str) or "\x00" in diretorio:
        return _erro("diretorio_invalido", "Diretorio informado e invalido.")
    try:
        pasta = Path(diretorio).expanduser().resolve() if diretorio.strip() else Path.home()
        if not pasta.is_dir():
            return _erro("diretorio_invalido", "O diretorio de trabalho nao existe.")
    except (OSError, ValueError):
        return _erro("diretorio_invalido", "Nao foi possivel acessar o diretorio de trabalho.")

    # Uma validacao unica protege tanto terminal quanto terminal_iniciar.
    # Nao usar filtros de texto: PowerShell arbitrario exige aprovacao local exata.
    if not politica.permitir(comando, str(pasta)):
        return {
            "ok": False,
            "erro": "aprovacao_local_necessaria",
            "mensagem": (
                "Comando nao autorizado. No proprio Windows execute autorizar.py "
                "e confirme o comando exato; a permissao vale por 120 segundos e um uso."
            ),
            "assinatura": politica.assinatura(comando, str(pasta)),
        }

    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
        "$OutputEncoding = [Console]::OutputEncoding\n"
        + comando
    )
    codificado = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    argumentos = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", codificado]

    ambiente = os.environ.copy()
    for segredo in ("CONTROL_PLANE_API_KEY", "CONTROL_PLANE_TUNNEL_ID",
                    "OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "MEU_PC_HABILITADO"):
        ambiente.pop(segredo, None)

    return {"ok": True, "argumentos": argumentos, "pasta": str(pasta), "ambiente": ambiente}


def encerrar_arvore(processo) -> None:
    """Tenta encerrar processo e filhos Windows; nunca aceita PID arbitrario."""
    if hasattr(processo, "poll") and processo.poll() is not None:
        return
    try:
        subprocess.run(
            ["taskkill", "/PID", str(processo.pid), "/T", "/F"],
            stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL, timeout=5, check=False,
        )
    except (OSError, subprocess.SubprocessError):
        pass
    try:
        if not hasattr(processo, "poll") or processo.poll() is None:
            processo.kill()
    except (OSError, ProcessLookupError):
        pass


def executar(comando: str, diretorio: str = "", timeout_segundos: int = 30) -> dict:
    """Modo sincrono, compativel com a ferramenta MCP terminal existente."""
    preparado = preparar(comando, diretorio, timeout_segundos)
    if not preparado["ok"]:
        return preparado

    inicio = time.monotonic()
    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            processo = subprocess.Popen(
                preparado["argumentos"],
                cwd=preparado["pasta"], env=preparado["ambiente"],
                stdin=subprocess.DEVNULL, stdout=stdout, stderr=stderr,
                shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            expirou = False
            try:
                processo.wait(timeout=timeout_segundos)
            except subprocess.TimeoutExpired:
                expirou = True
                encerrar_arvore(processo)
                try:
                    processo.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    return _erro("falha_encerramento", "Nao foi possivel confirmar o encerramento do processo.")

            texto_saida, truncada_saida = _ler_saida(stdout)
            texto_erro, truncado_erro = _ler_saida(stderr)
            return {
                "ok": not expirou and processo.returncode == 0,
                "codigo_saida": None if expirou else processo.returncode,
                "stdout": texto_saida,
                "stderr": texto_erro,
                "saida_truncada": truncada_saida or truncado_erro,
                "tempo_esgotado": expirou,
                "duracao_ms": int((time.monotonic() - inicio) * 1000),
            }
    except (OSError, subprocess.SubprocessError) as exc:
        return _erro("falha_execucao", f"Falha no PowerShell: {type(exc).__name__}.")
