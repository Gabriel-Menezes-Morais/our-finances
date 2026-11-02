# Dependências e referências

A licença [MIT](LICENSE) cobre o código e a documentação originais deste repositório. Bibliotecas instaladas, serviços externos e referências de produto mantêm seus próprios termos e licenças; a licença deste projeto não os substitui.

As versões das dependências estão em `uv.lock`, e a lista direta está em `pyproject.toml`. Os provedores OpenAI, ElevenLabs, Telegram, Microsoft e Google exigem credenciais e condições próprias. O repositório não inclui credenciais, contas nem licenças desses serviços.

Referências que orientaram a experiência e a arquitetura:

- [rafaPassarinho/google-sheets-gemini-automation](https://github.com/rafaPassarinho/google-sheets-gemini-automation): fluxo em português, voz e planilha. O projeto de origem publica sua própria licença Apache-2.0; preserve os avisos aplicáveis se incorporar seu código.
- [Multi-modal expense tracking, template 10155](https://n8n.io/workflows/10155-multi-modal-expense-tracking-with-telegram-gemini-ai-and-google-sheets/): normalização de texto, áudio e imagens antes da interpretação. O aplicativo deste repositório não depende do n8n em execução.
- [OurLifeCosts](https://ourlifecosts.org/en/): referência funcional de organização, orçamento e relatórios pelo chat. Não é uma dependência incorporada.

O gerador EPPlus foi pesquisado como possível caminho para Excel pessoal; não é uma dependência instalada ou uma integração entregue. Qualquer adoção futura precisa avaliar sua licença e a compatibilidade dos objetos no Excel real.
