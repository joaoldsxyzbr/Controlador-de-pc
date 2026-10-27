"""Integração MCP P2: analise offline nao gera efeitos colaterais."""

import unittest
from unittest import mock

import servidor


class TesteFerramentasIA(unittest.TestCase):
    def test_analise_textual_nao_chama_terminal(self):
        with mock.patch.object(servidor, "executar") as executar, \
             mock.patch.object(servidor.gerenciador, "iniciar") as iniciar:
            r = servidor.ia_analisar_erro("Permission denied while accessing directory", codigo_saida=1)
        self.assertTrue(r["ok"])
        self.assertEqual(r["categoria"], "acesso_negado")
        executar.assert_not_called()
        iniciar.assert_not_called()

    def test_analise_tarefa_nao_expoe_stdout_e_stderr(self):
        segredo = "TOKEN-PRIVADO-12345"
        with mock.patch.object(servidor.gerenciador, "consultar", return_value={
            "ok": False, "id": "id-teste", "status": "falhou",
            "stderr": f"Access is denied to the private path {segredo}",
            "stdout": f"nunca_exibir:{segredo}", "codigo_saida": 1,
            "tempo_esgotado": False,
        }) as consultar, mock.patch.object(servidor, "executar") as executar:
            r = servidor.ia_analisar_tarefa("id-teste")
        consultar.assert_called_once_with("id-teste")
        self.assertTrue(r["ok"])
        self.assertEqual(r["analise"]["categoria"], "acesso_negado")
        self.assertNotIn(segredo, str(r))
        executar.assert_not_called()

    def test_tarefa_inexistente_usa_mesmo_erro_do_gerenciador(self):
        with mock.patch.object(servidor.gerenciador, "consultar", return_value={
            "ok": False, "erro": "tarefa_inexistente", "mensagem": "Tarefa ausente."
        }):
            r = servidor.ia_analisar_tarefa("invalido")
        self.assertEqual(r["erro"], "tarefa_inexistente")

    def test_tarefa_pendente_nao_le_conteudo(self):
        with mock.patch.object(servidor.gerenciador, "consultar", return_value={
            "ok": None, "id": "r", "status": "executando", "stdout": "segredo",
            "stderr": "", "codigo_saida": None,
        }):
            r = servidor.ia_analisar_tarefa("r")
        self.assertEqual(r["categoria"], "aguardando")
        self.assertNotIn("segredo", str(r))

    def test_tarefa_concluida_sem_stderr_nao_afirma_efeito(self):
        with mock.patch.object(servidor.gerenciador, "consultar", return_value={
            "ok": True, "id": "r", "status": "concluido", "stdout": "informacao pessoal",
            "stderr": "", "codigo_saida": 0,
        }):
            r = servidor.ia_analisar_tarefa("r")
        self.assertEqual(r["categoria"], "sem_falha_reportada")
        self.assertNotIn("informacao pessoal", str(r))

    def test_falha_de_terminal_anexa_analise_sem_executar_outro_comando(self):
        retorno = {
            "ok": False, "codigo_saida": 1, "stderr": "Access denied. Permission denied",
            "stdout": "", "tempo_esgotado": False,
        }
        with mock.patch.object(servidor, "executar", return_value=retorno) as executar:
            resposta = servidor.terminal("Get-Content teste.txt")
        executar.assert_called_once_with(
            comando="Get-Content teste.txt", diretorio="", timeout_segundos=30
        )
        self.assertEqual(resposta["analise_ia"]["categoria"], "acesso_negado")

    def test_bloqueio_p1_nao_recebe_falso_diagnostico(self):
        retorno = {"ok": False, "erro": "aprovacao_local_necessaria",
                   "mensagem": "Use o autorizador local."}
        with mock.patch.object(servidor, "executar", return_value=retorno):
            resposta = servidor.terminal("Get-Date")
        self.assertEqual(resposta, retorno)
        self.assertNotIn("analise_ia", resposta)

    def test_consulta_tarefa_finalizada_falha_com_analise(self):
        retorno = {
            "ok": False, "id": "id", "status": "falhou", "codigo_saida": 1,
            "stderr": "The term is not recognized as the name of a cmdlet",
            "stdout": "", "tempo_esgotado": False,
        }
        with mock.patch.object(servidor.gerenciador, "consultar", return_value=retorno) as consultar:
            resposta = servidor.terminal_consultar("id")
        consultar.assert_called_once_with("id")
        self.assertEqual(resposta["analise_ia"]["categoria"], "comando_desconhecido")

    def test_sucesso_de_terminal_nao_gera_analise_desnecessaria(self):
        retorno = {"ok": True, "codigo_saida": 0, "stderr": "", "stdout": "ok"}
        with mock.patch.object(servidor, "executar", return_value=retorno):
            resposta = servidor.terminal("Write-Output ok")
        self.assertNotIn("analise_ia", resposta)

    def test_classificador_nao_modifica_permissoes(self):
        with mock.patch("politica.conceder") as conceder, \
             mock.patch("politica.permitir") as permitir, \
             mock.patch("subprocess.Popen") as popen:
            servidor.ia_analisar_erro("ModuleNotFoundError module not installed", codigo_saida=1)
        conceder.assert_not_called()
        permitir.assert_not_called()
        popen.assert_not_called()


if __name__ == "__main__":
    unittest.main()
