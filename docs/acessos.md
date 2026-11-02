# Credenciais por instalação

Nenhuma chave, bot compartilhado ou conta de provedor acompanha o repositório. Configure seus próprios recursos. Copie `.env.example` somente na instalação inicial, edite `.env` localmente e nunca publique seus valores.

| Integração | Necessário | Estado do código |
|---|---|---|
| Demonstração e testes offline | Nenhuma credencial | Disponíveis |
| Telegram | Bot próprio e `TELEGRAM_BOT_TOKEN`; proprietário vinculado por `app.telegram.setup` | Disponível |
| OpenAI | `OPENAI_API_KEY` com acesso ao modelo configurado | Interpretação implementada; acesso depende da conta |
| ElevenLabs STT | `ELEVENLABS_API_KEY` com permissão para o modelo STT configurado | Disponível; independente de texto |
| ElevenLabs TTS | Chave, `ELEVENLABS_VOICE_ID` e `ELEVENLABS_TTS_MODEL` | Preparado; escolha e prova real obrigatórias |
| PostgreSQL local | `scripts.bootstrap_local` gera arquivos próprios em `credentials/` | Disponível |
| Hospedagem | Conta, orçamento e segredos cadastrados no provedor escolhido | Deploy não realizado |
| Microsoft | Consentimento e workbook de sandbox; conta/licença compatível com a rota | Conector não implementado |
| Google | Projeto/conta e planilha de sandbox autorizada | Conector não implementado |
| Backup externo | Destino, retenção e cópia segura da chave de cifragem | Não configurado |

`APP_MODE=offline` é o padrão. O parâmetro `--connected` inicia as integrações configuradas e pode gerar cobrança por uso. Instanciar a configuração não faz rede.

Não cadastre senhas de contas, códigos de login, tokens de outra instalação ou chaves em documentos. Use o editor local e o cofre de segredos do provedor. Qualquer chave exposta deve ser revogada e substituída.

## Microsoft 365 Personal

A API de workbook não atende OneDrive Consumer; a API de arquivos admite publicação em conta pessoal. A rota proposta para prova é gerar o XLSX completo no servidor e publicar no OneDrive, com validação de objetos nativos e preservação de edições. Isso ainda não é uma integração pronta.

Office Scripts com Power Automate exige licença empresarial. Não assumir que assinar Personal libera esse mecanismo. Fontes, alternativas e critérios de aceite estão em [excel-pessoal.md](excel-pessoal.md).
