"""Testes reais do motor assincrono com processos Python inofensivos."""

import os
from pathlib import Path
import sys
import time
import unittest
from unittest import mock

import core
import politica
from tarefas import Gerenciador, MAX_ATIVAS


def preparado(script):
    return {
        "ok": True,
        "argumentos": [sys.executable, "-X", "utf8", "-u", "-c", script],
        "pasta": str(Path.cwd()),
        "ambiente": os.environ.copy(),
    }


def esperar(gerenciador, id, limite=7):
    prazo = time.monotonic() + limite
    while time.monotonic() < prazo:
        retorno = gerenciador.consultar(id)
        if retorno["status"] != "executando":
            return retorno
        time.sleep(0.025)
    raise AssertionError(f"Tarefa {id} nao finalizou em {limite} segundos")


class TesteTarefas(unittest.TestCase):
    def setUp(self):
        self.gerenciador = Gerenciador()
        self.addCleanup(self.gerenciador.encerrar_todos)

    def iniciar_python(self, script, timeout=10):
        with mock.patch.object(core, "preparar", return_value=preparado(script)):
            return self.gerenciador.iniciar("teste", timeout_segundos=timeout)

    def test_execucao_assincrona_e_retorno_estruturado(self):
        r = self.iniciar_python("print('ola terminal')", 10)
        self.assertTrue(r["ok"])
        fim = esperar(self.gerenciador, r["id"])
        self.assertEqual(fim["status"], "concluido")
        self.assertEqual(fim["codigo_saida"], 0)
        self.assertIn("ola terminal", fim["stdout"])
        self.assertIsInstance(fim["duracao_ms"], int)
        self.assertFalse(fim["saida_truncada"])
        self.assertTrue(fim["ok"])

    def test_falha_com_codigo_saida(self):
        r = self.iniciar_python("raise SystemExit(7)")
        fim = esperar(self.gerenciador, r["id"])
        self.assertEqual(fim["status"], "falhou")
        self.assertEqual(fim["codigo_saida"], 7)
        self.assertFalse(fim["ok"])

    def test_limite_memoria_sem_bloqueio_de_pipe(self):
        r = self.iniciar_python("import sys;sys.stdout.write('A'*50000);sys.stderr.write('B'*50000)")
        fim = esperar(self.gerenciador, r["id"])
        self.assertEqual(fim["status"], "concluido")
        self.assertTrue(fim["saida_truncada"])
        self.assertEqual(len(fim["stdout"]), core.LIMITE_SAIDA_BYTES)
        self.assertEqual(len(fim["stderr"]), core.LIMITE_SAIDA_BYTES)

    def test_cancelamento_de_processo_proprio(self):
        r = self.iniciar_python("import time;time.sleep(15)")
        self.assertEqual(self.gerenciador.cancelar(r["id"])["status"], "cancelamento_solicitado")
        fim = esperar(self.gerenciador, r["id"])
        self.assertEqual(fim["status"], "cancelado")
        self.assertFalse(fim["ok"])

    def test_timeout_encerra_processo(self):
        r = self.iniciar_python("import time;time.sleep(15)", timeout=1)
        fim = esperar(self.gerenciador, r["id"])
        self.assertEqual(fim["status"], "tempo_esgotado")
        self.assertTrue(fim["tempo_esgotado"])

    def test_limite_simultaneo(self):
        ids = [self.iniciar_python("import time;time.sleep(15)")["id"] for _ in range(MAX_ATIVAS)]
        excedente = self.iniciar_python("print('excedente')")
        self.assertEqual(excedente["erro"], "limite_tarefas")
        for id in ids:
            self.gerenciador.cancelar(id)
            esperar(self.gerenciador, id)

    def test_listagem_nao_divulga_saidas(self):
        r = self.iniciar_python("print('informacao')", timeout=10)
        esperar(self.gerenciador, r["id"])
        resultado = self.gerenciador.listar()
        self.assertTrue(resultado["ok"])
        self.assertEqual(len(resultado["tarefas"]), 1)
        self.assertNotIn("stdout", resultado["tarefas"][0])
        self.assertNotIn("stderr", resultado["tarefas"][0])
        self.assertEqual(self.gerenciador.consultar("id-invalido")["erro"], "tarefa_inexistente")
        self.assertEqual(self.gerenciador.cancelar(r["id"])["erro"], "tarefa_encerrada")

    def test_nao_inicia_sem_autorizacao_local(self):
        with mock.patch.object(core, "sistema_windows", return_value=True), \
             mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "0"}):
            r = self.gerenciador.iniciar("Get-Date")
        self.assertEqual(r["erro"], "terminal_desabilitado")


@unittest.skipUnless(os.name == "nt", "Smoke test exige Windows real")
class TesteWindowsReal(unittest.TestCase):
    def test_powershell_real(self):
        with mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"}), \
             mock.patch.object(politica, "permitir", return_value=True):
            r = core.executar("Write-Output 'P0-WINDOWS-OK'", timeout_segundos=15)
        self.assertTrue(r["ok"], r)
        self.assertIn("P0-WINDOWS-OK", r["stdout"])

    def test_tarefa_powershell_real(self):
        g = Gerenciador()
        self.addCleanup(g.encerrar_todos)
        with mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"}), \
             mock.patch.object(politica, "permitir", return_value=True):
            tarefa = g.iniciar("Write-Output 'P0-ASINCRONO-WINDOWS-OK'", timeout_segundos=15)
        self.assertTrue(tarefa["ok"], tarefa)
        retorno = esperar(g, tarefa["id"], limite=20)
        self.assertEqual(retorno["status"], "concluido", retorno)
        self.assertIn("P0-ASINCRONO-WINDOWS-OK", retorno["stdout"])


if __name__ == "__main__":
    unittest.main()
