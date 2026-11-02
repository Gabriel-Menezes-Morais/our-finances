# Plano de implementação do OUR_FINANCES

- **Objetivo:** colocar em funcionamento um produto próprio de finanças, operado pelo Telegram, com `gpt-6-luna`, áudio ElevenLabs, Excel online e Google Sheets.
- **Estado:** desenvolvimento ativo pausado, código publicado sob MIT para instalação própria e continuação. Núcleo local implementado; hospedagem e integrações online pendentes. Verificação e retomada em [docs/validacao.md](docs/validacao.md) e [docs/retomada.md](docs/retomada.md). O roadmap preserva o escopo restante sem prometer prazos.
- **Referências de especificação:** [ARQUITETURA.md](ARQUITETURA.md), [STACK.md](STACK.md) e [README.md](README.md).
- **Forma de execução:** marcar um item apenas depois de produzir sua evidência. Nomes de módulos abaixo são o desenho original; o mapa real e os comandos de validação ficam na seção seguinte. Nenhuma credencial ou prova de uma instalação anterior acompanha a publicação.
- **Regra de escopo:** a entrega completa inclui todas as fases. Um bot que só lança gastos ou exporta CSV é um marco intermediário.
- **Regra de acesso:** pedir ao proprietário qualquer API, conta, acesso ou autorização quando a etapa precisar disso. Ele gerará as chaves. Sem chave, continuar apenas o trabalho independente e registrar a integração como pendente.
- **Regra de segredo:** orientar cadastro local/cofre; nunca salvar chave no Markdown, Git, print, fixture ou log. Não buscar credenciais em outros projetos.
- **Regra de revisão:** tarefas de código devem terminar com testes proporcionais, revisão do diff e commit específico quando o repositório já estiver inicializado. Não fazer deploy ou contratar recursos por inferência.

## Situação da implementação local

- [ ] Entregar o workbook com análises pré-prontas instaladas por padrão: mensal/anual, categorias/áreas, orçamento, compromissos, metas e pivôs. Registrar gasto deve atualizar essas análises sem pedido de criação ao agente.
- [ ] Provar conta Personal por geração de XLSX completo e publicação OneDrive; API de arquivos é suportada, API de workbook não. Comparar alternativas e validar objetos nativos antes de escolher gerador/conector. Ver `docs/excel-pessoal.md`.
- [ ] Implementar base contínua, modos Mês atual/Mês escolhido e atualização de calendário sem gasto novo; testar novembro→dezembro→janeiro, limites recorrentes, correções atrasadas e preservação de filtros/edições.

- [x] Fundação: `app/db.py`, `app/models/`, Alembic e `tests/integration/test_database.py`; SQLite persistente e prova PostgreSQL isolada.
- [x] Domínio: `app/domain/service.py` concentra organização, contas, movimentações, rateios, cartões, limites, metas, recorrências, agenda, relatórios e cenários; testes em `tests/unit/test_finance_domain.py`.
- [x] Filas e confirmações: `app/jobs/store.py`, `app/runtime.py` e `app/agent/orchestrator.py`; testes de jobs, runtime e ações do agente.
- [x] IA/áudio: saída estruturada, contexto autorizado, transcrição e síntese preparada; a voz TTS ainda depende de escolha e teste real.
- [x] Analítica: `app/analytics/`, `app/reports/` e `app/spreadsheets/`; CSV/XLSX/PNG, cenários, projeção e importação controlada locais.
- [x] Operação: scheduler, health/webhook, pausas pelo bot, uso de provedores, backup cifrado e restauração isolada.
- [x] Qualidade: suíte de 216 testes aprovada, 3 testes PostgreSQL opcionais pulados na rodada final, cobertura de 85%; Ruff e mypy aprovados. Detalhes e ressalvas em `docs/validacao.md`.
- [ ] Conectar e provar Excel/Sheets, pivôs e segmentações nativos, links e sincronização reais.
- [ ] Escolher/autorizar PaaS, fazer build/implantação, configurar backup externo e validar operação contínua.
- [ ] Escolher voz TTS, limite de consumo e política de retenção; ampliar avaliação real PT-BR e fazer aceite pessoal.
- [ ] Completar itens posteriores do plano que extrapolam o núcleo pessoal: compartilhamento por convite/papéis e exclusão definitiva confirmada. Nenhum deles é anunciado como disponível.

Os itens detalhados a seguir preservam o escopo completo e suas provas de aceite. Uma tarefa que mistura implementação local e integração real permanece aberta até completar ambas; os arquivos reais substituem subdivisões previstas quando não havia necessidade de separá-las.

## Mapa de arquivos previstos

- **Documentação existente:** os seis arquivos Markdown na raiz e o diagrama `docs/arquitetura.svg`.
- **Fundação:**
  - `pyproject.toml`, `uv.lock`: dependências e comandos reproduzíveis.
  - `.env.example`, `.gitignore`, `app/config.py`: configuração sem segredos.
  - `compose.yaml`, `Dockerfile`: API, worker e PostgreSQL.
  - `app/main.py`, `app/worker.py`: entradas dos dois processos.
- **Dados e finanças:**
  - `app/db.py`, `app/models/`, `migrations/`: persistência e migrações.
  - `app/domain/`: organização, movimentações, orçamento, recorrências, cartões, metas e regras.
  - `app/jobs/`: inbox, outbox, agenda, leases e reconciliação.
- **Interface e IA:**
  - `app/telegram/`: autenticação, handlers, callbacks, anexos e entrega.
  - `app/ai/llm.py`: única fronteira OpenAI e declarações de ferramentas.
  - `app/agent/`: política, orquestração, propostas e confirmações.
  - `app/audio/elevenlabs.py`: STT/TTS; `app/audio/formats.py`: conversão.
- **Análises e planilhas:**
  - `app/analytics/`: métricas, consultas, cenários e definições de relatório.
  - `app/spreadsheets/`: contrato comum, projeção, importação e sincronização.
  - `app/integrations/google_sheets.py`, `app/integrations/excel_online.py`: adaptadores.
  - `integrations/excel/scripts/`: Office Scripts versionados.
  - `app/reports/`: imagens, relatórios e exportações.
- **Validação e operação:**
  - `tests/unit/`, `tests/integration/`, `tests/e2e/`: testes isolados por camada.
  - `evals/`: casos de linguagem, jornadas, rubricas e resultados.
  - `scripts/`: preflight, smoke, reconciliação e backup/restore.
  - `docs/operacao.md`, `docs/metricas.md`, `docs/acessos.md`: decisões operacionais, definições e estado dos acessos, sem segredos.
- **Decomposição:** o mapa acima preserva o desenho original. A implementação existente usa somente os módulos necessários; conectores Microsoft/Google ainda não foram criados porque o caminho de acesso precisa ser provado.

## Fase 0. Confirmar acessos e provar as integrações críticas

### 01. Preparar um ambiente isolado

- [x] Conferir as instruções locais e manter todas as alterações dentro de `OUR_FINANCES`.
- [x] Criar `pyproject.toml`, `.gitignore` e `.env.example`; listar apenas variáveis, sem valores secretos.
- [x] Criar ambiente Python 3.12 isolado e instalar dependências necessárias ao preflight e testes.
- [x] Gerar `uv.lock` e registrar as versões efetivamente resolvidas.
- [x] Criar teste de configuração que recuse segredo ausente no modo conectado, mas permita testes offline com fixtures.
- [x] Verificar: `uv run pytest tests/unit/test_config.py -q`; esperado: testes verdes e nenhuma chave real necessária.
- [x] Se falhar, corrigir instalação/configuração; não comentar a validação para prosseguir.
- [x] Concluir quando um ambiente limpo reproduzir o teste; revisar diff e versionar os arquivos específicos.

### 02. Pedir os acessos iniciais e registrar o estado

- [x] Criar `docs/acessos.md` com serviço, finalidade, escopo, ambiente, responsável e estado; não incluir segredos.
- [x] Implementar pareamento de bot próprio por Telegram user ID; cada instalação fornece seu token e executa o vínculo.
- [x] Implementar configuração e preflight OpenAI com modelo configurado; cada instalação precisa fornecer/verificar acesso próprio.
- [x] Implementar STT ElevenLabs e configuração própria; voz/modelo TTS e provas reais dependem de quem instala.
- [ ] Obter autorização de workbook/fluxo de testes e decidir rota Excel: Microsoft 365 Personal confirmado, sem elegibilidade empresarial da integração originalmente proposta. Não contratar nem mudar plano sem autorização.
- [ ] Pedir conta/projeto Google e autorização para planilha de teste; combinar OAuth ou compartilhamento com conta de serviço.
- [ ] Verificar que sandbox e produção têm IDs explícitos e separados; não testar em arquivo pessoal existente sem autorização.
- [ ] Concluir quando o estado de cada acesso estiver documentado como fornecido, pendente ou incompatível; não exigir todos para iniciar trabalho offline.

### 03. Provar o Excel online antes do conector completo

- [ ] Preparar `integrations/excel/scripts/probe.ts`, `scripts/probe_excel.py` e `tests/integration/test_excel_probe.py`.
- [ ] Com acesso autorizado, confirmar Office Scripts habilitado, licença empresarial elegível e mecanismo de disparo Power Automate autenticado.
- [ ] Criar workbook de sandbox com tabela, fórmulas, pivô nativo, gráfico e segmentação; registrar os IDs no estado do teste.
- [ ] Inserir nova categoria e transação fictícias; criar/recriar o pivô gerado sobre a revisão nova e conferir os valores retornados, sem confiar apenas em refresh.
- [ ] Repetir o mesmo job e provar que não cria tabela, gráfico, categoria ou lançamento em duplicidade; preservar filtros e objetos manuais.
- [ ] Simular erro após escrita e antes da resposta; descobrir o estado pelo job ID/revisão antes de repetir.
- [ ] Verificar: `uv run pytest tests/integration/test_excel_probe.py -m live -q`; esperado: objetos nativos existentes, totais novos corretos e repetição sem duplicidade.
- [ ] Se licença/API/criação de pivô impedir o teste, apresentar o obstáculo ao proprietário e pedir decisão; não trocar por CSV nem Excel desktop silenciosamente.
- [ ] Concluir quando houver evidência real do caminho completo no tenant escolhido; registrar limitações em `docs/acessos.md`.

### 04. Provar Google Sheets, OpenAI e ElevenLabs

- [ ] Preparar `scripts/preflight.py`, `tests/integration/test_providers.py` e fixtures fictícias de texto/áudio.
- [x] Prova OpenAI: catálogo/modelo, inferência mínima e três casos estruturados fictícios passaram. Ações de domínio são propostas tipadas executadas pelo orquestrador, sem SQL livre.
- [ ] Completar prova ElevenLabs: transcrição de amostra sintética passou com scribe_v2. Nota PT-BR com centavos e síntese ainda não testadas; escolha de voz pendente.
- [ ] Com acesso Google autorizado, criar tabela de sandbox, pivô nativo e gráfico; conferir um total e a propriedade/permissão do arquivo.
- [ ] Simular chave inválida, quota, indisponibilidade e permissão revogada; classificar o erro sem expor segredo.
- [ ] Verificar: `uv run pytest tests/integration/test_providers.py -m live -q`; esperado: cada provedor autorizado passa sua prova; pendentes ficam explicitamente não executados.
- [ ] Se falhar, corrigir somente o serviço afetado e pedir novo acesso quando necessário; não trocar o modelo ou provedor.
- [ ] Concluir quando integrações provadas e pendências estiverem registradas com evidência, sem afirmar funcionamento dos serviços ainda não testados.

## Fase 1. Construir a base segura e o domínio financeiro

### 05. Criar aplicação, banco e migrações

- [x] Criar `app/main.py`, `app/db.py`, testes de health/rollback, configuração de banco e Compose.
- [x] Criar PostgreSQL local com volume e credencial própria; nenhum banco externo utilizado.
- [x] Configurar Alembic; migração inicial e teste de aplicação em banco vazio.
- [x] Implementar transações, timestamps UTC, UUIDs e escopo obrigatório de workspace.
- [x] Provar rollback quando houver erro entre duas gravações relacionadas.
- [x] Verificar: `uv run pytest tests/integration/test_database.py -q`; migração limpa, integridade e rollback aprovados.
- [ ] Concluir quando reiniciar os processos preservar dados e as migrações forem reproduzíveis; revisar e versionar.

### 06. Implementar identidade e permissões

- [ ] Criar `app/domain/access.py`, `app/models/identity.py` e `tests/unit/test_access.py`.
- [x] Vincular proprietário por Telegram user ID e procedimento explícito; proibir autoinscrição aberta como owner.
- [ ] Criar workspace e membership; decidir no onboarding nome, moeda BRL e fuso sugerido.
- [ ] Preparar compartilhamento por convite explícito e papéis owner/editor/viewer, sem compartilhar dados antes de aceite.
- [x] Validar usuário, chat e workspace em cada ação, callback e envio; recusar mensagens de grupos não vinculados.
- [ ] Verificar: `uv run pytest tests/unit/test_access.py -q`; esperado: nenhum usuário ou callback de outro workspace acessa dados.
- [ ] Concluir quando os testes negativos passarem; revisar e versionar.

### 07. Implementar áreas, categorias e dimensões

- [ ] Criar `app/domain/organization.py`, `app/models/organization.py` e `tests/unit/test_organization.py`.
- [ ] Implementar áreas, categorias/subcategorias, aliases, tags e projetos com nomes configuráveis e UUIDs estáveis.
- [ ] Implementar criação, renomeação, arquivamento, reparentamento e mesclagem com validação de ciclos e colisões.
- [ ] Preservar histórico e permitir reclassificação por período mediante prévia; não apagar categoria referenciada.
- [ ] Testar categorias de nomes próximos, árvore com múltiplos níveis, pai inválido e renomeação com relatórios existentes.
- [ ] Verificar: `uv run pytest tests/unit/test_organization.py -q`; esperado: operações consistentes e nenhuma categoria fixa imposta pelo código.
- [ ] Concluir quando criar uma categoria não exigir editar enum, prompt ou layout de células; revisar e versionar.

### 08. Implementar lançamentos, contas e divisões

- [ ] Criar `app/domain/transactions.py`, `app/models/finance.py` e `tests/unit/test_transactions.py`.
- [ ] Implementar receitas, despesas, contas, saldos iniciais, datas de ocorrência/competência/liquidação, status e classificações configuráveis de variabilidade/necessidade.
- [ ] Implementar allocations por categoria/área/projeto com soma exata em centavos.
- [ ] Implementar transferências balanceadas, taxa separada, estorno/reembolso vinculado e revisão de lançamento.
- [ ] Testar unidades mínimas por moeda, câmbio ausente sem contravalor inventado, valores inválidos, divisão desigual, mudança de mês/fuso e duas despesas legítimas idênticas.
- [ ] Verificar: `uv run pytest tests/unit/test_transactions.py -q`; esperado: totais exatos, transferências sem consumo e reembolso sem renda falsa.
- [ ] Concluir quando as invariantes financeiras da arquitetura estiverem cobertas por testes; revisar e versionar.

### 09. Implementar cartões, parcelas e recorrências

- [ ] Criar `app/domain/commitments.py`, `app/models/commitments.py` e `tests/unit/test_commitments.py`.
- [ ] Modelar fechamento/vencimento, compra no cartão, fatura, pagamento e passivo sem duplicar despesa.
- [ ] Gerar parcelas com soma exata e regra de arredondamento estável; diferenciar consumo total e desembolso por período.
- [ ] Implementar recorrências com timezone, exceção, cancelamento e chave única de ocorrência.
- [ ] Testar compra próxima ao fechamento, fevereiro, virada de ano, centavo residual e reexecução de rotina.
- [ ] Verificar: `uv run pytest tests/unit/test_commitments.py -q`; esperado: calendário correto e nenhuma cobrança/ocorrência duplicada.
- [ ] Concluir quando o mesmo caso puder ser visto por caixa e competência sem misturar os resultados; revisar e versionar.

### 10. Implementar orçamento, metas e agenda financeira

- [ ] Criar `app/domain/budgets.py`, `app/domain/goals.py` e testes correspondentes em mudanças separadas.
- [ ] Implementar limites por área, categoria, projeto e responsável; janelas semanal/mensal/anual/personalizada, vigência e revisão.
- [ ] Tratar sem limite como null, teto zero como zero e descendentes sem dupla contagem; explicitar orçamentos sobrepostos.
- [ ] Implementar alertas configuráveis, transporte opcional de saldo e histórico das mudanças, sem impedir registro de gasto ocorrido.
- [ ] Implementar metas, reservas, contribuições, assinaturas, vencimentos e lembretes ligados às finanças/projetos.
- [ ] Verificar: `uv run pytest tests/unit/test_budgets.py tests/unit/test_goals.py -q`; esperado: limite hierárquico correto, alertas únicos e metas sem criar receita fictícia.
- [ ] Concluir quando todos os estados puderem ser consultados por serviços de domínio; revisar e versionar.

## Fase 2. Entregar o agente de Telegram com texto e áudio

### 11. Criar inbox, outbox e worker duráveis

- [ ] Criar `app/jobs/inbox.py`, `app/jobs/outbox.py` e testes de persistência; adicionar worker em alteração própria.
- [ ] Persistir evento antes do ACK; aplicar unicidade por bot/update e por item de ação.
- [ ] Gravar evento financeiro, auditoria e job de publicação na mesma transação.
- [ ] Implementar leases com fencing, tentativas, backoff, retomada controlada e escritor exclusivo por workbook; escrita externa incerta exige reconciliação antes de liberar nova escrita.
- [ ] Testar reinício, entrega dupla, falha pós-commit, worker antigo com lease expirada e ordem 11 seguida de 10; revisão publicada nunca regride.
- [ ] Verificar: `uv run pytest tests/integration/test_jobs.py -q`; esperado: sem perda de job e sem duplicação de fato financeiro.
- [ ] Concluir quando a fila sobreviver a reinício; revisar e versionar.

### 12. Conectar Telegram e persistir conversas

- [ ] Criar `app/telegram/router.py`, `app/telegram/delivery.py` e testes de handlers; manter autorização no serviço existente.
- [ ] Implementar onboarding, texto, voz, documento/imagem e botões; iniciar com polling no desenvolvimento.
- [ ] Persistir propostas, perguntas pendentes e referências a itens; retomar conversa depois de reinício.
- [ ] Implementar respostas recebida, aguardando confirmação, registrada e destino pendente sem confundi-las.
- [ ] Validar callback expirado, remetente errado, edição de mensagem e reentrega do Telegram.
- [ ] Verificar: `uv run pytest tests/integration/test_telegram.py -q`; esperado: acesso negado antes de processamento e conversa recuperável.
- [ ] Concluir quando mensagens reais de sandbox chegarem e respostas voltarem ao chat autorizado; revisar e versionar.

### 13. Implementar a fronteira GPT-6 Luna

- [ ] Criar `app/ai/llm.py`, `app/agent/contracts.py` e `tests/unit/test_ai_contracts.py`.
- [ ] Concentrar cliente OpenAI, modelo exato, erros, retentativas, uso e schemas de ferramentas nessa fronteira.
- [ ] Implementar extração comum de texto/transcrição/comprovante para proposta tipada com referências de origem e campos ausentes.
- [ ] Disponibilizar contexto mínimo de categorias, contas e regras; nunca enviar segredos ou deixar o modelo escolher workspace.
- [ ] Tratar recusa, saída inválida, nome inexistente e resposta ambígua com esclarecimento, sem inventar valores ou categorias.
- [ ] Verificar: `uv run pytest tests/unit/test_ai_contracts.py -q`; esperado: casos inválidos não geram mutação e a configuração preserva `gpt-6-luna`.
- [ ] Com a API autorizada, executar lote de avaliação de sandbox e registrar respostas/uso sem segredos.
- [ ] Concluir quando a interpretação real funcionar e os erros estiverem recuperáveis; revisar e versionar.

### 14. Conectar ferramentas de organização e finanças

- [ ] Criar `app/agent/orchestrator.py`, `app/agent/policy.py` e `tests/integration/test_agent_actions.py`.
- [ ] Ligar ferramentas tipadas aos serviços de categorias, limites, metas, lançamentos, cartões e recorrências.
- [ ] Implementar prévia e confirmação vinculadas a usuário, payload, revisão e validade para ações de impacto.
- [ ] Implementar corrigir/cancelar/desfazer, referência ao último item e seleção entre candidatos ambíguos.
- [ ] Impedir SQL, shell, fórmulas ou código livre; limitar ferramentas por turno e verificar efeitos após execução.
- [ ] Verificar: `uv run pytest tests/integration/test_agent_actions.py -q`; esperado: comando natural produz a mudança certa e autorização é reaplicada em cada ferramenta.
- [ ] Testar múltiplas despesas em uma mensagem sem misturar a confirmação de itens.
- [ ] Concluir quando as jornadas de organização e finanças puderem ocorrer integralmente no chat; revisar e versionar.

### 15. Implementar ElevenLabs de ponta a ponta

- [ ] Criar `app/audio/elevenlabs.py`, `app/audio/formats.py` e `tests/integration/test_audio.py`.
- [ ] Baixar mídia somente de usuário autorizado, validar tamanho/duração/MIME e persistir estado de processamento.
- [ ] Transcrever com o modelo STT verificado na conta e enviar o texto ao mesmo fluxo de interpretação.
- [ ] Gerar respostas faladas a partir do resumo calculado; converter formato quando necessário e enviar junto do texto.
- [ ] Tratar ruído, silêncio, números ambíguos, idioma, timeout e falta de crédito; apagar mídia conforme retenção escolhida.
- [ ] Verificar: `uv run pytest tests/integration/test_audio.py -q`; esperado: falha de áudio não duplica nem reverte movimentação e não bloqueia texto.
- [ ] Executar teste `live` autorizado com centavos e correção por voz; conferir áudio e texto manualmente.
- [ ] Concluir quando entrada e saída de áudio operarem pelo Telegram com ElevenLabs real; revisar e versionar.

## Fase 3. Publicar dados confiáveis em Excel online e Sheets

### 16. Definir o contrato de planilha e a projeção

- [ ] Criar `app/spreadsheets/contracts.py`, `app/spreadsheets/projection.py` e `tests/unit/test_projection.py`.
- [ ] Definir nomes/IDs estáveis, UUID, revisão de dado/esquema/relatório, projection_revision monotônica e data de atualização; Lancamentos tem uma linha por movimentação e Rateios uma linha por allocation.
- [ ] Implementar snapshot de workspace com valores, dimensões e agregações necessárias, sem segredo.
- [ ] Separar áreas geradas, fórmulas protegidas, entradas manuais e análises livres preservadas.
- [ ] Criar testes com árvore de categorias, divisão de gasto, moeda diferente e dados vazios.
- [ ] Verificar: `uv run pytest tests/unit/test_projection.py -q`; esperado: projeção reconcilia com os fatos e mantém valores numéricos/tipos corretos.
- [ ] Concluir quando ambos os adaptadores puderem consumir o mesmo contrato sem conhecer a estrutura interna do domínio; revisar e versionar.

### 17. Implementar publicação no Google Sheets

- [ ] Criar `app/integrations/google_sheets.py`, `app/spreadsheets/google_layout.py` e `tests/integration/test_sheets_sync.py`.
- [ ] Criar as abas da arquitetura, formatos BRL/data, validações, intervalos protegidos e fórmulas próprias do Sheets.
- [ ] Implementar publicação por UUID/revisão, rejeitar job obsoleto antes da escrita, expandir a origem das análises e controlar objetos por IDs persistidos.
- [ ] Implementar backoff para limites, detecção de timeout após escrita, verificação e reconciliação.
- [ ] Testar inserção, correção, estorno, categoria renomeada, token revogado e repetição do lote.
- [ ] Verificar: `uv run pytest tests/integration/test_sheets_sync.py -q`; esperado: adapter simulado cobre falhas sem append duplicado.
- [ ] Com acesso real autorizado, publicar fixtures e comparar contagens/totais por moeda/tipo.
- [ ] Concluir quando estado verificado e link correto retornarem ao Telegram; revisar e versionar.

### 18. Implementar publicação no Excel online

- [ ] Criar `app/integrations/excel_online.py`, `integrations/excel/scripts/publish.ts` e `tests/integration/test_excel_sync.py`.
- [ ] Transformar o probe aprovado da fase 0 em fluxo autenticado que recebe snapshot/lote e retorna evidência.
- [ ] Criar abas, tabelas estruturadas, fórmulas, nomes, validações e proteções com referências absolutas.
- [ ] Serializar escrita por workbook no worker e no fluxo; implementar job ID, revisão monotônica, rejeição de job obsoleto, retentativas e leitura de resultado real.
- [ ] Testar arquivo ocupado, falha após escrita, duplicidade, permissão expirada e alteração manual conflitante.
- [ ] Verificar: `uv run pytest tests/integration/test_excel_sync.py -q`; esperado: timeout não cria duplicata e erro não vira sucesso.
- [ ] Executar a versão conectada no tenant autorizado e conferir números no Excel online aberto no navegador.
- [ ] Concluir quando os registros se atualizarem com origem e revisão visíveis; revisar e versionar.

### 19. Implementar edição controlada nas planilhas

- [ ] Criar `app/spreadsheets/imports.py`, `app/spreadsheets/conflicts.py` e `tests/integration/test_sheet_edits.py`.
- [ ] Implementar `Entrada_Alteracoes` para lançamentos, categorias e limites, com campos permitidos, UUID e revisão-base.
- [ ] Expor no Telegram consultar alterações, pré-visualizar, confirmar, rejeitar e resolver conflito.
- [ ] Detectar edições candidatas por leitura/poll autorizado; não presumir eventos instantâneos de célula.
- [ ] Aplicar alterações pelo domínio e republicar; preservar fórmulas/abas manuais e sinalizar edição inesperada em área gerada.
- [ ] Verificar: `uv run pytest tests/integration/test_sheet_edits.py -q`; esperado: edição concorrente não sobrescreve mudança e fórmula injetada é tratada como texto.
- [ ] Testar a mesma entrada importada duas vezes e um lançamento dividido em categorias.
- [ ] Concluir quando os dois destinos aceitarem o fluxo de edição com confirmação pelo Telegram; revisar e versionar.

## Fase 4. Entregar análises avançadas e objetos nativos

### 20. Criar catálogo de métricas e consultas

- [ ] Criar `app/analytics/metrics.py`, `app/analytics/query.py` e `tests/unit/test_metrics.py`.
- [ ] Documentar em `docs/metricas.md` definição, população, período, regime, unidade e tratamento de nulos de cada métrica.
- [ ] Implementar orçamento x realizado, disponível, desvio, saldo, poupança, comprometimento, ranking e participação.
- [ ] Implementar comparações mensais/anuais, acumulado, média móvel, frequência distinta de movimentações, ticket global/alocado, média/mediana, distribuição e sinais explicáveis de valores fora do padrão.
- [ ] Compilar filtros/dimensões permitidos para SQL parametrizado; usar allocations sem dupla contagem.
- [ ] Verificar: `uv run pytest tests/unit/test_metrics.py -q`; esperado: denominador zero, meses incompletos, reembolsos e transferências têm resultados definidos.
- [ ] Conferir por SQL e nas duas planilhas uma compra de R$ 600,00 dividida em dois rateios de R$ 300,00: total R$ 600,00, uma movimentação, dois rateios e ticket global R$ 600,00.
- [ ] Concluir quando cada indicador tiver definição e teste; revisar e versionar.

### 21. Implementar fluxo de caixa, cenários e patrimônio informado

- [ ] Criar `app/analytics/scenarios.py`, `app/analytics/forecast.py` e testes em alterações separadas.
- [ ] Projetar recebíveis, parcelas, faturas, recorrências e vencimentos por caixa, sem somá-los novamente como consumo.
- [ ] Criar cenários separados com premissas de renda, redução de categoria e despesa extraordinária.
- [ ] Implementar patrimônio líquido de ativos/passivos informados e cronograma de dívida com taxas fornecidas.
- [ ] Exibir cobertura e histórico insuficiente; não preencher taxa, cotação ou tendência ausente com números inventados.
- [ ] Verificar: `uv run pytest tests/unit/test_scenarios.py tests/unit/test_forecast.py -q`; esperado: cenário nunca altera realizado e ajustes reconciliam com as premissas.
- [ ] Concluir quando o Telegram puder criar, comparar, explicar e descartar cenários; revisar e versionar.

### 22. Implementar definições de análise e tabelas dinâmicas

- [ ] Criar `app/analytics/reports.py`, `app/spreadsheets/pivots.py` e `tests/integration/test_pivots.py`.
- [ ] Definir ReportDefinition com nome, linhas, colunas, métricas, filtros, período, ordenação, limites de tamanho e revisão.
- [ ] Implementar ferramentas para criar, editar, salvar, duplicar e remover análises geradas no Telegram.
- [ ] Criar pivôs nativos com soma/contagem/média/mínimo/máximo compatíveis com o grão; publicar medida não aditiva em área auxiliar identificada quando o destino não suportar contagem distinta, sem somar frequência por categoria.
- [ ] Implementar atualização/reconstrução de pivôs gerados usando o caminho provado, preservando filtros e objetos manuais.
- [ ] Verificar: `uv run pytest tests/integration/test_pivots.py -q`; esperado: editar linhas/colunas muda o agrupamento sem perda nem duplicação dos fatos.
- [ ] Com sandbox autorizado, conferir objeto pivot real, dados atuais, drill-down e totais em ambos os serviços.
- [ ] Concluir quando "crie uma tabela dinâmica por categoria e mês" funcionar sem edição de código ou criação manual de pivô; revisar e versionar.

### 23. Implementar dashboards, gráficos, filtros e segmentações

- [ ] Criar `app/analytics/charts.py`, `app/spreadsheets/dashboards.py` e `tests/integration/test_dashboards.py`.
- [ ] Construir painéis mensal/anual, orçamento x realizado, evolução, composição, Pareto, calendário/heatmap e compromissos.
- [ ] Implementar gráficos nativos suportados e suas alternativas editáveis, com especificação explícita por destino.
- [ ] Implementar filtros/segmentações de período, área, categoria, projeto, responsável, conta, tipo e status.
- [ ] Ligar criação/alteração de gráficos e filtros às ferramentas do Telegram, preservando a análise salva.
- [ ] Verificar: `uv run pytest tests/integration/test_dashboards.py -q`; esperado: o filtro altera números e gráficos de acordo com o mesmo conjunto de dados.
- [ ] Abrir Excel online e Sheets reais de sandbox; conferir objetos, legibilidade, pivôs, segmentações, totais e fórmulas sem erro.
- [ ] Concluir quando uma categoria nova aparecer nas análises sem editar fórmulas manualmente e houver paridade semântica; revisar e versionar.

### 24. Implementar relatórios no chat e exportações

- [ ] Criar `app/reports/render.py`, `app/reports/export.py` e `tests/integration/test_reports.py`.
- [ ] Gerar PNG de gráficos e resumo com período, filtros, revisão e origem dos valores; reutilizar métricas oficiais.
- [ ] Gerar relatório completo e exportar CSV/XLSX; obter o XLSX sofisticado a partir do workbook Excel publicado/verificado.
- [ ] Preservar tabelas dinâmicas e objetos no caminho de exportação; não chamar exportação básica de workbook completo.
- [ ] Implementar pedidos pelo Telegram: relatório, link da análise, arquivo, gráfico e resumo em áudio ElevenLabs.
- [ ] Verificar: `uv run pytest tests/integration/test_reports.py -q`; esperado: os números do texto, gráfico e arquivo coincidem e conteúdo de fórmula não confiável é escapado.
- [ ] Abrir arquivos exportados e conferir ausência de erros, tamanho e envio ao destinatário autorizado.
- [ ] Concluir quando relatórios e workbook chegarem pelo Telegram sem dependência de operação manual; revisar e versionar.

## Fase 5. Automatizar rotinas e fechar a operação

### 25. Implementar agenda, alertas e revisão periódica

- [ ] Criar `app/jobs/scheduler.py`, `app/domain/notifications.py` e `tests/integration/test_schedules.py`.
- [ ] Persistir rotinas para resumo semanal/mensal, revisão de orçamento, assinaturas, faturas e metas.
- [ ] Permitir criar, consultar, alterar, pausar e cancelar pelo Telegram, com fuso e destino explícitos.
- [ ] Impedir alerta repetido do mesmo limiar/período/revisão e execução dupla após reinício.
- [ ] Aplicar política de atrasos e falhas; não disparar uma sequência antiga de lembretes sem contexto.
- [ ] Verificar: `uv run pytest tests/integration/test_schedules.py -q`; esperado: rotina dispara uma vez e cancelamento persiste após reinício.
- [ ] Concluir quando o resumo programado chegar ao chat autorizado com valores atuais e links corretos; revisar e versionar.

### 26. Implementar observabilidade, custos e comandos operacionais

- [ ] Criar `app/observability.py`, `app/domain/operations.py` e `tests/unit/test_operations.py`.
- [ ] Registrar correlation ID, revisões, latência, tentativas, fila e erro seguro, sem texto financeiro completo por padrão.
- [ ] Medir uso OpenAI/ElevenLabs e operações de integração; carregar preços vigentes quando houver prova, sem estimativas disfarçadas de faturamento.
- [ ] Pedir ao proprietário limite de consumo e destinatário dos avisos; implementar bloqueio configurável e mensagem clara.
- [ ] Expor no Telegram status, última sincronização, jobs pendentes, reconexão e chaves de bloqueio por função/destino.
- [ ] Verificar: `uv run pytest tests/unit/test_operations.py -q`; esperado: usuário sem permissão não pausa o sistema e log não contém segredos.
- [ ] Concluir quando uma falha de provedor puder ser diagnosticada sem abrir dados pessoais nem falsificar sucesso; revisar e versionar.

### 27. Implementar backup, restauração e exclusão controlada

- [ ] Criar `scripts/backup.py`, `scripts/restore.py` e `tests/integration/test_restore.py`.
- [ ] Pedir destino autorizado, retenção, RPO/RTO pretendidos e tratamento de mídia/anexos antes de backup externo.
- [ ] Salvar banco, versões, análises e parâmetros; manter recuperação de segredos em procedimento separado.
- [ ] Restaurar em banco/arquivos de sandbox sem sobrescrever produção; conferir totais, relações e jobs.
- [ ] Implementar exportação completa e pedido confirmado de exclusão; documentar limites de backups e cópias nos fornecedores.
- [ ] Verificar: `uv run pytest tests/integration/test_restore.py -q`; esperado: restauração íntegra e nenhuma publicação automática em destino de produção.
- [ ] Concluir quando uma restauração real isolada estiver registrada e o runbook existir; revisar e versionar.

## Fase 6. Validar qualidade e funcionar com dados reais

### 28. Montar a avaliação do agente e o teste de segurança

- [ ] Criar `evals/cases.jsonl`, `evals/rubric.md` e `tests/e2e/test_agent_journeys.py`.
- [ ] Incluir pelo menos 20 casos de interpretação com valores, datas, referências, múltiplos itens e ambiguidades; rotular fixtures como fictícias.
- [ ] Separar regressão de capacidade e manter casos reservados; adicionar traces reais apenas com consentimento/anonimização.
- [ ] Cobrir jornadas com múltiplas interações: criar categoria, definir limite, lançar áudio, corrigir item, pedir pivô, filtrar, criar cenário e exportar.
- [ ] Cobrir ações proibidas: usuário desconhecido, callback roubado, prompt injection em comprovante, planilha com fórmula maliciosa e troca de workspace.
- [ ] Executar jornadas essenciais quatro vezes com estado isolado; registrar falhas e uso, sem selecionar só a melhor tentativa.
- [ ] Verificar: `uv run pytest tests/e2e/test_agent_journeys.py -m "not live" -q`; esperado: estado final e ferramentas autorizadas correspondem à rubrica, inclusive quando a resposta verbal alega sucesso.
- [ ] Fazer revisão humana da semântica; não acrescentar outro modelo avaliador nem declarar calibração sem escolha e acesso do proprietário.
- [ ] Concluir quando falhas relevantes tiverem correção e regressão correspondente; revisar e versionar.

### 29. Fazer a conferência financeira e visual completa

- [ ] Preparar um conjunto de sandbox com receitas, despesas, transferências, reembolso, cartão, parcelas, limites hierárquicos e cenários.
- [ ] Executar o conjunto pelo Telegram, usando texto e áudio reais autorizados.
- [ ] Conferir banco, Excel online e Sheets por UUID, revisão, contagem e total por moeda/tipo/período.
- [ ] Criar e editar pivôs, gráficos, filtros e segmentações pelo Telegram; conferir resultado real em ambos os serviços.
- [ ] Simular offline, quota, token revogado, reinício, timeout pós-escrita e duas alterações concorrentes; recuperar sem perda/duplicidade.
- [ ] Verificar: `uv run pytest tests --cov=app --cov-report=term-missing -m "not live"`; esperado: suíte verde, cobertura de pelo menos 80% e invariantes críticas sem lacunas conhecidas.
- [ ] Registrar separadamente o resultado dos testes conectados e da inspeção visual; teste pulado não conta como integração aprovada.
- [ ] Concluir quando os casos de aceite do produto estiverem cobertos e os arquivos exportados preservarem objetos; revisar e versionar.

### 30. Preparar o ambiente que ficará ligado

- [ ] Pedir ao proprietário a preferência de hospedagem, conta, orçamento e autorização antes de criar qualquer recurso externo.
- [ ] Comparar as alternativas brasileiras em `docs/hospedagem.md`, incluindo preço mensal sem compromisso longo, renovação, backup e manutenção; não depender da reabertura de cadastros do Railway.
- [ ] Escolher e documentar o ambiente; configurar domínio/HTTPS se usar webhook e segredos separados de sandbox.
- [ ] Preparar `Dockerfile`, `compose.yaml` e `docs/operacao.md` com persistência, health, logs, atualização, rollback e recuperação.
- [ ] Configurar polling ou webhook, nunca ambos para o mesmo bot; validar secret e persistência de inbox antes do ACK.
- [ ] Configurar backup e monitoramento nos destinos autorizados; remover publicação acidental para workbooks de teste.
- [ ] Verificar: `docker compose up -d`; esperado: API, worker e PostgreSQL saudáveis; `docker compose restart` não perde agenda, dados ou jobs.
- [ ] Executar smoke conectado e teste de recuperação no ambiente escolhido, com autorização para deploy concedida nesta etapa.
- [ ] Concluir quando o bot operar sem depender da sessão de desenvolvimento; revisar e versionar a configuração sem segredos.

### 31. Fazer onboarding pessoal e iniciar piloto

- [ ] Confirmar workspace, moeda, fuso, áreas da vida, contas, saldos iniciais, categorias, metas e política de orçamento pelo Telegram.
- [ ] Criar/vincular planilhas de produção somente após autorização; conferir permissões e destinatários.
- [ ] Pedir arquivo e autorização específica se houver importação de histórico; produzir prévia, deduplicação por origem e reconciliação antes de aplicar.
- [ ] Começar com confirmação de lançamento; habilitar registro direto com Desfazer apenas após teste e escolha do proprietário.
- [ ] Usar o bot no cotidiano e revisar erros, custos, latência, categorias, alertas e entendimento de áudio; cada falha relevante vira caso de teste.
- [ ] Verificar: realizar pelo Telegram uma receita, despesa por áudio, correção, novo limite, pivô, gráfico, cenário e exportação; esperado: efeitos corretos nas duas planilhas.
- [ ] Concluir quando o proprietário conseguir executar essas jornadas e entender as pendências de sincronização sem suporte técnico.

### 32. Encerrar a implantação e manter o sistema

- [ ] Atualizar o README de planejamento para funcionamento comprovado, citando somente integrações realmente testadas.
- [ ] Registrar em `docs/operacao.md` comandos, periodicidade de backup, renovação de tokens, preços usados na medição e procedimento de incidente.
- [ ] Conferir que todas as funções do catálogo analítico e da interface Telegram têm entrega e evidência; listar pendências honestamente, sem declarar conclusão parcial como total.
- [ ] Pedir aceite do proprietário sobre resultado, custos e riscos residuais depois de apresentar a versão funcionando.
- [ ] Programar manutenção de dependências, revisão das APIs e testes periódicos de restore; obter autorização para rotinas externas quando necessário.
- [ ] Revisar diff final, segredos e escopo; preservar a escolha `gpt-6-luna` e ElevenLabs em todas as configurações.
- [ ] Concluir quando não houver requisito solicitado sem implementação ou decisão explícita do proprietário e o runbook permitir reiniciar e recuperar o serviço.

## Checklist de aceite do começo ao fim

- [ ] Mensagens e áudios entram pelo Telegram somente de usuários autorizados.
- [ ] GPT-6 Luna interpreta pedidos e chama ferramentas seguras; ElevenLabs faz STT/TTS real.
- [ ] Áreas, categorias, subcategorias, aliases, tags e projetos são configuráveis no chat.
- [ ] Limites hierárquicos, períodos, metas, alertas e revisões funcionam sem dupla contagem.
- [ ] Receitas, despesas, divisões, transferências, reembolsos, cartões, parcelas e recorrências têm números corretos.
- [ ] Correção, confirmação e desfazer funcionam após reinício e com múltiplos itens.
- [ ] Excel online e Sheets mostram dados reconciliados e o estado de atualização.
- [ ] Tabelas dinâmicas e gráficos são objetos reais, editáveis e criados/alterados pelo Telegram.
- [ ] Filtros e segmentações mudam os dados certos; categorias novas entram automaticamente.
- [ ] Painéis mensal/anual, composição, Pareto, distribuição, caixa, metas, cenários e patrimônio informado estão disponíveis.
- [ ] Importações e alterações nas planilhas têm prévia e resolução de conflito.
- [ ] Relatórios, links, áudios e XLSX chegam ao chat correto com os mesmos valores.
- [ ] Falhas e reentregas não causam perda, duplicação ou falsa confirmação.
- [ ] Backup, restauração, limites de API e operação contínua foram testados.
- [ ] Todos os acessos e recursos foram fornecidos/autorizados pelo proprietário, sem segredos no repositório.
