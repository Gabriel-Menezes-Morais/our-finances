# Excel pessoal, análises prontas e virada de mês

Pesquisa e requisitos de referência em 02/11/2026. Excel online com Microsoft 365 Personal é um cenário estudado; nenhuma integração Microsoft pronta acompanha o repositório. A licença e as permissões de cada instalação precisam de verificação própria.

## Funcionamento solicitado

O workbook deve chegar pronto. O uso cotidiano é registrar gastos pelo Telegram e consultar as análises existentes; criar um relatório pelo agente é uma opção adicional, não requisito para ver os indicadores básicos.

Fluxo: mensagem/áudio → interpretação e confirmação → registro no banco → atualização automática da planilha → painéis e análises prontos. Hospedagem mantém o processamento quando o computador está desligado. Uma falha da planilha mantém o registro salvo e a publicação pendente, sem duplicar o gasto.

| Aba ou painel padrão | Conteúdo preparado |
|---|---|
| Início | Mês atual, gastos, receitas informadas, resultado, limites disponíveis, alertas e última atualização. Saldo bancário só se houver saldo inicial e movimentações suficientes. |
| Lançamentos | Histórico contínuo com datas, descrição, conta, moeda, tipo, origem, revisão e identificador estável. |
| Categorias e áreas | Estrutura configurável, subcategorias, aliases, projetos e classificações informadas. |
| Orçamento mensal | Limite, realizado, disponível, percentual consumido e alertas por área/categoria/projeto. Sem limite permanece sem limite; não inventar tetos. |
| Painel mensal | Composição por categoria/área, evolução diária, maiores gastos, frequência e comparativo com histórico. |
| Painel anual | Meses lado a lado, acumulado e evolução; mês corrente identificado como incompleto. |
| Tabelas dinâmicas | Categoria × mês, área × mês e conta × mês com medidas aditivas; contagens distintas/tickets calculados no grão correto. Objetos nativos fazem parte do aceite. |
| Compromissos | Parcelas, vencimentos, recorrências e assinaturas informadas; visões de caixa e consumo separadas. |
| Metas e cenários | Progresso com contribuições reais; projeções condicionadas às premissas disponíveis. |
| Conferências | Totais por moeda, revisão do banco/publicação, contagens e eventuais pendências. |

Os painéis devem ser instalados e publicados por padrão, mesmo sem pedido de criação de relatório. Sem dados, mostram estado vazio explicado; nenhuma categoria, renda, conta ou limite pessoal é inventado. O desenho pode reutilizar o motor analítico e exportações existentes, mas o workbook final online com esses comportamentos ainda precisa ser implementado e validado.

## Virada dos meses

- Uma base contínua guarda vários meses e anos. Não criar uma base independente nem apagar/copiar lançamentos a cada mês.
- Cada lançamento tem data de ocorrência, competência e liquidação quando informadas; o mês deriva da data e do regime selecionado.
- O painel abre por padrão no mês atual do workspace (`America/Sao_Paulo`, configurável) e permite selecionar mês/ano anteriores.
- A opção de período terá modo **Mês atual** e modo **Mês escolhido**, evitando substituir a consulta histórica que o usuário deixou selecionada. O padrão inicial é Mês atual.
- Exemplo: na passagem de novembro para dezembro, a visão Mês atual muda para dezembro, novembro permanece no histórico e a visão anual contém ambos. Janeiro inicia outra visão anual e conserva o ano anterior.
- Uma rotina de calendário atualiza a referência e publica o novo período mesmo que não haja gasto novo; somente publicar após um lançamento não garante a virada automática.
- Limites mensais recorrentes começam nova janela sem novo cadastro; os gastos de dezembro não consomem o limite de novembro. Limites com vigência encerrada não são prorrogados silenciosamente.
- Transporte de sobra do orçamento ocorre somente se configurado. O resultado do orçamento não redefine saldo bancário nem elimina parcelas/recorrências em aberto.
- Gastos atrasados e correções atualizam o período financeiro correspondente com auditoria. Não mover para o mês do envio apenas porque o registro chegou depois.
- Compra parcelada pode ter consumo no mês da compra e desembolsos em meses futuros; as duas visões ficam identificadas para evitar dupla contagem.
- Novas categorias entram nas tabelas, listas e fontes das análises na publicação seguinte, sem edição de fórmulas pelo proprietário.
- Seleção de mês, filtros e análises pessoais precisam ser preservados nas atualizações; essa é uma prova obrigatória se a publicação substituir o arquivo inteiro.

## O que a conta Personal permite

**Arquivo no OneDrive:** Microsoft Graph permite criar/substituir conteúdo de arquivos usando autenticação delegada de conta pessoal. Isso dá suporte documental a publicar um XLSX produzido pelo servidor; não equivale a editar células pela API de workbook. [Upload de arquivo, permissões pessoais](https://learn.microsoft.com/en-us/graph/api/driveitem-put-content?view=graph-rest-1.0).

**API de workbook:** a Microsoft informa que Excel REST não atende workbooks no OneDrive Consumer; o endpoint de sessão também marca contas pessoais como não suportadas. [Escopo Excel REST](https://learn.microsoft.com/en-us/graph/api/resources/excel?view=graph-rest-1.0), [permissões de sessão](https://learn.microsoft.com/en-us/graph/api/workbook-createsession?view=graph-rest-1.0).

**Office Scripts:** a documentação oferece Personal/Family em preview, com requisitos próprios. Isso não libera execução por Power Automate: essa integração exige licença empresarial. [Requisitos e limites](https://learn.microsoft.com/en-us/office/dev/scripts/testing/platform-limits).

**Power Automate pessoal:** o portal deixou de admitir autenticação por conta pessoal após 27/07/2025. Portanto, criar um fluxo usando somente a assinatura Personal não é a solução direta. [FAQ oficial, contas admitidas](https://learn.microsoft.com/en-us/power-automate/frequently-asked-questions).

**Conector Excel Online (OneDrive):** existe conector oficial específico para MSA, também disponível em Logic Apps. Pode inserir/alterar linhas, mas não suporta pivôs e limita o arquivo a 5 MB; possui restrições de concorrência, bloqueio e repetição. Sua existência não remove a restrição de login do Power Automate. [Conector e limites](https://learn.microsoft.com/en-us/connectors/excelonline/).

**Atualização de pivôs no Excel:** inserir dados na fonte não é prova de pivô atualizado. A Microsoft documenta refresh e recursos automáticos com restrições de versão/Insider; precisamos validar o Excel web da conta real, sem exigir clique manual como solução definitiva. [Atualização de pivôs](https://support.microsoft.com/en-gb/excel/refresh-pivottable-data?nochrome=true).

## Caminhos avaliados

| Caminho | Vantagem | Limite e prova necessária |
|---|---|---|
| Personal + servidor gera XLSX completo + OneDrive publica o arquivo | Mantém a assinatura atual; processamento independe de Excel desktop aberto. É a primeira rota proposta para prova. | Novo gerador deve criar/calcular objetos nativos, preservar edição/filtros manuais e lidar com workbook aberto/alterado. Upload oficial está documentado; experiência final ainda não foi provada. |
| Personal + Logic Apps + conector OneDrive | Há conector oficial para adicionar linhas em MSA. | Introduz conta/custo Azure e não resolve pivôs por si só. Não provisionar antes de comparar custo e provar atualização. |
| Conta/licença empresarial elegível + Office Scripts | Rota nativa para automatizar objetos Excel, já prevista na arquitetura. | Conta, licença e consentimentos adicionais; depende de escolha do proprietário. Nem mesmo nela HTTP 200 comprova atualização de pivôs. |

Não substituir silenciosamente tabelas dinâmicas por resumos estáticos, trocar Excel por Sheets ou exigir computador pessoal ligado. Automação de interface por navegador e COM desktop não são a rota principal proposta para o serviço contínuo.

Para a primeira rota, EPPlus é uma candidata técnica: documenta criação/cálculo de pivôs, gráficos e segmentações. É uma biblioteca .NET adicional, não componente já instalado; sua licença permite uso pessoal/não comercial sob condições e exige licença comercial em uso empresarial. Alternativas e impacto de runtime devem ser avaliados antes da adoção. [Objetos suportados](https://epplussoftware.com/en/Developers/Features), [cálculo de pivôs](https://epplussoftware.com/docs/8.3/api/OfficeOpenXml.Table.PivotTable.ExcelPivotTable.html), [licenciamento](https://epplussoftware.com/docs/8.3/api/index.html). Não há contratação autorizada.

## Proteção do arquivo e aceite da prova

- Autorizar uma pasta/workbook de sandbox e autenticar na Microsoft; senha e códigos de login permanecem no serviço oficial.
- Avaliar escopo restrito à pasta do aplicativo antes de pedir acesso amplo. [Pasta de aplicativo OneDrive](https://learn.microsoft.com/en-us/graph/onedrive-sharepoint-appfolder).
- Produzir arquivo fictício com duas moedas, compra dividida, reembolso e meses novembro/dezembro/janeiro; conferir banco, fórmulas, objetos e caches dos pivôs.
- Publicar, abrir no Excel web real, registrar gasto pelo bot e verificar novas linhas, totais, gráficos e pivôs sem reconstrução manual.
- Repetir o mesmo job, corrigir gasto antigo, criar categoria e simular a virada sem gasto novo; nenhuma duplicação nem perda de período/filtros.
- Testar atualização com workbook aberto e alteração manual concorrente. Se houver divergência, preservar o arquivo e pedir reconciliação; não sobrescrever.
- Usar proteção de concorrência suportada pelo endpoint, incluindo eTag/If-Match quando aplicável, e verificar revisão/conteúdo depois da publicação. [Upload com controle de versão](https://learn.microsoft.com/en-us/graph/api/driveitem-createuploadsession?view=graph-rest-1.0).
- Se a aba já aberta não refletir o arquivo novo automaticamente, registrar essa limitação; publicar arquivo não garante atualização visual instantânea de uma sessão de navegador.
- Só marcar a rota como aprovada após essa jornada. Até lá: alternativa tecnicamente fundamentada, integração não comprovada.
