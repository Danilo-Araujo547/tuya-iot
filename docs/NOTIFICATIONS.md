# Notificações nas automações

Em Adicionar bloco → Notificação, escolha WhatsApp, Telegram ou Webhook HTTP. Conecte o bloco a um gatilho, condição, espera ou ação. Ele também pode terminar o fluxo; para notificar por vários canais, conecte vários blocos. Sem ligação ou com fluxo desativado, não envia.

No painel do bloco, Configurar abre a conexão do canal. Uma conexão é compartilhada por todos os blocos do mesmo canal. Informe o token no campo protegido. Deixar token vazio preserva o atual; Remover token salvo revoga a configuração local. Salvar conexão não envia mensagens. URL e token de webhook são campos protegidos que não são devolvidos pela API; deixe URL vazia para manter a já salva. URL do Telegram é fixa em https://api.telegram.org.

Os tokens ficam em arquivos privados do servidor, fora do desenho e das execuções. Na instalação Windows deste projeto: work/private/notifications, sob o diretório privado existente. No Docker Compose: volume notifications montado em /var/lib/tuya-notifications, gravável apenas pelo usuário da aplicação. Não inclua esses arquivos no repositório. A API exige sessão administrativa e CSRF para alterar conexões.

## WhatsApp

Implementação conforme o anexo WhatsApp API 2.1.0. URL inicial http://172.16.0.59:3011, POST /api/send, Authorization: Bearer TOKEN. O token é o da API instalada, normalmente em .whatsapp-token no projeto WhatsApp; não é a senha do dashboard Tuya.

Escolha exatamente um tipo de destino: phone, group_id ou chat_id. O bloco envia esse campo e message. A conta deve estar conectada antes da execução. Para sucesso, exige success=true e accepted=true; não confunde HTTP 200 com aceitação. Envio aceito pelo socket não confirma recebimento ou leitura. Não usa send-batch, QR/reset, documentos ou as rotas de bot compatíveis do serviço WhatsApp.

## Telegram

Usa a [Bot API oficial](https://core.telegram.org/bots/api#sendmessage), POST /botTOKEN/sendMessage com chat_id e text. Configure token do bot e chat_id numérico (inclusive negativo para grupos) ou @canal. O bot precisa ter acesso e permissão para enviar. Em conversa privada, inicie o bot primeiro. A resposta exige ok=true. Mensagens são texto simples sem parse_mode.

## Webhook

Configure uma URL HTTP(S) completa e, se necessário, um Bearer token. Envia POST JSON com event=automation.notification, message, run_id, node_id, flow_name, revision e timestamp UTC Unix. Acrescenta Idempotency-Key run_id:node_id; o receptor decide se fará deduplicação. HTTP 2xx representa aceitação; redirects não são seguidos. Não são permitidos usuário/senha na URL, esquemas não HTTP(S), nem fragmentos.

## Execução e diagnóstico

Mensagem de texto simples até 4096 caracteres. Destinatários e mensagens vazios podem ser salvos como rascunho, mas impedem ativação quando conectados. Timeout configurável de 3 a 30 segundos. O motor persiste a etapa antes de enviar, não repete automaticamente após timeout, queda de rede ou reinício durante o envio. Um resultado desconhecido exige inspeção humana. Erro interrompe a execução inteira, como nos comandos de dispositivo. Aceitação permite seguir ao próximo bloco. As notificações compartilham o limite global de 20 envios/comandos por minuto.

Execuções mostra canal, HTTP quando disponível, identificador retornado pelo provedor e aceitação/falha/resultado desconhecido. Não registra corpo bruto da resposta nem tokens. O log HTTP do cliente é suprimido para não registrar o token Telegram presente no caminho. Não há confirmação de leitura nem teste automático com envio real ao salvar.

## Operação

API: GET /api/v1/notification-connections e PUT /api/v1/notification-connections/{whatsapp|telegram|webhook}. PUT recebe url, token e clear_token. GET retorna apenas canal, configuração disponível e presença de token. A mensagem no fluxo usa kind=notification e data={channel,destination_type,destination,message,timeout_seconds}.

Também é possível iniciar configurações por WHATSAPP_API_URL, WHATSAPP_API_TOKEN, TELEGRAM_API_TOKEN, WEBHOOK_API_URL e WEBHOOK_API_TOKEN (ou variáveis com sufixo _FILE). Arquivos salvos no painel têm prioridade. NOTIFICATION_CONFIG_DIR define o diretório privado.

O backup Compose inclui o volume de conexões no repositório Restic criptografado junto do dump PostgreSQL. Restaure /var/lib/tuya-notifications no mesmo volume, proprietário UID 10001, diretório modo 700 e arquivos 600. Revise fluxos ativos antes de iniciar o worker após restauração. Em instalação nativa, inclua o diretório privado das conexões no seu backup criptografado.

Validação: suíte usa transporte HTTP simulado. Nenhuma mensagem real foi enviada; a homologação final depende dos tokens, destinatários e conexão do serviço instalado.
