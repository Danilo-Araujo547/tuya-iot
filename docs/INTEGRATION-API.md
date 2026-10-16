# API de dispositivos e automações — guia de integração

Use esta API para consultar dispositivos, leituras e execuções e para enviar comandos ou gerenciar automações. O cliente utiliza um token Bearer; não precisa do login administrativo nem das credenciais Cloud da Tuya. O token é a credencial da integração: guarde-o no backend ou no gerenciador de segredos da aplicação cliente.

## 1. Gerar o token no terminal do servidor

Na pasta do projeto com Docker Compose em execução:

```sh
# Somente visualização.
docker compose exec -T api python -m app.cli create-token --name painel-leitura

# Visualização e comandos de dispositivos.
docker compose exec -T api python -m app.cli create-token --name controle-interno --control

# Visualização e gerenciamento das automações.
docker compose exec -T api python -m app.cli create-token --name gestor-automacoes --automations

# Todas as permissões de integração acima.
docker compose exec -T api python -m app.cli create-token --name integracao-completa --control --automations
```

O comando imprime **somente o token**, uma vez. O banco armazena apenas seu hash; não é possível recuperar o valor depois. Escolha um nome exclusivo para cada integração. Nenhum dos comandos acima envia comandos aos dispositivos ou ativa automações.

Para execução sem Docker, com Python e `DATABASE_URL`/`DATABASE_URL_FILE` do servidor configurados, execute na pasta `backend`:

```sh
python -m app.cli create-token --name integracao-completa --control --automations
python -m app.cli list-tokens
python -m app.cli revoke-token --name integracao-completa
```

Na instalação Windows local desta sessão, a partir da pasta de trabalho do chat:

```powershell
.\work\venv\Scripts\python.exe work/api_tokens.py create-token --name integracao-completa --control --automations
.\work\venv\Scripts\python.exe work/api_tokens.py list-tokens
.\work\venv\Scripts\python.exe work/api_tokens.py revoke-token --name integracao-completa
```

Esse auxiliar usa a configuração privada já instalada neste computador. Não deve ser copiado para outros servidores; nesses casos, use Docker Compose ou configure o ambiente do backend.

Listagem e revogação em Docker:

```sh
docker compose exec -T api python -m app.cli list-tokens
docker compose exec -T api python -m app.cli revoke-token --name painel-leitura
```

A listagem mostra nomes e permissões, nunca o token ou seu hash. Revogar bloqueia as próximas requisições; comandos já enviados não são desfeitos. Tokens não expiram automaticamente nesta versão. Para rotacionar, crie outro token, atualize o cliente e revogue o antigo. Os comandos antigos `create-key` e `revoke-key` continuam funcionando. Tokens antigos mantêm as permissões originais; somente novos tokens com `--automations` recebem essa autorização.

| Permissão | Sem flags | `--control` | `--automations` |
|---|---|---|---|
| Consultar dispositivos, leituras, capacidades e histórico | Sim | Sim | Sim |
| Consultar fluxo, regras e execuções | Sim | Sim | Sim |
| Enviar comandos a dispositivos | Não | Sim | Não |
| Criar/editar/ativar/pausar automações | Não | Não | Sim |

As flags podem ser combinadas. A permissão de automações permite configurar ações e notificações que o worker poderá executar quando o fluxo for ativado; ela é independente da permissão de comandos manuais. Cadastro de dispositivos, descoberta de teclas IR, sincronização manual, imagens de fundo e configuração dos canais de notificação permanecem administrativos.

## 2. Conectar sem login e senha

Base local: `https://127.0.0.1:8443/api/v1`. Em outro computador, use o endereço LAN/VPN do servidor, com certificado confiável. `127.0.0.1` sempre aponta para o computador do próprio cliente. Não é necessário chamar `/auth/login`, enviar cookie, `Origin` ou token CSRF ao usar Bearer.

Exemplo em PowerShell:

```powershell
$apiBase = 'https://127.0.0.1:8443/api/v1'
# Defina TUYA_IOT_API_TOKEN no ambiente do cliente com o token gerado.
$headers = @{ Authorization = "Bearer $env:TUYA_IOT_API_TOKEN" }
Invoke-RestMethod "$apiBase/devices" -Headers $headers
```

Exemplo curl, em shell Linux/macOS:

```sh
# API_TOKEN deve conter o token, vindo do ambiente seguro do cliente.
API_BASE='https://seu-servidor/api/v1'
curl --fail-with-body -H "Authorization: Bearer $API_TOKEN" "$API_BASE/devices"
```

Se usa a autoridade certificadora privada do projeto, configure a confiança no cliente; para curl, use `--cacert /caminho/ca.crt`. Não desative a validação TLS. Toda autenticação é feita pela API local; o cliente não assina requisições Tuya.

## 3. Visualizar dispositivos e leituras

Todos os caminhos abaixo são relativos a `/api/v1`.

| Método | Caminho | Resultado |
|---|---|---|
| GET | `/devices` | Dispositivos, capacidades, conectividade e último estado |
| GET | `/devices/{id}/state` | Estado de um dispositivo |
| GET | `/devices/{id}/connectivity` | `online`, `offline` ou `desconhecida`, com horário da informação |
| GET | `/devices/{id}/history` | Histórico de uma propriedade no intervalo solicitado |
| GET | `/devices/{id}/control` | Perfil IR, capacidades, estado estimado e últimos comandos |
| GET | `/status` | Saúde da ingestão e do worker |

Use o `id` retornado por `/devices`. Exemplo:

```powershell
$deviceId = 'ID_RETORNADO_PELA_API'
Invoke-RestMethod "$apiBase/devices/$deviceId/state" -Headers $headers
Invoke-RestMethod "$apiBase/devices/$deviceId/connectivity" -Headers $headers
Invoke-RestMethod "$apiBase/devices/$deviceId/control" -Headers $headers
```

Interprete a leitura junto com os indicadores:

```json
{
  "connectivity": "offline",
  "online": false,
  "states": [{
    "property": "temperature",
    "value": 21.6,
    "unit": "°C",
    "current": false,
    "stale": true,
    "freshness_reason": "sensor_offline",
    "measurement_at": null
  }]
}
```

Esse é um exemplo parcial de resposta: `21.6` é último valor conhecido, não temperatura atual. `online: null` significa conectividade desconhecida. `measurement_at: null` significa ausência do horário real da medição. `observed` e `received` são timestamps Unix UTC; quando a origem não fornece horário, `observed` pode ser o horário da consulta. O campo `source: estimado` em IR não confirma fisicamente o aparelho.

Histórico das últimas 24 horas, agregado por hora:

```powershell
$end = [DateTimeOffset]::UtcNow
$startText = [uri]::EscapeDataString($end.AddHours(-24).ToString('o'))
$endText = [uri]::EscapeDataString($end.ToString('o'))
$historyUrl = "$apiBase/devices/$deviceId/history?property=temperature&aggregation=hour&start=$startText&end=$endText"
Invoke-RestMethod $historyUrl -Headers $headers
```

Propriedades: `temperature` ou `humidity`. Agregação: `hour`, `day` ou `raw`. Intervalo obrigatório, com fuso, até 90 dias; início incluso, fim exclusivo. Agregados retornam média em `value`, além de `min`, `max` e `count`. Lacunas são `null`, não zero. `offline_intervals` traz períodos offline confirmados em `{start,end}`; os agregados excluem medições nesses períodos. Para dados brutos use `limit=500` (máximo 2000) e envie `cursor_time` e `cursor_id` de `next_cursor` para continuar, mantendo os demais filtros.

As consultas acima leem o banco. A exceção de leitura explícita da nuvem é `POST /devices/{id}/control/status`, disponível quando `capabilities.cloud_status` estiver habilitada; essa rota aceita token de leitura, aplica limite local e retorna estado IR estimado. O WebSocket `/events` continua reservado à sessão do dashboard; clientes com Bearer devem consultar as rotas REST.

## 4. Controlar um dispositivo

Exige token criado com `--control`. Consulte primeiro `/devices/{id}/control`: envie apenas capacidades habilitadas e valores permitidos.

| Tipo | Corpo de `POST /devices/{id}/control/commands` |
|---|---|
| Ligar/desligar discreto | `{"type":"power","value":true}` ou `false` |
| Temperatura do ar | `{"type":"temperature","value":22}` |
| Modo do ar | `{"type":"mode","value":0}` — somente códigos permitidos nas capacidades |
| Ventilação | `{"type":"fan","value":0}` — somente códigos permitidos nas capacidades |
| Tecla IR | `{"type":"ir_key","value":"Volume-"}` — use a chave exata de `capabilities.keys` |

Uma TV por teclas pode oferecer `Power`, que **alterna** energia; não significa ligar ou desligar de forma discreta. Não presuma o estado físico da TV.

```powershell
# Gere UMA chave por intenção de comando; preserve-a para eventual repetição da requisição.
$requestKey = [guid]::NewGuid().ToString()
$commandHeaders = @{ Authorization = "Bearer $env:TUYA_IOT_API_TOKEN"; 'Idempotency-Key' = $requestKey }
$command = @{ type = 'ir_key'; value = 'Volume-' } | ConvertTo-Json
$result = Invoke-RestMethod "$apiBase/devices/$deviceId/control/commands" `
  -Method Post -Headers $commandHeaders -ContentType 'application/json' -Body $command
Invoke-RestMethod "$apiBase/commands/$($result.id)" -Headers $headers
```

Esse exemplo envia um comando real quando executado. `Idempotency-Key` é obrigatória, de 8 a 128 caracteres. Repetir o mesmo corpo com a mesma chave recupera a solicitação anterior; trocar o corpo com a mesma chave retorna 409. Se houver timeout, consulte o resultado ou repita com a mesma chave; não gere outra chave automaticamente. Estados: `solicitado`, `aceito pela Tuya`, `falhou`, `resultado desconhecido`. Aceitação pela nuvem não comprova recepção física. `GET /commands/{id}` limita tokens aos comandos emitidos por eles próprios; o histórico do dispositivo pode incluir comandos de outras origens.

Para dispositivos compatíveis com o comando genérico, `POST /devices/{id}/commands` também aceita `{"power":true}` com token de controle e a mesma exigência de idempotência.

## 5. Visualizar automações

| Método | Caminho | Resultado |
|---|---|---|
| GET | `/automation-flow` | Fluxo visual, revisão, ativação, blocos, conexões, problemas e runtime |
| GET | `/automation-flow/runs` | Últimas 60 execuções e seus resultados/esperas |
| GET | `/automations` | Regras legadas cadastradas |
| GET | `/automations/history/runs` | Últimas 100 execuções legadas; filtro opcional `rule_id` |

```powershell
$flow = Invoke-RestMethod "$apiBase/automation-flow" -Headers $headers
Invoke-RestMethod "$apiBase/automation-flow/runs" -Headers $headers
```

O fluxo visual é o modelo utilizado pela tela atual. As regras legadas permanecem para compatibilidade e auditoria; depois da adoção do fluxo visual, a API impede reativá-las em paralelo.

## 6. Gerenciar automações por token

Exige `--automations`. `--control` sozinho não autoriza alterações de automações. Não há endpoint para “executar agora”: o worker executa o fluxo habilitado quando seus gatilhos ocorrerem.

Pausar o fluxo com a revisão lida:

```powershell
$flow = Invoke-RestMethod "$apiBase/automation-flow" -Headers $headers
$body = @{ enabled = $false; revision = $flow.revision } | ConvertTo-Json
Invoke-RestMethod "$apiBase/automation-flow/enabled" -Method Patch `
  -Headers $headers -ContentType 'application/json' -Body $body
```

Para ativar, leia a revisão atual novamente e envie `enabled = $true`. Ativar permite ações reais. Problemas de capacidades ou configuração retornam 422. Pausar cancela esperas pendentes, sem desfazer comandos já enviados.

Salvar ou validar um desenho:

```powershell
$flow = Invoke-RestMethod "$apiBase/automation-flow" -Headers $headers
$definition = @{
  name = $flow.name
  revision = $flow.revision
  cooldown_seconds = $flow.cooldown_seconds
  nodes = @($flow.nodes)
  edges = @($flow.edges)
} | ConvertTo-Json -Depth 30

# Só valida: não salva, não ativa e não envia comandos.
Invoke-RestMethod "$apiBase/automation-flow/validate" -Method Post `
  -Headers $headers -ContentType 'application/json' -Body $definition

# Salva: desativa o fluxo e cancela esperas pendentes.
Invoke-RestMethod "$apiBase/automation-flow" -Method Put `
  -Headers $headers -ContentType 'application/json' -Body $definition
```

Guarde a nova `revision` retornada ou consulte de novo antes de alterar/ativar. Revisão antiga retorna 409. O formato completo dos blocos e conexões está em [WORKFLOWS.md](WORKFLOWS.md). Canais de notificação devem estar previamente configurados pelo administrador; um token não pode consultar ou alterar suas credenciais.

Regras legadas também aceitam `--automations`:

| Método | Caminho | Uso |
|---|---|---|
| POST | `/automations` | Cria regra desativada |
| PUT | `/automations/{id}` | Edita e desativa |
| PATCH | `/automations/{id}/enabled` | `{"enabled":true}` ou `false` |
| POST | `/automations/{id}/preview` | Avalia sem enviar comandos |
| DELETE | `/automations/{id}` | Exclui a regra; preserva auditoria |

O contrato das regras legadas está em [AUTOMATIONS.md](AUTOMATIONS.md).

## 7. Erros e documentação interativa

| Código | Significado |
|---|---|
| 401 | Token ausente, inválido ou revogado |
| 403 | Token sem a permissão necessária ou operação reservada ao administrador |
| 404 | Dispositivo, comando ou regra inexistente/inacessível |
| 409 | Revisão antiga, idempotência conflitante ou operação incompatível com o fluxo adotado |
| 422 | Corpo, capacidade, ação ou intervalo inválido |
| 429 | Limite de chamadas atingido |
| 502/503 | Serviço externo indisponível ou resposta inválida |

OpenAPI: `/api/v1/openapi.json`. Swagger: `/api/v1/docs`. Para clientes com Bearer, envie o cabeçalho `Authorization` explicitamente nos exemplos acima; a interface Swagger desta versão não oferece um esquema Bearer de autorização automática. A API não retorna o token em consultas de dispositivos ou automações.
