# Controlador de PC

Controle seu próprio Windows pelo ChatGPT usando **Python**, o **SDK MCP oficial** e o **Secure MCP Tunnel da OpenAI**. Não há servidor web nem portas de entrada expostas.

## Ferramentas

- **diagnostico**: confirma sistema e disponibilidade do terminal.
- **terminal**: executa comandos PowerShell com diretório opcional, timeout de 1 a 90 segundos, saída e código de retorno.

O terminal permite manipular arquivos, abrir programas, consultar processos e executar ferramentas do Windows, sempre com os privilégios do usuário que iniciou o agente.

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
   $env:CONTROL_PLANE_API_KEY = Read-Host "Chave de runtime do tunel"
   ```

4. Prepare o comando do MCP com caminhos absolutos e configure o túnel:

   ```powershell
   $python = (Resolve-Path ".\.venv\Scripts\python.exe").Path
   $servidor = (Resolve-Path ".\servidor.py").Path
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

- A ferramenta de terminal nasce **desabilitada**. Ela só funciona quando o processo local recebe `MEU_PC_HABILITADO=1`. Enquanto habilitada, não pede confirmação local por comando.
- Não execute como administrador. Não compartilhe esse plugin nem o túnel com terceiros.
- Antes de operações destrutivas, mudanças críticas ou envio de arquivos, confirme a intenção do usuário. Essa instrução ao modelo não substitui isolamento de sistema.
- Não há telemetria própria ou log local dos comandos. A OpenAI pode processar comandos e resultados conforme suas políticas.
- Segredos de runtime da OpenAI/túnel são removidos do ambiente dos processos PowerShell filhos; outros arquivos/segredos acessíveis ao usuário Windows continuam sujeitos aos comandos autorizados.
- O retorno é limitado a 12 KiB por fluxo. Comandos longos são interrompidos e processos independentes iniciados em segundo plano podem continuar ativos.
- A instalação final, o suporte real ao Windows e o túnel precisam ser verificados no PC do usuário; testes em CI não comprovam acesso remoto.
- A opção de adicionar MCP personalizado depende do plano e das permissões do workspace: https://help.openai.com/pt-br/articles/12584461-connecting-custom-mcp-servers-in-chatgpt

## Desenvolvimento

- `servidor.py`: ferramentas do MCP.
- `core.py`: executa PowerShell com autorização local, timeout e limite de saída.
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
