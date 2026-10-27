"""P1: autorizacao local estrita, expiracao e permissao de uso unico."""

import os
from pathlib import Path
import tempfile
import threading
import unittest
from unittest import mock

import core
import politica
from tarefas import Gerenciador


class TestePolitica(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.pasta = Path(self.temp.name)
        self.patch_pasta = mock.patch.object(politica, "_pasta_aprovacoes",
                                            return_value=self.pasta / "aprovacoes")
        self.patch_pasta.start()
        self.addCleanup(self.patch_pasta.stop)
        self.env = mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.windows = mock.patch.object(core, "sistema_windows", return_value=True)
        self.windows.start()
        self.addCleanup(self.windows.stop)

    def test_comando_livre_negado_por_padrao_sem_iniciar_processo(self):
        with mock.patch.object(core.subprocess, "Popen") as iniciar:
            r = core.executar("Remove-Item C:/teste -Recurse", diretorio=str(self.pasta))
        self.assertEqual(r["erro"], "aprovacao_local_necessaria")
        self.assertEqual(len(r["assinatura"]), 64)
        iniciar.assert_not_called()

    def test_assinatura_diferencia_comando_e_diretorio(self):
        a = politica.assinatura("Get-Date", str(self.pasta))
        self.assertNotEqual(a, politica.assinatura("Get-Date; exit", str(self.pasta)))
        self.assertNotEqual(a, politica.assinatura("Get-Date", str(self.pasta / "outro")))

    def test_aprovacao_uma_vez_e_exata(self):
        comando = "Get-Date"
        politica.conceder(comando, str(self.pasta))
        self.assertFalse(politica.permitir("Get-Date ; Write-Output 1", str(self.pasta)))
        self.assertFalse(politica.permitir(comando, str(Path.home())))
        self.assertTrue(politica.permitir(comando, str(self.pasta)))
        self.assertFalse(politica.permitir(comando, str(self.pasta)))

    def test_expiracao_nega(self):
        comando = "Get-Date"
        politica.conceder(comando, str(self.pasta))
        with mock.patch.object(politica.time, "time", return_value=politica.time.time() + 300):
            self.assertFalse(politica.permitir(comando, str(self.pasta)))

    def test_protecao_concorrente_um_unico_consumidor(self):
        politica.conceder("Get-Date", str(self.pasta))
        resultados = []
        barreira = threading.Barrier(5)

        def usar():
            barreira.wait()
            resultados.append(politica.permitir("Get-Date", str(self.pasta)))

        threads = [threading.Thread(target=usar) for _ in range(5)]
        for thread in threads:
            thread.start()
        for thread in threads:
            thread.join()
        self.assertEqual(resultados.count(True), 1)

    def test_consulta_fixa_sem_aprovacao(self):
        r = core.preparar(politica.CONSULTAS["sistema"])
        self.assertTrue(r["ok"], r)
        r = core.preparar(politica.CONSULTAS["sistema"] + "; Remove-Item C:/")
        self.assertEqual(r["erro"], "aprovacao_local_necessaria")

    def test_async_nao_inicia_comando_nao_aprovado(self):
        gerente = Gerenciador()
        with mock.patch("tarefas.subprocess.Popen") as popen:
            resultado = gerente.iniciar("Set-Content -Path a.txt -Value teste", diretorio=str(self.pasta))
        self.assertEqual(resultado["erro"], "aprovacao_local_necessaria")
        popen.assert_not_called()

    def test_aprovacao_so_apos_validacoes_anteriores(self):
        politica.conceder("Get-Date", str(self.pasta))
        self.assertEqual(core.preparar("Get-Date", str(self.pasta), timeout_segundos=0)["erro"], "timeout_invalido")
        self.assertTrue(core.preparar("Get-Date", str(self.pasta))["ok"])
        self.assertEqual(core.preparar("Get-Date", str(self.pasta))["erro"], "aprovacao_local_necessaria")

    def test_arquivo_contem_so_hash_e_validade(self):
        comando = "Write-Output 'nao salvar comando sensivel'"
        politica.conceder(comando, str(self.pasta))
        arquivos = list((self.pasta / "aprovacoes").glob("*.permit"))
        self.assertEqual(len(arquivos), 1)
        self.assertNotIn(comando, arquivos[0].read_text(encoding="ascii"))
        self.assertTrue(arquivos[0].name.endswith(".permit"))

    def test_input_invalido_nao_autoriza(self):
        for valor in ("", " ", "x" * 8001, "a\x00b"):
            with self.assertRaises(ValueError):
                politica.conceder(valor, str(self.pasta))



@unittest.skipUnless(os.name == "nt", "Execucao end-to-end exige Windows")
class TesteWindowsAprovacaoReal(unittest.TestCase):
    def test_aprovar_executar_uma_vez_e_bloquear_repeticao(self):
        comando = "Write-Output 'P1-AUTORIZACAO-OK'"
        with tempfile.TemporaryDirectory() as pasta, \
             mock.patch.object(politica, "_pasta_aprovacoes", return_value=Path(pasta)), \
             mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"}):
            politica.conceder(comando, str(Path.home().resolve()))
            resposta = core.executar(comando, timeout_segundos=20)
            self.assertTrue(resposta["ok"], resposta)
            self.assertIn("P1-AUTORIZACAO-OK", resposta["stdout"])
            repeticao = core.executar(comando, timeout_segundos=20)
            self.assertEqual(repeticao["erro"], "aprovacao_local_necessaria")


if __name__ == "__main__":
    unittest.main()
