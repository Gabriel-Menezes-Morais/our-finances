# Operação

Cada instalação é independente. O projeto não fornece hospedagem, bot ou credenciais compartilhadas. O desenvolvimento está pausado; os comandos abaixo permitem testar e operar a base local por sua conta.

## Demonstração e bot

```sh
uv sync --locked
uv run --locked python -m scripts.smoke_local
```

O smoke cria dados fictícios isolados e não faz rede. Para um bot real, siga o pareamento em [telegram.md](telegram.md), configure suas chaves e inicie:

```sh
uv run --locked python -m app.main --connected
```

Encerre com Ctrl+C. Sem `--connected` e com `APP_MODE=offline`, a entrada HTTP não inicia polling nem chama provedores; o runtime HTTP ainda exige proprietário configurado. Para testar sem proprietário, use o smoke, não o servidor HTTP.

Banco padrão: SQLite em `data/our_finances.sqlite3`. Health: `http://127.0.0.1:8000/health`; readiness: `/ready`. Altere `PORT` se necessário. Esses endpoints não expõem dados financeiros. Uma resposta de health não comprova toda a jornada do bot.

Não inicie dois consumidores do mesmo token. Para execução permanente, use um serviço/container com monitoramento; abrir um terminal não cria inicialização automática após reboot.

## PostgreSQL local opcional

```sh
uv run --locked python -m scripts.bootstrap_local
docker compose up -d db
uv run --locked --env-file credentials/host-postgres.env python -m scripts.migrate
uv run --locked python -m scripts.check_all --postgres-local
```

O bootstrap gera senhas próprias em `credentials/`, sem imprimir valores ou substituir arquivos existentes. PostgreSQL fica restrito a `127.0.0.1:55439`, em volume próprio. Se essa porta estiver ocupada, revise Compose, arquivo de conexão e validador do script de checks em conjunto; não encerre outros serviços para liberá-la.

Para usar o bot com esse PostgreSQL, depois de configurar e parear seu bot:

```sh
uv run --locked --env-file credentials/host-postgres.env python -m app.main --connected
```

Os testes PostgreSQL usam schemas temporários com nomes próprios; não aponte `OUR_FINANCES_TEST_POSTGRES_URL` para produção. Falha de conexão não conta como teste pulado/aprovado.

## Docker e hospedagem

`docker compose --profile runtime up --build` inicia aplicação e banco, usando o `.env` e os arquivos locais do bootstrap. Primeiro encerre qualquer polling local desse token. O Compose persiste banco e exportações em volumes. Não remova volumes de uso real sem backup validado.

O Dockerfile executa com usuário sem privilégios e exclui segredos/dados pelo `.dockerignore`. Migrações são aplicadas antes da inicialização. Build e medição no seu ambiente continuam necessários.

`render.yaml` é um template opcional de recursos pagos; importar/provisionar não é parte dos testes. Outros PaaS/VPS podem usar o mesmo Dockerfile. Aplicação, polling e worker podem compartilhar um processo, com banco PostgreSQL separado.

Para worker separado, use `RUN_WORKER_IN_APP=false` na API e execute `python -m app.worker` em outro processo com o mesmo banco. O worker não inicia polling.

Webhook exige modo conectado, `TELEGRAM_TRANSPORT=webhook`, URL HTTPS e `TELEGRAM_WEBHOOK_SECRET`. O registro externo do webhook é uma etapa própria; nunca manter polling e webhook ao mesmo tempo. Inbox é persistido antes do ACK.

Arquivos gerados aguardando entrega têm cópia dos bytes no job durável, até 8 MB por arquivo. Isso protege anexos enfileirados contra perda do disco efêmero; não substitui backup do banco.

## Backup e restauração

```sh
uv run --locked python -m scripts.backup
uv run --locked python -m scripts.restore backups/ARQUIVO.ofbackup --name teste-restauracao
```

Use o caminho efetivamente gerado. O backup contém dados/estados do banco, cifrados e autenticados com a chave `credentials/backup.key`. Credenciais dos provedores não entram no backup do banco. Guarde a chave separadamente; sem ela não existe recuperação.

A restauração cria outro SQLite em `data/restore_sandbox`, sem sobrescrever um banco existente. Jobs externos ficam incertos/suspensos, confirmações são canceladas e rotinas/integrações são pausadas; os fatos financeiros e auditoria são preservados.

Escolha destino externo, retenção, frequência e metas de recuperação antes de produção. Chave criada em disco efêmero de PaaS precisa de armazenamento seguro permanente; copiar apenas o arquivo cifrado é insuficiente.

## Falhas e custos

Recebimento, propostas, confirmações, ações, auditoria e jobs são persistidos. Confirmações usam identidade, chat, revisão, validade e chave idempotente. Repetir um botão não duplica a movimentação.

Um envio Telegram com timeout pode ter resultado incerto. O job fica `uncertain`, sem reenvio cego. Avalie a entrega antes de reconciliar; nunca refaça o lançamento financeiro só porque a resposta falhou.

Excel/Sheets ficam pendentes até haver conector real. Salvar no banco não autoriza anunciar sincronização. Leases e proteção de revisão existentes não substituem a prova de escrita no destino.

As flags `ai`, `audio`, `mutations`, `excel`, `sheets`, `schedules` usam `true` para pausa. O bot permite `/pausar` e `/retomar` com confirmação, inclusive recuperação da IA pausada.

O sistema registra unidades de uso retornadas por chamadas bem-sucedidas. Isso não é fatura nem limite monetário implementado. Defina teto de consumo e retenção antes de dados reais. Atualize dependências, monitore espaço em disco e repita restaurações de teste.
