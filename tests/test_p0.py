"""Regressoes do motor de terminal P0 (sem executar PowerShell no CI Linux)."""

import os
import unittest
from unittest import mock

import core
import politica


class ProcessoFake:
    pid = 321
    returncode = 0

    def __init__(self, stdout, stderr):
        self.stdout = stdout
        self.stderr = stderr

    def wait(self, timeout):
        self.stdout.write(b"ok\n")
        return 0

    def kill(self):
        pass


class TesteTerminalP0(unittest.TestCase):
    def test_execucao_informa_duracao_sem_quebrar_retorno_antigo(self):
        with mock.patch.object(core, "sistema_windows", return_value=True), \
             mock.patch.dict(os.environ, {"MEU_PC_HABILITADO": "1"}), \
             mock.patch.object(politica, "permitir", return_value=True), \
             mock.patch.object(core.subprocess, "Popen",
                               side_effect=lambda args, **kw: ProcessoFake(kw["stdout"], kw["stderr"])):
            retorno = core.executar("Write-Output ok")
        self.assertTrue(retorno["ok"])
        self.assertEqual(retorno["stdout"], "ok\n")
        self.assertIsInstance(retorno["duracao_ms"], int)
        self.assertGreaterEqual(retorno["duracao_ms"], 0)


if __name__ == "__main__":
    unittest.main()
