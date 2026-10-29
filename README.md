# Trabalho 4 - Link Extractor

Implementação experimental independente, baseada em `step4`, `step5` e `step6` do [Link Extractor](https://github.com/ibnesayeed/linkextractor), licença MIT. O código original foi preservado no commit `fb3bcadcb41afbb9ff484adf95bdc9ff3099fc56`.

**Estado: implementação e pilotos de baixa carga concluídos; campanha oficial pendente de aprovação explícita.**
Os dados oficiais, o PDF de defesa e a apresentação final dependem da campanha aprovada. Nenhum resultado foi simulado.

## Executar no PowerShell

Abra este diretório e utilize o Docker Desktop em modo Linux:

```powershell
Set-Location C:\compDist\Trabalho4-LinkExtractor\trabalho4
docker compose config --quiet
docker compose build api-python api-ruby web
python -X utf8 scripts/experimento.py audit
python -X utf8 scripts/experimento.py plan
python -X utf8 scripts/experimento.py pilot
python -m pip install -r scripts/requirements-analysis.txt
python -X utf8 scripts/analisar.py --kind pilot
python -X utf8 scripts/auditar_resultados.py
```

O piloto usa **5 usuários**, rampa de 5 s, medição de 20 s, uma repetição por cenário e recuperação de 5 s. A rampa e o piloto não entram na campanha oficial. O controlador aguarda sequências completas nas duas fronteiras da medição. As durações reais ficam em `summary.json`.

## Demonstração PHP

```powershell
$env:CACHE_ENABLED='true'
docker compose up -d --wait paginas redis web api-python api-ruby
Start-Process http://localhost:8085
# Encerrar somente os serviços deste projeto:
docker compose stop
```

Interface: http://localhost:8085. APIs: Python http://localhost:5104/health e Ruby http://localhost:5106/health. Páginas: http://localhost:8084/pagina01.html até pagina10.html. Benchmarks usam a rede Docker e acessam uma única API diretamente; PHP fica fora do caminho medido. Somente a demonstração inicia ambas as APIs.

## Campanha oficial: bloqueio de aprovação

A execução sem aprovação termina com erro **antes** de qualquer acesso ao Docker. Após a aprovação real do usuário, registrar `configuracoes/aprovacao.json` com `approved: true`, `approved_at` e `user_message` contendo o texto efetivamente recebido. Não criar esse registro antecipadamente.

```powershell
python -X utf8 scripts/experimento.py official --approval-file configuracoes/aprovacao.json
python -X utf8 scripts/analisar.py --kind official
```

Plano: `configuracoes/campanha-planejada.csv`. São 36 execuções sequenciais, 10/50/100 usuários, 30 s de rampa, 120 s de medição, três repetições e 10 s de recuperação. A ordem é aleatória em blocos por repetição, semente 20261029. Estimativa inicial: 1h45 a 2h, incluindo preparação e verificações. As cargas de 50/100 usuários permanecem propostas, ainda sem validação em alta carga.

Cada execução prepara apenas suas próprias chaves de cache volátil, aquece e verifica as dez URLs, exporta dados, monitora recursos e interrompe a campanha se detectar anomalia. A automação encerra os serviços deste projeto ao terminar, inclusive em erro. Não há limpeza global nem alterações em outros projetos.

## Arquivos e rastreabilidade

- `api-python/`, `api-ruby/`, `web/`: serviços experimentais.
- `paginas-teste/manifest.json`: oráculo independente de links, tamanho e SHA-256 de cada HTML.
- `locust/locustfile.py`: tarefa de dez invocações, validação de respostas e controle de fases.
- `scripts/experimento.py`: ambiente, validação, pilotos, proteção de aprovação e campanha.
- `scripts/analisar.py`: consolidação, dispersão entre repetições e gráficos por métrica.
- `resultados/pilotos/`: dados exploratórios, com tentativas inválidas preservadas e identificadas.
- `resultados/oficial/`: reservado à campanha autorizada; não misturar com pilotos.
- `documentacao/`: auditoria, metodologia, evidências e relatório dos pilotos.

`request_samples.csv` -> `locust_final_stats.csv` -> `summary.json` -> `consolidado/execucoes.csv` -> `agregados.csv` -> gráficos. `locust_stats.csv` é o arquivo periódico original, que pode terminar antes do último lote. O snapshot final usa o próprio serializador do Locust. Ambos são preservados. `rastreabilidade-sha256.csv` registra a origem e o hash dos dados.

Integrantes e matrículas: **PENDENTES DE PREENCHIMENTO**. Não foram inferidos de trabalhos anteriores.
