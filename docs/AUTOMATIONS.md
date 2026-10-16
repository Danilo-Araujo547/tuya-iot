# Automações e infravermelho

## Usar o painel

No menu ☰, abra **Controle do ar**. Em **Cadastrar dispositivo**, informe nome e Device ID e escolha as funções: leitura de temperatura/umidade, infravermelho ou ambas. Um sensor combinado deve ter um único cadastro com as duas funções marcadas; aparelhos separados têm cadastros próprios. O hub IR e o controle virtual do ar têm campos separados. O remote_id não é o ID do sensor. É possível salvar o cadastro enquanto o controle ainda não estiver disponível.

Configure os códigos e escalas reais de temperatura e umidade do novo sensor. Os campos iniciais `va_temperature` (escala 1) e `va_humidity` (escala 0) correspondem ao sensor virtual já validado, não a todos os produtos. Só marque as capacidades IR como validadas depois de conferir os comandos e o resultado físico. Não se envia comando ao salvar um cadastro. IDs e capacidades ficam no PostgreSQL; configurações feitas na interface são preservadas pelo provisionamento durante reinícios.

Os botões **Ligar**, **Desligar**, **Baixar/Aumentar temperatura**, **Aplicar temperatura** e **Consultar status na Tuya** usam somente capacidades habilitadas. Os botões de temperatura ajustam o valor desejado; **Aplicar** envia a temperatura absoluta. O estado retornado pelo IR é estimado e pode divergir do aparelho após o uso do controle físico. Comandos não são repetidos automaticamente após timeout; o histórico conserva o resultado desconhecido.

Em **Automações → Nova regra**, escolha:

- **Temperatura:** sensor, acima/abaixo do limite, duração mínima e margem para rearmar.
- **Horário:** hora, minuto e dias da semana, sempre em America/Sao_Paulo.
- Até cinco ações: ligar, desligar ou definir temperatura absoluta. É possível ligar o ar e ajustar a temperatura na mesma regra; não repita o mesmo tipo de comando no mesmo aparelho.
- Intervalo mínimo entre execuções, inicialmente cinco minutos.

Exemplo: acima de 27 °C por cinco minutos → ligar o ar. Com margem de 0,5 °C, a regra precisa observar 26,5 °C ou menos antes de poder armar novamente. Para desligar ao esfriar, crie outra regra com limite e intervalo adequados ao aparelho. Não há desligamento implícito na regra de ligar.

Salvar ou editar deixa a regra desativada. Rascunhos sem destino podem ser guardados; o botão de habilitar só libera regras com ações e capacidades válidas. Usar valores virtuais para comandar um aparelho exige autorização explícita no editor. Nesta instalação foi deixado o rascunho **Resfriar acima de 27 °C**, desativado e sem destino enquanto o IR não estiver configurado.

## Como o motor executa

API e worker compartilham as definições no PostgreSQL. O worker avalia regras a cada cinco segundos; a interface pode ser fechada. Estado de contagem, rearme, intervalo e ocorrências são persistidos. Uma lacuna superior a vinte segundos entre avaliações reinicia a contagem pendente e mantém a trava de uma condição já executada; tempo com o servidor parado não conta como prova de temperatura contínua.

Medição ausente, estimada, antiga (mais de três intervalos esperados), sem horário de origem conhecido ou aparelho explicitamente offline interrompem a contagem. Consultas da nuvem sem timestamp são identificadas; elas não comprovam que uma leitura física é nova. Para testar com o sensor virtual, o opt-in permite considerar horários de consulta. Eventos de temperatura intermediários processados entre avaliações são considerados, incluindo quedas que interrompem a condição. O limite de processamento por avaliação é conservador: sobrecarga reinicia a contagem.

A condição de temperatura dispara uma vez e fica travada até sair da faixa de rearme. Agendas não recuperam horários perdidos: executam no minuto selecionado e nos dias escolhidos. A ocorrência local (data/hora) é única por regra; reiniciar ou reabilitar no mesmo minuto não repete uma agenda já registrada.

O worker registra a execução antes de enviar qualquer comando. Comandos de cada execução têm chaves de idempotência estáveis e auditoria persistida antes da chamada externa. Falha, rejeição ou resultado desconhecido interrompem as ações restantes; não há reenvio automático. Uma execução interrompida fica desconhecida na manutenção. Não há garantia de execução física exatamente uma vez em sistemas IR; a estratégia evita reenvio automático quando a resposta é ambígua.

Regras concorrentes compartilham os limites de chamadas e comandos e respeitam um intervalo por aparelho, inclusive após comandos manuais. A primeira pode ser aceita e a outra ficar bloqueada, o que aparece no histórico; ações bloqueadas não ficam em fila para executar mais tarde. Desativar uma regra bloqueia as próximas ações, mas não desfaz um sinal já enviado. A auditoria de execuções é mantida por 180 dias e sobrevive à exclusão da regra.

## Adaptadores e configuração futura

`app/control_profiles.py` define as capacidades e valida os comandos. `app/tuya.py` contém os adaptadores HTTP; `app/controls.py` cuida de cadastro, consulta e comandos manuais. `app/commands.py` oferece auditoria e idempotência comuns ao painel e ao motor. `app/automations.py` avalia condições e coordena execuções. Uma nova API pode ser adicionada ao adaptador/perfil sem reescrever a avaliação de regras.

O perfil inicial é `tuya_ac_v2`:

- Envio: `POST /v2.0/infrareds/{infrared_id}/air-conditioners/{remote_id}/command`, com `code` e `value`.
- Leitura: `GET /v2.0/infrareds/{infrared_id}/remotes/{remote_id}/ac/status`.
- `power`: 0/1; `temp`: temperatura absoluta dentro da faixa validada. O backend também tem contratos para `mode` e `wind`, expostos apenas se configurados no perfil; não são presumidos no cadastro inicial.

A configuração por arquivo continua aceitando os adaptadores legados de potência e IR. Para um aparelho combinado, mantenha `properties` com as medições e `command` com o perfil IR no mesmo Device. A reconciliação consulta as propriedades de sensores combinados e não trata controles virtuais puros como sensores Tuya genéricos.

Referências oficiais: [comando de ar-condicionado](https://developer.tuya.com/en/docs/cloud/2b433a31dc?id=Kb3oeafwj8rhh), [status IR](https://developer.tuya.com/en/docs/cloud/7c201040b7?id=kb3oea6v4yxy5) e [IR Control Hub](https://developer.tuya.com/en/docs/cloud/ir-control-hub-open-service?id=Kb3oe2mk8ya72).

## Implantação

Atualize as dependências, compile o frontend e execute a migração 003 antes de reiniciar API e worker. O banco inclui definições, estado de execução, histórico de regras e comandos; o backup PostgreSQL inclui tudo. A migração é aditiva e preserva a galeria e medições existentes. Confira `health.automations` em `/api/v1/status` para verificar a atividade do motor e o número de regras habilitadas.

O hub físico Data Center e a TV Samsung vinculada já foram cadastrados. Volume − recebeu retorno positivo da API e confirmação física do usuário; essa é a tecla fisicamente validada até o momento. O ar-condicionado continua dependendo de cadastro e validação próprios. Capturas marcadas PRÉVIA usam banco isolado com cópia das evidências; elas não transmitem comandos adicionais ao aparelho real.


## TV e controles por teclas

No menu **Controle IR**, escolha o perfil **TV e outros controles por teclas**. Informe os IDs do hub e do controle virtual, permita o envio e use **Atualizar teclas na Tuya** para consultar a biblioteca. A API não recebe listas arbitrárias de teclas do navegador: somente teclas padrão retornadas pelo serviço ficam disponíveis. Ao trocar o hub, remote_id ou biblioteca, a lista ou a evidência física anterior é invalidada conforme a alteração.

`POST /api/v1/devices/{id}/control/discover` consulta a biblioteca sem transmitir infravermelho. `POST /api/v1/devices/{id}/control/commands`, com `{"type":"ir_key","value":"Volume-"}` e chave de idempotência, envia uma tecla auditada. O backend usa `POST /v2.0/infrareds/{hub}/remotes/{remote}/command` com `categoryId`, `remoteIndex` e `key`, conforme o exemplo oficial e o teste real aceito. O contrato e a proteção contra reenvio são compartilhados com o perfil de ar-condicionado.

A TV Samsung vinculada ao sensor Data Center já foi testada com Volume −, com retorno positivo da Tuya e confirmação física do usuário. A tecla Power desse controle alterna ligado/desligado; a interface não inventa um estado de energia. O perfil não oferece status de ar-condicionado nem comandos de temperatura. Ações de regra podem usar `type: ir_key` e uma tecla da biblioteca, mas nenhuma regra da instalação foi habilitada automaticamente para a TV.
