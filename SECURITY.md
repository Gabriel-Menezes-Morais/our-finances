# Segurança

Projeto experimental com desenvolvimento ativo pausado. Não há SLA de correção nem revisão de segurança independente. O código usa autorização privada, confirmação de alterações, auditoria, idempotência e proteção contra fórmulas não confiáveis; isso não substitui revisão antes de uso com dados reais.

## Relatar uma vulnerabilidade

Use **Security → Advisories → Report a vulnerability** neste repositório para relatos privados. Não inclua chaves, tokens, dados financeiros, dumps ou áudio pessoal. Informe versões, passos mínimos para reproduzir e impacto com dados fictícios.

Não publique uma vulnerabilidade com dados sensíveis em uma issue pública. Se o canal privado estiver indisponível, use uma reprodução fictícia sem segredos e aguarde um canal privado antes de compartilhar detalhes exploráveis.

## Instalação

- Cada instalação cria seu próprio bot, APIs, banco e identidade de proprietário.
- Configure segredos localmente ou no cofre do provedor. Não coloque valores em YAML, imagem Docker, código, mensagens de log ou histórico Git.
- Guarde a chave de backup separadamente: sem ela, o backup cifrado não é recuperável.
- Revogue e substitua qualquer chave que tenha sido compartilhada ou publicada; adicionar `.gitignore` depois não remove segredos do histórico.
- Use apenas um consumidor de polling para cada bot. Webhook exige HTTPS e secret próprio.
- Mantenha PostgreSQL restrito à rede necessária. Defina retenção, limite de consumo e backup externo antes de operação permanente.
- Texto/áudio/imagens enviados ao agente podem ser processados por OpenAI e ElevenLabs. Verifique as condições e retenção dos fornecedores antes de enviar dados reais.

Os workflows de CI usam apenas fixtures e não recebem chaves das APIs do aplicativo.
