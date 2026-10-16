# Validação Cloud — sensor virtual

Em 15/10/2026, nesta sessão, foram executadas consultas autenticadas à Tuya Cloud usando o backend da aplicação. Credenciais e respostas brutas ficam em arquivos privados fora da pasta de entrega. O pacote não contém o Client Secret nem access tokens.

## Resultado confirmado

| Item | Resultado |
|---|---|
| Endpoint | `https://openapi.tuyaus.com` |
| Autenticação | Token obtido por assinatura HMAC-SHA256; consultas autenticadas aceitas |
| Status | `GET /v1.0/iot-03/devices/vdevo179208885319728/status` — sucesso |
| Especificação | `GET /v1.0/iot-03/devices/vdevo179208885319728/specification` — sucesso |
| Categoria retornada | `wsdcg` |
| Temperatura | `va_temperature`, inteiro, escala 1, unidade °C, faixa declarada −20 a 60 °C |
| Umidade | `va_humidity`, inteiro, escala 0, unidade %, faixa declarada 0 a 100% |
| Valores consultados | Temperatura bruta −200 → **−20,0 °C**; umidade bruta 0 → **0%** |
| Aplicação | Reconciliação real, persistência, normalização e renderização no dashboard aprovadas |

O dispositivo foi informado como virtual pelo usuário e é identificado assim na configuração. Os valores foram retornados pela API; não comprovam medições ambientais físicas. O status não forneceu timestamp de medição: o backend registra a consulta e expõe `observation_time_known: false` e `time_basis: cloud_query`. O dashboard mostra **Consulta à nuvem**, sem apresentar esse horário como horário de medição.

O sensor também retornou bateria e propriedades de configuração; somente temperatura e umidade foram habilitadas. Nenhuma configuração do sensor foi alterada e nenhum comando foi enviado. Não é necessário `local_key` para essa integração Cloud.

## Configuração entregue

`config/sensor-virtual.validated.json` contém o ID, a família `iot-03`, as duas propriedades e as escalas confirmadas. Não contém credenciais. Para usar somente esse sensor no servidor:

```sh
cp config/sensor-virtual.validated.json config/devices.json
docker compose run --rm --no-deps api python -m app.cli provision
```

Use `TUYA_ACCESS_ID_FILE` e `TUYA_ACCESS_SECRET_FILE` para os segredos montados pelo Compose. O backend também aceita os nomes alternativos `TUYA_CLIENT_ID`, `TUYA_CLIENT_SECRET` e suas variantes `_FILE`. Os nomes originais `ACCESS_*` têm precedência. Não envie esses valores ao frontend ou ao controle de versão.

A reconciliação seleciona `/iot-03/.../status` para esse sensor. Dispositivos antigos continuam usando a família `legacy`. O CLI `probe` usa `iot-03` por padrão; passe `--api-family legacy` quando necessário.

## Ainda não comprovado

- Recepção de eventos pelo Message Service/Pulsar e configuração da assinatura no console.
- Horário real da medição e frequência de atualização do sensor virtual.
- Cotas, serviços habilitados e validade das assinaturas do projeto.
- Operação no servidor Linux/Compose e ensaio de 48 horas.
- Execução de comandos em aparelhos reais, que permanecem fora desta validação de leitura.

O projeto e o asset informados foram mantidos como contexto; as rotas consultadas usam somente o ID do dispositivo, portanto não validam independentemente esses identificadores.

## Correção de atualização do dashboard

Uma consulta posterior retornou temperatura bruta `110` (**11,0 °C**) enquanto o banco ainda guardava −20,0 °C. O botão antigo apenas relia o banco e a reconciliação era horária. O botão agora usa `POST /api/v1/devices/sync` para consultar a Tuya e devolver os valores já persistidos. O fluxo autenticado foi testado contra a API real, retornando 11,0 °C e 0%. Na instalação local, a reconciliação automática foi reduzida para cinco minutos. Uma conexão Pulsar aceita, isoladamente, não comprova que as mudanças do sensor estão chegando por eventos.
