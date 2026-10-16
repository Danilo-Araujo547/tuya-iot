# Tuya IoT — Ambiente

Aplicação local para temperatura, umidade, histórico e comandos de energia. Backend FastAPI, dashboard React/TypeScript e PostgreSQL. Inclui regras persistentes por temperatura e horário e painel modular de controle infravermelho. Consulte `docs/AUTOMATIONS.md` para cadastro dos dispositivos, funcionamento e limites.

## Visual e imagem de fundo

O dashboard usa a referência Spatial Climate: mostrador circular, cartões de vidro translúcido e menu lateral recolhível pelo ícone de hambúrguer. As páginas, atualização, conta e personalização ficam nesse menu. **Sala Solar**, **Estúdio** e **Luz Nórdica** usam as três fotografias Unsplash fornecidas no HTML de referência; Sala Solar é o padrão inicial.

Abra **Menu → Papel de parede** para escolher um cenário padrão ou enviar uma foto JPG, PNG ou WebP de até 12 MB. O navegador prepara um JPEG de até 1920 pixels e 3 MB; a API valida, remove metadados e salva a imagem no PostgreSQL. A galeria guarda até 20 imagens distintas e a escolha ativa é compartilhada entre navegadores autenticados, com sincronização em até 30 segundos ou ao voltar à janela. As imagens ficam incluídas no backup do banco e sobrevivem a reinícios; não dependem de localStorage. A imagem não é enviada à Tuya. **Restaurar fundo padrão** volta à Sala Solar sem apagar a galeria. As fotografias padrão precisam de conexão com `images.unsplash.com`; em caso de falha, um fundo degradê mantém a interface utilizável.

O mostrador e os cartões continuam usando os estados reais do backend. O gráfico oferece temperatura e umidade juntas ou separadas, com eixos e unidades distintos; os valores virtuais continuam identificados como simulação na Tuya Cloud.

**Situação:** código implementado e verificações locais descritas em `VALIDATION.md`. Autenticação, status e especificação do sensor virtual foram validados com a Tuya Cloud; veja `docs/CLOUD-VALIDATION.md` e `config/sensor-virtual.validated.json`. Eventos Pulsar, implantação e ensaio de 48 horas continuam pendentes.

## Arquitetura

```mermaid
flowchart LR
  S[Sensor Zigbee] --> G[Gateway Tuya]
  W[Sensor Wi-Fi] --> T[Tuya Cloud]
  G --> T
  T -->|Pulsar com TLS| C[Consumidor SDK adaptado]
  C -->|Persistir antes de ACK| Q[(PostgreSQL: inbox)]
  Q --> P[Processador]
  P --> H[(Histórico + estado atual)]
  H --> A[API FastAPI]
  A -->|REST + WebSocket| D[Dashboard React]
  D -->|Comando autenticado| A
  A --> U[Adaptador OpenAPI / IR]
  U --> T
  T --> I[IR blaster]
  I -->|IR sem retorno físico garantido| R[Aparelho]
```

O worker confirma mensagens apenas após persistência. O processamento grava histórico e último estado na mesma transação. Eventos antigos não substituem estados novos. A API consulta o banco e envia retratos por WebSocket, verificando mudanças a cada dois segundos; o navegador não faz polling de estado. Histórico é atualizado por minuto enquanto a página está aberta. A reconciliação Tuya ocorre no início, após reconexão e de hora em hora, com limite compartilhado de chamadas.

O botão **Atualizar** realiza uma consulta autenticada à Tuya, em vez de apenas recarregar o banco. `TUYA_RECONCILE_SECONDS` define a reconciliação automática, com padrão de 3600 segundos. Na instalação local com um sensor virtual foi configurado 300 segundos (cinco minutos), pois a conexão ao Message Service não comprovou entrega dos eventos de alteração desse sensor. O intervalo consome chamadas da conta e deve respeitar suas cotas.

## Instalação no servidor Linux

Requisitos: Docker Engine com Compose v2, DNS ou nome VPN para o servidor e destino separado para backups. Referência inicial: 2 CPUs, 4 GB de RAM e SSD; dimensionar armazenamento pelo volume real de eventos.

Execute na pasta deste projeto:

```sh
cp .env.example .env
cp config/devices.example.json config/devices.json
docker build -t tuya-iot-api:local backend
docker run --rm -it --network none -v "$PWD/secrets:/secrets" tuya-iot-api:local python -m app.bootstrap --dir /secrets
```

O assistente solicita senha administrativa e credenciais Tuya sem imprimi-las. Não comite `secrets/`, `.env` ou a configuração real de dispositivos. Os arquivos gerados são restritos e pertencem ao UID 10001 usado pela aplicação. Faça os comandos administrativos de arquivos como proprietário ou com `sudo`.

Edite `.env`: `APP_HOST` deve ser o nome que o navegador usará, sem protocolo; `BIND_ADDRESS` deve ser o IP privado específico do servidor. Ajuste ambos os endpoints Tuya à região do projeto. Ajuste `BACKUP_PATH` para um volume externo ou armazenamento montado separado do banco. O padrão `./backups` serve apenas à avaliação local.

```sh
docker compose build
docker compose up -d db
docker compose run --rm migrate
docker compose run --rm --no-deps api python -m app.cli provision
docker compose up -d
docker compose logs --tail=100 worker backup
```

Acesse `https://APP_HOST` com usuário `admin`. O Caddy usa uma autoridade certificadora privada: instale seu certificado raiz como confiável nos clientes da LAN/VPN. Extraia-o com `docker compose cp web:/data/caddy/pki/authorities/local/root.crt ./tuya-local-root.crt`. Distribua somente o certificado público, nunca a chave da autoridade. Não desabilite a verificação TLS.

O PostgreSQL e a API não publicam portas no host. O proxy expõe somente HTTPS no endereço escolhido. Configure o firewall para LAN/VPN e não encaminhe a porta no roteador. O Docker deve iniciar no boot do Linux.

## Validar dispositivos e serviços Tuya

1. No console Tuya, confirme região, conta Smart Life vinculada, projeto e permissões. Consulte cotas e validade; os números de Trial do desenho original não são garantidos.
2. Liste a conta vinculada: `docker compose run --rm --no-deps api python -m app.cli discover --uid SEU_UID`.
3. Inspecione cada sensor ou hub: `docker compose run --rm --no-deps api python -m app.cli probe --device ID`. Para os controles virtuais de um hub: acrescente `--infrared`.
4. Substitua IDs e propriedades no arquivo `config/devices.json`. Os códigos, escalas e corpos IR do exemplo são ilustrativos, não universais. `gateway_id` documenta a associação física Zigbee; a nuvem continua responsável pela conexão do gateway.
5. Para sensor, registre os códigos do evento real, tipo, escala e unidade. Exemplo: valor `245`, escala `1` resulta em `24,5 °C`. Registre o intervalo esperado do aparelho.
6. Para dispositivo Wi-Fi controlável, use `command: {"kind":"device","validated":false,"code":"CODIGO_REAL"}` e mapeie a propriedade de energia reportada como booleano. Para IR, configure o caminho da API e os corpos `on`/`off` específicos do controle. Prefira comandos explícitos de energia: um comando toggle não deve ser mapeado como ligar/desligar.
7. Confirme o Message Service e a recepção de eventos em Diagnóstico. Nenhuma credencial entra no navegador. Provisione novamente após qualquer alteração de configuração.
8. Após conferir o contrato da API e a biblioteca IR, habilite `validated: true` para o aparelho que será testado, reprovisione e execute ligar e desligar no dashboard, observando fisicamente o resultado. Se falhar, desabilite a capacidade. Mantenha a evidência em um relatório local protegido.

O retorno positivo da Tuya significa aceitação pela nuvem. O estado fica **estimado** até um evento independente reportá-lo. Um controle IR convencional continua estimado mesmo quando a API oferece estado do controle virtual. Na ausência de dados, a interface mostra estado ou conectividade desconhecidos; após três intervalos sem medição, mostra dado desatualizado.

## Integração pela API

O [guia de integração](docs/INTEGRATION-API.md) documenta somente visualização e controle de dispositivos e automações, com exemplos PowerShell/curl. Gere tokens no terminal usando `python -m app.cli create-token --name integracao`: `--control` libera comandos manuais e `--automations` libera gerenciamento de automações. `list-tokens` lista permissões; `revoke-token --name integracao` revoga. O cliente usa Bearer e não recebe as credenciais administrativas ou da Tuya. A migração 005 preserva as permissões de tokens antigos.

## Desenvolvimento e testes

```sh
python -m venv .venv
. .venv/bin/activate
pip install -r backend/requirements.txt
python -m pytest backend/tests -q
cd frontend
npm ci
npm run build
```

Os testes padrão usam SQLite em memória para isolamento. Para verificar os mesmos cenários em PostgreSQL, defina `TEST_POSTGRES_URL=postgresql+psycopg://USUARIO:SENHA@HOST/BANCO_DE_TESTE` antes do pytest. **Use um banco descartável:** a suíte cria e remove suas próprias tabelas. Não use o banco operacional.

O frontend de desenvolvimento precisa de proxy HTTPS para a API: cookies de sessão permanecem `Secure` em todos os ambientes. Não há modo de demonstração nem credenciais padrão no produto. Para detalhes, consulte `docs/API.md` e `docs/OPERATIONS.md`.

## Temperatura externa

`GET /api/v1/weather/current` exige a mesma autenticação de leitura das demais consultas. O backend consulta Open-Meteo, mantém cache por dez minutos e limita novas tentativas após erro. O resultado é uma estimativa de modelo meteorológico, separado das medições internas Tuya; não entra no histórico do sensor. Em falha temporária, a última leitura disponível é marcada como antiga; leituras com mais de duas horas não são apresentadas. Sem dado utilizável, a API retorna 503 e o card indica indisponibilidade.

A referência padrão é Votuporanga, nas coordenadas -20.42278, -49.97278. Para mudar, configure `WEATHER_LATITUDE` e `WEATHER_LONGITUDE` no ambiente do backend. O dashboard exibe apenas “Temperatura externa”, sem cidade ou estado. A fonte é creditada no próprio card. Documentação: https://open-meteo.com/en/docs . A API pública gratuita é destinada a uso não comercial; em implantação comercial, adequar o plano e endpoint ao contrato do provedor.

Os seletores de sensor e período usam menus próprios com navegação por teclado (setas, Home, End e Escape), indicação da opção ativa e fechamento ao clicar fora.


O sensor real **Sensor temperatura Data Center** está cadastrado nas duas funções, e a TV Samsung vinculada está disponível no menu **Controle IR**. Volume − foi validado fisicamente pelo usuário. Consulte `docs/CLOUD-VALIDATION.md` para a evidência e `config/data-center.validated.json` para a configuração sem credenciais. A regra de exemplo continua desativada; o controle do ar-condicionado depende de seu próprio remote_id.


Automações agora usam um editor visual de fluxo único. Consulte [Editor de fluxos](docs/WORKFLOWS.md).

Bloco de notificação disponível para WhatsApp, Telegram e webhook. Veja [Notificações](docs/NOTIFICATIONS.md).
