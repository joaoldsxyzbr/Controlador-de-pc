"""Avaliacao offline P3: comparacao objetiva com referencia P2.

Todos os exemplos sao sinteticos. Nao contem logs do usuario, textos
recebidos pelas ferramentas MCP nem dados de producao. A saida apresenta
somente contagens agregadas, nunca o texto das amostras.
"""

import json
from pathlib import Path
import sys

import aprendizado
import mini_ia

CAMINHO_AVALIACAO = Path(__file__).resolve().parent / "dados" / "avaliacao.json"

# Referencia aprovada do primeiro P3. Atualizacoes futuras so devem elevar
# estes limites apos revisao explicita dos dados de teste e metricas.
MIN_ACERTOS_P3 = 19
TOTAL_CONHECIDOS_P3 = 21
MIN_DESCONHECIDOS_P3 = 5


def verificar_separacao(treino, avaliacao) -> None:
    """Impede repeticao literal de casos entre treino e holdout."""
    vistos = {aprendizado.normalizar(texto) for _, texto in treino}
    holdout = set()
    for _, texto in avaliacao:
        chave = aprendizado.normalizar(texto)
        if chave in vistos or chave in holdout:
            raise ValueError("Conjuntos de treino e avaliacao com vazamento ou duplicacao.")
        holdout.add(chave)


def _carregar_validacao(caminho: Path = CAMINHO_AVALIACAO):
    doc = aprendizado._ler_documento(caminho)
    if (set(doc) != {"versao", "origem", "casos"} or doc["versao"] != 1
            or doc["origem"] != "avaliacao-sintetica-independente"
            or not isinstance(doc["casos"], list)
            or not 10 <= len(doc["casos"]) <= 200):
        raise ValueError("Esquema de avaliacao invalido.")
    categorias = set(mini_ia.TREINO) | {"inconclusivo"}
    resultado = []
    classes = set()
    for caso in doc["casos"]:
        if (not isinstance(caso, dict) or set(caso) != {"categoria", "texto"}
                or not isinstance(caso["categoria"], str)
                or caso["categoria"] not in categorias
                or not isinstance(caso["texto"], str)
                or not 8 <= len(caso["texto"]) <= 220
                or "\x00" in caso["texto"]):
            raise ValueError("Caso de avaliacao invalido.")
        resultado.append((caso["categoria"], caso["texto"]))
        classes.add(caso["categoria"])
    if classes != categorias:
        raise ValueError("A avaliacao deve representar todas as classes e inconclusivos.")
    return tuple(resultado)


def _medir(casos, modelo):
    conhecidos = 0
    acertos = 0
    classificados = 0
    acertos_classificados = 0
    desconhecidos = 0
    desconhecidos_rejeitados = 0
    por_categoria = {chave: {"total": 0, "acertos": 0, "abstencoes": 0}
                     for chave in mini_ia.TREINO}
    for esperado, texto in casos:
        resposta = mini_ia.analisar(texto, codigo_saida=1, _modelo_avaliacao=modelo)
        previsto = resposta["categoria"]
        if esperado == "inconclusivo":
            desconhecidos += 1
            desconhecidos_rejeitados += int(previsto == "inconclusivo")
            continue
        conhecidos += 1
        acertos += int(previsto == esperado)
        classificados += int(previsto != "inconclusivo")
        acertos_classificados += int(previsto == esperado)
        stat = por_categoria[esperado]
        stat["total"] += 1
        stat["acertos"] += int(previsto == esperado)
        stat["abstencoes"] += int(previsto == "inconclusivo")
    return {
        "conhecidos": conhecidos,
        "acertos_conhecidos": acertos,
        "acuracia_conhecidos": round(acertos / conhecidos, 4) if conhecidos else 0,
        "cobertura_conhecidos": round(classificados / conhecidos, 4) if conhecidos else 0,
        "precisao_classificados": round(acertos_classificados / classificados, 4) if classificados else 0,
        "desconhecidos": desconhecidos,
        "desconhecidos_rejeitados": desconhecidos_rejeitados,
        "falsos_positivos_desconhecidos": desconhecidos - desconhecidos_rejeitados,
        "por_categoria": por_categoria,
    }


def sem_regressao(referencia: dict, candidato: dict) -> bool:
    """Proibe perder acertos conhecidos ou aumentar falsos positivos desconhecidos."""
    return (candidato["acertos_conhecidos"] >= referencia["acertos_conhecidos"]
            and candidato["falsos_positivos_desconhecidos"]
            <= referencia["falsos_positivos_desconhecidos"])


def preserva_qualidade_p3(candidato: dict) -> bool:
    """Compara com desempenho P3 ja demonstrado, nao so contra P2."""
    return (candidato["conhecidos"] == TOTAL_CONHECIDOS_P3
            and candidato["acertos_conhecidos"] >= MIN_ACERTOS_P3
            and candidato["desconhecidos"] >= MIN_DESCONHECIDOS_P3
            and candidato["falsos_positivos_desconhecidos"] == 0)


def gerar_relatorio() -> dict:
    extras = aprendizado.carregar_exemplos(set(mini_ia.TREINO))
    casos = _carregar_validacao()
    treino_base = [(classe, frase) for classe, frases in mini_ia.TREINO.items()
                   for frase in frases]
    verificar_separacao(treino_base + list(extras), casos)
    modelo_p2 = mini_ia._montar_modelo()
    modelo_p3 = mini_ia._montar_modelo(extras)
    referencia = _medir(casos, modelo_p2)
    candidato = _medir(casos, modelo_p3)
    return {
        "versao": 1,
        "base": "dataset_sintetico_fixo",
        "amostras_treino_p2": len(treino_base),
        "amostras_adicionais": len(extras),
        "referencia_p2": referencia,
        "candidato_p3": candidato,
        "sem_regressao": sem_regressao(referencia, candidato),
        "qualidade_p3_preservada": preserva_qualidade_p3(candidato),
    }


def main() -> int:
    try:
        relatorio = gerar_relatorio()
    except ValueError:
        print("Erro: datasets invalidos ou sobrepostos.", file=sys.stderr)
        return 2
    print(json.dumps(relatorio, ensure_ascii=False, indent=2, sort_keys=True))
    if not relatorio["sem_regressao"] or not relatorio["qualidade_p3_preservada"]:
        print("Falha: modelo P3 nao preservou a qualidade de referencia.", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
