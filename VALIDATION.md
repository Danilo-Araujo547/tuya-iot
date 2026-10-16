# Validação da implementação

Data: 15/10/2026. As imagens iniciais usam dados sintéticos identificados como **validação local**. `sensor-cloud-preview.png` mostra valores consultados na API do sensor virtual. Nenhum aparelho real foi comandado nesta sessão.

| Verificação | Resultado |
|---|---|
| Suíte automatizada em PostgreSQL 18.4 temporário | 37 testes aprovados |
| Suíte rápida em SQLite | 35 testes aprovados; dois cenários exclusivos de PostgreSQL omitidos |
| Correção de atualização manual Cloud | 37 testes SQLite aprovados, dois exclusivos de PostgreSQL omitidos; build aprovado; fluxo de sincronização autenticado validado na Tuya real com 11,0 °C e 0% |
| API Cloud do sensor virtual | Autenticação, status e especificação validados com sucesso |
| Reconciliação real do sensor | Rota iot-03 → persistência → estado normalizado aprovada |
| Dashboard com valores Cloud | −20,0 °C e 0%; horário apresentado como consulta à nuvem; sem erros JavaScript |
| Migração SQL inicial | Aplicação e reaplicação com preservação dos dados aprovadas |
| Concorrência de comando com mesma chave | Um único envio ao adaptador, aprovado |
| Persistência antes de ACK Pulsar | Aprovada com transporte simulado, inclusive falha de gravação |
| TLS do adaptador Pulsar | Verificação de certificado exigida, aprovada |
| Eventos duplicados/atrasados/inválidos | Deduplicação, histórico e transação atômica aprovados |
| Token expirado, 429, 503 e timeout | Comportamento validado com HTTP simulado |
| Sessão, CSRF, escopo de chave e WebSocket | Aprovados |
| Retenção e recuperação de comando interrompido | Aprovadas |
| Frontend TypeScript + build Vite | Aprovados, com separação do bundle de gráficos |
| Navegador Edge/Playwright — 1440 px e 390 px | Dashboard, histórico, diagnóstico e layout aprovados; zero erros JavaScript e sem overflow horizontal |
| Auditoria npm, incluindo desenvolvimento | Zero vulnerabilidades conhecidas na consulta realizada |
| Auditoria pip dos requisitos e dependências transitivas | Zero vulnerabilidades conhecidas na consulta realizada |
| Backup Restic 0.19.1 criptografado | Criação, verificação integral e extração aprovadas |
| Restauração PostgreSQL em banco vazio | Aprovada: migração 001, dois dispositivos e 48 medições recuperados; dump extraído idêntico ao original |
| Sintaxe shell e estrutura Compose | Aprovadas por análise local |
| Quadro Miro | Componentes, fluxos e limites da V1 atualizados |

A suíte em PostgreSQL usa uma base descartável e transportes externos simulados. Ela não valida assinatura, permissões ou capacidade de um produto real na conta Tuya. Existem avisos de depreciação do cliente de testes Starlette/httpx e AnyIO; não provocaram falhas.

## Pendências de homologação

- Executar os containers no Linux: Docker não está instalado no computador usado nesta sessão. PostgreSQL 16 é a imagem definida no Compose; os testes locais usaram PostgreSQL 18.4.
- Configurar os segredos no servidor. O sensor virtual já tem autenticação, status e especificação Cloud validados; detalhes em `docs/CLOUD-VALIDATION.md`. Outros dispositivos e contratos IR ainda precisam ser cadastrados e testados.
- Conferir região, permissões, cotas e vencimentos na conta Tuya.
- Receber medições pelo Message Service real e testar cada categoria de comando com observação física.
- Confiar na CA privada HTTPS nos clientes e validar acesso somente por LAN/VPN.
- Configurar destino de backup separado e repetir a restauração usando o Compose no servidor.
- Completar 48 horas com dispositivos reais, queda de internet e reinício supervisionados.

## Artefatos

## Verificação do visual Spatial Climate

- Build TypeScript/Vite aprovado após a adaptação do HTML fornecido pelo usuário.
- Três cenários padrão carregados com sucesso: Sala Solar, Estúdio e Luz Nórdica.
- Escolha de cenário e foto personalizada preservadas após recarregar.
- Arquivo não reconhecido como imagem rejeitado com mensagem legível.
- Página de diagnóstico, períodos e filtros de temperatura/umidade verificados.
- Layout conferido em 1440 × 1000 e 390 × 844; sem rolagem horizontal após correção de tooltip.
- Nenhum erro JavaScript na verificação visual.
- Imagens `glass-desktop-preview.jpg`, `glass-mobile-preview.jpg` e `glass-background-options.jpg` mostram a prévia isolada com uma cópia dos valores do sensor (15 °C e 30%), identificada como prévia local. Essa prévia não contém credenciais Tuya nem controla aparelhos.

## Arquivos de referência

- `README.md`: instalação e configuração.
- `docs/API.md`: contratos de autenticação, estados, histórico e comandos.
- `docs/OPERATIONS.md`: manutenção, backup, restauração e homologação.
- `dashboard-preview.png`, `mobile-preview.png`, `login-preview.png`: imagens da execução local com dados de teste.

Código implementado não equivale a implantação homologada. As pendências acima não foram marcadas como concluídas.

### Card de extremos de temperatura

O card de temperatura mostra mínima e máxima do histórico salvo, com seletor próprio de 1h, 6h, 24h (padrão), 7d e 30d. Usa os extremos dos agregados horários, preservando picos que não aparecem nas médias do gráfico. Atualiza após novas consultas e a cada minuto, sem consultar a Tuya. Períodos vazios, carregamento e falha são indicados sem valores inventados. Os títulos superiores foram removidos.

Validação: compilação TypeScript/Vite concluída; seleção do período e extremos conferidos na prévia local com cópia das medições, em 1440px e 390px, sem rolagem horizontal no celular. A prévia mostrou mínima de -20 °C e máxima de 15 °C em 24h. Capturas: temperature-range-desktop.jpg e temperature-range-mobile.jpg.

### Temperatura externa e seletores

Incluída consulta autenticada à Open-Meteo, cache de dez minutos, validação de leituras e indicação de indisponibilidade. Verificados seis cenários de teste: autenticação/cache, falha com dado antigo e rejeição de quatro valores inválidos. Consulta real retornou 26,1 °C; endpoint em produção validado com certificado HTTPS local confiado explicitamente e login administrativo. Confirmados menus de período/sensor, seleção, Escape e versão móvel sem rolagem horizontal. Evidências: weather-selectors-desktop.jpg e weather-mobile.jpg. Capturas usam cópia local das medições internas; temperatura externa é consultada no provedor real.

### Menu recolhível, alinhamento e papéis de parede persistentes — 16/10/2026

Removidas as barras superiores. O botão de hambúrguer abre um menu lateral modal com páginas, papel de parede, atualização e saída. O menu fecha após navegação; Escape e foco são gerenciados pelo diálogo nativo. Rótulos dos limites do mostrador agora usam as mesmas coordenadas SVG da escala e ficam abaixo dos traços, sem sobreposição, inclusive no celular.

Migração PostgreSQL 002 aplicada no ambiente local. Imagens JPEG validadas, reprocessadas e sem metadados ficam no banco, junto com a escolha ativa; galeria com até 20 imagens e deduplicação. Nenhuma imagem de teste foi inserida na galeria operacional. A prévia visual utiliza cópia das medições e banco SQLite isolado para testar uploads.

Validação: compilação TypeScript/Vite concluída; suíte padrão com 47 testes aprovados e 2 dependentes de PostgreSQL ignorados. Os 4 novos testes de aparência também passaram em banco PostgreSQL descartável, verificando persistência entre sessões, recuperação binária, seleção, deduplicação, limites, permissões e CSRF. Consulta autenticada à API operacional confirmou a migração e a disponibilização da interface. Upload pela interface da prévia recuperado após reload. Navegação, abertura da personalização e layout em 1440px e 390px conferidos; sem rolagem horizontal no celular. Evidências: navigation-desktop.jpg, navigation-menu.jpg e navigation-mobile.jpg.

Verificação adicional: suíte completa também executada no PostgreSQL descartável, com **49 testes aprovados**, incluindo migrações 001/002 repetidas e preservação de dados e imagens já salvos.

### Automações persistentes e controle IR modular — 16/10/2026

Implementados os painéis Automações e Controle do ar, cadastro de dispositivos por funções independentes, adaptador Tuya AC v2, comandos absolutos de temperatura, consulta estimada de status, motor por temperatura/duração e agenda semanal em America/Sao_Paulo. Um dispositivo pode acumular sensoriamento e IR ou as funções podem usar IDs separados. Registros feitos pela interface ficam no banco e são preservados pelo provisionamento em reinícios. Ao trocar hub/remote, estados estimados anteriores são limpos; alterações do mapeamento do sensor reiniciam contagens pendentes.

Migração 003 aplicada ao PostgreSQL local. API e worker atualizados e operando; a saúde do motor foi conferida por HTTPS com o certificado local explicitamente confiado. O rascunho `Resfriar acima de 27 °C` está salvo desativado, sem ação IR. O cadastro operacional continua contendo somente o sensor virtual, sem dispositivos fictícios de teste.

Validação: suíte completa com **71 testes aprovados em PostgreSQL**; depois de incluir a limpeza de estado na troca de remote_id, os **8 testes de controle passaram novamente em PostgreSQL**, incluindo o novo cenário. Ao todo são 72 cenários únicos. A suíte SQLite anterior passou com 68 testes e 3 verificações específicas de PostgreSQL ignoradas. Compilação TypeScript/Vite concluída. Foram exercitados duração, queda intermediária, dado desatualizado, rearme, pausa do servidor, agenda local, prevenção de execução dupla por workers concorrentes, resultado desconhecido sem reenvio, limite entre regras, ações sequenciais de potência/temperatura, sensor virtual, permissões, status estimado, faixas de temperatura e dispositivo combinado.

Verificação visual em prévia isolada: cadastro de IR, comandos manuais com adaptador simulado, consulta de status, criação/edição de regra por temperatura, escolha e persistência de hora/minuto, cartões de regras e layouts em 1440px e 390px sem rolagem horizontal. Registros de demonstração têm prefixo PRÉVIA, ficam apenas no banco isolado da prévia e não enviam comandos à Tuya. Evidências: automations-preview.jpg, automation-editor-preview.jpg, automations-mobile.jpg, infrared-control-preview.jpg e infrared-control-mobile.jpg.

**Limite da entrega:** ainda não há hub/controle virtual real configurado nem validação física de infravermelho. A assinatura Cloud já usada para o sensor e as rotas IR foram verificadas por testes e documentação oficial; isso não comprova permissões IR da conta, biblioteca compatível ou recepção física pelo ar-condicionado. Configure e valide esses pontos antes de habilitar capacidades reais e regras.

### Sensor real combinado e TV Samsung

- Consultas reais de detalhe, status, especificação, controles virtuais e teclas concluídas no projeto Tuya.
- Cadastro único do sensor/hub Data Center, com temperatura e umidade normalizadas pelas escalas da especificação. Reconciliação e leitura do cadastro confirmadas após reinícios.
- Perfil de TV por teclas padrão implementado. Envio restrito à lista consultada, com idempotência e auditoria. Power não é tratado como ligar/desligar discreto; não se apresenta estado físico nem temperatura de ar-condicionado para a TV.
- Um único teste real de Volume − foi aceito pela Tuya; o usuário confirmou que a TV respondeu. Registro físico associado somente a essa tecla. Verificador posterior consultou o cadastro e a auditoria sem transmitir outro comando.
- Suíte padrão atualizada: **72 testes aprovados, 3 verificações de concorrência/migração específicas de PostgreSQL ignoradas**. Os **10 testes de controle e 16 testes de automações passaram em PostgreSQL**, incluindo descoberta de teclas, whitelist, troca de remote_id, não atribuição de energia e ação IR em regra.
- Compilação TypeScript/Vite concluída. Prévia isolada com cópia da configuração e leituras reais conferida em 1440px e 390px: 21 teclas, teste físico identificado, ausência de controles de temperatura para TV e sem rolagem horizontal. A captura desktop inclui cópia do registro real de teste. Nenhum comando adicional foi transmitido ao conferir a interface.
- Evidências: `tv-control-preview.jpg`, `tv-control-mobile.jpg`, configuração `config/data-center.validated.json` e relatório em `docs/CLOUD-VALIDATION.md`. As credenciais permanecem fora do pacote.
