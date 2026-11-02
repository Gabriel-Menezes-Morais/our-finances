# Como contribuir

O desenvolvimento ativo está pausado. O código está disponível para estudo, uso pessoal e forks sob a licença MIT; não há prazo de manutenção ou de resposta a issues.

## Ambiente

Use Python 3.12 e uv. Crie uma branch no seu fork e instale as dependências com `uv sync --locked`.

```sh
uv run --locked python -m scripts.check_all --coverage
uv run --locked python -m scripts.smoke_local
```

Esses comandos não precisam de chaves e não devem chamar provedores. A prova PostgreSQL é opcional e exige banco local de teste explícito; veja [operação](docs/operacao.md).

## Alterações

- Descreva o problema, o comportamento final e a validação executada no pull request.
- Mantenha os valores monetários em unidades mínimas e taxas em Decimal.
- Preserve autorização por usuário/chat/workspace, confirmações, auditoria e idempotência.
- Inclua testes proporcionais para mudanças financeiras, de permissão e de recuperação.
- Atualize a documentação quando mudar configuração, comandos ou estado de uma integração.
- Reutilize o domínio financeiro e o catálogo de métricas; a IA não é a autoridade de cálculos nem de permissões.

Não envie bancos, relatórios pessoais, áudios, tokens ou arquivos `.env`. Exemplos e fixtures devem ser fictícios. Testes reais de OpenAI, ElevenLabs, Telegram ou planilhas ficam separados e exigem consentimento e credenciais próprias; nunca adicione chamadas pagas aos testes comuns ou ao CI.

O modelo configurado no projeto é `gpt-6-luna`; não há fallback automático. Uma mudança de modelo precisa ser explícita e revalidada, sem anunciar compatibilidade de API sem teste.

Para segurança, veja [SECURITY.md](SECURITY.md). Dependências e referências têm suas próprias licenças; veja [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md).
