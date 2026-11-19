# QS Miner

O QS Miner é uma ferramenta de pesquisa em Python que compara estratégias de priorização de testes de regressão. Sua heurística CARP (*Change-Aware Risk-based Prioritization*) escolhe, a cada passo, o teste que cobre mais linhas alteradas ainda inéditas por segundo estimado de execução.

## Executar a ferramenta

Na raiz do repositório, com Python 3.10 ou mais recente:

```text
python -m qsminer --help
python -m qsminer rank datasets/synthetic_profile.json
python -m unittest discover -s tests -v
```

O perfil sintético serve para verificar a ordenação. O núcleo usa a biblioteca padrão do Python. O comando `rank` recebe somente as mudanças, a cobertura por teste e as durações estimadas.

## Reproduzir o piloto com Moment.js

Use Node.js 24 e salve as distribuições oficiais como `moment-2.22.2.js` e `moment-2.23.0.js` na raiz do clone. O executor confere o hash de cada arquivo.

- [Moment.js 2.22.2, versão com defeito](https://raw.githubusercontent.com/moment/moment/2.22.2/moment.js)
- [Moment.js 2.23.0, versão corrigida](https://raw.githubusercontent.com/moment/moment/2.23.0/moment.js)

```text
python -m experiments.moment_followup.run --buggy moment-2.22.2.js --fixed moment-2.23.0.js --out results/moment-piloto
```

Use um diretório de saída novo a cada execução. O script coleta cobertura LCOV e durações por teste na versão corrigida, grava 11 ordens, executa a mesma suíte de 13 testes em três blocos na versão com defeito e gera `summary.csv`. Os testes de referência de cada defeito entram apenas na avaliação. O piloto cobre os defeitos #4417 e #4698 da mesma atualização do Moment.js. O primeiro piloto, com nove testes, pode ser executado trocando o módulo por `experiments.moment_4417.run`.

O projeto Moment.js foi identificado no [repositório de mineração de merges JavaScript](https://github.com/PriscilaDevGirl/MinerreporJavascriptMerge). Os casos foram selecionados a partir do [histórico da versão 2.23.0](https://github.com/moment/moment/blob/develop/CHANGELOG.md#2230-see-full-changelog).

## Adaptador Java

O repositório também inclui um adaptador para [Defects4J 3.0.1](https://github.com/rjust/defects4j/tree/v3.0.1). Para usar o adaptador no Linux ou WSL, instale o benchmark com JDK 11 segundo a documentação oficial e coloque `defects4j` no PATH. Use `python3 -m qsminer doctor` para verificar a instalação e `python3 -m qsminer run --help` para consultar as opções. O piloto documentado acima usa Node.js.
