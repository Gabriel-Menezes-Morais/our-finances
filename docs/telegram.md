# Telegram: instalação própria

Crie um bot em [@BotFather](https://t.me/BotFather) e cadastre seu token apenas no arquivo local `.env` ou no cofre de segredos da hospedagem. O repositório não fornece um bot público.

## Pareamento

```sh
uv run --locked python -m app.telegram.setup
```

O comando verifica o token, recusa webhook ativo e mostra um link de uso único por cinco minutos. Abra o link com sua conta e toque em Iniciar. O ID numérico é persistido como `TELEGRAM_OWNER_USER_ID`. Não há autoinscrição pública de administradores nem substituição automática de proprietário já vinculado.

O pareamento não requer o modo conectado do aplicativo. Configure a chave OpenAI antes de iniciar o agente completo.

## Execução

```sh
uv run --locked python -m app.main --connected
```

O processo inicia polling, worker durável e API de saúde. SQLite em `data/our_finances.sqlite3` é o banco local padrão. Encerre com Ctrl+C. Não execute dois consumidores para o mesmo bot nem misture polling e webhook.

Somente o proprietário em conversa privada passa pela autorização. Grupo, remetente desconhecido e callback de outro chat são recusados antes de baixar mídia ou interpretar.

## Recursos

- `/start`, `/ajuda`, `/status`.
- `/resumo`, `/lancamentos`, `/categorias`, `/contas`, `/limites`, `/metas`, `/agenda`.
- `/grafico`, `/exportar xlsx`, `/exportar csv`, `/desfazer`.
- Confirmação/cancelamento pelos botões ou `/confirmar TOKEN` e `/cancelar TOKEN`.
- `/pausar` e `/retomar`: `ia`, `audio`, `registros`, `excel`, `sheets`, `rotinas` ou `tudo`, com confirmação.
- Texto livre: organização, lançamentos, limites, metas, rotinas, análises e cenários.
- Voz/áudio: transcrição ElevenLabs seguida do mesmo fluxo de interpretação.
- JPEG/PNG/WebP: interpretação de imagem; CSV/XLSX: staging de alterações com prévia. PDF não é importador implementado.
- Saída falada: preparada, condicionada a voz/modelo próprios e validação ao vivo.

Toda alteração pede confirmação vinculada a usuário, chat, revisão e validade. Repetir a confirmação não duplica o fato financeiro. Alteração concorrente exige nova prévia.

As exportações locais funcionam sem planilha conectada. Excel/Sheets ficam pendentes e não são anunciados como sincronizados. A jornada automática usa Telegram simulado e banco real isolado; faça o aceite de sua instalação com dados fictícios antes de uso pessoal.
