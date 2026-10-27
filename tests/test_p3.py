"""P3: aprendizado supervisionado somente de exemplos revisados via GitHub."""

import json
from pathlib import Path
import tempfile
import unittest
from unittest import mock

import mini_ia


class TesteAprendizadoP3(unittest.TestCase):
    def test_carrega_dataset_revisado_e_classifica_erros_novos(self):
        import aprendizado
        extras = aprendizado.carregar_exemplos(set(mini_ia.TREINO))
        self.assertGreaterEqual(len(extras), 7)
        self.assertTrue(all(categoria in mini_ia.TREINO for categoria, _ in extras))
        resposta = mini_ia.analisar("QuotaExceeded volume quota reached", codigo_saida=1)
        self.assertEqual(resposta["categoria"], "disco_cheio")

    def test_dataset_com_segredos_ou_campos_extras_e_rejeitado(self):
        import aprendizado
        casos = [
            [{"categoria": "acesso_negado", "texto": "Email particular pessoa@exemplo.com nao pode acessar"}],
            [{"categoria": "acesso_negado", "texto": "token sk-proj-1234567890 da pessoa"}],
            [{"categoria": "acesso_negado", "texto": "Acesso recusado sem permissao", "comando": "Get-Date"}],
            [{"categoria": "categoria_falsa", "texto": "Acesso recusado sem permissao"}],
            [{"categoria": "acesso_negado", "texto": "Acesso recusado sem permissao"}] * 2,
        ]
        with tempfile.TemporaryDirectory() as temp:
            arq = Path(temp) / "treino.json"
            for exemplos in casos:
                with self.subTest(exemplos=exemplos):
                    arq.write_text(json.dumps({"versao": 1, "exemplos": exemplos}), encoding="utf-8")
                    with self.assertRaises(ValueError):
                        aprendizado.carregar_exemplos(set(mini_ia.TREINO), caminho=arq)

    def test_dataset_ausente_ou_corrompido_rejeita_sem_fallback_silencioso(self):
        import aprendizado
        with tempfile.TemporaryDirectory() as temp:
            arq = Path(temp) / "inexistente.json"
            with self.assertRaises(ValueError):
                aprendizado.carregar_exemplos(set(mini_ia.TREINO), caminho=arq)
            arq.write_text("JSON incorreto", encoding="utf-8")
            with self.assertRaises(ValueError):
                aprendizado.carregar_exemplos(set(mini_ia.TREINO), caminho=arq)

    def test_avaliacao_rejeita_vazamento_entre_treino_e_holdout(self):
        import avaliacao_ia
        with self.assertRaises(ValueError):
            avaliacao_ia.verificar_separacao([
                ("disco_cheio", "Disco cheio ao gravar arquivo")
            ], [("disco_cheio", "DISCO CHEIO AO GRAVAR ARQUIVO")])

    def test_avaliacao_retorna_metricas_agrupadas_sem_texto_privado(self):
        import avaliacao_ia
        relatorio = avaliacao_ia.gerar_relatorio()
        self.assertEqual(relatorio["versao"], 1)
        self.assertIn("referencia_p2", relatorio)
        self.assertIn("candidato_p3", relatorio)
        self.assertIn("por_categoria", relatorio["candidato_p3"])
        self.assertNotIn("texto", str(relatorio))
        self.assertNotIn("comando", relatorio)
        self.assertIsInstance(relatorio["candidato_p3"]["acertos_conhecidos"], int)

    def test_avaliacao_detecta_regressao_de_precisao(self):
        import avaliacao_ia
        referencia = {"acertos_conhecidos": 13, "falsos_positivos_desconhecidos": 0}
        candidato = {"acertos_conhecidos": 12, "falsos_positivos_desconhecidos": 0}
        self.assertFalse(avaliacao_ia.sem_regressao(referencia, candidato))
        self.assertFalse(avaliacao_ia.sem_regressao(
            referencia, {"acertos_conhecidos": 14, "falsos_positivos_desconhecidos": 1}
        ))
        self.assertTrue(avaliacao_ia.sem_regressao(referencia, referencia))

    def test_classificador_permanece_sem_execucao_e_sem_registro_automatico(self):
        with mock.patch("subprocess.Popen") as processo, \
             mock.patch("politica.conceder") as conceder:
            resposta = mini_ia.analisar("QuotaExceeded volume quota reached", codigo_saida=1)
        self.assertTrue(resposta["ok"])
        processo.assert_not_called()
        conceder.assert_not_called()


if __name__ == "__main__":
    unittest.main()
