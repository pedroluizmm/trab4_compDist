# Auditoria técnica - 29/10/2026

## Fonte e requisitos

Fonte primária disponível para o Trabalho 4: `missao-original.txt`, fornecida pelo usuário. A busca por PDFs no workspace localizou material do Trabalho 3, sem enunciado do Trabalho 4. O material antigo foi somente lido para identificação; não foi alterado. Nomes/matrículas do Trabalho 4 permanecem pendentes.

Repositório original: https://github.com/ibnesayeed/linkextractor, commit `fb3bcadcb41afbb9ff484adf95bdc9ff3099fc56`. As pastas `step0` a `step6` contêm 36 arquivos, protegidos por inventário SHA-256 em `originais-sha256.json`.

## Problemas encontrados e decisões

| Original | Decisão experimental | Consequência |
|---|---|---|
| Python `python:3`, pacotes sem versão, `app.run` | Python 3.12, Flask 3.1.2 e Gunicorn 23.0.0 | Ambiente explícito e servidor com concorrência configurada |
| Ruby 2.6, Sinatra/Nokogiri/Redis sem versão | Ruby 3.3, Sinatra 4.1.1, Nokogiri 1.18.10 e Puma 6.6.1 | Compatibilidade com bibliotecas atuais, versões registradas |
| `open(url)` em Ruby antigo | `Net::HTTP` com timeout e proxy desativado para rede local | Evita incompatibilidade com `Kernel#open` e URLs modernas |
| PHP 7 | PHP 8.3/Apache | Demonstração funcional separada dos benchmarks |
| Redis sempre usado em step5/6 | `CACHE_ENABLED` avaliado ao iniciar cada API | OFF não cria cliente Redis; ON faz GET/SET e retorna HIT/MISS |
| Ruby grava log síncrono por extração | Cabeçalho X-Cache em ambas; amostragem no gerador | Evita custo de arquivo exclusivo de Ruby |
| Campos de links sem `href` tratados de modo diferente | Ambas ignoram âncoras sem `href` | Contrato explícito; corpus contém links válidos |
| Extratores sem timeout/status validado | Timeout de origem de 5 s; erro 502; Redis indisponível retorna 503 em ON | Falhas observáveis e execução limitada |
| Recepção de URL em `/api/<url>` | Preservada e adicionada `/api/extract?url=...` | Query permite envio sem ambiguidade; caminho legado testado |
| Sinatra 4 normaliza barras repetidas no parâmetro splat | Ler REQUEST_URI no endpoint legado | Preserva http:// e evita rejeitar a URL válida |
| Acesso arbitrário a sites externos | APIs experimentais aceitam somente as dez URLs locais | Corpus estável; é uma adaptação para experimento, documentada |

O Python original normaliza texto com `split` e `urljoin`; o Ruby usa Nokogiri e `URI.join`. O corpus testa caminhos relativos, absolutos, fragmentos, query strings, texto com acentos, espaços e âncoras com imagem. Cada API é comparada com um oráculo gerado independentemente dos parsers. A equivalência semântica é por lista ordenada de `{text, href}`; JSONs não são comparados apenas por número de links.

As versões diretas e transitivas estão fixadas em requirements.lock.txt e Gemfile.lock; as imagens base, Nginx, Redis e Locust estão fixadas por digest, registrado em ambiente/imagens-e-bases.json. A reconstrução com locks passou em ambas as APIs. Não se executam as etapas antigas para evitar conflitos nas portas 80/5000 e dependências obsoletas. Todo o código novo fica em `trabalho4/`.

## Equidade e limites

Cada API: 1 CPU, 512 MiB, dois processos e quatro threads por processo. Gunicorn usa `gthread`; Puma usa workers em cluster e pool de quatro threads. São oito posições nominais por serviço; isso não torna servidores, runtime, parser, GIL/GVL ou bibliotecas idênticos. Redis Ruby usa cliente por thread; Python utiliza pool de conexões. O experimento compara essas pilhas completas. Não demonstra superioridade intrínseca de linguagem.

Nginx/páginas: 0,5 CPU/64 MiB. Redis: 0,5 CPU/128 MiB, sem persistência habilitada. PHP: 0,25 CPU/128 MiB. Locust: 2 CPUs/512 MiB, um processo gevent, cuja saturação de um núcleo é verificada separadamente. Nenhuma configuração de energia, CPU ou memória do Windows/WSL foi alterada.

Hardware confirmado: Intel Core Ultra 7 155H, 16 núcleos, 22 processadores lógicos, 16.505.966.592 bytes de RAM física (~15,37 GiB). Docker: 22 CPUs visíveis e 7.990.726.656 bytes (~7,44 GiB). Windows 11 Home Single Language, WSL 2.7.3.0, Ubuntu WSL2, kernel 6.6.114.1. Docker Desktop 4.74.0, Engine 29.4.3, Compose 5.1.3; Python do host 3.13.6.

Dois contêineres externos de storefront/Redis estavam ativos. Não foram parados, reiniciados ou modificados. São monitorados como possível interferência. A RAM disponível no host estava próxima de 1 GiB durante a preparação, condição a acompanhar durante cargas maiores. O gerador, APIs, Redis, origem HTML e outras aplicações compartilham hardware. Cotas de CPU não significam núcleos físicos exclusivos, especialmente em processador híbrido.

## Referências oficiais consultadas

- Link Extractor: https://github.com/ibnesayeed/linkextractor
- Locust/tarefas: https://docs.locust.io/en/stable/writing-a-locustfile.html
- Locust/headless: https://docs.locust.io/en/stable/running-without-web-ui.html
- Gunicorn/threads: https://gunicorn.org/reference/settings/
- Puma/processos e threads: https://puma.io/puma/
- Sinatra/autorização de host: https://sinatrarb.com/intro.html

As APIs das ferramentas foram conferidas também nas versões efetivamente instaladas. O snapshot final de CSV utiliza `locust.stats.StatsCSV` da versão 2.46.7, e não depende do último flush do exportador periódico.
