# Metodologia reproduzível

## Pergunta experimental

Como latência, vazão e falhas das duas pilhas de extração mudam com usuários e cache? A=Python/OFF, B=Python/ON, C=Ruby/OFF, D=Ruby/ON. A aplicação contém PHP e Redis; a carga principal acessa somente a API. Apenas uma combinação é medida de cada vez.

## Corpus e contrato

As URLs são `http://paginas/pagina01.html` a `http://paginas/pagina10.html` na rede Docker. Cinco tamanhos exatos (8, 16, 64, 128, 256 KiB) são cruzados com dois números de links (5 e 50). São dez páginas diferentes; identificadores, HTML, tamanho, links esperados e SHA-256 constam em `paginas-teste/manifest.json` e `inventario.csv`. Tamanho e quantidade de links são fatores independentes. O texto de preenchimento fica em comentários HTML; o resultado não equivale a páginas reais com DOM complexo ou scripts.

Cada usuário chama as dez URLs na mesma ordem. São chamadas HTTP GET sequenciais, uma por URL. HTTP 200, JSON como lista, a lista completa dos links e `X-Cache` são validados. A origem só é acessada pela API e não carrega imagens/JS/links encontrados. O teste valida conteúdo antes de considerar a chamada bem-sucedida.

## Unidade de carga

- Usuário virtual: uma instância de `HttpUser`, com fluxo e conexão próprios.
- Invocação: uma requisição HTTP individual à API de extração.
- Sequência/tarefa: dez invocações distintas, uma a cada URL.
- Taxa de tarefas: sequências completas por segundo.
- RPS: requisições individuais por segundo, inclusive tentativas com falha.
- RPS sem falha: requisições bem-sucedidas divididas pela duração efetiva.
- Taxa de falhas: chamadas com falha / total de chamadas; conteúdo incorreto também é falha.

A espera entre sequências segue uniforme de 1 a 2 s, com semente por usuário. A espera entre invocações é 0 s por padrão, configurável. Timeout do cliente: 10 s por chamada. Há no máximo uma chamada em andamento por usuário. É um modelo fechado: uma API mais lenta reduz a taxa de novas requisições; RPS não representa uma taxa de chegada externa fixa. Com espera entre sequências, redução de latência não implica ganho proporcional de RPS.

## Fronteiras da medição

1. Rampa oficial de 30 s, com taxa `usuários/30` por segundo. Tráfego dessa fase é identificado como `ramp` e excluído dos agregados.
2. Barreira: todos os usuários terminam a sequência em andamento e aguardam. O controlador exige o número esperado de usuários, zera as estatísticas e inicia simultaneamente a janela medida.
3. Medição de 120 s. Novas sequências só começam nessa fase. Cada sequência tem dez chamadas; ao atingir o prazo nenhuma nova sequência é iniciada.
4. Drenagem: as sequências em andamento completam suas dez chamadas. A duração efetiva vai do início medido até o maior valor entre o prazo de 120 s e a última sequência concluída. A espera final até os usuários estacionarem não é contada como tempo de serviço.
5. A campanha verifica amostras = 10 x sequências; cada usuário deve ter pelo menos três sequências completas e todas as URLs devem ter a mesma quantidade de amostras. O snapshot final do CSV usa o serializador nativo do Locust.

Não se usa `--run-time`, porque seu relógio inclui a rampa e pode interromper tarefas. `--stop-timeout=110` é uma proteção adicional. Barreira/drenagem têm limite de 110 s. Uma drenagem maior que 5 s ou 5% da janela (o maior dos dois) marca anomalia. Registra-se tanto o tempo efetivo medido quanto o tempo total do processo e da orquestração.

RPS consolidado = total/duração efetiva. O CSV nativo usa o intervalo calculado internamente pelo Locust até a última amostra, podendo diferir levemente. Os dados nativos são preservados; a fórmula do consolidado é explícita e consistente entre cenários. Média, mediana e percentis são derivados da mesma janela de estatísticas. Percentis do Locust usam histograma de tempos arredondados; as amostras individuais sem esse arredondamento também ficam disponíveis.

## Cache

ON: apagar somente as dez chaves voláteis do cenário no Redis dedicado; confirmar dez MISS/SET e dez HIT, conteúdo válido e dez chaves presentes. Antes da carga, todas as páginas já estão no cache. Durante rampa e medição exigir somente HIT e nenhum novo SET/MISS. OFF: variável falsa ao iniciar a API, nenhum cliente Redis criado e diferença zero nos contadores GET/SET/hits/misses. O piloto também para somente o Redis deste projeto: OFF deve continuar com HTTP 200, ON deve responder 503. Após a prova, restaurar Redis e reaquecer ON. Limpeza de chaves não é usada como substituto de cache OFF.

## Desenho da campanha

2 APIs x 2 caches x 3 cargas (10, 50, 100) x 3 repetições = 36 execuções. Em cada repetição, as 12 combinações são embaralhadas com semente fixa 20261029. Isso reduz confusão sistemática com ordem e aquecimento, mas não elimina efeitos térmicos ou de outras aplicações. Os parâmetros temporais e esperas são iguais em todas as configurações oficiais. Recuperação de 10 s entre testes, acrescida da preparação do cenário seguinte.

Os pilotos são reduzidos a 5 usuários, rampa de 5 s, medição de 20 s e recuperação de 5 s para verificar correção com baixa carga. Essa redução não estima a capacidade máxima e não valida previamente 50/100 usuários. Os níveis oficiais são uma proposta; alterações após aprovação exigem justificativa, identificação e parâmetros comparáveis.

## Recursos, anomalias e análise

Amostras de CPU/memória dos contêineres e RAM disponível do host ficam em `docker-resources.jsonl`; são filtradas por timestamps da janela efetiva. O Locust registra CPU do próprio processo, RSS, atraso do event loop e throttling do cgroup. CPU >=85% de um núcleo por cinco amostras consecutivas ou p95 de atraso >100 ms marca saturação do gerador. Sem métricas não se presume ausência de saturação. O monitor externo inclui os outros contêineres, mas não os modifica. RAM disponível <384 MiB em três coletas consecutivas aciona encerramento controlado.

Reinícios, OOM, duração anormal, perda de aquecimento, uso indevido de Redis em OFF ou sequências incompletas invalidam comparação e interrompem a campanha. Taxa de falhas >5% também interrompe a campanha para inspeção. Os arquivos permanecem preservados; não há descarte silencioso nem repetição automática para melhorar os números.

A consolidação oficial exige as 36 combinações/repetições únicas e válidas. Cada repetição contribui igualmente à média; o desvio-padrão é amostral (`n-1`). A média das medianas e a média dos P95/P99 entre execuções não são percentis de um conjunto mesclado. Com três repetições, dispersão não é prova de significância. Gráficos de cache aquecido são explicitamente identificados; não há campanha de cache frio misturada.

Ganho de latência = 100 x (média OFF - média ON)/média OFF. Ganho de RPS = 100 x (RPS ON - RPS OFF)/RPS OFF. O script calcula pares da mesma carga, linguagem e bloco de repetição, mantendo denominadores e dispersão explícitos. Conclusões devem separar fatos medidos, inferências arquiteturais e hipóteses. Diferenças de parser, servidor e runtime impedem atribuir os resultados apenas à linguagem.
