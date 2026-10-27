"""Testes do controle local sem acessar um PC Windows real."""

import base64
import os
import subprocess
import unittest
from pathlib import Path
from unittest import mock

import core
import politica


class ProcessoFalso:
    def __init__(self, stdout, stderr, saida=b"ok\n", erro=b"", codigo=0, estourar=False):
        self.pid = 4242
        self.returncode = codigo
        self._stdout = stdout
        self._stderr = stderr
        self._saida = saida
        self._erro = erro
        self._estourar = estourar

    def wait(self, timeout):
        self._stdout.write(self._saida)
        self._stderr.write(self._erro)
        if self._estourar:
            self._estourar = False
            raise subprocess.TimeoutExpired(cmd="powershell.exe", timeout=timeout)
        return self.returncode

    def kill(self):
        pass


class TesteControle(unittest.TestCase):
    def setUp(self):
        self.env = mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"})
        self.env.start()
        self.windows = mock.patch.object(core, "sistema_windows", return_value=True)
        self.windows.start()
        self.addCleanup(self.env.stop)
        self.addCleanup(self.windows.stop)
        self.permitir = mock.patch.object(politica, "permitir", return_value=True)
        self.permitir.start()
        self.addCleanup(self.permitir.stop)

    def test_bloqueado_por_padrao(self):
        with mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "0"}):
            r = core.executar("Get-Date")
        self.assertFalse(r["ok"])
        self.assertEqual(r["erro"], "terminal_desabilitado")

    def test_impede_uso_em_outro_sistema(self):
        with mock.patch.object(core, "sistema_windows", return_value=False):
            r = core.executar("Get-Date")
        self.assertEqual(r["erro"], "sistema_nao_suportado")

    def test_validacao_entrada(self):
        for comando in ("", "   ", "a" * 8001):
            with self.subTest(comando=comando[:10]):
                self.assertEqual(core.executar(comando)["erro"], "comando_invalido")
        for tempo in (0, 91):
            with self.subTest(tempo=tempo):
                self.assertEqual(core.executar("Get-Date", timeout_segundos=tempo)["erro"], "timeout_invalido")
        self.assertEqual(core.executar("Get-Date", diretorio="Z:/inexistente/aqui")["erro"], "diretorio_invalido")

    def test_execucao_retorna_saida_sem_shell_e_sem_credenciais_do_tunel(self):
        chamadas = []

        def iniciar(argumentos, **kwargs):
            chamadas.append((argumentos, kwargs))
            return ProcessoFalso(kwargs["stdout"], kwargs["stderr"], saida="Olá, PC!\n".encode(), codigo=0)

        with mock.patch.dict(os.environ, {"CONTROL_PLANE_API_KEY": "chave-que-nao-pode-vazar", "OPENAI_ADMIN_KEY": "chave-admin"}), \
                mock.patch.object(core.subprocess, "Popen", side_effect=iniciar):
            resposta = core.executar('Write-Output "Olá, PC!"', diretorio=str(Path.home()), timeout_segundos=12)

        self.assertTrue(resposta["ok"])
        self.assertEqual(resposta["stdout"], "Olá, PC!\n")
        self.assertEqual(resposta["codigo_saida"], 0)
        argumentos, kwargs = chamadas[0]
        self.assertEqual(argumentos[:4], ["powershell.exe", "-NoLogo", "-NoProfile", "-NonInteractive"])
        self.assertFalse(kwargs["shell"])
        script = base64.b64decode(argumentos[-1]).decode("utf-16-le")
        self.assertIn('Write-Output "Olá, PC!"', script)
        self.assertNotIn("CONTROL_PLANE_API_KEY", kwargs["env"])
        self.assertNotIn("OPENAI_ADMIN_KEY", kwargs["env"])
        self.assertNotIn("MEU_PC_HABILITADO", kwargs["env"])

    def test_saida_grande_e_limitada(self):
        with mock.patch.object(core.subprocess, "Popen", side_effect=lambda *args, **kwargs: ProcessoFalso(kwargs["stdout"], kwargs["stderr"], saida=b"A" * 20000)):
            r = core.executar("Get-Date")
        self.assertTrue(r["ok"])
        self.assertTrue(r["saida_truncada"])
        self.assertLessEqual(len(r["stdout"]), core.LIMITE_SAIDA_BYTES)

    def test_comando_com_erro_retorna_codigo(self):
        with mock.patch.object(core.subprocess, "Popen", side_effect=lambda *args, **kwargs: ProcessoFalso(kwargs["stdout"], kwargs["stderr"], erro=b"falhou", codigo=3)):
            r = core.executar("exit 3")
        self.assertFalse(r["ok"])
        self.assertEqual(r["codigo_saida"], 3)
        self.assertEqual(r["stderr"], "falhou")

    def test_timeout_encerra_processo(self):
        with mock.patch.object(core.subprocess, "Popen", side_effect=lambda *args, **kwargs: ProcessoFalso(kwargs["stdout"], kwargs["stderr"], estourar=True)), \
             mock.patch.object(core.subprocess, "run") as terminar:
            r = core.executar("Start-Sleep -Seconds 99", timeout_segundos=1)
        self.assertFalse(r["ok"])
        self.assertTrue(r["tempo_esgotado"])
        terminar.assert_called_once()
        self.assertEqual(terminar.call_args.args[0], ["taskkill", "/PID", "4242", "/T", "/F"])

    def test_estado_expoe_diagnostico_minimo(self):
        r = core.estado()
        self.assertEqual(r["sistema"], "Windows" if os.name == "nt" else "Nao Windows")
        self.assertIn("terminal_habilitado", r)
        self.assertNotIn("chave", str(r).lower())


if __name__ == "__main__":
    unittest.main()
