# Editor visual de automações

Em ☰ → Automações há um único fluxo com blocos arrastáveis e ligações direcionadas. Usa React Flow (https://reactflow.dev/learn). O desenho, posições, configurações e execuções ficam no PostgreSQL.

- Gatilho: temperatura, umidade ou horário de Brasília, com duração contínua e histerese nos sensores.
- Espera: prazo persistente entre 1 segundo e 24 horas; continua após reinício. Não é um timeout de rede nem garante que a condição inicial permaneça verdadeira. Use uma condição depois da espera para conferir novamente.
- Condição: comparação de temperatura ou umidade, saídas Sim e Não. Dado inválido/desatualizado bloqueia ambas.
- Ação: ligar/desligar, temperatura desejada ou tecla IR conforme capacidades validadas do dispositivo.

Vários gatilhos conectados a uma ação significam OU: cada gatilho pode iniciar sua própria execução. Não há sincronização E entre eventos independentes. Para exigir uma condição adicional, encadeie um bloco Condição. Caminhos convergentes dentro da mesma execução executam cada bloco uma única vez. Gatilhos simultâneos continuam sujeitos à proteção mínima entre comandos do aparelho; a segunda execução pode ser bloqueada e aparece no histórico.

Blocos desconectados não executam. Ligações a gatilhos, conexões duplicadas e ciclos são rejeitados. Limites: 60 blocos, 150 conexões, 100 execuções pendentes. Novas ocorrências acima do limite são ignoradas e diagnosticadas no gatilho. Horários perdidos não são recuperados automaticamente.

Salvar desativa o fluxo e cancela esperas pendentes. Desativar também cancela esperas; comandos já enviados não podem ser desfeitos. Ativar começa nova avaliação, sem reaproveitar contagens antigas. O navegador pode ser fechado; o worker executa a cada 5 segundos. Timeout ou interrupção após assumir uma ação produz resultado desconhecido sem reenvio automático. Falha interrompe toda aquela execução, inclusive os outros ramos.

As regras antigas são apresentadas como desenho importado. O primeiro salvamento adota o fluxo único e desativa o motor antigo, mantendo regras e auditoria anteriores. Revisões impedem sobrescrever alterações de outra aba. A API antiga não permite reativar regras depois da adoção.

## API autenticada

GET /api/v1/automation-flow — desenho e estado.
PUT /api/v1/automation-flow — name, revision, cooldown_seconds, nodes, edges; salva desativado.
PATCH /api/v1/automation-flow/enabled — enabled e revision.
POST /api/v1/automation-flow/validate — valida o desenho sem emitir comandos.
GET /api/v1/automation-flow/runs — últimas 60 execuções, etapas, resultados e esperas.

Nós: {id, kind: trigger|delay|condition|action, label, position:{x,y}, data:{...}}.
Arestas: {id, source, target, port:out|yes|no}. Condições exigem yes/no; demais blocos usam out.
Mutações exigem administrador e CSRF. Chaves de integração só consultam. Migração 004_workflows.sql incluída. Backup PostgreSQL também preserva os fluxos e esperas. Auditoria mantida por 180 dias.

O bloco Ação apresenta todos os botões IR habilitados diretamente numa grade. Cada botão seleciona o comando a salvar; não transmite ao clicar. Capacidades de energia, temperatura, modos e ventilação aparecem quando validadas. Cada nó envia um comando; encadeie nós para uma sequência.
