# API v1

Base: `/api/v1`. OpenAPI: `/api/v1/openapi.json`; interface Swagger: `/api/v1/docs`. O frontend não contém credenciais Tuya.

## Autenticação

`POST /auth/login` recebe `{"username":"admin","password":"..."}` com `Origin` igual a `APP_ORIGIN`. Retorna `csrf_token` e cookie `session` Secure, HttpOnly, SameSite=Strict, válido por oito horas. `GET /auth/session` recupera o token CSRF após recarregar a página. Mutações com sessão exigem `Origin` e `X-CSRF-Token`. `POST /auth/logout` revoga a sessão.

Integrações usam `Authorization: Bearer CHAVE`. Gere chaves pelo CLI `create-key --name zabbix`; acrescente `--control` somente para quem enviará comandos. O valor é mostrado uma vez; o banco guarda apenas SHA-256. Revogue com `revoke-key --name zabbix`. O WebSocket aceita somente a sessão de navegador e valida sua origem e validade a cada ciclo.

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
| GET / POST | `/automations` | Listar ou cadastrar regras; criação somente administrativa, sempre desativada |
| PUT / DELETE | `/automations/{id}` | Editar (desativa) ou excluir; auditoria de execuções preservada |
| PATCH | `/automations/{id}/enabled` | `{"enabled":true}` ou `false`; habilitação valida capacidades e definições |
| POST | `/automations/{id}/preview` | Avaliação sem enviar comandos ou alterar runtime; somente administrador |
| GET | `/automations/history/runs` | Últimas cem execuções; filtro opcional `rule_id` |

Definições, tipos de gatilho, perfis e semântica de execução estão em `AUTOMATIONS.md`. A consulta `/status` inclui `health.automations`. Registros de comandos agora incluem `action`; `power` permanece para compatibilidade e é nulo em comandos de temperatura. Estados e medições distinguem horários de consulta sem origem conhecida; consultas sem timestamp não sustentam regras físicas de duração.

O cadastro aceita também `profile: tuya_standard_ir` e `keys_enabled`. `POST /devices/{id}/control/discover` exige administrador, consulta os metadados na Tuya e salva a lista de teclas padrão. Comandos `type: ir_key` usam `value` string pertencente a essa lista. As capacidades retornam `keys`; o perfil de TV não expõe capacidades de potência discreta, temperatura ou status AC. `GET /devices/{id}/control` retorna a confirmação física registrada por tecla em `physical_tests`, quando houver evidência. Essa confirmação não representa o estado atual da TV.
