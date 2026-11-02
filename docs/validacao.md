# Validação

A suíte local foi executada em Python 3.12 com dados fictícios. Resultados de referência: **216 testes aprovados, três testes PostgreSQL opcionais pulados, cobertura de aproximadamente 85% e Ruff/mypy sem erros**. O CI reproduz a suíte offline; o resultado da instalação atual deve ser conferido no workflow e na execução local.

```sh
uv run --locked python -m scripts.check_all --coverage
uv run --locked python -m scripts.smoke_local
```

## Cobertura funcional

Os testes verificam unidades mínimas por moeda, rateios, transferências, reembolsos, cartões/parcelas, calendário, limites hierárquicos, metas, recorrências, correção, auditoria e idempotência. Também cobrem autorização, callbacks, confirmações concorrentes, falhas simuladas de provedor, inbox/outbox, leases, importação e fórmulas não confiáveis.

A jornada E2E usa SQLite real isolado e Telegram simulado, sem rede. Ela confere texto, CSV, XLSX, PNG, backup cifrado e restauração. O workbook de demonstração contém tabelas estruturadas e gráficos nativos; não é prova de pivô online.

A cobertura global não garante todos os caminhos. Polling prolongado, mídia real, síntese de voz, implantação e conectores online precisam de provas separadas.

## Artefatos reproduzíveis

- `data/sandbox/local-validation.json`: resultado e caminhos/hashes dos arquivos da demonstração.
- `data/sandbox/coverage.json`: cobertura gerada com `--coverage`.
- `exports/sandbox/`: arquivos fictícios da demonstração.
- `data/sandbox/`: bancos e backups isolados criados pelo smoke.

Esses caminhos são ignorados pelo Git e não acompanham a publicação. Gere-os com os comandos acima; não dependa de recibos de outra instalação.

## PostgreSQL

`tests/integration/test_postgres_finance.py` exige `OUR_FINANCES_TEST_POSTGRES_URL` explicitamente apontando para sandbox local. Cada teste cria um schema temporário próprio. O conjunto verifica migração/rollback, idempotência concorrente e disputa de jobs.

Sem a URL, os três testes são pulados. SQLite aprovado não substitui essa prova. Instruções locais em [operacao.md](operacao.md).

## Provedores e avaliação

HTTPs simulados validam contratos e tratamento de falhas; não medem compreensão semântica do modelo. `evals/` contém 24 casos fictícios: 12 de regressão e 12 reservados, com rubrica e coletor.

Execuções `--live` usam credenciais e recursos próprios e podem gerar custo. Nenhuma chave, transcrição pessoal, trace de usuário ou recibo privado acompanha o repositório. O acesso e a qualidade devem ser avaliados na conta de quem instala.

Permanecem pendentes: Excel/Sheets conectados, pivôs/segmentações nativos online, recálculo no Excel real, medição de hospedagem, backup externo e aceite das jornadas. Ver [PLANO.md](../PLANO.md).
