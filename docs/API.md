# API v1

Base: `/api/v1`. OpenAPI: `/api/v1/openapi.json`; interface Swagger: `/api/v1/docs`. O frontend não contém credenciais Tuya.

## Autenticação

`POST /auth/login` recebe `{"username":"admin","password":"..."}` com `Origin` igual a `APP_ORIGIN`. Retorna `csrf_token` e cookie `session` Secure, HttpOnly, SameSite=Strict, válido por oito horas. `GET /auth/session` recupera o token CSRF após recarregar a página. Mutações com sessão exigem `Origin` e `X-CSRF-Token`. `POST /auth/logout` revoga a sessão.

Integrações usam `Authorization: Bearer TOKEN`. Gere tokens pelo CLI `create-token --name zabbix`; acrescente `--control` para comandos de dispositivos e `--automations` para gerenciar automações. Permissões independentes; tokens existentes não ganham permissões novas. O valor é mostrado uma vez e o banco guarda apenas SHA-256. Liste com `list-tokens` e revogue com `revoke-token --name zabbix`. Os aliases `create-key` e `revoke-key` continuam disponíveis. O WebSocket aceita somente sessão de navegador.

## Recursos

| Método | Caminho | Contrato |
|---|---|---|
| GET | `/devices` | Lista de dispositivos, capacidades, conectividade e estados |
| POST | `/devices/sync` | Administrador com sessão e CSRF: consulta a Tuya, processa os eventos recebidos e retorna estados atualizados; limite de duas solicitações por minuto |
| GET | `/devices/{id}/state` | Mesmo retrato para um aparelho |
| GET | `/devices/{id}/history` | `property`, `start`, `end` obrigatórios; datas RFC3339 com fuso; intervalo máximo 90 dias |
| POST | `/devices/{id}/commands` | `{"power":true}` ou `false`; header `Idempotency-Key` de 8–128 caracteres obrigatório |
| GET | `/commands/{id}` | Consulta da execução; chave de integração lê somente seus próprios comandos |
| GET | `/status` | Conexão, ingestão, fila, falhas, chamadas no minuto e worker |
| GET | `/appearance` | Fundo selecionado e galeria salva; exige autenticação |
| PUT | `/appearance` | Administrador com sessão e CSRF: seleciona um padrão ou imagem salva com `{"id":"..."}` |
| POST | `/appearance/wallpapers` | Administrador com sessão e CSRF: corpo JPEG, `Content-Type: image/jpeg`, até 3 MB; persiste a imagem e a seleciona |
| GET | `/appearance/wallpapers/{id}` | JPEG autenticado, cache privado; URLs e IDs estáveis |
| WS | `/events` | Mensagens `snapshot` com `devices` e `heartbeat`; novo retrato após reconexão |

Cada estado inclui `property`, `value`, `unit`, `observed`, `received`, `source` e `stale`. Timestamps de saída são segundos Unix em UTC. `source` é `reportado` ou `estimado`; ausência de estado representa desconhecido. `connectivity` é independente: `online`, `offline` ou `desconhecida`.

Para o sensor virtual cuja API não retorna timestamp de medição, `observation_time_known` é `false`, `observed` representa o horário da consulta e o histórico inclui `time_basis: cloud_query`. Esse horário não comprova a idade da medição. O retrato identifica o dispositivo com `virtual: true`.

Histórico: `aggregation=raw|hour|day`, `limit=1..2000` para dados brutos. O cursor retornado contém `cursor_time` e `cursor_id`; envie ambos com os filtros originais para continuar. Agregados retornam `value` (média), `min`, `max`, `count` e `time`. Buckets vazios têm valores nulos e contagem zero. O intervalo é fechado no início e aberto no final.

Comandos retornam ID de correlação, destino, solicitação, horários, resposta e um dos estados `solicitado`, `aceito pela Tuya`, `falhou`, `resultado desconhecido`. Um resultado desconhecido não autoriza repetição automática. Reutilizar a mesma chave e corpo retorna o registro anterior; mesma chave com comando diferente retorna 409. Em caso de perda da resposta, repetir a requisição com a mesma chave é seguro. Após 180 dias, os registros de comando expiram junto com suas chaves de idempotência.

Erros: 401 sem autenticação válida; 403 sem escopo ou CSRF/origem inválidos; 404 recurso ausente; 409 conflito de idempotência; 422 capacidade ou entrada inválida; 429 limite local. Comando sem capacidade validada é sempre rejeitado. Limites iniciais: dez tentativas de login e vinte solicitações de comando por minuto, além do orçamento global Tuya configurável.

## Automações e controle infravermelho

| Método | Caminho | Contrato |
|---|---|---|
| GET | `/integrations/devices` | Cadastros e capacidades, sem credenciais Tuya |
| PUT | `/integrations/devices` | Somente administrador com sessão e CSRF; papéis `sensing` e `infrared` podem coexistir no mesmo `id`; hub e remote_id separados |
| GET | `/devices/{id}/control` | Capacidades, estado estimado e últimos vinte comandos; sem consulta à Tuya |
| POST | `/devices/{id}/control/commands` | `{"type":"power","value":true}` ou `{"type":"temperature","value":22}`; controle autorizado e Idempotency-Key obrigatório |
| POST | `/devices/{id}/control/status` | Consulta explícita de status IR, capacidade validada e limite local; resultado sempre estimado |
| GET / POST | `/automations` | Listar; criar com sessão administrativa ou token `--automations`, sempre desativada |
| PUT / DELETE | `/automations/{id}` | Editar (desativa) ou excluir; auditoria de execuções preservada |
| PATCH | `/automations/{id}/enabled` | `{"enabled":true}` ou `false`; habilitação valida capacidades e definições |
| POST | `/automations/{id}/preview` | Avaliação sem comandos ou alteração de runtime; sessão administrativa ou token `--automations` |
| GET | `/automations/history/runs` | Últimas cem execuções; filtro opcional `rule_id` |

Definições, tipos de gatilho, perfis e semântica de execução estão em `AUTOMATIONS.md`. A consulta `/status` inclui `health.automations`. Registros de comandos agora incluem `action`; `power` permanece para compatibilidade e é nulo em comandos de temperatura. Estados e medições distinguem horários de consulta sem origem conhecida; consultas sem timestamp não sustentam regras físicas de duração.

O cadastro aceita também `profile: tuya_standard_ir` e `keys_enabled`. `POST /devices/{id}/control/discover` exige administrador, consulta os metadados na Tuya e salva a lista de teclas padrão. Comandos `type: ir_key` usam `value` string pertencente a essa lista. As capacidades retornam `keys`; o perfil de TV não expõe capacidades de potência discreta, temperatura ou status AC. `GET /devices/{id}/control` retorna a confirmação física registrada por tecla em `physical_tests`, quando houver evidência. Essa confirmação não representa o estado atual da TV.


## Fluxo visual

Contrato e semântica em [WORKFLOWS.md](WORKFLOWS.md). Novas rotas sob `/api/v1/automation-flow`.

GET `/api/v1/notification-connections` e PUT `/api/v1/notification-connections/{channel}` configuram canais de notificação, somente com sessão administrativa. [Contrato completo](NOTIFICATIONS.md).

## Conectividade e validade das medições

`GET /api/v1/devices/{id}/connectivity` exige sessão ou chave de integração de leitura. Retorna `id`, `name`, `connectivity` (`online`, `offline`, `desconhecida`), `online` (`true`, `false`, `null`) e `connectivity_checked_at` (UTC Unix; última informação de conectividade). Se a informação de conexão estiver desatualizada, retorna `online: null`, preservando o horário da última confirmação.

`GET /api/v1/devices/{id}/state` e `GET /api/v1/devices` incluem os mesmos campos de conectividade. Para temperatura e umidade, cada estado informa `current`, `freshness_reason` e `measurement_at`. Quando offline: `current: false`, `stale: true`, `freshness_reason: sensor_offline`; o valor preservado representa a última leitura conhecida. `measurement_at: null` indica que a Tuya não informou o horário real da medição. O horário de consulta não comprova uma nova medição. Para sensores reais sem horário de origem, a leitura fica com `freshness_reason: measurement_time_unknown` e não é apresentada como atual.

Reconciliações em que a Tuya retorna explicitamente `online: false` atualizam somente a conectividade, sem registrar as propriedades armazenadas na nuvem como novas medições. Registros antigos já persistidos não são apagados retroativamente.

### Períodos offline no histórico

As respostas de histórico incluem `offline_intervals: [{start, end}]`, em UTC Unix, limitados ao intervalo solicitado. São reconstruídos a partir de registros de conectividade; notificações offline repetidas são unidas, e a confirmação expira após três intervalos esperados sem atualização. Assim, ausência de informação não é rotulada como queda confirmada. Início e fim representam horários registrados/consultados, não necessariamente o instante físico exato da desconexão.

Agregados de temperatura/umidade excluem valores registrados durante períodos confirmados offline, inclusive snapshots antigos. Dados brutos são preservados para auditoria. O gráfico mostra faixas de perda, interrompe as linhas nesses períodos e oferece os horários em “Perdas de conexão”.

## Guia de integração por token

Veja [INTEGRATION-API.md](INTEGRATION-API.md) para comandos do terminal e exemplos de visualização e controle de dispositivos e automações. Tokens com `--automations` podem alterar fluxos e regras legadas; as restrições de adoção do fluxo visual continuam aplicáveis. Cadastro de dispositivos, descoberta IR, sincronização manual, papéis de parede e conexões de notificação permanecem administrativos.
