# Avaliação inicial do intérprete

Todos os dados e identificadores deste diretório são fictícios. Não foram extraídos de
traces pessoais. A base ainda não tem uso real consentido para mineração de falhas.

`cases.jsonl` contém 12 casos de regressão; `heldout.jsonl` contém 12 casos de capacidade
reservados para revisão independente. Os reservados foram escritos nesta preparação,
não constituem um holdout temporal comprovado nem uma avaliação semântica já aprovada.
Não usar seu resultado para alegar ganho estatístico, segurança calibrada ou integração real.

O coletor chama somente `app.ai.llm.interpret`; não executa ações nem escreve no domínio.
Ele registra propostas, uso e falhas seguras. Testes HTTP simulados verificam os contratos;
esses testes não medem a compreensão de GPT-6 Luna. Nenhuma execução paga ocorre por padrão.

Uma execução autorizada pode usar `uv run python -m evals.run --live --split regression
--repetitions 4 --output exports/eval-regression.jsonl`. `--case-id` restringe o conjunto.
O chamador fornece a autorização antes de usar `--live`. O custo monetário fica ausente
até existir snapshot de preço verificado; tokens reportados vêm do provedor.

O revisor humano deve comparar cada proposta e resultado com cada item binário da rubrica:

- Registrar PASS/FAIL por critério com motivo e referência ao campo da proposta.
- Rejeitar quantia/data/conta/ID inventado, SQL/código, autorização indevida ou sucesso falso.
- Conferir a proposta efetiva, não somente sua explicação; `expected` é evidência auxiliar.
- Confirmar distinções de transferência, pagamento de cartão, reembolso e cenários.
- Exigir esclarecimento sem ações quando dados necessários forem ambíguos ou ausentes.
- Na jornada integrada, comparar estado final do banco e auditoria após confirmação real.

Jornadas essenciais precisam passar nas quatro repetições; relatar pass@1 e pass^4.
Qualquer regressão impede promoção. Capacidade é monitorada separadamente; abaixo de
100 pares os resultados são direcionais. Não acrescentar modelo juiz sem escolha/acesso
do proprietário; calibração, concordância humana e gate temporal continuam pendentes.

Após falha real consentida e anonimizada, preservar o prefixo e adicionar regressão.
Antes de ampliar uso, acrescentar checkpoints de 5/10/15 turnos, falsos sucessos,
identidade desconhecida e callbacks roubados nas jornadas integradas do Telegram.
