# Hospedagem

Nenhum provedor foi contratado. O desenvolvimento está pausado e os templates não criam recursos por conta própria.

O aplicativo suporta execução local com SQLite e implantação com PostgreSQL. O Dockerfile e o Compose permitem bot, aplicação e banco na mesma VPS; um PaaS pode hospedar aplicação e banco como recursos separados.

## Escolha de ambiente

| Modelo | Vantagem | Responsabilidade |
|---|---|---|
| Computador local | Demonstração sem hospedagem paga | Precisa ficar ligado enquanto o bot estiver em execução |
| PaaS + PostgreSQL gerenciado | Painel de deploy e serviços administrados pelo provedor | Pagar aplicação/banco e validar limites, backups e disco efêmero |
| VPS + Compose | Aplicação e banco compartilham os recursos contratados | Atualizações, firewall, monitoramento e backup externo próprios |

Meça memória durante geração de XLSX e gráficos antes de definir o tamanho permanente. A IA usa APIs externas; não é necessário alugar GPU para essa arquitetura.

## Referências de preço

Consulta de referência: 02/11/2026. Valores não são oferta garantida; confirme moeda, país, impostos, renovação e contratação no checkout.

- [Render](https://render.com/pricing): aplicação de 512 MB por US$ 7/mês e PostgreSQL de entrada por US$ 6/mês, base de US$ 13/mês. O template `render.yaml` usa esse formato; o plano gratuito possui limites de suspensão/expiração incompatíveis com a proposta de operação permanente.
- [Sevalla aplicação](https://sevalla.com/application-hosting/pricing/) e [banco](https://sevalla.com/database-hosting/pricing/): S1 de 1 GB por US$ 10/mês + banco de entrada por US$ 5/mês, base de US$ 15/mês. Builds e tráfego podem ser cobrados à parte.
- [netcup nano](https://www.netcup.com/en/server/vps/vps-nano-g11.5s-iv-6m-nue): 2 GB, 2 vCPU e 60 GB, € 3,69/mês exibidos com contrato/faturamento de seis meses; país altera tributos.
- [Hostinger KVM 1](https://www.hostinger.com/br/servidor-vps): 4 GB por R$ 29,99/mês equivalente, com pagamento do contrato de 24 meses; não tratar o valor equivalente como mensal sem compromisso.

OpenAI, ElevenLabs, licenças Microsoft, backup externo e eventuais complementos são custos separados. Uma VPS não inclui administração contínua do aplicativo só porque permite instalar Docker.

## Antes da implantação

- Criar recursos e segredos próprios; não usar credenciais ou banco de outra instalação.
- Fazer build e smoke da imagem, confirmar limites e medir o gerador de arquivos.
- Aplicar migrações, restringir PostgreSQL e configurar health/monitoramento.
- Ativar somente um consumidor Telegram, por polling ou webhook.
- Guardar a chave de backup fora do disco efêmero e testar restore isolado.
- Validar uma jornada financeira com dados fictícios, incluindo confirmação, consulta, exportação e reinício.
- Provar os conectores online separadamente; um deploy saudável não significa Excel/Sheets sincronizados.

Execução e recuperação em [operacao.md](operacao.md).
