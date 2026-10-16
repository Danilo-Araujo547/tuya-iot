# API — dispositivos e automações

Referência para integração com outro sistema. Todos os caminhos abaixo usam o prefixo `/api/v1`. Endereço do servidor e token são fornecidos separadamente.

## Dispositivos

| Método | Endpoint | Finalidade |
|---|---|---|
| GET | `/devices` | Listar dispositivos, capacidades, conectividade e estados |
| GET | `/devices/{id}/state` | Consultar o último estado de um dispositivo |
| GET | `/devices/{id}/connectivity` | Consultar conectividade e horário da informação |
| GET | `/devices/{id}/history` | Consultar histórico de temperatura ou umidade |
| GET | `/devices/{id}/control` | Consultar capacidades IR, estado estimado e últimos comandos |
| POST | `/devices/{id}/control/commands` | Enviar comando de controle |
| GET | `/commands/{id}` | Consultar o resultado de um comando enviado pela integração |

Use o identificador retornado em `/devices`. Envie somente comandos disponíveis nas capacidades do dispositivo.

### Leituras e conectividade

- `connectivity`: `online`, `offline` ou `desconhecida`.
- `online`: booleano; `null` quando a conectividade é desconhecida.
- `connectivity_checked_at`: horário da última informação de conectividade.
- `states`: propriedades com `value`, `unit`, `source`, `observed` e `received`.
- `current`: indica se a leitura pode ser apresentada como atual.
- `stale`: indica leitura desatualizada ou sem confirmação atual.
- `freshness_reason`: motivo, como `sensor_offline`, `measurement_time_unknown` ou `measurement_stale`.
- `measurement_at`: horário real da medição; `null` quando não informado.

Com o sensor offline, o valor preservado é a última leitura conhecida. O horário de consulta não comprova uma nova medição. Estados IR estimados não confirmam o estado físico do aparelho. Timestamps de resposta são segundos Unix em UTC.

### Histórico

Parâmetros obrigatórios: `property` (`temperature` ou `humidity`), `start` e `end` (datas com fuso). Intervalo máximo: 90 dias; início incluso e fim exclusivo.

- `aggregation`: `raw`, `hour` ou `day`.
- `limit`: até 2000 registros para dados brutos.
- Paginação: enviar `cursor_time` e `cursor_id` de `next_cursor`, mantendo os filtros.
- Agregados: `time`, `value` (média), `min`, `max` e `count`.
- Lacunas: valores `null`; não interpretar como zero.
- `offline_intervals`: períodos offline confirmados, com `start` e `end`.

### Comandos

O corpo contém `type` e `value`:

| `type` | `value` |
|---|---|
| `power` | Booleano para ligar/desligar discreto |
| `temperature` | Inteiro em °C, dentro da faixa suportada |
| `mode` | Código inteiro permitido nas capacidades |
| `fan` | Código inteiro permitido nas capacidades |
| `ir_key` | Nome exato de uma tecla de `capabilities.keys` |

Cabeçalho obrigatório: `Idempotency-Key`, entre 8 e 128 caracteres. Use uma chave por intenção de comando. Em timeout, consulte o resultado ou repita o mesmo corpo com a mesma chave; não gere outra chave automaticamente.

A resposta contém o identificador do comando e seu resultado: `solicitado`, `aceito pela Tuya`, `falhou` ou `resultado desconhecido`. Aceitação pela nuvem não garante recepção física. A tecla IR `Power` pode alternar a energia, sem distinguir ligar de desligar.

## Automações — fluxo visual atual

| Método | Endpoint | Finalidade |
|---|---|---|
| GET | `/automation-flow` | Consultar desenho, revisão, ativação, problemas e runtime |
| GET | `/automation-flow/runs` | Consultar últimas 60 execuções, resultados e esperas |
| POST | `/automation-flow/validate` | Validar desenho sem salvar ou enviar comandos |
| PUT | `/automation-flow` | Salvar desenho; desativa o fluxo e cancela esperas pendentes |
| PATCH | `/automation-flow/enabled` | Ativar ou pausar o fluxo |

Para validar/salvar: `name`, `revision`, `cooldown_seconds`, `nodes` e `edges`.

- Blocos: `id`, `kind`, `label`, `position` e `data`.
- Tipos de bloco: `trigger`, `delay`, `condition`, `action` e `notification`.
- Conexões: `id`, `source`, `target` e `port` (`out`, `yes` ou `no`).
- Para ativar/pausar: `enabled` e a `revision` atual.

Sempre use a revisão mais recente; conflito retorna 409. Salvar não ativa o fluxo. O worker executa automaticamente os gatilhos de fluxos ativos; não há endpoint de execução imediata. Pausar cancela esperas, sem desfazer comandos já enviados. Blocos desconectados não executam. O esquema completo dos campos está no OpenAPI e em [WORKFLOWS.md](WORKFLOWS.md).

## Automações legadas

| Método | Endpoint | Finalidade |
|---|---|---|
| GET / POST | `/automations` | Listar ou criar regras desativadas |
| PUT / DELETE | `/automations/{id}` | Editar ou excluir regra |
| PATCH | `/automations/{id}/enabled` | Ativar ou pausar regra |
| POST | `/automations/{id}/preview` | Avaliar regra sem enviar comandos |
| GET | `/automations/history/runs` | Consultar últimas 100 execuções; filtro opcional `rule_id` |

Use o fluxo visual para novas integrações. Após sua adoção, regras legadas não podem ser reativadas em paralelo. Contrato legado em [AUTOMATIONS.md](AUTOMATIONS.md).

## Respostas de erro

| Código | Significado |
|---|---|
| 401 | Token ausente, inválido ou revogado |
| 403 | Operação sem permissão |
| 404 | Recurso não encontrado |
| 409 | Conflito de revisão, idempotência ou operação |
| 422 | Entrada, capacidade ou configuração inválida |
| 429 | Limite de solicitações atingido |
| 502 / 503 | Serviço externo indisponível ou resposta inválida |

Esquema completo: `/api/v1/openapi.json`. Referência interativa: `/api/v1/docs`.
