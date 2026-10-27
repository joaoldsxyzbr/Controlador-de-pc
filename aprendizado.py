"""Treino P3: somente frases curadas e versionadas no proprio GitHub.

Nao recolhe, grava ou transforma saidas reais de comandos em dados de treino.
A revisao humana do PR continua obrigatoria para qualquer exemplo novo.
"""

import json
from pathlib import Path
import re

CAMINHO_TREINO = Path(__file__).resolve().parent / "dados" / "treino_curado.json"
MAX_EXEMPLOS = 200
MAX_BYTES = 65_536
TERMOS_PRIVADOS = re.compile(
    r"(?i)(?:senha|password|passwd|secret|segredo|token|api[_ -]?key|"
    r"private[_ -]?key|bearer|sk[-_])"
)
CARACTERES_PERMITIDOS = re.compile(r"^[\wÀ-ÿ ._-]+$", re.UNICODE)


def normalizar(texto: str) -> str:
    return " ".join(texto.casefold().split())


def validar_frase(texto: object) -> bool:
    """FILTRO básico para exemplos *sintéticos*, nao anonimização segura."""
    return (
        isinstance(texto, str)
        and 16 <= len(texto) <= 180
        and texto == texto.strip()
        and not any(ch in texto for ch in ("@", "/", "\\", ":", "\n", "\r", "\t"))
        and bool(CARACTERES_PERMITIDOS.fullmatch(texto))
        and TERMOS_PRIVADOS.search(texto) is None
        and len(texto.split()) >= 3
        and len(normalizar(texto)) >= 16
        and not any(len(parte) > 32 for parte in texto.split())
    )


def _ler_documento(caminho: Path) -> dict:
    try:
        # Rejeita arquivos grandes antes de carrega-los inteiros na memoria.
        if caminho.stat().st_size > MAX_BYTES:
            raise ValueError("Dataset excede o tamanho maximo.")
        with caminho.open("r", encoding="utf-8") as arquivo:
            obj = json.load(arquivo)
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ValueError("Dataset ausente ou invalido.") from None
    if not isinstance(obj, dict):
        raise ValueError("Dataset invalido.")
    return obj


def carregar_exemplos(categorias: set[str], caminho: Path | None = None) -> tuple[tuple[str, str], ...]:
    """Rejeita campos desconhecidos, exemplos repetidos e indicios de PII.

    Exige revisao humana adicional: filtros nao identificam todo dado privado.
    """
    if not isinstance(categorias, (set, frozenset)) or not categorias:
        raise ValueError("Categorias invalidas.")
    documento = _ler_documento(Path(caminho) if caminho is not None else CAMINHO_TREINO)
    if (set(documento) != {"versao", "origem", "exemplos"}
            or documento["versao"] != 1
            or documento["origem"] != "sintetico-curado-em-pr"
            or not isinstance(documento["exemplos"], list)
            or not 1 <= len(documento["exemplos"]) <= MAX_EXEMPLOS):
        raise ValueError("Esquema de treinamento invalido.")

    novos = []
    vistos = set()
    for amostra in documento["exemplos"]:
        if (not isinstance(amostra, dict) or set(amostra) != {"categoria", "texto"}
                or not isinstance(amostra["categoria"], str)
                or amostra["categoria"] not in categorias
                or not validar_frase(amostra["texto"])):
            raise ValueError("Exemplo de treinamento invalido.")
        chave = normalizar(amostra["texto"])
        if chave in vistos:
            raise ValueError("Exemplos de treinamento duplicados.")
        vistos.add(chave)
        novos.append((amostra["categoria"], amostra["texto"]))
    return tuple(novos)
