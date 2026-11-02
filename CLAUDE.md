# Contexto de trabalho para Claude

## Entrada obrigatória

Ler e seguir [AGENTS.md](AGENTS.md). Ele contém as regras normativas compartilhadas para agentes neste projeto, incluindo as instruções de YAGNI do proprietário. Este arquivo complementa o contexto e não cria uma segunda política divergente.

Ordem de leitura: [README.md](README.md), [ARQUITETURA.md](ARQUITETURA.md), [STACK.md](STACK.md) e [PLANO.md](PLANO.md).

## Objetivo do proprietário

Construir seu próprio sistema de finanças pessoais. O Telegram é o meio de registrar texto/áudio, organizar áreas da vida e categorias, definir limites e metas e criar análises em planilhas. Excel online / Microsoft 365 foi escolhido como ambiente principal; Google Sheets também está no escopo.

O produto precisa ter gráficos, tabelas dinâmicas nativas, filtros, segmentações, análises salvas, cenários e relatórios. Tudo deve ser operável pelo agente, sem pedir que o proprietário edite código para criar uma categoria ou análise.

## Decisões que devem permanecer

- IA: `gpt-6-luna` na OpenAI Responses API. Não trocar silenciosamente.
- Áudio: ElevenLabs para STT e TTS, com voz escolhida pelo proprietário.
- APIs e acessos: sempre pedir quando necessários. O proprietário gerará as chaves; não procurar segredos em projetos vizinhos.
- Referências: RafaPassarinho para a experiência de voz PT-BR, template multimodal 10155 para normalização comum e OurLifeCosts para categorias/orçamento/planilha.
- Backend proposto: monólito Python, PostgreSQL, API/bot e worker durável; os motivos estão em STACK e ARQUITETURA.
- Dados oficiais no banco, projeções e entrada controlada nas planilhas. A edição direta exige revisão-base e resolução de conflito.

## Estado da entrega inicial

O desenvolvimento ativo está pausado. O código é público sob MIT para instalação própria; não há bot compartilhado, hospedagem ou credenciais incluídas. Núcleo local e relatórios implementados; ver docs/retomada.md, docs/operacao.md, docs/validacao.md e docs/implementacao-local.md. SQLite e PostgreSQL/Alembic suportados. Não iniciar polling durante manutenção/publicação. Excel/Sheets online, objetos nativos, TTS, retenção e orçamento continuam pendentes de implementação/configuração e prova. Não tratar mocks como integração conectada.

O `PLANO.md` contém a checklist do começo ao fim. Não marcar passos como feitos por encontrar nomes de funções ou telas ilustrativas. Quando houver pedido para implementar, avançar pela checklist e atualizar esta seção/README conforme a evidência.

## Primeira dependência técnica

Microsoft 365 Personal é um cenário do projeto. Office Scripts via Power Automate exige licença empresarial; a proposta de publicar XLSX completo no OneDrive pessoal ainda precisa de prova. Avaliar a conta de cada instalação e obter decisão antes de mudar assinatura ou mecanismo. Manter Excel no escopo.

Alguns métodos de refresh de pivôs podem não funcionar em Power Automate apesar de retornarem sucesso. A fase 0 prova criação/reconstrução de pivôs nativos, filtros e valores atuais no tenant. Não declarar que `refreshAllPivotTables()` resolve sozinho e não trocar por exportação estática.

## Cuidados durante a implementação

- Usar unidades mínimas da moeda original, centavos em BRL, e Decimal para taxas; a IA interpreta e propõe ferramentas. Câmbio ausente não produz contravalor fictício.
- Persistir evento antes do ACK, com auditoria/outbox na transação financeira.
- Manter autorização por user ID/workspace em cada ação e callback.
- Confirmar ações de impacto com prévia vinculada a payload, versão e prazo; permitir corrigir e desfazer.
- Separar registrado de sincronizado; mostrar qual destino está pendente.
- Impedir regressão de revisão publicada e concorrência de escritores após lease expirada.
- Separar grão de movimentação e rateio: uma compra dividida continua sendo uma movimentação para frequência/ticket global.
- Não apagar abas manuais, fórmulas ou trabalho do usuário ao reconstruir objetos gerados.
- Usar APIs reais somente com acesso fornecido e testes conectados explícitos; fixtures financeiras são fictícias por padrão.
- Preservar os requisitos sofisticados na entrega completa; fases organizam a execução e não reduzem escopo.

## Retomada de sessão

1. Conferir a última solicitação do proprietário e o estado real dos arquivos.
2. Localizar a primeira tarefa pendente e suas dependências em PLANO.
3. Conferir os requisitos de acesso em `docs/acessos.md`; não presumir que uma instalação nova tenha credenciais.
4. Continuar trabalho autorizado e independente; pedir somente os acessos/decisões necessários à próxima integração.
5. Registrar testes executados e pendências honestamente ao encerrar.
