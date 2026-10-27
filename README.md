# Controlador de PC

Controle seu próprio Windows pelo ChatGPT usando **Python**, o **SDK MCP oficial** e o **Secure MCP Tunnel da OpenAI**. Não há servidor web nem portas de entrada expostas.

## Ferramentas

- **diagnostico**: confirma sistema, disponibilidade do terminal e politica de autorizacao.
- **ia_analisar_erro**: mini IA offline para classificar possiveis erros PowerShell, sem executar comandos.
- **ia_analisar_tarefa**: interpreta uma tarefa P0 existente, sem devolver sua saida bruta.
- **consulta_segura**: consultas de somente leitura e sem parametros livres (`sistema`, `memoria`, `processos`, `discos`).
- **terminal**: executa PowerShell sincrono (1 a 90 segundos), com saida, codigo de retorno e duracao.
- **terminal_iniciar**: executa tarefa em segundo plano (1 a 600 segundos), com ID para acompanhamento.
- **terminal_consultar**: consulta estado, saida parcial e resultado final da tarefa.
- **terminal_cancelar**: interrompe tarefa iniciada por este processo MCP.
- **terminal_tarefas**: lista tarefas recentes sem mostrar comandos ou saidas.

O terminal consegue manipular arquivos, programas e processos com os privilegios do usuario Windows, **mas o P1 bloqueia comandos livres ate receber aprovacao local especifica**.

## Instalação no Windows

Pré-requisitos: Windows 10/11, Python 3.11+, acesso a MCPs personalizados no ChatGPT e Secure MCP Tunnel na OpenAI Platform.

1. Baixe ou clone o repositório. Abra o **PowerShell** na pasta do projeto e instale o SDK oficial:

   ```powershell
   py -3.11 -m venv .venv
   .\.venv\Scripts\python.exe -m pip install -r requirements.txt
   ```

2. Crie um túnel em https://platform.openai.com/settings/organization/tunnels e instale o executável oficial para Windows: https://github.com/openai/tunnel-client/releases/latest. Obtenha o identificador do túnel e uma chave de **runtime**, com permissões Tunnels Read + Use (não use chave de administrador).

3. No PowerShell, habilite conscientemente o terminal **para esta sessão** e informe a chave sem adicioná-la ao código:

   ```powershell
   $env:MEU_PC_HABILITADO = "1"
   $chave = Read-Host "Chave de runtime do tunel" -AsSecureString
   $env:CONTROL_PLANE_API_KEY = [System.Net.NetworkCredential]::new("", $chave).Password
   Remove-Variable chave
   ```

4. Prepare o comando do MCP com caminhos absolutos e configure o túnel:

   ```powershell
   $python = (Resolve-Path ".\.venv\Scripts\python.exe").Path.Replace([char]92, [char]47)
   $servidor = (Resolve-Path ".\servidor.py").Path.Replace([char]92, [char]47)
   $comandoMcp = '"' + $python + '" "' + $servidor + '"'
   tunnel-client init --sample sample_mcp_stdio_local --profile meu-pc --tunnel-id tunnel_SEU_ID --mcp-command $comandoMcp
   tunnel-client doctor --profile meu-pc --explain
   tunnel-client run --profile meu-pc
   ```

   Mantenha o processo de túnel em execução. Verifique a saúde em http://127.0.0.1:8080/ui (porta local de diagnóstico padrão do cliente).

5. No ChatGPT web, em **Plugins → Adicionar servidor MCP personalizado**, escolha **Túnel**, selecione o `tunnel_id` e adicione o plugin, se sua conta permitir.

6. Teste com: “Verifique o diagnóstico do Meu PC” e “Mostre a versão do Windows pelo Meu PC”. Para parar o serviço, pressione Ctrl+C no terminal do túnel.

## Segurança

**Este projeto executa comandos arbitrários e não é sandbox.** O túnel evita expor portas, mas não torna os comandos inofensivos.

- O terminal nasce **desabilitado** e requer `MEU_PC_HABILITADO=1`. **No P1, todo PowerShell livre exige aprovação interativa no próprio Windows, vinculada ao texto exato e diretório, por um único uso em até 120 segundos.**
- Não execute como administrador. Não compartilhe esse plugin nem o túnel com terceiros.
- Confirme o conteúdo exato no utilitário local `autorizar.py`. O ChatGPT não pode aprovar via ferramenta MCP; a política não é sandbox e não impede que um comando já autorizado inicie outros processos ou altere arquivos.
- Não há telemetria própria nem log de comandos. O P1 grava somente a assinatura SHA-256 do comando/diretório e prazo de validade em `LOCALAPPDATA`, consumidos no primeiro uso; a OpenAI pode processar comandos e resultados conforme suas políticas.
- Segredos de runtime da OpenAI/túnel são removidos do ambiente dos processos PowerShell filhos; outros arquivos/segredos acessíveis ao usuário Windows continuam sujeitos aos comandos autorizados.
- O retorno é limitado a 12 KiB por fluxo. Comandos longos são interrompidos e processos independentes iniciados em segundo plano podem continuar ativos.
- A instalação final, o suporte real ao Windows e o túnel precisam ser verificados no PC do usuário; testes em CI não comprovam acesso remoto.
- A opção de adicionar MCP personalizado depende do plano e das permissões do workspace: https://help.openai.com/pt-br/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Desenvolvimento

- `servidor.py`: ferramentas do MCP.
- `core.py`: executa PowerShell com autorização local, timeout e limite de saída.
- `politica.py`: autorizações de uso único e catálogo restrito.
- `mini_ia.py`: modelo estatistico offline para hipotese de causas de falhas, sem dependencias novas.
- `autorizar.py`: confirmação interativa executada localmente no Windows.
- `tarefas.py`: motor de tarefas P0.
- `tests/test_core.py`: testes unitários sem comandos no Windows.
- `requirements.txt`: somente o SDK oficial `mcp>=2,<3`.

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q core.py servidor.py tests
```

Documentação: https://developers.openai.com/api/docs/guides/secure-mcp-tunnels e https://github.com/openai/tunnel-client/blob/master/docs/onboarding.md


## P0 — Motor de terminal

O MCP oferece dois modos. Use `terminal` para chamadas curtas e `terminal_iniciar`
para comandos longos; consulte periodicamente com `terminal_consultar`, ou interrompa
com `terminal_cancelar`. Nunca repita automaticamente um comando que possa produzir
efeitos duplicados.

Os retornos das tarefas incluem `id`, `status`, `stdout`, `stderr`,
`codigo_saida`, `tempo_esgotado`, `saida_truncada` e `duracao_ms`.
Estados: `executando`, `concluido`, `falhou`, `cancelado` e `tempo_esgotado`.
O indicador `ok` fica nulo enquanto a tarefa nao termina.

**Limites:** ate 3 tarefas simultaneas; timeout de 1 a 600 segundos;
saidas de ate 12 KiB **por fluxo** (stdout e stderr), drenadas continuamente
sem acumular toda a saida na memoria. Tarefas concluidas permanecem consultaveis
por ate 10 minutos (historico limitado a 24). Os estados sao mantidos somente
em memoria; reiniciar o MCP perde os IDs e resultados, e uma interrupcao forcada
do servidor pode deixar processos independentes ativos. O encerramento da arvore
usa `taskkill /T /F` em Windows, com fallback para o processo principal.

O modo sincrono existente permanece compatível. Sua saida de resposta e limitada
a 12 KiB por fluxo, mas sua captura temporaria pode usar espaco em disco enquanto
o comando esta rodando. Para comandos de grande saida, prefira tarefas assincronas.

**Atencao:** nenhuma das ferramentas isola o comando em sandbox. Todas herdam as
permissoes do usuario Windows; confirme operacoes destrutivas, mudancas de seguranca
e transferencias de dados antes de executa-las. Nao ha telemetria propria nem
persistencia de logs. A mini IA e outros recursos ficam fora do escopo do P0.

### Validacao

```powershell
.\.venv\Scripts\python.exe -m unittest discover -s tests -v
.\.venv\Scripts\python.exe -m compileall -q core.py servidor.py tarefas.py tests
```

O CI executa os testes de unidade no Linux e no Windows e um smoke test com
PowerShell real no Windows. Um CI verde nao comprova automaticamente a reconexao
do plugin no ChatGPT apos atualizar o servidor local.


## P1 — Permissoes e confirmacao local

**Negacao por padrao:** `MEU_PC_HABILITADO=1` continua obrigatorio, mas
nao da mais permissao para executar PowerShell arbitrario. Os MCPs
`terminal` e `terminal_iniciar` retornam `aprovacao_local_necessaria`
e uma `assinatura` SHA-256 ate que haja aprovacao local correspondente.

Para realizar uma operacao livre:

1. Solicite ao ChatGPT o **comando exato** (e informe o diretorio, se houver).
2. **No proprio computador Windows, fora do plugin**, abra PowerShell na pasta
   do projeto e execute `py autorizar.py` (para um comando de uma linha).
   Alternativa: `py autorizar.py --arquivo comando.ps1 --diretorio C:/Projetos`.
3. Cole o texto **exato** do comando, revise o conteudo mostrado e confira
   a assinatura com a que apareceu no MCP. Digite `AUTORIZAR` localmente.
4. Repita no ChatGPT a ferramenta/comando original. A autorizacao dura ate
   **120 segundos** e e consumida por **uma unica tentativa de execucao**,
   mesmo que essa tentativa falhe antes de iniciar o PowerShell.
   Uma segunda tentativa exige nova aprovacao.

Para verificacoes comuns, use `consulta_segura(tipo)` com `sistema`,
`memoria`, `processos` ou `discos`, sem precisar aprovar cada chamada.
Sao comandos predefinidos, sem parametro PowerShell externo.

A politica nao tenta identificar comandos perigosos por palavras-chave
— isto seria burlavel com aliases, invocacoes indiretas, scripts ou codificacao.
Em vez disso, **todo comando livre requer consentimento local**.

**Limites de seguranca:** nao ha sandbox de Windows, isolamento de arquivos
nem usuario de baixo privilegio forcado. Um unico comando aprovado pode
realizar varias acoes e criar processos filhos. Outro programa com acesso
a mesma conta Windows pode interferir nas permissoes do usuario. Nao inicie
este servico como administrador e nao compartilhe o tunel.
A protecao se aplica somente ao servidor Python atualizado: o processo
antigo do MCP continuara com suas regras antigas ate voce atualiza-lo
e reinicia-lo.

### CI do P1

O CI testa expiracao, negacao por padrao, uso unico, corrida entre
solicitacoes simultaneas e bloqueio de tarefas; tambem valida uma
execucao PowerShell real no Windows com aprovacao consumida.


## P2 — Mini IA especializada em terminal

A mini IA P2 e um **classificador estatistico supervisionado Naive Bayes**,
em Python nativo. Nao e um LLM, nao usa rede neural e nao aprende sozinho.
Escolhemos este ponto de partida porque a base atual de exemplos e pequena:
um modelo neural treinado do zero provavelmente seria menos confiavel sem
dados reais de qualidade. Ha 49 exemplos de treinamento ficticios/versionados
(7 categorias com 7 amostras cada) e nenhum dado privado do usuario.

Ela roda **integralmente offline**, sem novos pacotes, GPU, servidor, API,
persistencia, telemetria ou alteracao de permissoes. O classificador e
conservador: quando ha poucos sinais independentes de uma categoria, retorna
`inconclusivo`. `confianca` e somente um grau de correspondencia
heuristico, **nao probabilidade calibrada de acerto**.

Ferramentas MCP:

- `ia_analisar_erro(texto, codigo_saida?, tempo_esgotado?)`: recebe ate
  12 mil caracteres. Nunca devolve o texto original; classifica em
  `acesso_negado`, `caminho_ausente`, `comando_desconhecido`,
  `rede_indisponivel`, `modulo_ausente`, `disco_cheio`,
  `politica_execucao`, `tempo_esgotado` ou `inconclusivo`.
- `ia_analisar_tarefa(id)`: examina a saida ja armazenada na memoria
  de uma tarefa iniciada pelo P0, sem expor stdout/stderr no resultado da
  analise. Quando esta em execucao, retorna `aguardando`.

As respostas incluem `categoria`, `confianca`, `origem`, `explicacao`,
`proximo_passo` e eventualmente um identificador `consulta_segura` para
diagnostico **predefinido**; nenhuma resposta e uma ordem de execucao.
No caso de `disco_cheio`, por exemplo, a mini IA sugere
`consulta_segura(tipo="discos")` e nao apaga arquivos.

**A mini IA nao executa, aprova, instala, corrige nem repete comandos.**
A politica P1 continua sendo a unica porta para PowerShell arbitrario.
Saidas de comandos, arquivos e mensagens de erro podem conter dados
privados ou tentativas de instrucao; sao tratados apenas como dados.

### Testes e limites

O CI executa testes de categorizacao em portugues/ingles, recusa de
entradas desconhecidas, entradas excessivas, injeções de instrucao,
ausencia de vazamento de texto, isolamento da politica P1, integracao
das ferramentas MCP e testes P0/P1 existentes em Linux e Windows.
Testes com amostras controladas nao comprovam qualidade em todos os
erros reais do Windows. Antes de expandir o modelo, medir falsos positivos
com conjuntos independentes e anonimizar quaisquer exemplos novos.

**Deploy:** implementar/testar/abrir PR no GitHub primeiro. O computador
do usuario nao recebe a mudanca sem solicitacao especifica.
