"""Mini IA P2: classificador estatistico local e CONSERVADOR de falhas PowerShell.

Nao e um modelo de linguagem nem uma rede neural. E um modelo supervisionado
Naive Bayes sobre exemplos versionados e auditaveis. Nao executa comandos,
nao consulta rede, nao salva entradas e nao modifica a politica de seguranca.
"""

from collections import Counter
from functools import lru_cache
import math
import re

LIMITE_TEXTO = 12000
VERSAO = "p2-naive-bayes-1"

# Exemplos criados para o projeto; NAO sao logs reais do computador.
TREINO = {
    "acesso_negado": (
        "Access is denied to the requested path",
        "Permission denied while opening the directory",
        "UnauthorizedAccessException access denied",
        "Acesso negado ao tentar abrir o arquivo",
        "Permissão negada para gravar neste caminho",
        "Requested registry access is not allowed",
        "Operação não permitida por falta de privilégios",
    ),
    "caminho_ausente": (
        "Cannot find path because it does not exist",
        "PathNotFound ItemNotFoundException file missing",
        "Could not find a part of the path",
        "The system cannot find the file specified",
        "O sistema não pode encontrar o caminho especificado",
        "Não foi possível localizar o arquivo na pasta",
        "Arquivo inexistente diretório não encontrado",
    ),
    "comando_desconhecido": (
        "The term is not recognized as the name of a cmdlet",
        "CommandNotFoundException cmdlet was not recognized",
        "Command is not recognized as an internal or external command",
        "O termo não é reconhecido como nome de cmdlet",
        "Comando desconhecido ou não reconhecido pelo PowerShell",
        "Não existe cmdlet com esse nome",
        "Executable was not found in the command path",
    ),
    "rede_indisponivel": (
        "Unable to resolve DNS name of remote host",
        "DNS name resolution failed for server",
        "No such host is known network failure",
        "Remote name could not be resolved",
        "Unable to connect to the remote server connection refused",
        "Falha de resolução DNS ao conectar no servidor",
        "A conexão com o servidor remoto foi recusada",
    ),
    "modulo_ausente": (
        "Import-Module specified module was not loaded because module file not found",
        "ModuleNotFoundError no module named required component",
        "Cannot load module because it was not installed",
        "O módulo não foi carregado porque não foi encontrado",
        "Módulo PowerShell não instalado neste computador",
        "No valid module file was found in module directory",
        "Falha ao importar módulo ausente na instalação",
    ),
    "disco_cheio": (
        "There is not enough space on the disk",
        "No space left on device disk full",
        "ENOSPC disk space exhausted",
        "Não há espaço suficiente em disco",
        "Disco cheio ao gravar arquivo",
        "Armazenamento insuficiente para salvar os dados",
        "Disk has insufficient free space for operation",
    ),
    "politica_execucao": (
        "Running scripts is disabled on this system",
        "PSSecurityException execution policy prevents script",
        "ExecutionPolicy restrictions script not digitally signed",
        "O script não pode ser carregado devido à política de execução",
        "A execução de scripts está desabilitada neste sistema",
        "File cannot be loaded because it is not digitally signed",
        "Script was blocked by the powershell execution policy",
    ),
}

# As respostas sao fixas: nao interpolar o texto, para impedir vazamento ou
# transformar instrucoes maliciosas presentes no stderr em novas ordens.
ORIENTACOES = {
    "acesso_negado": (
        "O erro sugere permissao insuficiente para acessar um recurso.",
        "Confira as permissoes do arquivo ou pasta e a conta Windows. Nao eleve privilegios automaticamente.",
        None,
    ),
    "caminho_ausente": (
        "O caminho ou arquivo solicitado pode nao existir.",
        "Confirme o caminho informado e se o arquivo existe antes de repetir a operacao.",
        None,
    ),
    "comando_desconhecido": (
        "O PowerShell pode nao reconhecer o comando ou executavel.",
        "Verifique a grafia, a instalacao da ferramenta e a disponibilidade no PATH.",
        None,
    ),
    "rede_indisponivel": (
        "Ha indicios de falha de rede, DNS ou conexao remota.",
        "Confira a conectividade e a resolucao DNS; evite repetir comandos com efeitos externos automaticamente.",
        None,
    ),
    "modulo_ausente": (
        "Ha indicios de modulo necessario ausente ou indisponivel.",
        "Verifique a instalacao, a versao e o nome do modulo antes de instalar qualquer dependencia.",
        None,
    ),
    "disco_cheio": (
        "O erro sugere espaco de armazenamento insuficiente.",
        "Consulte o espaco disponivel. Nao remova arquivos automaticamente.",
        "discos",
    ),
    "politica_execucao": (
        "O PowerShell parece ter bloqueado a execucao de scripts por politica.",
        "Confira a politica aplicada; nao a desative automaticamente para contornar a protecao.",
        None,
    ),
    "tempo_esgotado": (
        "O motor informou que a execucao excedeu o limite de tempo.",
        "Investigue a duracao e o estado da tarefa antes de tentar novamente; nao repita comandos com efeitos sem verificar.",
        None,
    ),
}

STOPWORDS = frozenset((
    "a", "o", "os", "as", "de", "da", "do", "dos", "das", "ao", "um", "uma", "no",
    "na", "em", "para", "por", "que", "e", "ou", "foi", "sao", "com", "mais", "nao",
    "the", "is", "was", "are", "to", "as", "in", "by", "with", "for", "this",
    "because", "cannot", "not", "it", "be", "of", "on", "from", "at", "an", "or",
))

TERMOS = re.compile(r"[a-zà-ÿ][a-zà-ÿ0-9_]*", re.IGNORECASE)


def _tokens(texto: str) -> set[str]:
    """Saco binario de palavras para evitar reforco artificial por repeticao."""
    return {t for t in TERMOS.findall(texto.casefold()) if len(t) > 2 and t not in STOPWORDS}


@lru_cache(maxsize=1)
def _modelo():
    contagens = {categoria: Counter() for categoria in TREINO}
    for categoria, frases in TREINO.items():
        for frase in frases:
            contagens[categoria].update(_tokens(frase))
    vocabulario = set().union(*(set(x) for x in contagens.values()))
    total = {classe: sum(cont.values()) for classe, cont in contagens.items()}
    # Quantas categorias empregam cada token (nao documentos).
    abrangencia = {token: sum(token in ct for ct in contagens.values()) for token in vocabulario}
    return contagens, total, vocabulario, abrangencia


def _inconclusivo() -> dict:
    return {
        "ok": True, "categoria": "inconclusivo", "confianca": "insuficiente",
        "origem": "modelo_estatistico",
        "explicacao": "Nao ha evidencias suficientes para sugerir uma causa.",
        "proximo_passo": "Verifique o codigo de saida e os detalhes relevantes do erro; nao execute correcoes automaticas.",
        "consulta_segura": None, "modelo": VERSAO,
    }


def analisar(texto: str, codigo_saida: int | None = None, tempo_esgotado: bool = False) -> dict:
    """Interpreta texto fornecido pelo chamador, sem I/O nem efeitos externos.

    Classificacao e hipotese (nao confirmacao de causa), inclusive no score alto.
    Nunca retorna o texto original, comandos novos ou caminhos recebidos.
    """
    if (not isinstance(texto, str) or len(texto) > LIMITE_TEXTO
            or isinstance(codigo_saida, bool)
            or (codigo_saida is not None
                and (not isinstance(codigo_saida, int) or abs(codigo_saida) > 2147483647))
            or not isinstance(tempo_esgotado, bool)):
        return {"ok": False, "erro": "entrada_invalida",
                "mensagem": "Texto ou metadados invalidos para analise."}

    if tempo_esgotado:
        explicacao, proximo, consulta = ORIENTACOES["tempo_esgotado"]
        return {
            "ok": True, "categoria": "tempo_esgotado", "confianca": "alta",
            "origem": "sinal_execucao", "explicacao": explicacao,
            "proximo_passo": proximo, "consulta_segura": consulta, "modelo": VERSAO,
        }

    termos = _tokens(texto)
    contagens, total, vocabulario, abrangencia = _modelo()
    encontrados = termos & vocabulario
    if len(encontrados) < 2:
        return _inconclusivo()

    pontuacoes = {}
    for categoria, frequencia in contagens.items():
        denominador = total[categoria] + len(vocabulario)
        # Dados de treino com numero igual de exemplos por categoria:
        # priori uniforme; frequencia de termos desconhecidos nao e usada.
        pontuacoes[categoria] = sum(
            math.log((frequencia[token] + 1) / denominador) for token in encontrados
        )

    ranking = sorted(pontuacoes, key=pontuacoes.get, reverse=True)
    melhor, segundo = ranking[:2]
    diferenca = pontuacoes[melhor] - pontuacoes[segundo]
    # Evidencia independente: ao menos dois termos presentes na classe e
    # presentes em no maximo duas categorias do treino.
    marcas = [
        token for token in encontrados
        if contagens[melhor][token] and abrangencia[token] <= 2
    ]
    if len(marcas) < 2 or diferenca < 1.0:
        return _inconclusivo()

    descricao, proximo, consulta = ORIENTACOES[melhor]
    return {
        "ok": True, "categoria": melhor,
        "confianca": "alta" if len(marcas) >= 3 and diferenca >= 2.5 else "moderada",
        "origem": "modelo_estatistico", "explicacao": descricao,
        "proximo_passo": proximo, "consulta_segura": consulta, "modelo": VERSAO,
    }
