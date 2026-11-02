# Métricas financeiras e exportações locais

Implementação local em `app/analytics`, `app/reports` e `app/spreadsheets`. A origem é um snapshot autorizado do domínio, identificado por workspace e revisão. O motor não consulta credenciais, não executa SQL/código/fórmulas recebidos e não acessa Microsoft ou Google.

## População, datas e unidades

Valores financeiros oficiais são inteiros na unidade mínima da moeda original. Divisões, proporções, medianas e taxas usam `Decimal`; resultados fracionários são serializados como strings decimais. A conversão para float existe somente na apresentação gráfica. Moedas são sempre agrupadas separadamente; nenhum câmbio é presumido. A apresentação conhece a precisão de moedas comuns, incluindo BRL (2), JPY (0) e KWD (3); moeda desconhecida mantém o rótulo de unidades mínimas.

Consultas usam `[start_date, end_date)`, início incluído e fim excluído. Por exemplo, outubro de 2026 é `2026-10-01` até `2026-11-01`. Os campos financeiros são datas locais do workspace; o fuso acompanha o resultado. O regime `competence` usa `competence_date`, `occurrence` usa `occurrence_date` e `cash` exige `settlement_date`. Uma data ausente de competência usa ocorrência; caixa ausente permanece fora da visão de caixa. Estados cancelados/excluídos não entram nos fatos.

Uma linha analítica representa um rateio. Sem rateios, o motor cria uma linha não categorizada. Rateios existentes precisam reconciliar exatamente com o lançamento. Uma compra de 60.000 unidades mínimas em dois rateios de 30.000 produz despesa global 60.000, uma movimentação, dois rateios e ticket global 60.000. Frequências por categoria não são aditivas. Na população filtrada por categoria, o ticket usa o valor alocado à população, não o valor integral original repetido.

Transferências, inclusive pagamentos de cartão registrados como transferência, têm consumo e receita iguais a zero. Reembolsos reduzem a despesa líquida e permanecem identificáveis. O ticket de compras usa somente despesas; reembolsos não criam compras negativas. Cada lançamento pode entrar em mais de um grupo de categoria; os totais distintos são recalculados a partir dos UUIDs, nunca somados dos grupos.

Filtros permitidos: datas, regime, `category_ids`, `area_ids`, `project_ids`, `account_ids`, `responsible_ids`, `tag_ids`, `types`, `statuses` e `currencies`. Listas vazias selecionam população vazia. Filtros se intersectam; categorias incluem descendentes e não duplicam filhos selecionados novamente. Classificações `variability` e `necessity` usam valores informados, herdados dos pais quando ausentes, com prioridade para o lançamento. O motor não atribui julgamentos às categorias.

## Catálogo

Todas as métricas abaixo usam a população filtrada e o regime/período visíveis, salvo indicação explícita.

| Campo | Definição / grão | Unidade e ausências |
|---|---|---|
| `expense_minor` | Soma de despesas alocadas menos reembolsos alocados. | Unidade mínima; soma vazia 0. |
| `income_minor` | Soma de receitas alocadas; transferências não entram. | Unidade mínima; soma vazia 0. |
| `net_minor` | Receita menos despesa líquida. | Unidade mínima; não equivale ao saldo bancário. |
| `transaction_count` | UUIDs distintos de receitas, despesas e reembolsos. | Contagem; exclui transferências do indicador financeiro. |
| `expense_transaction_count` | UUIDs distintos de compras que são despesas. | Contagem; população do ticket. |
| `allocation_count` | Linhas de fatos selecionadas, incluindo transferências quando consultadas. | Contagem de rateios, distinta da frequência de compras. |
| `ticket_minor` | Valor alocado das compras / UUIDs distintos de compras. | Decimal na unidade mínima; `null` sem compras. |
| `median_ticket_minor` | Mediana dos valores de compra agregados por UUID. | Decimal na unidade mínima; `null` sem compras. |
| `min_ticket_minor`, `max_ticket_minor` | Extremos da mesma população de compras. | Unidade mínima; `null` sem compras. |
| `population_variance_minor_squared` | Variância populacional dos valores por UUID de compra. | Decimal em unidade mínima ao quadrado; `null` sem compras. |
| `population_stddev_minor` | Raiz Decimal da variância populacional. | Decimal na unidade mínima; `null` sem compras. |
| `saving_rate` | `(income_minor - expense_minor) / income_minor`. | Proporção decimal; `null` com receita zero. |
| `expense_income_ratio` | Despesa líquida / receita. | Proporção decimal; `null` com receita zero. |
| `share` | Despesa líquida da categoria / despesa líquida global da moeda. | Proporção; `null` se denominador zero. |
| `rank` | Ordem decrescente da despesa líquida por moeda. | Inteiro; desempate determinístico por categoria. |
| `pareto_cumulative_rate` | Participação acumulada na ordem do ranking. | Proporção; reembolsos podem produzir valores negativos ou acumulado não monotônico. |
| `month_change_rate` | `(mês - mês anterior) / mês anterior`. | `null` sem histórico ou com denominador zero. |
| `year_change_rate` | Comparação com o mesmo mês do ano anterior. | `null` sem histórico ou com denominador zero. |
| `rolling_3_month_mean_minor` | Média dos últimos três meses da população consultada. | `null` com menos de três meses; meses vazios internos valem zero. |
| `rolling_3_month_median_minor` | Mediana dos mesmos três meses. | `null` com menos de três meses. |
| `ytd_expense_minor` | Acumulado dentro do ano e da população consultada. | `ytd_partial_population` indica início de consulta posterior a 1º de janeiro. |
| `incomplete_period` | Consulta não cobre todo o mês civil. | Booleano; comparação parcial não é apresentada como mês completo. |
| `distributions` | Até dez faixas inteiras com contagens de compras por UUID. | Limites na unidade mínima; contagens não são valores monetários. |
| `anomalies` | Com ≥5 compras, sinal acima de mediana + 3 MAD; se MAD=0, acima de 3× mediana. | Regra, mediana e MAD acompanham o UUID. Sinal para revisão; não afirma fraude ou erro. |

Agrupamentos diários, mensais, anuais, por categoria, área, projeto e classificações usam essas mesmas fórmulas. Não há preenchimento de tendência estatística, receita desconhecida, taxa ou cotação.

## Orçamentos e metas

Cada orçamento possui população própria: moeda, descendentes de categoria e filtros de área/projeto/responsável. Orçamentos sobrepostos são apresentados individualmente e não somados como despesa. O regime `accrual` do domínio corresponde à competência; `cash` usa liquidação.

Períodos `week`, `month` e `year` repetem a partir da data de início informada; fim de mês é ajustado sem perder o dia âncora seguinte. `custom` usa a janela explícita. `end_date` é exclusivo. O relatório apresenta os períodos que intersectam a consulta. Um recorte parcial preserva o limite inteiro e mostra sua cobertura.

| Campo | Definição | Ausências / limites |
|---|---|---|
| `base_limit_minor` | Limite configurado do período. | `null` significa sem limite; 0 é limite zero. |
| `carryover_applied_minor` | Saldo restante do período anterior quando carryover está habilitado. | Pode ser negativo após estouro. Começa em 0 na vigência do orçamento. |
| `limit_minor` | Limite base + carryover. | `null` continua sem limite. |
| `actual_minor` | Despesa líquida da população do orçamento intersectada com a consulta. | Não multiplica pais nem filhos. |
| `budget_actual_minor` | Despesa líquida de toda a população do orçamento, antes do filtro visual. | Mantém saldo e alertas fiéis ao orçamento inteiro. |
| `remaining_minor` | Limite efetivo menos realizado da população inteira do orçamento. | `null` sem limite. |
| `deviation_minor` | Realizado do orçamento inteiro menos limite efetivo. | `null` sem limite. |
| `consumed_rate` | Realizado do orçamento inteiro / limite efetivo. | `null` com limite ausente ou zero; `zero_limit` distingue os casos. |
| `thresholds_reached` | Limiares informados atingidos por realizado ≥ limiar × limite. | Resultado de cálculo; envio e deduplicação do alerta pertencem ao worker. |
| `daily_expense_minor` | Realizado / dias observados da janela. | `null` sem dias observados. |
| `projected_expense_minor` | Ritmo diário observado × duração total do período. | Projeção mecânica com cobertura explícita; não altera realizado. |
| `projected_overrun` | Projeção maior que limite efetivo. | `null` sem projeção ou limite. |
| `contributed_minor` | Contribuições informadas até a data de referência da meta. | Moeda da meta; não presume valorização. |
| `remaining_minor` de meta | Máximo entre zero e objetivo menos contribuições. | `null` sem objetivo. |
| `progress_rate` | Contribuições / objetivo. | `null` com objetivo ausente ou zero. |
| `required_daily_minor` | Saldo a contribuir / dias até o prazo. | `null` sem prazo, sem referência ou prazo vencido. |

Carryover usa a população completa do orçamento antes do recorte visual: filtrar uma categoria no relatório não cria saldo disponível adicional.

## Caixa, cenários e patrimônio

`forecast(snapshot, assumptions)` produz compromissos separados do consumo realizado. A data inicial vem de premissa explícita ou de `snapshot.as_of`; ausência de ambas é erro. A janela é `[start_date, end_date)`, limitada a 3.660 dias. O padrão é 90 dias, sem tendência inventada.

Entram lançamentos pendentes, parcelas ainda não liquidadas descontando `paid_minor`, e recorrências habilitadas a partir da primeira ocorrência ainda não materializada (`next_date`). Um lançamento com parcelas não é incluído novamente como compromisso integral. Exceções e pausas de recorrências são respeitadas. Rateios acompanham os compromissos proporcionalmente, com resíduo inteiro reconciliado. A data de término de uma configuração de recorrência segue o contrato de agenda do domínio, distinto do fim exclusivo da consulta.

Créditos de reembolso também descontam `refunded_minor` das parcelas. Chaves de recorrência já materializadas não voltam à projeção mesmo se o cursor for recuado; o dia âncora preservado mantém 31 de março após 28 de fevereiro. Reembolso nunca é receita: reduz despesa ou dívida.

No caixa realizado, compra de cartão só gera despesa quando existem pagamentos de parcelas vinculados à transferência de quitação. A data é a liquidação dessa transferência e a categoria continua sendo a da compra original. O rateio do pagamento reconcilia centavos, sem nova movimentação de consumo. Crédito de reembolso no próprio cartão reduz dívida e compromissos; não inventa recebimento de dinheiro em banco. Na liquidez projetada entram os saldos de contas `bank`/`cash`; cartões e passivos ficam fora do saldo inicial líquido para não subtrair a mesma dívida duas vezes.

Saldo de conta = saldo inicial informado + movimentação liquidada desde a data de abertura até a referência. Transferências saem de uma conta e entram na outra. Saldo inicial ausente permanece `null`, acompanhado da variação registrada; saldo de referência anterior à abertura também é desconhecido. Um filtro parcial de categorias não permite inferir saldo final total. A projeção explicita que contém apenas compromissos informados.

Patrimônio usa somente ativos e passivos informados, por moeda e respectivas datas. Se algum valor de uma moeda é desconhecido, seu patrimônio líquido consolidado permanece `null`. Uma dívida só ganha cronograma quando valor, taxa, unidade da taxa (`month`/`year`) e pagamento periódico foram fornecidos. Juros usam `Decimal` e arredondamento de meio para cima na unidade mínima. Não se presume CET, indexador ou capitalização adicional.

`scenario` recebe alteração proporcional de renda, reduções por categoria e despesas extraordinárias datadas. A redução se aplica apenas ao rateio correspondente, com descendentes; quando pai e filho se sobrepõem aplica-se a maior redução uma única vez. Cada compromisso arredonda na unidade mínima. O resultado devolve projeção base, cenário, premissas e ajustes conciliáveis. Não escreve no snapshot nem muda realizado.

Também são aceitos `income_minor` como renda mensal absoluta da moeda-base e `extra_expenses_minor` como despesa extraordinária agregada sem data. A renda absoluta substitui a renda mensal projetada; meses parciais recebem a premissa explícita de proporção pelos dias corridos cobertos. Ajustes mensais e despesa sem data são devolvidos separadamente com `date=null`, sem fabricar recebimentos/vencimentos. Nesse caso, saldo de caixa final permanece desconhecido. Renda absoluta e alteração proporcional não podem ser solicitadas simultaneamente.

## Relatórios, arquivos e staging

`ReportDefinition` valida nome, dimensões, métricas, gráfico, filtros, ordenação, limite de células e revisão. Pivôs locais reagrupam fatos e recalculam medidas não aditivas nos totais; não executam SQL nem fórmulas livres. Moeda é uma chave obrigatória mesmo quando omitida dos eixos visíveis. `build_pivot_spec` separa medidas nativas aditivas das auxiliares não aditivas e mantém a publicação em estado pendente.

`export_csv` gera fatos de rateio com workspace, revisão, regime e valores mínimos numéricos. `export_xlsx` cria um arquivo **analítico local**, com tabelas Excel reais, gráficos editáveis por moeda, fórmulas confiáveis, painéis mensal/anual, orçamento, composição, caixa, patrimônio, conferências e entrada manual validada. Valores do motor materializados são identificados como dados com origem/revisão. Fórmulas de soma, saldo, disponível, proporções e conferências são objetos reais. Azul identifica inputs/dados; preto, fórmula; verde, referência entre abas.

O XLSX não é o workbook sofisticado exportado do Excel online. Ele não contém pivôs nativos ou segmentações verificados. As especificações e a prova exigida estão na aba `Tabelas_Dinamicas`. Nenhum arquivo existente com objetos manuais é aberto/regravado. Não foi executado recálculo de fórmulas por Excel/LibreOffice; `formula_cache_verified=false`, com recálculo solicitado ao abrir. PNGs usam o backend Agg e o mesmo conjunto filtrado de dados, sem substituir objetos nativos dos destinos.

Nomes de arquivo não podem escapar da pasta de saída. Texto não confiável iniciado por `=`, `+`, `-`, `@` ou caracteres de controle de planilha é escapado nas exportações; valores numéricos continuam numéricos.

Importação local lê UTF-8 CSV com staging ou colunas transacionais explícitas (`type`, `amount_minor`, `occurrence_date`, `account_id`), ou somente a aba `Entrada_Alteracoes` do XLSX. Limites: 20 MB de entrada, 100 MB descompactados e 5.000 linhas. Fórmulas da aba de entrada, macros e links externos são rejeitados. Abas geradas não são interpretadas como alterações.

Cada alteração tem ID estável, workspace, entidade, operação, UUID alvo quando atualização, revisão-base e campos permitidos. `preview_changes` separa candidatos, conflitos, inválidos e repetições; nunca aplica dados. Atualizações conferem a revisão da entidade; criações conferem a revisão do workspace. `confirmed_commands` exige confirmação do hash exato da prévia e revisão ainda atual, e produz comandos com chave idempotente. O domínio precisa revalidar e aplicar esses comandos atomicamente, sob autorização; a planilha não ganha autoridade financeira.

## Evidência e pendências

Testes locais cobrem compra dividida, reembolso, moedas, transferências, períodos semiabertos, nulos/zero, hierarquia, carryover, cenários, parcelas parciais, projeções, filtros, injeção de fórmulas, staging conflitante e conferência de objetos OOXML reais. O detalhamento dos testes executados fica no resultado da implementação.

Continuam pendentes até a conexão autorizada: criação e reconstrução de pivôs/segmentações nos destinos reais, prova por leitura de revisão/valores, preservação de objetos sofisticados ao baixar workbook, consentimentos/licença Microsoft, paridade conectada com Sheets e recálculo real das fórmulas. Uma especificação local não é prova de integração concluída.
