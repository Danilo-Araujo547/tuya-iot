# Operação, recuperação e homologação

## Monitoramento

Consulte `GET /api/v1/status` com chave somente de leitura ou a página Diagnóstico. Integre ao Zabbix por HTTPS, confiando na autoridade certificadora do Caddy. Monitore `tuya_connected`, a idade de `health.worker.updated`, `health.last_ingest.at`, o atraso de `oldest_pending`, `pending`, `dead`, `commands_unknown` e `http_calls_window`. Falta de eventos também pode representar sensores silenciosos: compare com os intervalos esperados.

O worker registra erros estruturados sem segredos ou payloads. Os containers têm política `unless-stopped`; configure o coletor do servidor para os logs do Docker. Verifique também `docker compose ps` e `docker compose logs backup`. Um healthcheck identifica falhas; por si só não reinicia um processo ainda vivo. Acompanhe o heartbeat pelo Zabbix.

Fila de falhas: `docker compose exec worker python -m app.cli dead-events`. Corrija a configuração e reprovisione antes de reprocessar com `python -m app.cli replay --event ID`. Eventos têm até cinco tentativas, espera exponencial e transação atômica. A exceção registrada não inclui conteúdo sensível.

O estado atual reside no banco. Falha de conexão WebSocket não altera medições; após reconexão o dashboard busca o retrato completo. Nenhum comando incerto ou interrompido é reenviado pelo worker. Solicitações que permanecem em `solicitado` por mais de 60 segundos passam a resultado desconhecido na manutenção.

## Backup e restauração

O serviço `backup` faz `pg_dump` consistente, criptografa com Restic, mantém sete cópias diárias e quatro semanais e verifica a integridade do repositório. Executa na inicialização e a cada 24 horas. Use destino montado separado; o diretório local padrão não protege contra perda do servidor. Copie os segredos, configuração de dispositivos e certificados Caddy por procedimento protegido separado: eles não fazem parte do dump do banco.

Backup sob demanda: `docker compose exec backup /backup.sh once`. Lista: `docker compose exec backup restic snapshots`. Não execute uma rotina manual ao mesmo tempo que o agendamento. Guarde `secrets/restic_password` fora do servidor: sem ela o backup não pode ser recuperado.

Teste de recuperação sem tocar no banco operacional: execute `sh ops/restore-check.sh`. Ele restaura o último dump em um banco vazio temporário, verifica migração e contagens e remove somente esse banco temporário. Registre saída e data. Verificação de arquivos Restic não substitui esse ensaio.

Para recuperação operacional, primeiro pare API e worker e gere uma cópia do banco existente. Restaure o dump validado em um **novo banco**, configure `secrets/database_url` para esse banco, execute migrações, provisione os dispositivos e inicie os serviços. Só descarte o banco antigo após validar dashboard, ingestão e histórico. Não use `docker compose down -v`: isso remove volumes persistentes.

## Atualização

Antes de atualizar: backup e ensaio de restauração. Depois: `docker compose build`, `docker compose run --rm migrate`, `docker compose up -d`. A migração 001 é transacional, versionada em `schema_migrations` e protegida por advisory lock no PostgreSQL. Alterações futuras exigem nova migração numerada e teste com dados preservados; não edite uma migração aplicada.

Retenções: medições por 90 dias; payload de eventos processados por sete dias; tombstones de deduplicação por 90 dias; auditoria de comandos por 180 dias. Eventos em falha são preservados até resolução. O último estado conhecido permanece disponível e é marcado desatualizado pelo tempo da observação.

## Critérios para homologação real

Preencha um relatório protegido com modelo e IDs dos dispositivos, região, serviços, cotas e vencimentos conferidos no console. Não inclua Access Secret, tokens ou chaves.

- Receber temperatura e umidade reais; comparar escala/unidade e horário com o aparelho.
- Confirmar gateway Zigbee, quando aplicável, e eventos de conectividade suportados.
- Executar ligar/desligar em cada categoria e conferir o resultado físico. Estado IR deve continuar estimado sem sensor independente.
- Operar por 48 horas, registrando horário inicial/final, disponibilidade do consumidor, volume de eventos e falhas.
- Interromper a internet em janela supervisionada; conferir desconexão, dados antigos e reconciliação após retorno.
- Reiniciar worker e servidor; conferir retomada dos eventos, estado e histórico e ausência de reenvio de comandos.
- Testar limitação e expiração de token sem exceder orçamento contratado.
- Gerar backup criptografado e executar restauração em banco vazio.
- Confirmar que portas do banco/API não são acessíveis fora da rede Docker e que HTTPS é confiável nos clientes VPN.

Somente após esses itens marque a implantação como homologada. A suíte com transporte simulado não comprova permissões ou execução física na Tuya.
