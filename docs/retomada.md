# Retomar o desenvolvimento

O desenvolvimento ativo foi pausado. O repositório público preserva o código, testes e roadmap para instalação própria e contribuições; não representa um bot compartilhado ou um serviço hospedado.

## Começar

1. Siga o [README](../README.md) e execute a demonstração sem chaves.
2. Rode `uv run --locked python -m scripts.check_all --coverage`.
3. Leia [ARQUITETURA.md](../ARQUITETURA.md), [STACK.md](../STACK.md) e [PLANO.md](../PLANO.md).
4. Escolha uma tarefa pendente e valide suas dependências antes de alterar o código.
5. Crie seu próprio bot e credenciais somente se precisar executar uma integração real.

O núcleo local inclui organização, finanças, confirmações, auditoria, filas, análises, importação controlada, arquivos e backup/restauração. As exportações não comprovam integração online.

## Próximas entregas

- Provar um caminho compatível com Excel online, incluindo a conta Personal: ver [excel-pessoal.md](excel-pessoal.md).
- Instalar análises prontas no workbook e atualizar após cada gasto, sem pedido de criação de relatório.
- Implementar base contínua, mês atual/mês escolhido e virada de calendário sem gasto novo; preservar períodos, filtros e edições.
- Conectar Google Sheets e provar paridade de valores e objetos nativos.
- Medir a imagem Docker, escolher hospedagem e testar publicação/recuperação. Nenhum serviço foi contratado.
- Escolher/testar voz TTS, definir teto de consumo, retenção e destino externo de backup.
- Completar compartilhamento por convite e exclusão definitiva confirmada, ainda não implementados.
- Fazer aceite das jornadas reais de texto/áudio com dados fictícios antes de uso pessoal.

O modelo e provedores configurados estão descritos no README. Não reutilize credenciais de outra instalação, não faça chamadas pagas nos testes comuns e não declare concluída uma integração apenas por existir seu contrato local.
