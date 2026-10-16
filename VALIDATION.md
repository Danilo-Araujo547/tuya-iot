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

### Visual sem gradientes e períodos lado a lado

Na branch `codex/menu-e-papeis-de-parede`, o menu lateral, o botão de abrir menu e os seletores usam fundos planos. O card de extremos passou a mostrar 1h, 6h, 24h, 7d e 30d como botões visíveis na mesma linha; histórico e filtros usam o mesmo estilo de seleção. Mantida a navegação por teclado e a indicação acessível da opção selecionada.

Validação: TypeScript/Vite compilou com sucesso; conferidas seleção de 6h e 30d, abertura/fechamento do menu e dimensões de 1440px e 390px em prévia isolada com dados de layout. As cinco opções permaneceram alinhadas, sem rolagem horizontal no celular. Estilos computados confirmaram `background-image: none` no menu e na opção selecionada. Nenhum erro JavaScript registrado. A prévia não acessa banco operacional, credenciais ou comandos Tuya; o clima externo fica indisponível nessa prévia. Evidências: clean-selectors-desktop.jpg, clean-selectors-mobile.jpg e clean-navigation.jpg.

### Card de umidade e campo Externo

O card superior direito voltou a mostrar a umidade do sensor. O terceiro campo abaixo do mostrador passou de Origem para Externo, com a temperatura meteorológica, consulta a cada dez minutos, indicação de dado antigo e valor ausente sem substituição inventada. A fonte Open-Meteo permanece acessível pelo link no valor e pela descrição acessível. Validado na prévia isolada: umidade de teste de 30%, temperatura externa consultada no provedor de 21,5 °C no momento da conferência, rótulo Externo e ausência do antigo campo Origem. TypeScript/Vite compilou com sucesso. Evidência: humidity-external-preview.jpg.
