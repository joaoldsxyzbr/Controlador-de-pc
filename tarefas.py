"""Tarefas PowerShell em segundo plano, com saida limitada e cancelamento.

O registro existe somente na memoria do processo MCP. Nao persiste comandos,
credenciais ou resultados em arquivos; reiniciar o servidor perde os estados.
"""

import atexit
import secrets
import subprocess
import threading
import time

import core

MAX_ATIVAS = 3
MAX_HISTORICO = 24
RETENCAO_SEGUNDOS = 600


class Gerenciador:
    def __init__(self):
        self._lock = threading.RLock()
        self._jobs = {}

    def _limpar(self):
        """Chamado com _lock; nao remove processos ainda ativos."""
        agora = time.monotonic()
        for identificador, job in list(self._jobs.items()):
            if job["fim"] is not None and agora - job["fim"] >= RETENCAO_SEGUNDOS:
                del self._jobs[identificador]
        concluidos = sorted(
            (job for job in self._jobs.values() if job["fim"] is not None),
            key=lambda job: job["fim"],
        )
        for job in concluidos[:-MAX_HISTORICO]:
            self._jobs.pop(job["id"], None)

    @staticmethod
    def _snapshot(job, incluir_saida=True):
        with job["lock"]:
            resultado = {
                "ok": job["status"] == "concluido" if job["fim"] is not None else None,
                "id": job["id"],
                "status": job["status"],
                "codigo_saida": job["codigo_saida"],
                "tempo_esgotado": job["status"] == "tempo_esgotado",
                "saida_truncada": job["truncado"],
                "duracao_ms": int(((job["fim"] or time.monotonic()) - job["inicio"]) * 1000),
            }
            if incluir_saida:
                resultado["stdout"] = bytes(job["stdout"]).decode("utf-8", errors="replace")
                resultado["stderr"] = bytes(job["stderr"]).decode("utf-8", errors="replace")
            return resultado

    @staticmethod
    def _drenar(job, nome):
        fluxo = getattr(job["processo"], nome)
        try:
            while True:
                bloco = fluxo.read1(4096) if hasattr(fluxo, "read1") else fluxo.read(4096)
                if not bloco:
                    break
                with job["lock"]:
                    buffer = job[nome]
                    restante = max(0, core.LIMITE_SAIDA_BYTES - len(buffer))
                    buffer.extend(bloco[:restante])
                    if len(bloco) > restante:
                        job["truncado"] = True
        except OSError:
            with job["lock"]:
                job["truncado"] = True
        finally:
            fluxo.close()

    def _observar(self, job):
        p = job["processo"]
        leitores = [
            threading.Thread(target=self._drenar, args=(job, campo), daemon=True)
            for campo in ("stdout", "stderr")
        ]
        for leitor in leitores:
            leitor.start()
        expirou = False
        falhou = False
        try:
            try:
                p.wait(timeout=job["timeout"])
            except subprocess.TimeoutExpired:
                expirou = True
                core.encerrar_arvore(p)
                p.wait(timeout=5)
        except (OSError, subprocess.SubprocessError):
            falhou = True
            core.encerrar_arvore(p)

        for leitor in leitores:
            leitor.join(timeout=3)
        with job["lock"]:
            if job["cancelado"]:
                job["status"] = "cancelado"
            elif expirou:
                job["status"] = "tempo_esgotado"
            elif falhou:
                job["status"] = "falhou"
            else:
                job["status"] = "concluido" if p.returncode == 0 else "falhou"
            job["codigo_saida"] = None if expirou else p.returncode
            job["fim"] = time.monotonic()

    def iniciar(self, comando: str, diretorio: str = "", timeout_segundos: int = 120) -> dict:
        preparado = core.preparar(comando, diretorio, timeout_segundos, core.TIMEOUT_TAREFA_MAXIMO)
        if not preparado["ok"]:
            return preparado
        with self._lock:
            self._limpar()
            ativos = sum(j["fim"] is None for j in self._jobs.values())
            if ativos >= MAX_ATIVAS:
                return core._erro("limite_tarefas", f"Limite de {MAX_ATIVAS} tarefas simultaneas.")
            try:
                processo = subprocess.Popen(
                    preparado["argumentos"], cwd=preparado["pasta"], env=preparado["ambiente"],
                    stdin=subprocess.DEVNULL, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                    shell=False, creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
                )
            except (OSError, subprocess.SubprocessError) as exc:
                return core._erro("falha_execucao", f"Falha ao iniciar tarefa: {type(exc).__name__}.")
            identificador = secrets.token_urlsafe(18)
            job = {
                "id": identificador, "processo": processo, "inicio": time.monotonic(),
                "fim": None, "status": "executando", "stdout": bytearray(),
                "stderr": bytearray(), "truncado": False, "cancelado": False,
                "codigo_saida": None, "timeout": timeout_segundos,
                "lock": threading.RLock(),
            }
            self._jobs[identificador] = job
            threading.Thread(target=self._observar, args=(job,), daemon=True).start()
            return {"ok": True, "id": identificador, "status": "executando",
                    "timeout_segundos": timeout_segundos}

    def consultar(self, identificador: str) -> dict:
        with self._lock:
            self._limpar()
            job = self._jobs.get(identificador) if isinstance(identificador, str) else None
        if not job:
            return core._erro("tarefa_inexistente", "Tarefa nao encontrada ou expirada.")
        return self._snapshot(job)

    def listar(self) -> dict:
        with self._lock:
            self._limpar()
            jobs = list(self._jobs.values())
        return {"ok": True, "tarefas": [self._snapshot(job, incluir_saida=False) for job in jobs]}

    def cancelar(self, identificador: str) -> dict:
        with self._lock:
            self._limpar()
            job = self._jobs.get(identificador) if isinstance(identificador, str) else None
        if not job:
            return core._erro("tarefa_inexistente", "Tarefa nao encontrada ou expirada.")
        with job["lock"]:
            if job["fim"] is not None:
                return core._erro("tarefa_encerrada", "A tarefa ja terminou.")
            job["cancelado"] = True
        core.encerrar_arvore(job["processo"])
        return {"ok": True, "id": identificador, "status": "cancelamento_solicitado"}

    def encerrar_todos(self):
        with self._lock:
            jobs = [j for j in self._jobs.values() if j["fim"] is None]
        for job in jobs:
            core.encerrar_arvore(job["processo"])


gerenciador = Gerenciador()
atexit.register(gerenciador.encerrar_todos)
