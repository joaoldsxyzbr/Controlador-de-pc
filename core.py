"""Execucao controlada de PowerShell no computador do proprio usuario.

A autorizacao ocorre localmente, no ambiente do processo que inicia o MCP.
O tunnel-client cuida do canal remoto; este modulo nao abre portas.
"""

import base64
import os
import subprocess
import tempfile
from pathlib import Path

LIMITE_COMANDO = 8000
LIMITE_SAIDA_BYTES = 12000
TIMEOUT_MAXIMO = 90


def sistema_windows() -> bool:
    return os.name == "nt"


def estado() -> dict:
    """Exibe um estado minimo sem divulgar usuario, diretorios ou credenciais."""
    return {
        "sistema": "Windows" if os.name == "nt" else "Nao Windows",
        "terminal_habilitado": os.environ.get("MEU_PC_HABILITADO") == "1",
        "transporte": "stdio (por Secure MCP Tunnel)",
    }


def _erro(tipo: str, mensagem: str) -> dict:
    return {"ok": False, "erro": tipo, "mensagem": mensagem}


def _ler_saida(arquivo) -> tuple[str, bool]:
    arquivo.seek(0, os.SEEK_END)
    tamanho = arquivo.tell()
    arquivo.seek(0)
    conteudo = arquivo.read(LIMITE_SAIDA_BYTES)
    return conteudo.decode("utf-8", errors="replace"), tamanho > LIMITE_SAIDA_BYTES


def executar(comando: str, diretorio: str = "", timeout_segundos: int = 30) -> dict:
    """Executa comando PowerShell com limites e autorizacao explicita local.

    O usuario controla inteiramente o comando: nao e sandbox. O processo
    possui os mesmos acessos do usuario Windows que iniciou o servidor.
    """
    if not sistema_windows():
        return _erro("sistema_nao_suportado", "Este agente foi criado para Windows.")
    if os.environ.get("MEU_PC_HABILITADO") != "1":
        return _erro("terminal_desabilitado", "Habilite MEU_PC_HABILITADO=1 localmente antes de iniciar o tunel.")
    if not isinstance(comando, str) or not comando.strip() or len(comando) > LIMITE_COMANDO or "\x00" in comando:
        return _erro("comando_invalido", f"Informe um comando PowerShell de ate {LIMITE_COMANDO} caracteres.")
    if isinstance(timeout_segundos, bool) or not isinstance(timeout_segundos, int) or not 1 <= timeout_segundos <= TIMEOUT_MAXIMO:
        return _erro("timeout_invalido", f"O tempo deve ficar entre 1 e {TIMEOUT_MAXIMO} segundos.")
    if not isinstance(diretorio, str) or "\x00" in diretorio:
        return _erro("diretorio_invalido", "Diretorio informado e invalido.")
    try:
        pasta = Path(diretorio).expanduser().resolve() if diretorio.strip() else Path.home()
        if not pasta.is_dir():
            return _erro("diretorio_invalido", "O diretorio de trabalho nao existe.")
    except (OSError, ValueError):
        return _erro("diretorio_invalido", "Nao foi possivel acessar o diretorio de trabalho.")

    # EncodedCommand evita erros de quoting e preserva caracteres especiais.
    # A codificacao nao limita o poder do comando: use apenas com um usuario confiavel.
    script = (
        "$ErrorActionPreference = 'Stop'\n"
        "[Console]::OutputEncoding = [System.Text.UTF8Encoding]::new()\n"
        "$OutputEncoding = [Console]::OutputEncoding\n"
        + comando
    )
    codificado = base64.b64encode(script.encode("utf-16-le")).decode("ascii")
    argumentos = ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive", "-EncodedCommand", codificado]

    ambiente = os.environ.copy()
    # Uma operacao de terminal nao precisa da chave que controla o tunel.
    for segredo in ("CONTROL_PLANE_API_KEY", "CONTROL_PLANE_TUNNEL_ID", "OPENAI_API_KEY", "OPENAI_ADMIN_KEY", "MEU_PC_HABILITADO"):
        ambiente.pop(segredo, None)

    try:
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            processo = subprocess.Popen(
                argumentos,
                cwd=str(pasta),
                env=ambiente,
                stdin=subprocess.DEVNULL,
                stdout=stdout,
                stderr=stderr,
                shell=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            expirou = False
            try:
                processo.wait(timeout=timeout_segundos)
            except subprocess.TimeoutExpired:
                expirou = True
                # Windows: encerra tambem os processos filhos, quando possivel.
                subprocess.run(
                    ["taskkill", "/PID", str(processo.pid), "/T", "/F"],
                    stdin=subprocess.DEVNULL,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                    timeout=5,
                    check=False,
                )
                try:
                    processo.kill()
                except ProcessLookupError:
                    pass  # O taskkill ja pode ter encerrado o processo.
                processo.wait(timeout=5)

            texto_saida, truncada_saida = _ler_saida(stdout)
            texto_erro, truncado_erro = _ler_saida(stderr)
            return {
                "ok": not expirou and processo.returncode == 0,
                "codigo_saida": None if expirou else processo.returncode,
                "stdout": texto_saida,
                "stderr": texto_erro,
                "saida_truncada": truncada_saida or truncado_erro,
                "tempo_esgotado": expirou,
            }
    except (OSError, subprocess.SubprocessError) as exc:
        # Erros de inicializacao e timeout de encerramento nao retornam dados sigilosos.
        return _erro("falha_execucao", f"Falha ao iniciar ou finalizar PowerShell: {type(exc).__name__}.")
