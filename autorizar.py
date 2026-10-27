"""Autorizacao LOCAL e interativa: nao e ferramenta MCP.

Exemplos:
  py autorizar.py
  py autorizar.py --arquivo comando.ps1 --diretorio C:/Projetos

O conteudo do comando nao e gravado no arquivo de aprovacao.
"""

import argparse
from pathlib import Path
import os
import sys

import politica


def main() -> int:
    parser = argparse.ArgumentParser(description="Permite UMA execucao PowerShell exata por 120 segundos")
    parser.add_argument("--arquivo", help="Arquivo local com comando PowerShell multilinha")
    parser.add_argument("--diretorio", default="", help="Diretorio de trabalho usado pelo MCP")
    argumentos = parser.parse_args()
    if os.name != "nt":
        print("A aprovacao local deste projeto deve ser realizada no Windows.", file=sys.stderr)
        return 2
    try:
        diretorio = (Path(argumentos.diretorio).expanduser().resolve()
                     if argumentos.diretorio else Path.home().resolve())
        if not diretorio.is_dir():
            raise ValueError("Diretorio nao existe.")
        if argumentos.arquivo:
            comando = Path(argumentos.arquivo).read_text(encoding="utf-8-sig")
        else:
            print("Cole o comando PowerShell EXATO em uma linha (sem aspas extras):")
            comando = input("> ")
        if not comando.strip() or len(comando) > politica.MAX_COMANDO or "\x00" in comando:
            raise ValueError("Comando invalido.")
    except (ValueError, OSError, UnicodeError, EOFError) as exc:
        print(f"Nao foi possivel preparar a aprovacao: {type(exc).__name__}", file=sys.stderr)
        return 2

    resumo = politica.assinatura(comando, str(diretorio))
    print("\n--- CONFIRA NO PC O COMANDO COMPLETO ---")
    print(comando)
    print("----------------------------------------")
    print(f"Diretorio: {diretorio}")
    print(f"Assinatura SHA-256: {resumo}")
    print("AVISO: pode executar qualquer operacao permitida pela conta Windows.")
    print("Nao aprove comandos desconhecidos, mesmo enviados por chat ou arquivos.")
    if input("Digite AUTORIZAR para permitir uma unica execucao por 120 segundos: ").strip() != "AUTORIZAR":
        print("Aprovacao cancelada.")
        return 1
    try:
        politica.conceder(comando, str(diretorio))
    except (OSError, ValueError):
        print("Nao foi possivel salvar a aprovacao.", file=sys.stderr)
        return 2
    print("Aprovado localmente para UMA execucao; expiracao em 120 segundos.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
