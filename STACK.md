# Stack do OUR_FINANCES

Desenvolvimento ativo pausado; versões em `uv.lock`. O núcleo usa SQLAlchemy/Alembic, PostgreSQL/SQLite, FastAPI/aiogram, OpenAI Responses, ElevenLabs, openpyxl e Matplotlib. Credenciais e acesso às APIs dependem de cada instalação; hospedagem e Excel/Sheets conectados continuam pendentes. Execução em [docs/operacao.md](docs/operacao.md).

## 1. Escolhas confirmadas e propostas

| Camada | Escolha | Estado | Motivo |
|---|---|---|---|
| Interface | Telegram Bot API | Confirmada | Texto, voz, botões, documentos, links e alertas em uma conversa. |
| Inteligência | OpenAI `gpt-6-luna`, via Responses API | Confirmada | Modelo explicitamente escolhido pelo proprietário. |
| Áudio | ElevenLabs STT e TTS | Confirmada | Transcrição de entrada e respostas faladas sob demanda. |
| Planilha principal | Excel online / Microsoft 365 | Confirmada | Ambiente escolhido pelo proprietário. |
| Segunda plataforma | Google Sheets | Confirmada no escopo | Mesmas métricas, organização e análises com objetos próprios. |
| Backend | Python 3.12, FastAPI, aiogram 3 | Implementado localmente | Uma stack para bot, dados, relatórios e integrações. |
| Validação | Pydantic e pydantic-settings | Implementado | Contratos estritos de comandos e configuração. |
| Persistência | PostgreSQL, SQLite local, SQLAlchemy e Alembic | Implementado e testado | Transações, restrições, versões, outbox e migrações. |
| HTTP | httpx assíncrono e SDK oficial OpenAI | Implementado | Timeouts e classificação segura de falhas. |
| Analítica | Consultas SQLAlchemy, inteiros em unidades mínimas e Decimal | Implementado | Agregação determinística sobre snapshot; sem pandas adicional. |
| Visualização no Telegram | Matplotlib para PNG e resumo em texto | Implementado | Mesmas métricas usadas nos arquivos e no chat. |
| Excel online | Office Scripts em TypeScript + Power Automate autenticado | Proposta, exige prova | Criação/manutenção de tabelas, pivôs, segmentações e gráficos. |
| Google Sheets | google-auth + cliente oficial Sheets API v4 | Proposta | Escrita em lote e criação de objetos nativos. |
| XLSX de intercâmbio | openpyxl | Implementado, com limite | Tabelas, fórmulas, validações, proteção e gráficos locais; sem pivôs online comprovados. |
| Formatos de áudio | Validação de assinatura; STT no formato recebido, TTS MP3 | Implementado | Sem instalar FFmpeg enquanto não houver conversão necessária. |
| Testes | pytest, pytest-asyncio, httpx.MockTransport, pytest-cov | Implementado | Regras financeiras, falhas de provedor, autorização e jornadas. |
| Qualidade | Ruff e mypy estrito | Implementado | Consistência e contratos de código. |
| Dependências | uv, pyproject.toml e uv.lock | Implementado | Ambiente reproduzível e versões resolvidas. |
| Execução | Processo local; Docker/Compose e template Render preparados | Parcial | API/bot e worker podem compartilhar um processo ou separar; deploy pendente. |

As versões efetivamente instaladas estão travadas em `uv.lock`. Python 3.12 é o ambiente atual; atualização futura depende de compatibilidade e aprovação.

Documentação de referência: [aiogram](https://docs.aiogram.dev/en/latest/), [SQLAlchemy](https://docs.sqlalchemy.org/), [FastAPI](https://fastapi.tiangolo.com/) e [Pydantic](https://docs.pydantic.dev/).

## 2. Decisões de simplicidade

- Um repositório e um monólito modular. API/bot e worker usam o mesmo pacote.
- PostgreSQL armazena jobs, agendamentos e outbox. Não adicionar Redis ou Celery inicialmente.
- Sem n8n em runtime: seu template orienta o fluxo, mas a aplicação é própria.
- Sem banco vetorial, framework de múltiplos agentes ou serviço de busca sem necessidade medida.
- A interface cotidiana é o Telegram. Excel e Sheets são as superfícies de análise solicitadas.
- Sem substituir provedores escolhidos por opções mais baratas ou por chaves existentes de outro projeto.

## 3. OpenAI e GPT-6 Luna

**Modelo obrigatório: `gpt-6-luna`.** ID e capacidades verificados na [documentação oficial](https://developers.openai.com/api/docs/models/gpt-6-luna). Responses API com saída estruturada tipada implementada; disponibilidade da chave e três casos fictícios comprovados em 02/11/2026. Ferramentas de domínio são executadas após validação e confirmação da proposta, sem SQL livre.

Chamadas OpenAI e schemas ficam em `app/ai/llm.py`. Código de produto recebe propostas validadas, sem montar payloads de provedor em vários módulos. O modelo pode interpretar texto e comprovantes, selecionar ferramentas e explicar resultados calculados. Não é o motor de somas, juros, saldos ou orçamento.

Não enviar áudio diretamente ao modelo escolhido: ElevenLabs produz a transcrição. Não programar fallback para outro modelo. Em 401/403, pedir correção do acesso; em indisponibilidade, pausar e retentar a mesma integração.

A implementação não deve definir `max_tokens`, `max_completion_tokens` ou `maxTokens` nas chamadas. Limitar quantidade de ferramentas por turno, concorrência, tempo, contexto enviado e consumo mensal por políticas da aplicação.

## 4. ElevenLabs

| Função | Caminho | Critério de aceite |
|---|---|---|
| Entrada em áudio | Telegram baixa mídia; ElevenLabs transcreve; texto segue ao agente. | Valores e datas de exemplos PT-BR preservados; ambiguidades pedem revisão. |
| Resposta falada | Texto calculado e aprovado para resposta; ElevenLabs sintetiza; Telegram envia voz. | Áudio e texto representam os mesmos números. |
| Erro de áudio | Estado persistido e mensagem clara ao usuário. | Texto continua; nenhuma movimentação duplicada ou perdida. |

Escolher IDs STT/TTS e voice ID no preflight da conta, depois que o proprietário fornecer a API e escolher uma voz. Não fixar um modelo de voz só por lembrança do nome. Clonagem de voz não é requisito.

Usar APIs de [transcrição](https://elevenlabs.io/docs/overview/capabilities/speech-to-text) e [síntese](https://elevenlabs.io/docs/overview/capabilities/text-to-speech). Não é necessário contratar uma plataforma de agentes de voz para processar notas de áudio do Telegram.

Guardar duração processada, caracteres sintetizados, resultado e erro seguro. Retenção de mídia e do fornecedor precisa ser revisada antes de dados reais.

## 5. Excel online: mecanismo nativo

**Atualização da viabilidade Personal:** a API de workbook não atende OneDrive Consumer. A API de arquivos admite publicação de XLSX em conta pessoal. A primeira rota proposta é provar geração completa no servidor com objetos nativos e publicação OneDrive, preservando filtros/edições; ainda não há gerador/conector final escolhido. O caminho Office Scripts descrito abaixo fica condicionado a conta/licença elegíveis, sem troca de assinatura autorizada. Evidências, alternativas, painéis padrão e virada de mês em [docs/excel-pessoal.md](docs/excel-pessoal.md).

O backend publica lotes versionados. Um fluxo Power Automate autenticado recebe a solicitação e executa Office Scripts sobre o workbook autorizado no OneDrive/SharePoint. Cada execução retorna job ID, revisão, contagens, totais de conferência e IDs dos objetos criados. Sem confirmação desses dados, o destino permanece pendente.

Scripts em TypeScript ficam no mesmo repositório, sob `integrations/excel/scripts/`; são componentes de integração, não um segundo backend. O script não precisa consultar OpenAI, ElevenLabs ou o banco diretamente. Recebe somente o lote necessário e especificações de relatório validadas.

### 5.1 Pré-requisitos que precisam ser pedidos ao proprietário

- Modalidade da conta Microsoft 365: pessoal/família ou empresarial; tenant quando houver.
- Confirmação de Office Scripts habilitado e licença elegível para uso via Power Automate.
- Autorização para criar uma pasta de trabalho de testes e, depois, o arquivo de produção.
- Permissões do fluxo, conexão Excel Online e mecanismo autenticado de disparo.
- Aprovação de eventual custo/licença adicional antes de contratação.

Usar Excel online não comprova esses requisitos. A documentação exige [licença empresarial para Office Scripts com Power Automate](https://learn.microsoft.com/en-us/office/dev/scripts/develop/power-automate-integration). Pedir os acessos somente na etapa que os utiliza.

### 5.2 Limitações e resposta técnica

| Item | Tratamento |
|---|---|
| Pivôs e segmentações | Criar objetos nativos via Office Scripts; especificações salvas no banco. |
| Refresh em Power Automate | Não confiar em sucesso de `PivotTable.refresh` ou `refreshAllPivotTables`. Provar atualização por leitura dos valores. |
| Pivô gerado desatualizado | Criar/recriar sobre dados atuais preservando definição e filtros; validar esse caminho na fase 0. |
| Recalcular fórmulas | Executar cálculo suportado e comparar resultados; célula com fórmula não comprova valor atualizado. |
| Power Query / Power Pivot / DAX | Não presumir autoria e refresh equivalentes ao desktop. Entregar modelo e métricas por meios web suportados; validar recursos adicionais antes de prometer. |
| Automação por COM/pywin32 | Não é baseline: o usuário escolheu Excel online. Não introduzir dependência de Excel desktop sem aprovação. |
| Google Sheets convertido em XLSX | Intercâmbio de dados; não assume preservação perfeita de pivôs, filtros e segmentações. |
| HTTP trigger do fluxo | Autenticação compatível com o tenant e identidade autorizada. URL secreta não substitui autorização. |

Fontes: [pivôs em Office Scripts](https://learn.microsoft.com/en-us/office/dev/scripts/develop/pivottables), [restrições de refresh](https://learn.microsoft.com/pt-br/office/dev/scripts/testing/power-automate-troubleshooting) e [autenticação de trigger HTTP](https://learn.microsoft.com/en-gb/power-automate/oauth-authentication).

Se o tenant impedir essa rota, a etapa fica bloqueada somente para Excel e a decisão é apresentada ao proprietário. A equipe pode continuar domínio, Telegram e testes independentes, mas não declarar Excel concluído ou remover o recurso do escopo.

## 6. Google Sheets e autenticação

Uma planilha específica por workspace, com IDs permitidos na aplicação. A primeira opção proposta para uso pessoal é uma conta de serviço do projeto compartilhada apenas com o arquivo autorizado. Se o proprietário preferir criação no próprio Drive com OAuth, usar consentimento e escopo mínimo viável.

Não assumir que conta de serviço cria arquivos no Drive pessoal sem restrições. Propriedade, pasta e cota serão validadas no preflight. Não solicitar acesso geral ao Drive por conveniência.

Criar tabelas dinâmicas por `batchUpdate/updateCells`, gráficos por requests próprios, além de slicers, filter views, validações e intervalos protegidos. Conferir semântica dos filtros. Ver [pivôs](https://developers.google.com/workspace/sheets/api/guides/pivot-tables) e [requests da API](https://developers.google.com/workspace/sheets/api/reference/rest/v4/spreadsheets/request).

Cada publicação usa UUIDs, revisões e conferências. Limites de API e retentativas seguem a [documentação de cotas](https://developers.google.com/workspace/sheets/api/limits), sem presumir uso ilimitado.

As revisões publicadas só avançam. O worker descarta jobs obsoletos e mantém um único escritor por workbook; escrita de resultado incerto exige reconciliação antes da próxima publicação. Não assumir compare-and-swap em células Google.

## 7. XLSX, fórmulas e visualização

`openpyxl` é apropriado para dados, inspeção e fórmulas, mas não deve ser apresentado como solução completa para criar pivôs nativos. Sua própria [documentação](https://openpyxl.readthedocs.io/en/stable/pivot.html) descreve suporte voltado à leitura/preservação, sem API de gerenciamento completa.

O XLSX completo preferencial será o workbook exportado do Excel online após publicação verificada. Exportações básicas independentes são identificadas como tal. Não processar o workbook sofisticado por uma biblioteca que possa remover extensões, segmentações ou objetos sem antes testar preservação.

Gráficos no chat usam dados do motor analítico. A captura em PNG não substitui o gráfico editável no workbook. Relatórios registram período, filtros, revisão e limitações dos dados.

Fontes de análise distinguem movimentações de rateios. Contagens distintas, tickets e medianas usam população explícita; um pivô sem suporte à medida não pode trocar contagem de movimentações por contagem de rateios. Medidas auxiliares calculadas são identificadas e reconciliadas.

A implementação local usa Matplotlib e formatos de áudio diretamente aceitos pelos provedores, sem FFmpeg/Kaleido. A imagem Docker ainda precisa de build e medição no ambiente de hospedagem escolhido.

## 8. Configuração prevista, sem segredos

Os nomes abaixo são o contrato de configuração. `.env.example` e o carregador local estão criados; `.env` com credenciais continua sob cadastro do proprietário. Campos de integrações ainda não implementadas serão acrescentados ao carregador quando necessários.

| Variável / credencial | Quem fornece | Quando solicitar |
|---|---|---|
| `TELEGRAM_BOT_TOKEN` | Proprietário, via BotFather | Primeiro teste real do bot. |
| `TELEGRAM_OWNER_USER_ID` | Proprietário ou bootstrap autenticado aprovado | Vinculação inicial; nunca por username apenas. |
| `TELEGRAM_WEBHOOK_SECRET` | Segredo gerado no projeto com instrução ao proprietário | Antes de webhook público. |
| `OPENAI_API_KEY` | Proprietário | Preflight e interpretação real. |
| `OPENAI_MODEL=gpt-6-luna` | Valor confirmado do projeto | Configuração inicial e verificação com a chave. |
| `ELEVENLABS_API_KEY` | Proprietário | Primeiro teste STT/TTS. |
| `ELEVENLABS_STT_MODEL`, `ELEVENLABS_TTS_MODEL`, `ELEVENLABS_VOICE_ID` | Catálogo autorizado e escolha do proprietário | Preflight de áudio. |
| Credencial Google + `GOOGLE_SPREADSHEET_ID` | Proprietário | Prova Sheets e publicação. |
| Identidade Microsoft / tenant / consentimentos | Proprietário | Prova Excel online. |
| `EXCEL_FLOW_URL` + credencial de autenticação aplicável | Proprietário/conexão aprovada | Integração do fluxo; URL também é dado sensível. |
| IDs OneDrive/SharePoint/workbook | Recursos autorizados | Publicação Excel. |
| `DATABASE_URL` | Ambiente local ou conta escolhida pelo proprietário | Fundação do banco. |
| `TOKEN_ENCRYPTION_KEY` | Segredo próprio do projeto | Antes de persistir tokens de usuário. |
| `APP_TIMEZONE`, `BASE_CURRENCY` | Proposta `America/Sao_Paulo` e `BRL` | Confirmar onboarding. |
| Orçamento de APIs, retenção e destinos de alertas | Proprietário | Antes de piloto com dados reais. |

Nunca pedir senha bancária, senha Microsoft/Google ou código de login para registrar no código. Autenticação interativa ocorre no serviço oficial. Pedir ao usuário que configure os segredos no ambiente; não registrar o conteúdo no chat.

## 9. Ambientes, deploy e custos

| Ambiente | Dados | Acessos | Evidência |
|---|---|---|---|
| Teste offline | Fictícios e isolados | Nenhuma chave necessária | Testes determinísticos e integrações simuladas. |
| Sandbox conectado | Fictícios | APIs e arquivos de teste autorizados | Provas reais de provedor, objetos nativos e falhas. |
| Piloto pessoal | Dados do proprietário autorizados | Recursos separados de sandbox | Reconciliação, uso, custos e aceite. |
| Operação | Dados reais | Credenciais de produção e backups | Monitoramento, restore, atualização e rollback. |

Desenvolvimento por polling Telegram evita depender de URL pública. Produção pode usar webhook HTTPS; o processo confirma recebimento somente depois de persistir inbox. Polling e webhook não ficam ativos simultaneamente para o mesmo bot.

Hospedagem continua em aberto. O plano não pressupõe conta paga, serviço gratuito permanente nem computador ligado continuamente. Antes de escolher serviço, pedir preferência, conta e limite de custo ao proprietário. Não criar deploy, assinatura ou cobrança nesta etapa.

Preferência mais recente do proprietário: PaaS simples e com bom custo-benefício, podendo ficar fora do Brasil, sem Railway. Render, Sevalla e Heroku foram comparados; há um template Render compacto com aplicação/worker no mesmo processo e PostgreSQL separado. Preços, fontes e ressalvas em [docs/hospedagem.md](docs/hospedagem.md). A pesquisa VPS permanece como referência, sem ser a recomendação principal atual. Nenhum provedor foi escolhido ou contratado. Memória/capacidade e build da imagem precisam ser medidos no piloto; APIs de IA dispensam GPU local.

Custos separados: OpenAI por uso, ElevenLabs por plano/consumo, Microsoft 365/Power Automate conforme elegibilidade, hospedagem, banco e backup. Medir o piloto e registrar a tabela de preços vigente quando houver credenciais; nenhuma estimativa de assinatura antiga será usada como promessa.

## 10. Comandos previstos de desenvolvimento

Disponíveis: ambiente reproduzível, análise estática, testes integrados/E2E, cobertura e execução local do bot. Docker/Compose estão preparados; build da imagem e smoke da implantação continuam pendentes. A verificação completa local usa `uv run --locked python -m scripts.check_all --coverage`.

```powershell
uv sync --locked
uv run ruff check .
uv run mypy app
uv run pytest tests/unit tests/integration -m "not live"
uv run pytest tests/e2e -m "not live"
uv run pytest tests --cov=app --cov-report=term-missing -m "not live"
docker compose up -d
```

Testes `live` ficam desligados por padrão, exigem credenciais e arquivos de sandbox explícitos. Nunca usar planilha de produção só porque um ID já está disponível no ambiente.
